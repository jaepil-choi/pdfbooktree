"""bookmark가 최소 1 depth tree 모양인 PDF만 pseudo label 후보로 거르는 실험.

배경:
- 생성된 pseudo label의 quality를 확인하기에 앞서, bookmark 개수가 지나치게 많거나
  계층 구조 없이 평평하게 덤프된 PDF를 먼저 제외하고 싶다.
- 가설: 진짜 book의 TOC는 chapter -> section 처럼 최소 1 depth 이상의 tree 구조를 가진다.
  반대로 level 1만 잔뜩 나열된 평평한 bookmark는 목차로 보기 어렵다.

이 실험은 data/ 아래 PDF의 기존 bookmark를 읽어 tree 구조 지표를 계산하고,
"최소 1 depth tree" 기준(서로 다른 level 2개 이상 + 실제 부모-자식 중첩 존재)으로
pseudo label 적합 여부를 판단한다.

monolithic script로 작성했고, bookmark 추출만 패키지 함수를 재사용한다.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "010_bookmark_tree_shape_filter"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DATA_DIR = ROOT_DIR / "data"

# pseudo label 후보가 되려면 tree depth(= max_level - min_level)가 이 값 이상이어야 한다.
MIN_TREE_DEPTH = 1


def analyze_bookmark_tree(bookmarks: list[dict[str, Any]]) -> dict[str, Any]:
    """bookmark level 시퀀스로 tree 모양 지표를 계산한다.

    - levels: 등장한 level 값 집합과 개수 분포
    - tree_depth: max_level - min_level. 평평한 list(전부 같은 level)이면 0.
    - has_nesting: level 1 다음에 더 깊은 level 자식이 실제로 나타나는지
    - parent_child_pairs: stack 기반으로 복원한 부모-자식 관계 수
    - level_jumps: level이 한 번에 2 이상 깊어지는(중간 단계를 건너뛰는) 비정상 케이스 수
    - max_children: 한 부모가 가진 최대 자식 수(평평/덤프 판단 참고용)
    """

    levels = [bookmark["level"] for bookmark in bookmarks]
    level_counts = Counter(levels)

    if not levels:
        return {
            "bookmark_count": 0,
            "level_counts": {},
            "distinct_levels": 0,
            "min_level": None,
            "max_level": None,
            "tree_depth": 0,
            "has_nesting": False,
            "parent_child_pairs": 0,
            "level_jumps": 0,
            "max_children": 0,
            "is_min_depth_tree": False,
        }

    min_level = min(levels)
    max_level = max(levels)
    tree_depth = max_level - min_level

    # stack으로 부모-자식 관계를 복원한다.
    # stack에는 (level, child_count)를 담고, 더 얕거나 같은 level이 오면 pop한다.
    stack: list[list[int]] = []
    parent_child_pairs = 0
    level_jumps = 0
    children_counter: list[int] = []

    for level in levels:
        while stack and stack[-1][0] >= level:
            done = stack.pop()
            children_counter.append(done[1])
        if stack:
            # stack 맨 위가 현재 항목의 부모다.
            if level - stack[-1][0] > 1:
                level_jumps += 1
            stack[-1][1] += 1
            parent_child_pairs += 1
        stack.append([level, 0])

    while stack:
        done = stack.pop()
        children_counter.append(done[1])

    has_nesting = parent_child_pairs > 0
    max_children = max(children_counter) if children_counter else 0

    return {
        "bookmark_count": len(bookmarks),
        "level_counts": {str(k): v for k, v in sorted(level_counts.items())},
        "distinct_levels": len(level_counts),
        "min_level": min_level,
        "max_level": max_level,
        "tree_depth": tree_depth,
        "has_nesting": has_nesting,
        "parent_child_pairs": parent_child_pairs,
        "level_jumps": level_jumps,
        "max_children": max_children,
        # 최소 1 depth tree: tree_depth가 기준 이상이고 실제 중첩이 존재해야 한다.
        "is_min_depth_tree": tree_depth >= MIN_TREE_DEPTH and has_nesting,
    }


def build_tree_preview(bookmarks: list[dict[str, Any]], limit: int = 20) -> list[str]:
    """bookmark 앞부분을 들여쓰기로 표현해 tree 모양을 눈으로 확인한다."""

    lines: list[str] = []
    for bookmark in bookmarks[:limit]:
        indent = "  " * (bookmark["level"] - 1)
        page = bookmark["pdf_page"]
        title = bookmark["title"] or "(빈 제목)"
        lines.append(f"{indent}- L{bookmark['level']} p{page} {title}")
    if len(bookmarks) > limit:
        lines.append(f"  ... (+{len(bookmarks) - limit} more)")
    return lines


def discover_pdfs() -> list[Path]:
    return sorted(DATA_DIR.rglob("*.pdf"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_finding(results: list[dict[str, Any]]) -> str:
    total = len(results)
    with_bookmark = [r for r in results if r["bookmark_count"] > 0]
    qualified = [r for r in results if r["is_min_depth_tree"]]
    flat = [r for r in with_bookmark if not r["is_min_depth_tree"]]

    parts = [
        f"data/ 아래 PDF {total}개 중 bookmark 보유 {len(with_bookmark)}개, "
        f"최소 {MIN_TREE_DEPTH} depth tree 기준 통과 {len(qualified)}개, "
        f"탈락(평평하거나 bookmark 없음) {total - len(qualified)}개다."
    ]
    for r in results:
        parts.append(
            f"{r['pdf']}는 bookmark {r['bookmark_count']}개, level 분포 {r['level_counts']}, "
            f"tree_depth {r['tree_depth']}, 부모-자식쌍 {r['parent_child_pairs']}, "
            f"최대 자식수 {r['max_children']}로 판정 {r['is_min_depth_tree']}이다."
        )
    if flat:
        names = ", ".join(r["pdf"] for r in flat)
        parts.append(f"평평한 bookmark로 제외된 PDF: {names}.")
    return " ".join(parts)


def update_experiment_registry(
    results: list[dict[str, Any]], input_pdfs: list[Path]
) -> None:
    if not EXPERIMENTS_JSON.exists():
        return
    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "data/ 아래 PDF의 기존 bookmark가 최소 1 depth tree 모양인지 판정해, "
            "계층 없이 평평하거나 bookmark 수가 과도한 PDF를 pseudo label 후보에서 거르는 "
            "필터 기준을 검증한다."
        ),
        "inputs": [
            str(path.relative_to(ROOT_DIR)).replace("/", "\\") for path in input_pdfs
        ],
        "outputs": "experiments\\outputs\\010_bookmark_tree_shape_filter",
        "min_tree_depth": MIN_TREE_DEPTH,
        "finding": build_finding(results),
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    registry["experiments"] = [
        e for e in registry["experiments"] if e.get("id") != EXPERIMENT_ID
    ]
    registry["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet", action="store_true", help="summary JSON 출력을 생략한다."
    )
    args = parser.parse_args()

    input_pdfs = discover_pdfs()
    results: list[dict[str, Any]] = []

    for pdf_path in input_pdfs:
        bookmarks = extract_existing_bookmarks(pdf_path)
        metrics = analyze_bookmark_tree(bookmarks)
        result = {
            "pdf": pdf_path.name,
            "relative_path": str(pdf_path.relative_to(ROOT_DIR)).replace("/", "\\"),
            **metrics,
            "tree_preview": build_tree_preview(bookmarks),
        }
        results.append(result)

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "min_tree_depth": MIN_TREE_DEPTH,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pdf_count": len(results),
        "qualified_count": sum(1 for r in results if r["is_min_depth_tree"]),
        "results": results,
        "finding": build_finding(results),
    }

    csv_rows = [
        {
            "pdf": r["pdf"],
            "bookmark_count": r["bookmark_count"],
            "distinct_levels": r["distinct_levels"],
            "min_level": r["min_level"],
            "max_level": r["max_level"],
            "tree_depth": r["tree_depth"],
            "parent_child_pairs": r["parent_child_pairs"],
            "level_jumps": r["level_jumps"],
            "max_children": r["max_children"],
            "level_counts": json.dumps(r["level_counts"], ensure_ascii=False),
            "is_min_depth_tree": r["is_min_depth_tree"],
        }
        for r in results
    ]

    write_csv(
        OUTPUT_DIR / "bookmark_tree_shape.csv", csv_rows, list(csv_rows[0].keys())
    )
    write_json(OUTPUT_DIR / "summary.json", summary)
    update_experiment_registry(results, input_pdfs)

    if not args.quiet:
        for r in results:
            mark = "PASS" if r["is_min_depth_tree"] else "DROP"
            print(
                f"[{mark}] {r['pdf']}\n"
                f"       bookmark={r['bookmark_count']} levels={r['level_counts']} "
                f"depth={r['tree_depth']} pairs={r['parent_child_pairs']} "
                f"max_children={r['max_children']} jumps={r['level_jumps']}"
            )
            for line in r["tree_preview"][:8]:
                print(f"       {line}")
            print()
        print("-" * 60)
        print(summary["finding"])


if __name__ == "__main__":
    main()
