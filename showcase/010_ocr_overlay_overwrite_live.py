"""showcase 010: indexed scanned PDF의 기존 OCR layer를 새 Document Parse OCR overlay로 교체한다.

이 showcase는 실제 고려대 계량경제학노트2 PDF의 첫 30쪽을 대상으로 public API
OcrOverlayBuilder를 호출한다. 입력 PDF에는 기존 bookmark가 있으므로 confirmation 없이
실행하면 자동 실패해야 하고, confirmation을 명시한 뒤에는 첫 30쪽에 대해 렌더링 이미지 + 새 invisible
text layer 방식의 searchable PDF를 생성해야 한다.

실행:
    uv run python showcase/010_ocr_overlay_overwrite_live.py

출력:
    showcase/outputs/010_ocr_overlay_overwrite_live/
        - kim_econometrics_note2_ocr.pdf
        - result.json
        - ocr_page_stats.jsonl / ocr_element_stats.jsonl / ocr_line_stats.jsonl
        - document_parse_cache/
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
from dotenv import load_dotenv

from pdfbooktree.ocr import OcrOverlayBuilder, OcrOverlayConfig
from pdfbooktree.ocr.builder import ExistingBookmarkConfirmationRequired

ROOT_DIR = Path(__file__).resolve().parents[1]
SHOWCASE_ID = "010_ocr_overlay_overwrite_live"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / SHOWCASE_ID
INPUT_PDF = (
    ROOT_DIR
    / "data"
    / "scanned-pdf-indexed"
    / "고려대_계량경제학노트2_김창진-compressed-indexed[econ stats book].pdf"
)
OUTPUT_PDF = OUTPUT_DIR / "kim_econometrics_note2_p001_030_ocr.pdf"
RESULT_JSON = OUTPUT_DIR / "result.json"
COMMAND = "uv run python showcase/010_ocr_overlay_overwrite_live.py"
PAGES_TO_PROCESS = list(range(1, 31))
SAMPLE_PAGES = [1, 3, 21, 30]


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    original_info = inspect_pdf(INPUT_PDF)
    confirmation_failure = prove_confirmation_gate()

    if not os.environ.get("UPSTAGE_API_KEY"):
        result = {
            "status": "blocked",
            "reason": "UPSTAGE_API_KEY가 없어 live Document Parse 호출을 실행할 수 없다.",
            "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
            "original": original_info,
            "confirmation_failure": confirmation_failure,
            "ran_at": now(),
        }
        write_result(result)
        record_showcase(result)
        raise RuntimeError(result["reason"])

    builder_result = OcrOverlayBuilder(
        OcrOverlayConfig(
            input_pdf=INPUT_PDF,
            output_pdf=OUTPUT_PDF,
            output_dir=OUTPUT_DIR,
            engine="upstage",
            render_dpi=300,
            force=True,
            confirm_bookmark_ocr_overwrite=True,
            pages=PAGES_TO_PROCESS,
            stats_word_level=False,
        )
    ).run()

    output_info = inspect_pdf(OUTPUT_PDF)
    stats_summary = summarize_stats(OUTPUT_DIR)
    text_samples = compare_text_samples(INPUT_PDF, OUTPUT_PDF, SAMPLE_PAGES)

    result = {
        "status": "processed",
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "output_pdf": str(OUTPUT_PDF.relative_to(ROOT_DIR)),
        "output_dir": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "construction_mode": "새 PDF를 page raster image와 Document Parse 기반 invisible text layer로 구성한다. 원본 PDF content stream과 기존 OCR text layer는 복사하지 않는다.",
        "confirmation_failure": confirmation_failure,
        "original": original_info,
        "output": output_info,
        "builder_result": {
            "status": builder_result.status,
            "page_count": builder_result.page_count,
            "processed_pages": builder_result.processed_pages,
            "engine": builder_result.engine,
            "cache_hit_count": builder_result.cache_hit_count,
            "cache_miss_count": builder_result.cache_miss_count,
            "line_stats_path": rel(builder_result.line_stats_path),
            "page_stats_path": rel(builder_result.page_stats_path),
            "element_stats_path": rel(builder_result.element_stats_path),
        },
        "stats_summary": stats_summary,
        "text_samples": text_samples,
        "proof": {
            "bookmark_confirmation_gate": confirmation_failure["raised_expected_exception"],
            "requested_output_page_count": output_info["page_count"] == len(PAGES_TO_PROCESS),
            "old_bookmarks_not_copied": original_info["bookmark_count"] > 0
            and output_info["bookmark_count"] == 0,
            "requested_pages_processed": builder_result.processed_pages == PAGES_TO_PROCESS,
            "line_stats_exists": (OUTPUT_DIR / "ocr_line_stats.jsonl").exists(),
        },
        "ran_at": now(),
    }
    write_result(result)
    record_showcase(result)


def prove_confirmation_gate() -> dict[str, Any]:
    try:
        OcrOverlayBuilder(
            OcrOverlayConfig(
                input_pdf=INPUT_PDF,
                output_pdf=OUTPUT_DIR / "should_not_be_created.pdf",
                output_dir=OUTPUT_DIR / "confirmation_gate",
                engine="upstage",
                render_dpi=300,
                force=True,
            )
        ).run()
    except ExistingBookmarkConfirmationRequired as exc:
        return {
            "raised_expected_exception": True,
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }
    return {
        "raised_expected_exception": False,
        "exception_type": None,
        "message": "confirmation 없이 실행이 통과했다. 이는 실패다.",
    }


def inspect_pdf(path: Path) -> dict[str, Any]:
    with fitz.open(path) as document:
        sample_text_counts = {
            str(page): len(document.load_page(page - 1).get_text("text"))
            for page in SAMPLE_PAGES
            if page <= document.page_count
        }
        return {
            "path": str(path.relative_to(ROOT_DIR)),
            "exists": path.exists(),
            "size_bytes": path.stat().st_size,
            "page_count": document.page_count,
            "bookmark_count": len(document.get_toc()),
            "sample_text_char_counts": sample_text_counts,
        }


def summarize_stats(output_dir: Path) -> dict[str, Any]:
    page_stats_path = output_dir / "ocr_page_stats.jsonl"
    line_stats_path = output_dir / "ocr_line_stats.jsonl"
    element_stats_path = output_dir / "ocr_element_stats.jsonl"

    page_rows = read_jsonl(page_stats_path)
    line_rows = read_jsonl(line_stats_path)
    element_rows = read_jsonl(element_stats_path)
    overlay_modes: dict[str, int] = {}
    categories: dict[str, int] = {}
    for row in element_rows:
        overlay_modes[str(row.get("overlay_mode"))] = overlay_modes.get(str(row.get("overlay_mode")), 0) + 1
        category = str(row.get("category") or "unknown")
        categories[category] = categories.get(category, 0) + 1

    return {
        "page_stats_rows": len(page_rows),
        "line_stats_rows": len(line_rows),
        "element_stats_rows": len(element_rows),
        "total_line_count": sum(int(row.get("line_count") or 0) for row in page_rows),
        "total_word_count": sum(int(row.get("word_count") or 0) for row in page_rows),
        "total_char_count": sum(int(row.get("char_count") or 0) for row in page_rows),
        "overlay_modes": dict(sorted(overlay_modes.items())),
        "top_categories": dict(sorted(categories.items(), key=lambda item: item[1], reverse=True)[:10]),
        "page_stats_path": str(page_stats_path.relative_to(ROOT_DIR)),
        "line_stats_path": str(line_stats_path.relative_to(ROOT_DIR)),
        "element_stats_path": str(element_stats_path.relative_to(ROOT_DIR)),
    }


def compare_text_samples(input_pdf: Path, output_pdf: Path, pages: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with fitz.open(input_pdf) as original, fitz.open(output_pdf) as overlay:
        for page in pages:
            if page > original.page_count or page > overlay.page_count:
                continue
            original_text = original.load_page(page - 1).get_text("text")
            overlay_text = overlay.load_page(page - 1).get_text("text")
            out.append(
                {
                    "pdf_page": page,
                    "original_char_count": len(original_text),
                    "overlay_char_count": len(overlay_text),
                    "overlay_preview": overlay_text[:500],
                }
            )
    return out


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_result(result: dict[str, Any]) -> None:
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def record_showcase(result: dict[str, Any]) -> None:
    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8")) if SHOWCASE_JSON.exists() else {"showcases": []}
    entry = {
        "id": SHOWCASE_ID,
        "purpose": "기존 bookmark와 OCR text layer가 있는 실제 scanned indexed PDF에서 OCR overlay public API가 confirmation gate를 강제하고, confirmation 후 첫 30쪽을 Upstage Document Parse live call로 새 text layer PDF로 생성함을 보여준다.",
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(RESULT_JSON.relative_to(ROOT_DIR)),
        "engine": "upstage/document-parse",
        "finding": build_finding(result),
        "command": COMMAND,
        "ran_at": result.get("ran_at", now()),
    }
    data["showcases"] = [item for item in data.get("showcases", []) if item.get("id") != SHOWCASE_ID]
    data["showcases"].append(entry)
    SHOWCASE_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_finding(result: dict[str, Any]) -> str:
    if result["status"] != "processed":
        return f"blocked: {result.get('reason')} confirmation_gate={result.get('confirmation_failure')}"
    stats = result["stats_summary"]
    proof = result["proof"]
    return (
        f"confirmation 없이 실행하면 {result['confirmation_failure']['exception_type']}로 실패했다. "
        f"confirmation 후 첫 30쪽을 OCR overlay 처리했다 "
        f"(cache_hit={result['builder_result']['cache_hit_count']}, cache_miss={result['builder_result']['cache_miss_count']}). "
        f"requested_output_page_count={proof['requested_output_page_count']}, old_bookmarks_not_copied={proof['old_bookmarks_not_copied']}, "
        f"line_stats_rows={stats['line_stats_rows']}, total_word_count={stats['total_word_count']}, overlay_modes={stats['overlay_modes']}."
    )


def rel(path: Path | None) -> str | None:
    return str(path.relative_to(ROOT_DIR)) if path is not None else None


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    main()



