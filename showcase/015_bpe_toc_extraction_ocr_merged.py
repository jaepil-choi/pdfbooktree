"""showcase 015: 통계학원론(김동욱) 실제 OCR PDF에서 공개 Processor로 TOC를 뽑는다.

`data/scanned-pdf-not-indexed/통계학원론 (김동욱)_OCR.compressed[stats book].pdf`는
이미 OCR text layer가 입혀진 481쪽 scanned 책이다. `inspect_bookmarks`로 먼저 확인해
보면 bookmark가 482개 있지만 전부 level 1이고 제목이 "1110001", "1110002"처럼 스캔
도구가 붙인 파일명이다(진짜 목차가 아니라 page-per-bookmark 잔재). 그래서
`ProcessingConfig(skip_existing_bookmarks=False)`로 강제해 기존 bookmark를 그대로
내보내는 경로 대신 font-size/height typography + BPE 계층 추론 파이프라인이 실제로
돌아가게 한다.

호출은 `Processor(pdf, output_dir, config).run()` 하나뿐이다(CLI의
``pdfbooktree process --no-skip-existing-bookmarks`` 명령과 동일한 진입점). 처리
후에는 결과 PDF의 실제 bookmark를 `inspect_bookmarks`로, plan/validation 요약을
`inspect_plan_artifact`로 확인한다. 모두 `pdfbooktree` 최상위에서 export하는
public API다.

synthetic/mock/stub 입력은 쓰지 않는다. 실제 481p 스캔본 + 실제 OCR text에 live로
파이프라인을 돌린 결과만 기록한다.

실행:
    uv run python showcase/015_bpe_toc_extraction_ocr_merged.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree import (
    ProcessingConfig,
    Processor,
    inspect_bookmarks,
    inspect_plan_artifact,
)

try:  # 콘솔에서 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
INPUT_PDF = (
    ROOT_DIR
    / "data"
    / "scanned-pdf-not-indexed"
    / "통계학원론 (김동욱)_OCR.compressed[stats book].pdf"
)
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "015_bpe_toc_extraction_ocr_merged"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
TREE_PATH = OUTPUT_DIR / "bookmark_tree.txt"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "015_bpe_toc_extraction_ocr_merged"


def render_tree(bookmarks: list[dict[str, Any]]) -> str:
    """실제 export된 PDF bookmark 목록을 들여쓰기 트리 텍스트로 만든다."""

    lines = [
        "# 통계학원론(김동욱) BPE bookmark tree (Processor 공개 인터페이스 결과)",
        "",
    ]
    for bookmark in bookmarks:
        indent = "  " * max(bookmark["level"] - 1, 0)
        lines.append(
            f"{indent}- [L{bookmark['level']}, p.{bookmark['pdf_page']}] {bookmark['title']}"
        )
    return "\n".join(lines) + "\n"


def record_showcase(summary: dict[str, Any]) -> None:
    """실행 결과를 showcase registry에 기록한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "기존 bookmark 482개가 전부 level 1 스캔 파일명(진짜 목차 아님)인 실제 "
            "통계학원론 OCR PDF에서, skip_existing_bookmarks를 꺼서 공개 Processor가 "
            "typography+BPE 파이프라인으로 실제 TOC(bookmark plan)를 새로 뽑아 결과 "
            "PDF에 심는지 inspect_bookmarks/inspect_plan_artifact로 확인한다."
        ),
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_PATH.relative_to(ROOT_DIR)),
        "finding": summary["finding"],
        "command": "uv run python showcase/015_bpe_toc_extraction_ocr_merged.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    showcases = data["showcases"]
    for index, existing in enumerate(showcases):
        if existing.get("id") == SHOWCASE_ID:
            showcases[index] = entry
            break
    else:
        showcases.append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    if not INPUT_PDF.exists():
        raise FileNotFoundError(f"입력 PDF가 없다: {INPUT_PDF}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    existing = inspect_bookmarks(INPUT_PDF)
    existing_levels = {b["level"] for b in existing["bookmarks"]}
    existing_is_meaningful = len(existing_levels) >= 2

    result = Processor(
        INPUT_PDF, OUTPUT_DIR, ProcessingConfig(skip_existing_bookmarks=False)
    ).run()

    summary: dict[str, Any] = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "existing_bookmark_count": existing["bookmark_count"],
        "existing_bookmark_levels": sorted(existing_levels),
        "existing_bookmark_is_meaningful": existing_is_meaningful,
        "status": result.status,
        "bookmark_count": result.bookmark_count,
        "confidence_summary": {
            "line_extraction": result.confidence_summary.line_extraction,
            "tiering": result.confidence_summary.tiering,
            "heading_candidates": result.confidence_summary.heading_candidates,
            "outline": result.confidence_summary.outline,
        },
        "warnings": result.warnings,
    }

    if result.status == "processed" and result.output_pdf is not None:
        plan_info = inspect_plan_artifact(OUTPUT_DIR)
        bookmark_info = inspect_bookmarks(result.output_pdf)
        bookmarks = bookmark_info["bookmarks"]
        level_counts = dict(sorted(Counter(b["level"] for b in bookmarks).items()))
        tree_text = render_tree(bookmarks)
        TREE_PATH.write_text(tree_text, encoding="utf-8")

        summary.update(
            {
                "output_pdf": str(result.output_pdf.relative_to(ROOT_DIR)),
                "output_pdf_bookmark_count": bookmark_info["bookmark_count"],
                "level_counts": level_counts,
                "bookmark_plan_item_count": plan_info["bookmark_plan_item_count"],
                "bookmark_plan_validation": plan_info["validation"],
                "tree_file": str(TREE_PATH.relative_to(ROOT_DIR)),
                "tree_preview": tree_text.splitlines()[2:26],
            }
        )
        summary["finding"] = (
            f"기존 bookmark {existing['bookmark_count']}개(전부 level 1, 진짜 목차 "
            f"아님)를 무시하고 재추출: status=processed, bookmark "
            f"{bookmark_info['bookmark_count']}개(levels={level_counts}) 추출, "
            f"outline confidence={summary['confidence_summary']['outline']}"
        )
    else:
        summary["finding"] = (
            f"기존 bookmark {existing['bookmark_count']}개(전부 level 1, 진짜 목차 "
            f"아님)를 무시하고 재추출 시도: status={result.status}, "
            f"bookmark_count={result.bookmark_count}, warnings={result.warnings}"
        )

    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_showcase(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
