"""showcase 010: indexed scanned PDF의 기존 OCR layer를 새 Document Parse OCR overlay로 교체한다.

이 showcase는 실제 고려대 계량경제학노트2 PDF의 첫 30쪽을 대상으로 public API
OcrOverlayBuilder를 호출한다. 입력 PDF에는 기존 bookmark가 있으므로 confirmation 없이
실행하면 자동 실패해야 한다. confirmation을 명시한 뒤에는 원본 PDF의 page content와
bookmark를 유지하면서 overwrite 대상 페이지의 기존 text object만 제거하고, 그 위에 새
Document Parse 기반 invisible text layer를 삽입해야 한다.

실행:
    uv run python showcase/010_ocr_overlay_overwrite_live.py

출력:
    showcase/outputs/010_ocr_overlay_overwrite_live/
        - kim_econometrics_note2_p001_030_ocr.pdf
        - result.json
        - ocr_page_stats.jsonl / ocr_element_stats.jsonl / ocr_line_stats.jsonl
        - document_parse_cache/
"""

from __future__ import annotations

import hashlib
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
UNPROCESSED_SAMPLE_PAGE = max(PAGES_TO_PROCESS) + 1
DUPLICATE_TEXT_RATIO_THRESHOLD = 1.5


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
    visual_samples = compare_render_samples(INPUT_PDF, OUTPUT_PDF, SAMPLE_PAGES)
    text_samples = compare_text_samples(
        INPUT_PDF,
        OUTPUT_PDF,
        SAMPLE_PAGES,
        stats_summary["page_stats_by_page"],
    )
    text_replacement_check = compare_output_text_to_inserted_stats(
        OUTPUT_PDF,
        stats_summary["page_stats_by_page"],
    )
    unprocessed_page_check = compare_unprocessed_page_text(
        INPUT_PDF,
        OUTPUT_PDF,
        UNPROCESSED_SAMPLE_PAGE,
    )

    result = {
        "status": "processed",
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "output_pdf": str(OUTPUT_PDF.relative_to(ROOT_DIR)),
        "output_dir": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "construction_mode": (
            "원본 PDF 전체를 유지한다. overwrite 대상 page의 기존 BT...ET text object만 "
            "제거하고 같은 page에 Document Parse 기반 invisible text layer를 삽입한다. "
            "page raster image로 새 PDF를 만들지 않는다."
        ),
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
        "visual_samples": visual_samples,
        "text_samples": text_samples,
        "text_replacement_check": text_replacement_check,
        "unprocessed_page_check": unprocessed_page_check,
        "proof": {
            "bookmark_confirmation_gate": confirmation_failure[
                "raised_expected_exception"
            ],
            "source_page_count_preserved": output_info["page_count"]
            == original_info["page_count"],
            "source_bookmarks_preserved": output_info["bookmark_count"]
            == original_info["bookmark_count"],
            "requested_pages_processed": builder_result.processed_pages
            == PAGES_TO_PROCESS,
            "processed_page_stats_rows": stats_summary["page_stats_rows"]
            == len(PAGES_TO_PROCESS),
            "line_stats_exists": (OUTPUT_DIR / "ocr_line_stats.jsonl").exists(),
            "processed_pages_visual_preserved": all(
                row["render_identical"] for row in visual_samples
            ),
            "no_old_text_duplication_signal": not text_replacement_check[
                "pages_over_threshold"
            ],
            "unprocessed_page_text_preserved": unprocessed_page_check.get(
                "text_preserved"
            ),
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
        overlay_mode = str(row.get("overlay_mode"))
        overlay_modes[overlay_mode] = overlay_modes.get(overlay_mode, 0) + 1
        category = str(row.get("category") or "unknown")
        categories[category] = categories.get(category, 0) + 1

    return {
        "page_stats_rows": len(page_rows),
        "line_stats_rows": len(line_rows),
        "element_stats_rows": len(element_rows),
        "total_line_count": sum(int(row.get("line_count") or 0) for row in page_rows),
        "total_word_count": sum(int(row.get("word_count") or 0) for row in page_rows),
        "total_char_count": sum(int(row.get("char_count") or 0) for row in page_rows),
        "page_stats_by_page": {str(row["pdf_page"]): row for row in page_rows},
        "overlay_modes": dict(sorted(overlay_modes.items())),
        "top_categories": dict(
            sorted(categories.items(), key=lambda item: item[1], reverse=True)[:10]
        ),
        "page_stats_path": str(page_stats_path.relative_to(ROOT_DIR)),
        "line_stats_path": str(line_stats_path.relative_to(ROOT_DIR)),
        "element_stats_path": str(element_stats_path.relative_to(ROOT_DIR)),
    }


def compare_render_samples(
    input_pdf: Path,
    output_pdf: Path,
    pages: list[int],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with fitz.open(input_pdf) as original, fitz.open(output_pdf) as overlay:
        for page in pages:
            if page > original.page_count or page > overlay.page_count:
                continue
            original_png = (
                original.load_page(page - 1)
                .get_pixmap(dpi=96, alpha=False)
                .tobytes("png")
            )
            overlay_png = (
                overlay.load_page(page - 1)
                .get_pixmap(dpi=96, alpha=False)
                .tobytes("png")
            )
            out.append(
                {
                    "pdf_page": page,
                    "original_sha256": sha256_bytes(original_png),
                    "overlay_sha256": sha256_bytes(overlay_png),
                    "render_identical": original_png == overlay_png,
                }
            )
    return out


def compare_text_samples(
    input_pdf: Path,
    output_pdf: Path,
    pages: list[int],
    page_stats_by_page: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with fitz.open(input_pdf) as original, fitz.open(output_pdf) as overlay:
        for page in pages:
            if page > original.page_count or page > overlay.page_count:
                continue
            original_text = original.load_page(page - 1).get_text("text")
            overlay_text = overlay.load_page(page - 1).get_text("text")
            stats = page_stats_by_page.get(str(page), {})
            inserted_chars = int(stats.get("char_count") or 0)
            out.append(
                {
                    "pdf_page": page,
                    "original_char_count": len(original_text),
                    "overlay_char_count": len(overlay_text),
                    "inserted_stats_char_count": inserted_chars,
                    "overlay_to_inserted_char_ratio": ratio(
                        len(overlay_text), inserted_chars
                    ),
                    "overlay_preview": overlay_text[:500],
                }
            )
    return out


def compare_output_text_to_inserted_stats(
    output_pdf: Path,
    page_stats_by_page: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with fitz.open(output_pdf) as document:
        for page_key, stats in sorted(
            page_stats_by_page.items(), key=lambda item: int(item[0])
        ):
            pdf_page = int(page_key)
            if pdf_page > document.page_count:
                continue
            inserted_chars = int(stats.get("char_count") or 0)
            if inserted_chars <= 0:
                continue
            output_chars = len(document.load_page(pdf_page - 1).get_text("text"))
            rows.append(
                {
                    "pdf_page": pdf_page,
                    "inserted_stats_char_count": inserted_chars,
                    "output_char_count": output_chars,
                    "overlay_to_inserted_char_ratio": ratio(
                        output_chars, inserted_chars
                    ),
                }
            )

    pages_over_threshold = [
        row
        for row in rows
        if row["overlay_to_inserted_char_ratio"] > DUPLICATE_TEXT_RATIO_THRESHOLD
    ]
    max_ratio = max(
        [row["overlay_to_inserted_char_ratio"] for row in rows], default=None
    )
    return {
        "checked_pages": len(rows),
        "duplicate_text_ratio_threshold": DUPLICATE_TEXT_RATIO_THRESHOLD,
        "max_overlay_to_inserted_char_ratio": max_ratio,
        "pages_over_threshold": pages_over_threshold,
    }


def compare_unprocessed_page_text(
    input_pdf: Path,
    output_pdf: Path,
    pdf_page: int,
) -> dict[str, Any]:
    with fitz.open(input_pdf) as original, fitz.open(output_pdf) as overlay:
        if pdf_page > original.page_count or pdf_page > overlay.page_count:
            return {"pdf_page": pdf_page, "status": "missing_page"}
        original_text = original.load_page(pdf_page - 1).get_text("text")
        overlay_text = overlay.load_page(pdf_page - 1).get_text("text")
        return {
            "pdf_page": pdf_page,
            "status": "checked",
            "original_char_count": len(original_text),
            "overlay_char_count": len(overlay_text),
            "text_preserved": original_text == overlay_text,
        }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def write_result(result: dict[str, Any]) -> None:
    RESULT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def record_showcase(result: dict[str, Any]) -> None:
    data = (
        json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
        if SHOWCASE_JSON.exists()
        else {"showcases": []}
    )
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "기존 bookmark와 OCR text layer가 있는 실제 scanned indexed PDF에서 OCR overlay "
            "public API가 confirmation gate를 강제하고, confirmation 후 overwrite 대상 "
            "페이지의 기존 text layer를 새 Document Parse invisible text layer로 교체함을 보여준다."
        ),
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(RESULT_JSON.relative_to(ROOT_DIR)),
        "engine": "upstage/document-parse",
        "finding": build_finding(result),
        "command": COMMAND,
        "ran_at": result.get("ran_at", now()),
    }
    data["showcases"] = [
        item for item in data.get("showcases", []) if item.get("id") != SHOWCASE_ID
    ]
    data["showcases"].append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_finding(result: dict[str, Any]) -> str:
    if result["status"] != "processed":
        return (
            f"blocked: {result.get('reason')} "
            f"confirmation_gate={result.get('confirmation_failure')}"
        )
    stats = result["stats_summary"]
    proof = result["proof"]
    replacement = result["text_replacement_check"]
    return (
        f"confirmation 없이 실행하면 {result['confirmation_failure']['exception_type']}로 실패했다. "
        f"confirmation 후 {len(PAGES_TO_PROCESS)}쪽을 OCR overlay overwrite 처리했다 "
        f"(cache_hit={result['builder_result']['cache_hit_count']}, "
        f"cache_miss={result['builder_result']['cache_miss_count']}). "
        f"source_page_count_preserved={proof['source_page_count_preserved']}, "
        f"source_bookmarks_preserved={proof['source_bookmarks_preserved']}, "
        f"processed_pages_visual_preserved={proof['processed_pages_visual_preserved']}, "
        f"no_old_text_duplication_signal={proof['no_old_text_duplication_signal']} "
        f"(max_overlay_to_inserted_char_ratio={replacement['max_overlay_to_inserted_char_ratio']}), "
        f"unprocessed_page_text_preserved={proof['unprocessed_page_text_preserved']}, "
        f"line_stats_rows={stats['line_stats_rows']}, total_word_count={stats['total_word_count']}, "
        f"overlay_modes={stats['overlay_modes']}."
    )


def rel(path: Path | None) -> str | None:
    return str(path.relative_to(ROOT_DIR)) if path is not None else None


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    main()
