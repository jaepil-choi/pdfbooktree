"""showcase 014: 실제 partial OCR artifact를 inspection public API로 확인한다.

실행:
    uv run python showcase/014_inspection_partial_ocr_artifact.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pdfbooktree import (
    inspect_bookmarks,
    inspect_ocr_artifact,
    inspect_page_count,
    inspect_text,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "014_inspection_partial_ocr_artifact"
INPUT_PDF = (
    ROOT_DIR
    / "data"
    / "scanned-pdf-not-indexed"
    / "수리통계학(개정판)-김우철_upocr_merged.pdf"
)
ARTIFACT_DIR = (
    ROOT_DIR / "showcase" / "outputs" / "014_ocr_overlay_math_statistics" / "artifacts"
)
OUTPUT_PATH = ARTIFACT_DIR.parent / "inspection_summary.json"


def record_showcase(summary: dict[str, object]) -> None:
    """실행 결과를 showcase registry에 기록한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "실제 수리통계학 PDF와 실행 중인 partial OCR artifact에서 inspection "
            "public API가 page count, page text, bookmark 부재, OCR 진행 상태와 "
            "cache page 연속성을 함께 보여주는지 확인한다."
        ),
        "inputs": [
            str(INPUT_PDF.relative_to(ROOT_DIR)),
            str(ARTIFACT_DIR.relative_to(ROOT_DIR)),
        ],
        "outputs": str(OUTPUT_PATH.relative_to(ROOT_DIR)),
        "finding": (
            f"pages={summary['page_count']}, bookmarks={summary['bookmark_count']}, "
            f"ocr_status={summary['ocr_status']}, completed={summary['completed_pages']}, "
            f"first_unprocessed={summary['first_unprocessed_page']}, "
            f"missing_completed={summary['missing_completed_pages']}, "
            f"duplicate_insertable={summary['duplicate_insertable_pages']}"
        ),
        "command": "uv run python showcase/014_inspection_partial_ocr_artifact.py",
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["showcases"] = [
        item for item in data["showcases"] if item.get("id") != SHOWCASE_ID
    ] + [entry]
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    """실제 PDF와 OCR artifact를 public inspection API로 검사한다."""

    page_count = inspect_page_count(INPUT_PDF)
    text = inspect_text(INPUT_PDF, [1])
    bookmarks = inspect_bookmarks(INPUT_PDF)
    ocr = inspect_ocr_artifact(ARTIFACT_DIR)
    summary = {
        "page_count": page_count["page_count"],
        "page_1_char_count": text["pages"][0]["char_count"],
        "bookmark_count": bookmarks["bookmark_count"],
        "ocr_status": ocr["status"],
        "completed_pages": ocr["progress_completed_pages"],
        "first_unprocessed_page": ocr["first_unprocessed_page"],
        "missing_completed_pages": ocr["missing_completed_pages"],
        "duplicate_insertable_pages": ocr["duplicate_insertable_pages"],
        "warnings": ocr["warnings"],
    }
    if summary["ocr_status"] not in {"partial", "complete"}:
        raise RuntimeError(
            f"OCR artifact 상태를 확인할 수 없다: {summary['ocr_status']}"
        )
    if summary["page_count"] != 637:
        raise RuntimeError(f"예상과 다른 page 수다: {summary['page_count']}")
    if summary["page_1_char_count"] <= 0:
        raise RuntimeError("첫 page text를 읽지 못했다.")
    if summary["ocr_status"] == "partial" and not summary["first_unprocessed_page"]:
        raise RuntimeError("partial OCR artifact의 다음 미처리 page가 없다.")

    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_showcase(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
