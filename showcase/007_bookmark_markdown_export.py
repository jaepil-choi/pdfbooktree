"""showcase 007: bookmark가 있는 PDF를 markdown 디렉터리 트리로 export한다.

대상은 bookmark(목차 outline)가 잘 들어 있는 indexed PDF다. 이런 책은 TOC 탐지나
LLM 없이 bookmark 트리를 그대로 파일시스템에 펼칠 수 있어야 한다. 공개 인터페이스
``Processor(pdf, out, ProcessingConfig()).run()``을 기본 config로 호출하면(기존
bookmark가 있으면 skip이 아니라 markdown export가 되어야 한다) 다음을 확인한다.

1. status == "processed", output_markdown_dir 생성.
2. bookmark 수만큼 ``NN_<제목>`` 디렉터리와 동명 ``.md``가 중첩 생성된다.
3. 본문 markdown에 ``<!-- pdf_page N -->`` 마커와 실제 page text가 들어간다.

모든 호출은 real data + live call이다. synthetic/mock/stub 입력은 쓰지 않는다.

실행:
    uv run python showcase/007_bookmark_markdown_export.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree import ProcessingConfig, Processor
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks

try:  # 콘솔에서 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "007_bookmark_markdown_export"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "007_bookmark_markdown_export"

# bookmark가 잘 있는 indexed 책들(native 1권 + scanned+OCR 1권).
CASE_PDFS = [
    ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf",
    ROOT_DIR
    / "data"
    / "scanned-pdf-indexed"
    / "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf",
]


def _walk_md_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.md"))


def _top_level_preview(root: Path, limit: int = 8) -> list[str]:
    """루트 바로 아래 디렉터리 이름을 일부 미리보기로 만든다."""

    dirs = sorted(p.name for p in root.iterdir() if p.is_dir())
    return dirs[:limit]


def run_case(pdf_path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"input_pdf": str(pdf_path.relative_to(ROOT_DIR))}

    if not pdf_path.exists():
        record["status"] = "blocked_missing_data"
        return record

    bookmarks = extract_existing_bookmarks(pdf_path)
    if not bookmarks:
        # showcase 규칙: 가짜 데이터로 대체하지 않고 blocked 사유를 남긴다.
        record["status"] = "blocked_no_bookmark"
        return record

    out_dir = OUTPUT_DIR / pdf_path.stem
    result = Processor(pdf_path, out_dir, ProcessingConfig()).run()

    record["status"] = result.status
    record["bookmark_count"] = result.bookmark_count
    record["warnings"] = result.warnings

    markdown_dir = result.output_markdown_dir
    if result.status != "processed" or markdown_dir is None:
        return record

    md_files = _walk_md_files(markdown_dir)
    nonempty = sum(
        1 for path in md_files if "<!-- pdf_page" in path.read_text(encoding="utf-8")
    )
    record["output_markdown_dir"] = str(markdown_dir.relative_to(ROOT_DIR))
    record["dir_count"] = sum(1 for _ in markdown_dir.rglob("*") if _.is_dir())
    record["md_file_count"] = len(md_files)
    record["nonempty_md_count"] = nonempty
    record["top_level_preview"] = _top_level_preview(markdown_dir)

    # 첫 챕터급 디렉터리의 markdown 한 개를 샘플로 떠 본다(본문 grounding 확인).
    sample = next(
        (p for p in md_files if "<!-- pdf_page" in p.read_text("utf-8")), None
    )
    if sample is not None:
        head = sample.read_text(encoding="utf-8")[:400]
        record["sample_md_file"] = str(sample.relative_to(markdown_dir))
        record["sample_md_head"] = head
    return record


def build_finding(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for result in results:
        status = result.get("status")
        name = Path(result["input_pdf"]).name
        if status != "processed":
            parts.append(f"{name}: {status}.")
            continue
        parts.append(
            f"{name}: bookmark {result['bookmark_count']}개 → markdown "
            f"디렉터리 {result['dir_count']}개, md {result['md_file_count']}개"
            f"(본문 있는 것 {result['nonempty_md_count']}개) export(processed)."
        )
    return " ".join(parts)


def record_showcase(results: list[dict[str, Any]], finding: str) -> None:
    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "bookmark가 있는 indexed PDF를 공개 인터페이스 Processor로 처리하면 "
            "skip이 아니라 bookmark 트리를 markdown 디렉터리 트리로 export하는지 "
            "real data로 검증한다(native 1권 + scanned+OCR 1권)."
        ),
        "inputs": [result["input_pdf"] for result in results],
        "outputs": "showcase/outputs/007_bookmark_markdown_export/result.json",
        "finding": finding,
        "command": "uv run python showcase/007_bookmark_markdown_export.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    data["showcases"] = [s for s in data["showcases"] if s.get("id") != SHOWCASE_ID]
    data["showcases"].append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = [run_case(pdf_path) for pdf_path in CASE_PDFS]

    summary = {
        "purpose": (
            "bookmark가 있는 indexed PDF의 bookmark 트리를 markdown 디렉터리 트리로 "
            "export하는 production 경로를 검증한다."
        ),
        "source_experiment": "019_bookmark_tree_to_markdown_dir",
        "case_count": len(results),
        "results": results,
    }
    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    finding = build_finding(results)
    record_showcase(results, finding)

    print("=== bookmark → markdown 디렉터리 export (indexed PDF) ===")
    for result in results:
        print(f"\n- {Path(result['input_pdf']).name}: {result.get('status')}")
        if result.get("status") != "processed":
            continue
        print(
            f"    bookmark={result['bookmark_count']} "
            f"dirs={result['dir_count']} md={result['md_file_count']} "
            f"nonempty={result['nonempty_md_count']}"
        )
        print(f"    markdown_dir={result['output_markdown_dir']}")
        print(f"    top dirs: {result['top_level_preview']}")
        if "sample_md_file" in result:
            print(f"    sample: {result['sample_md_file']}")


if __name__ == "__main__":
    main()
