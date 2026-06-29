"""실험 019: PDF bookmark를 디렉터리 트리 + markdown으로 구체화한다.

목적
- bookmark(목차)가 잘 들어 있는 PDF를 받았을 때, 그 bookmark 트리를
  실제 파일시스템 디렉터리 트리로 펼치고 각 노드의 본문 텍스트를
  markdown 파일로 떨어뜨리는 핵심 기능을 PoC로 검증한다.
- 이 기능은 bookmark가 있는 PDF에서는 LLM/heuristic TOC 탐지 없이도
  곧장 트리 + 본문을 만들 수 있어야 한다는 요구를 만족하는지 본다.

설계
- flat bookmark (level, title, pdf_page) 목록을 중첩 트리로 복원한다.
- 각 노드의 "자기 본문 구간"은 자기 시작 page부터 reading order상
  바로 다음 bookmark 시작 page 직전까지로 잡는다. 즉 자식/다음 절이
  시작하기 전의 도입부 텍스트가 그 노드에 귀속된다.
- 마지막 bookmark는 문서 끝 page까지 본문으로 갖는다.
- 각 노드는 'NN_제목' 디렉터리가 되고, 그 안에 본문 markdown 파일과
  자식 디렉터리가 들어간다.

규칙
- real data 사용. 합성/mock 입력으로 성공을 주장하지 않는다.
- 모든 page 번호는 1-based PDF page다.
- bookmark가 있는 John Hull 책을 기본 입력으로 쓴다.

이 파일은 AGENTS.md §3에 따라 monolithic PoC script로 작성한다.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz

from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "019_bookmark_tree_to_markdown_dir"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"

DEFAULT_PDF = (
    ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf"
)

# Windows 파일명에서 금지되는 문자
ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_NAME_LEN = 80


def sanitize_name(title: str) -> str:
    """bookmark 제목을 파일시스템에서 안전한 디렉터리/파일 이름으로 바꾼다."""

    name = ILLEGAL_CHARS.sub("", title).strip()
    name = re.sub(r"\s+", " ", name)
    name = name.rstrip(". ")  # Windows는 뒤에 점/공백을 싫어한다
    if not name:
        name = "untitled"
    if len(name) > MAX_NAME_LEN:
        name = name[:MAX_NAME_LEN].rstrip()
    return name


def build_tree(bookmarks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """flat bookmark 목록을 level 기반 중첩 트리로 복원한다.

    각 노드에 reading order상 다음 bookmark의 시작 page를 함께 계산해두면,
    뒤에서 본문 구간(자기 page ~ 다음 bookmark 직전)을 쉽게 자를 수 있다.
    """

    # reading order상 다음 bookmark의 시작 page(=자기 본문 구간의 exclusive end 힌트)
    nodes: list[dict[str, Any]] = []
    for i, bm in enumerate(bookmarks):
        next_page = None
        for nxt in bookmarks[i + 1 :]:
            if nxt["pdf_page"] is not None:
                next_page = nxt["pdf_page"]
                break
        nodes.append(
            {
                "order": bm["order"],
                "level": bm["level"],
                "title": bm["title"],
                "start_page": bm["pdf_page"],
                "next_start_page": next_page,
                "children": [],
            }
        )

    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for node in nodes:
        while stack and stack[-1]["level"] >= node["level"]:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


def own_span(node: dict[str, Any], page_count: int) -> tuple[int, int] | None:
    """노드의 '자기 본문' page 구간 [start, end](1-based, inclusive)를 계산한다.

    start는 노드 시작 page, end는 다음 bookmark 시작 page 직전이다. 다음 bookmark가
    같은 page에서 시작하면(빈 구간) None을 돌려 빈 본문임을 알린다.
    """

    start = node["start_page"]
    if start is None:
        return None
    end_exclusive = node["next_start_page"] if node["next_start_page"] else page_count + 1
    end = end_exclusive - 1
    if end < start:
        return None
    return (start, end)


def extract_span_markdown(
    document: "fitz.Document", span: tuple[int, int] | None
) -> str:
    """page 구간의 text layer를 모아 간단한 markdown 본문으로 만든다."""

    if span is None:
        return ""
    start, end = span
    chunks: list[str] = []
    for pdf_page in range(start, end + 1):
        page = document.load_page(pdf_page - 1)
        text = page.get_text("text").strip()
        if text:
            chunks.append(f"<!-- pdf_page {pdf_page} -->\n\n{text}")
    return "\n\n".join(chunks)


def write_node(
    node: dict[str, Any],
    parent_dir: Path,
    index: int,
    document: "fitz.Document",
    page_count: int,
    stats: dict[str, int],
) -> None:
    """노드를 디렉터리로 만들고 본문 markdown과 자식 디렉터리를 재귀로 쓴다."""

    dir_name = f"{index:02d}_{sanitize_name(node['title'])}"
    node_dir = parent_dir / dir_name
    node_dir.mkdir(parents=True, exist_ok=True)
    stats["dirs"] += 1

    # 과거 실행에서 만든 고정 이름 content.md가 있으면 정리한다(이름 규칙 변경 흔적).
    stale = node_dir / "content.md"
    if stale.exists():
        stale.unlink()

    span = own_span(node, page_count)
    body = extract_span_markdown(document, span)
    span_label = f"{span[0]}-{span[1]}" if span else "none"
    header = f"# {node['title']}\n\n<!-- own page span: {span_label} -->\n\n"
    # 파일명은 디렉터리명(=bookmark 제목 기반)과 똑같이 맞춘다: aaaa/aaaa.md 형태
    (node_dir / f"{dir_name}.md").write_text(header + body, encoding="utf-8")
    stats["md_files"] += 1
    if body:
        stats["nonempty_md"] += 1

    for child_index, child in enumerate(node["children"], start=1):
        write_node(child, node_dir, child_index, document, page_count, stats)


def count_nodes(roots: list[dict[str, Any]]) -> int:
    total = 0
    stack = list(roots)
    while stack:
        node = stack.pop()
        total += 1
        stack.extend(node["children"])
    return total


def tree_preview(roots: list[dict[str, Any]], max_lines: int = 25) -> list[str]:
    """트리 상위 일부를 사람이 읽을 수 있는 들여쓰기 미리보기로 만든다."""

    lines: list[str] = []

    def walk(nodes: list[dict[str, Any]], depth: int) -> None:
        for node in nodes:
            if len(lines) >= max_lines:
                return
            span = node["start_page"]
            lines.append(f"{'  ' * depth}- {node['title']} (p{span})")
            walk(node["children"], depth + 1)

    walk(roots, 0)
    return lines


def record_experiment(summary: dict[str, Any]) -> None:
    """experiments.json에 이번 실행 결과를 append/갱신한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "bookmark가 잘 있는 PDF의 bookmark 트리를 파일시스템 디렉터리 트리로 "
            "펼치고, 각 노드의 본문 텍스트를 markdown으로 저장하는 핵심 기능을 PoC로 "
            "검증한다."
        ),
        "inputs": [str(summary["pdf"])],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "finding": summary["finding"],
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    experiments = data.get("experiments", data) if isinstance(data, dict) else data
    experiments = [e for e in experiments if e.get("id") != EXPERIMENT_ID]
    experiments.append(entry)
    if isinstance(data, dict):
        data["experiments"] = experiments
    else:
        data = experiments
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument(
        "--no-record", action="store_true", help="experiments.json 기록을 건너뛴다"
    )
    args = parser.parse_args()

    pdf_path = args.pdf.resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF가 없다: {pdf_path}")

    bookmarks = extract_existing_bookmarks(pdf_path)
    if not bookmarks:
        raise SystemExit(f"bookmark가 없다(이 실험 대상 아님): {pdf_path}")

    roots = build_tree(bookmarks)

    # 통째 삭제는 열려 있는 폴더에서 잠금(WinError 32)을 일으키므로 제자리 덮어쓰기로 한다.
    book_dir = OUTPUT_DIR / sanitize_name(pdf_path.stem)
    book_dir.mkdir(parents=True, exist_ok=True)

    stats = {"dirs": 0, "md_files": 0, "nonempty_md": 0}
    with fitz.open(pdf_path) as document:
        page_count = document.page_count
        for index, root in enumerate(roots, start=1):
            write_node(root, book_dir, index, document, page_count, stats)

    total_nodes = count_nodes(roots)
    preview = tree_preview(roots)

    finding = (
        f"{pdf_path.name}: bookmark {len(bookmarks)}개를 {len(roots)}개 root / "
        f"총 {total_nodes}개 노드 트리로 복원했다. 디렉터리 {stats['dirs']}개, "
        f"markdown {stats['md_files']}개(본문 있는 것 {stats['nonempty_md']}개)를 "
        f"{book_dir.relative_to(ROOT_DIR)} 아래에 생성했다. "
        f"page_count={page_count}."
    )

    summary = {
        "pdf": str(pdf_path.relative_to(ROOT_DIR)),
        "page_count": page_count,
        "bookmark_count": len(bookmarks),
        "root_count": len(roots),
        "total_nodes": total_nodes,
        "dirs": stats["dirs"],
        "md_files": stats["md_files"],
        "nonempty_md": stats["nonempty_md"],
        "output_dir": str(book_dir.relative_to(ROOT_DIR)),
        "tree_preview": preview,
        "finding": finding,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(finding)
    print("\n트리 미리보기:")
    print("\n".join(preview))

    if not args.no_record:
        record_experiment(summary)
        print("\nexperiments.json에 기록 완료.")


if __name__ == "__main__":
    main()
