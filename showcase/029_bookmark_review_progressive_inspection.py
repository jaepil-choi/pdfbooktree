"""showcase 029: 실제 PDF에서 bookmark review evidence 탐색 흐름을 검증한다.

native PDF, OCR PDF와 bookmark 수가 다른 실제 책을 public 단계형 API로 infer한 뒤
summary → attention item → 단일 item → 원본 page text 순서로 필요한 근거만 읽는다.
자동 품질 판정이나 synthetic/mock 입력은 사용하지 않는다.

실행
    uv run python showcase/029_bookmark_review_progressive_inspection.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree import (
    TypographyConfig,
    analyze_pdf,
    infer_bookmarks,
    inspect_plan_artifact,
    inspect_text,
    write_inference_artifacts,
)

try:  # 콘솔에서 한글이 깨지지 않게 한다.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT_DIR / "showcase" / "outputs" / "029_bookmark_review_progressive_inspection"
)
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "029_bookmark_review_progressive_inspection"

BOOKS = [
    {
        "key": "native_hull",
        "traits": ["native", "many_bookmarks"],
        "pdf": ROOT_DIR
        / "data"
        / "native-pdf-indexed"
        / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf",
    },
    {
        "key": "scanned_indexed_shreve",
        "traits": ["ocr", "many_bookmarks"],
        "pdf": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / (
            "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I "
            "The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf"
        ),
    },
    {
        "key": "ocr_math_statistics",
        "traits": ["ocr", "fewer_bookmarks"],
        "pdf": ROOT_DIR
        / "showcase"
        / "outputs"
        / "014_ocr_overlay_math_statistics"
        / "pdfs"
        / "수리통계학(개정판)-김우철_upocr_merged_ocr.pdf",
    },
]


def write_json(path: Path, value: Any) -> None:
    """UTF-8 JSON을 기록한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def review_book(spec: dict[str, Any]) -> dict[str, Any]:
    """실제 책 한 권을 infer하고 점진적 review 경로를 검증한다."""

    pdf: Path = spec["pdf"]
    if not pdf.is_file():
        raise FileNotFoundError(f"실제 showcase PDF가 없다: {pdf}")
    book_output = OUTPUT_DIR / spec["key"]
    config = TypographyConfig()
    analysis = analyze_pdf(pdf, config)
    inference = infer_bookmarks(analysis, config)
    if not inference.validation.valid or not inference.plan:
        raise RuntimeError(
            f"실제 typography plan이 review할 수 없다: key={spec['key']}, "
            f"valid={inference.validation.valid}, count={len(inference.plan)}, "
            f"warnings={inference.validation.warnings}"
        )
    artifacts = write_inference_artifacts(
        book_output,
        inference,
        input_pdf=pdf,
        total_pages=analysis.total_pages,
    )

    summary_inspection = inspect_plan_artifact(book_output)
    attention_inspection = inspect_plan_artifact(
        book_output,
        include_items=True,
        attention_only=True,
        limit=5,
    )
    attention_items = attention_inspection["bookmark_review_items"]
    selected_id = attention_items[0]["node_id"] if attention_items else "n0001"
    detail_inspection = inspect_plan_artifact(book_output, item_id=selected_id)
    detail = detail_inspection["bookmark_review_items"][0]
    original_page = inspect_text(pdf, [detail["pdf_page"]])["pages"][0]

    summary = summary_inspection["bookmark_review_summary"]
    plan_index = int(selected_id[1:]) - 1
    plan_item = inference.plan[plan_index]
    validation = {
        "summary_path_linked": (
            Path(summary_inspection["bookmark_review_summary_path"])
            == artifacts["bookmark_review_summary"]
        ),
        "items_path_linked": (
            Path(summary_inspection["bookmark_review_items_path"])
            == artifacts["bookmark_review_items"]
        ),
        "summary_count_matches_plan": (
            summary["plan_item_count"] == len(inference.plan)
        ),
        "candidate_mapping_complete": (
            summary["candidate_mapping"]["missing_count"] == 0
            and summary["candidate_mapping"]["ambiguous_count"] == 0
        ),
        "attention_filter_bounded": (
            attention_inspection["review_query"]["returned_item_count"] <= 5
        ),
        "detail_preserves_plan": (
            detail["title"] == plan_item.title
            and detail["source"] == plan_item.source
            and detail["confidence"] == plan_item.confidence
            and detail["evidence"] == plan_item.evidence
        ),
        "original_page_reachable": (original_page["pdf_page"] == detail["pdf_page"]),
        "review_policy_is_not_verdict": "판정이 아니다" in summary["review_policy"],
    }
    if not all(validation.values()):
        raise RuntimeError(
            f"review showcase validation이 실패했다: key={spec['key']}, {validation}"
        )
    return {
        "key": spec["key"],
        "traits": spec["traits"],
        "input_pdf": str(pdf.relative_to(ROOT_DIR)),
        "page_count": analysis.total_pages,
        "plan_item_count": len(inference.plan),
        "source_counts": summary["source_counts"],
        "attention_item_count": summary["attention"]["item_count"],
        "attention_returned_count": len(attention_items),
        "selected_item": {
            "node_id": selected_id,
            "title": detail["title"],
            "pdf_page": detail["pdf_page"],
            "source": detail["source"],
            "signals": detail["attention_signals"],
            "surrounding_line_count": len(detail["surrounding_lines"]),
            "page_preview_char_count": len(detail["page_text_preview"]),
            "original_page_char_count": original_page["char_count"],
        },
        "review_summary_path": str(
            artifacts["bookmark_review_summary"].relative_to(ROOT_DIR)
        ),
        "review_items_path": str(
            artifacts["bookmark_review_items"].relative_to(ROOT_DIR)
        ),
        "validation": validation,
        "validation_passed": True,
    }


def update_showcase_json(result: dict[str, Any]) -> None:
    """showcase 실행 결과를 registry에 upsert한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    books = result["books"]
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "실제 native/OCR PDF에서 review summary, attention filter, item detail과 "
            "원문 page로 이어지는 progressive inspection 흐름을 검증한다."
        ),
        "inputs": [book["input_pdf"] for book in books],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "finding": result["finding"],
        "command": (
            "uv run python showcase/029_bookmark_review_progressive_inspection.py"
        ),
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    showcases = data["showcases"]
    for index, existing in enumerate(showcases):
        if existing.get("id") == SHOWCASE_ID:
            showcases[index] = entry
            break
    else:
        showcases.append(entry)
    write_json(SHOWCASE_JSON, data)


def main() -> None:
    books = [review_book(spec) for spec in BOOKS]
    finding = "; ".join(
        f"{book['key']}: plan={book['plan_item_count']}, "
        f"attention={book['attention_item_count']}, valid={book['validation_passed']}"
        for book in books
    )
    result = {
        "books": books,
        "book_count": len(books),
        "all_validation_passed": all(book["validation_passed"] for book in books),
        "finding": finding,
    }
    write_json(OUTPUT_PATH, result)
    update_showcase_json(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
