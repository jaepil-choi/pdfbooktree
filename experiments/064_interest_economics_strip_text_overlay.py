"""experiment 064: 금리의 경제학 원본 PDF에서 text object를 지우고 OCR layer를 다시 얹는다.

배경: 060은 clean native PDF였던 `퀀트의 세계`를 대상으로 해서 잘못된 음성 사례가 됐다.
이번 실험은 새로 OCR을 마친 scanned PDF `금리의 경제학`에서 원본 PDF의 이미지와 압축을
가능한 유지하면서 기존 text object(BT...ET)를 제거하고, Document Parse insertable cache로
새 invisible OCR text layer만 얹을 수 있는지 검증한다.

실행:
    uv run python experiments/064_interest_economics_strip_text_overlay.py

출력:
    experiments/outputs/064_interest_economics_strip_text_overlay/
        - interest_economics_text_stripped.pdf
        - interest_economics_original_stripped_overlay_ocr.pdf
        - verify.json
        - sample_page_*_*.png
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import pikepdf

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "064_interest_economics_strip_text_overlay"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

INPUT_PDF = ROOT_DIR / "data" / "scanned-pdf-not-indexed" / "금리의_경제학_-_홍완표.pdf"
SANDWICH_OCR_PDF = (
    ROOT_DIR / "outputs" / "interest_economics_ocr" / "interest_economics_ocr.pdf"
)
INSERTABLE_CACHE_DIR = (
    ROOT_DIR
    / "outputs"
    / "interest_economics_ocr"
    / "document_parse_cache"
    / "insertable"
)
STRIPPED_PDF = OUTPUT_DIR / "interest_economics_text_stripped.pdf"
OUTPUT_PDF = OUTPUT_DIR / "interest_economics_original_stripped_overlay_ocr.pdf"
FONT_FILE = Path(r"C:\Windows\Fonts\malgun.ttf")
SAMPLE_PAGES = [1, 42, 264]

TEXT_OBJECT_BEGIN = "BT"
TEXT_OBJECT_END = "ET"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_insertable_pages() -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for path in INSERTABLE_CACHE_DIR.glob("*.json"):
        page = read_json(path)
        page["_cache_file"] = str(path.relative_to(ROOT_DIR))
        pages.append(page)
    pages.sort(key=lambda item: int(item["pdf_page"]))
    return pages


def text_lines(page_model: dict[str, Any]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for element in page_model.get("elements", []):
        for line in element.get("lines", []):
            text = " ".join(str(line.get("text", "")).split())
            if not text:
                continue
            lines.append(
                {
                    "text": text,
                    "bbox": line["bbox"],
                    "category": element.get("category"),
                    "overlay_mode": element.get("overlay_mode"),
                }
            )
    return lines


def scale_rect(
    bbox: dict[str, Any],
    *,
    page_rect: fitz.Rect,
    width_px: int,
    height_px: int,
) -> fitz.Rect:
    sx = page_rect.width / width_px
    sy = page_rect.height / height_px
    rect = fitz.Rect(
        float(bbox["x0"]) * sx,
        float(bbox["y0"]) * sy,
        float(bbox["x1"]) * sx,
        float(bbox["y1"]) * sy,
    )
    if rect.height < 2:
        rect.y1 = rect.y0 + 2
    if rect.width < 2:
        rect.x1 = rect.x0 + 2
    return rect


def strip_text_objects(input_pdf: Path, output_pdf: Path) -> dict[str, Any]:
    """page content stream에서 BT...ET text object를 통째로 제거한다."""

    stats = {
        "pages_seen": 0,
        "pages_changed": 0,
        "removed_ops": 0,
        "parse_failed_pages": [],
    }
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.open(input_pdf) as pdf:
        for page_index, page in enumerate(pdf.pages):
            stats["pages_seen"] += 1
            try:
                instructions = pikepdf.parse_content_stream(page)
            except Exception as exc:  # noqa: BLE001
                stats["parse_failed_pages"].append(
                    {
                        "pdf_page": page_index + 1,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue

            stripped = []
            in_text_object = False
            removed_on_page = 0
            for operands, operator in instructions:
                op = str(operator)
                if op == TEXT_OBJECT_BEGIN:
                    in_text_object = True
                    removed_on_page += 1
                    continue
                if in_text_object:
                    removed_on_page += 1
                    if op == TEXT_OBJECT_END:
                        in_text_object = False
                    continue
                stripped.append((operands, operator))

            if removed_on_page:
                page.Contents = pdf.make_stream(
                    pikepdf.unparse_content_stream(stripped)
                )
                stats["pages_changed"] += 1
                stats["removed_ops"] += removed_on_page

        pdf.save(
            output_pdf,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
    return stats


def insert_invisible_lines(
    doc: fitz.Document, page_models: list[dict[str, Any]]
) -> dict[str, Any]:
    font = fitz.Font(fontfile=str(FONT_FILE))
    stats: dict[str, Any] = {
        "pages_seen": 0,
        "pages_inserted": 0,
        "lines_inserted": 0,
        "lines_failed": 0,
        "failed_samples": [],
    }

    for page_model in page_models:
        pdf_page = int(page_model["pdf_page"])
        if pdf_page < 1 or pdf_page > doc.page_count:
            continue

        stats["pages_seen"] += 1
        page = doc[pdf_page - 1]
        lines = text_lines(page_model)
        if not lines:
            continue

        width_px = int(page_model["width_px"])
        height_px = int(page_model["height_px"])
        writer = fitz.TextWriter(page.rect)
        inserted_on_page = 0
        for line in lines:
            rect = scale_rect(
                line["bbox"],
                page_rect=page.rect,
                width_px=width_px,
                height_px=height_px,
            )
            font_size = max(3.0, min(18.0, rect.height * 0.88))
            try:
                writer.append(
                    (rect.x0, rect.y1),
                    line["text"],
                    font=font,
                    fontsize=font_size,
                )
            except Exception as exc:  # noqa: BLE001
                stats["lines_failed"] += 1
                if len(stats["failed_samples"]) < 20:
                    stats["failed_samples"].append(
                        {
                            "pdf_page": pdf_page,
                            "text": line["text"][:120],
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                continue

            inserted_on_page += 1
            stats["lines_inserted"] += 1

        if inserted_on_page:
            writer.write_text(page, overlay=True, render_mode=3)
            stats["pages_inserted"] += 1

    return stats


def build_overlay_pdf(
    stripped_pdf: Path, output_pdf: Path, page_models: list[dict[str, Any]]
) -> dict[str, Any]:
    doc = fitz.open(stripped_pdf)
    try:
        insert_stats = insert_invisible_lines(doc, page_models)
        doc.save(
            output_pdf,
            garbage=4,
            deflate=True,
            deflate_fonts=True,
            use_objstms=1,
            compression_effort=100,
        )
    finally:
        doc.close()
    return insert_stats


def render_page_png(pdf_path: Path, pdf_page: int, dpi: int = 96) -> bytes:
    doc = fitz.open(pdf_path)
    try:
        return doc[pdf_page - 1].get_pixmap(dpi=dpi, alpha=False).tobytes("png")
    finally:
        doc.close()


def render_samples() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pdf_page in SAMPLE_PAGES:
        if pdf_page > page_count(INPUT_PDF):
            continue
        original_png = render_page_png(INPUT_PDF, pdf_page)
        stripped_png = render_page_png(STRIPPED_PDF, pdf_page)
        overlay_png = render_page_png(OUTPUT_PDF, pdf_page)
        original_path = OUTPUT_DIR / f"sample_page_{pdf_page:03d}_original.png"
        stripped_path = OUTPUT_DIR / f"sample_page_{pdf_page:03d}_stripped.png"
        overlay_path = OUTPUT_DIR / f"sample_page_{pdf_page:03d}_overlay.png"
        original_path.write_bytes(original_png)
        stripped_path.write_bytes(stripped_png)
        overlay_path.write_bytes(overlay_png)
        rows.append(
            {
                "pdf_page": pdf_page,
                "original_png": str(original_path.relative_to(ROOT_DIR)),
                "stripped_png": str(stripped_path.relative_to(ROOT_DIR)),
                "overlay_png": str(overlay_path.relative_to(ROOT_DIR)),
                "original_sha256": sha256_bytes(original_png),
                "stripped_sha256": sha256_bytes(stripped_png),
                "overlay_sha256": sha256_bytes(overlay_png),
                "stripped_visual_identical": original_png == stripped_png,
                "overlay_visual_identical": original_png == overlay_png,
            }
        )
    return rows


def page_count(pdf_path: Path) -> int:
    doc = fitz.open(pdf_path)
    try:
        return doc.page_count
    finally:
        doc.close()


def text_summary() -> dict[str, Any]:
    original = fitz.open(INPUT_PDF)
    stripped = fitz.open(STRIPPED_PDF)
    overlay = fitz.open(OUTPUT_PDF)
    try:
        samples: list[dict[str, Any]] = []
        totals = {
            "original_chars": 0,
            "stripped_chars": 0,
            "overlay_chars": 0,
        }
        for pdf_page in SAMPLE_PAGES:
            if pdf_page > original.page_count:
                continue
            original_text = original[pdf_page - 1].get_text()
            stripped_text = stripped[pdf_page - 1].get_text()
            overlay_text = overlay[pdf_page - 1].get_text()
            totals["original_chars"] += len(original_text)
            totals["stripped_chars"] += len(stripped_text)
            totals["overlay_chars"] += len(overlay_text)
            samples.append(
                {
                    "pdf_page": pdf_page,
                    "original_chars": len(original_text),
                    "stripped_chars": len(stripped_text),
                    "overlay_chars": len(overlay_text),
                    "overlay_preview": " ".join(overlay_text.split())[:300],
                }
            )
        return {"sample_totals": totals, "sample_pages": samples}
    finally:
        original.close()
        stripped.close()
        overlay.close()


def append_experiment_record(verify: dict[str, Any]) -> None:
    data = read_json(EXPERIMENTS_JSON)
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "금리의 경제학 원본 PDF의 이미지와 압축을 가능한 보존한 채 기존 text object를 "
            "지우고 Document Parse 기반 invisible OCR layer만 다시 얹을 수 있는지 검증한다."
        ),
        "inputs": [
            str(INPUT_PDF.relative_to(ROOT_DIR)),
            str(INSERTABLE_CACHE_DIR.relative_to(ROOT_DIR)),
            str(SANDWICH_OCR_PDF.relative_to(ROOT_DIR)),
        ],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "pikepdf parse_content_stream으로 page content의 BT...ET text object를 제거한 뒤, "
            "PyMuPDF TextWriter(render_mode=3)로 line 단위 invisible text를 추가했다."
        ),
        "sizes": verify["sizes"],
        "size_ratios": verify["size_ratios"],
        "strip_stats": verify["strip_stats"],
        "insert_stats": verify["insert_stats"],
        "visual_sample": verify["visual_sample"],
        "text_extract_sample": verify["text_extract_sample"],
        "finding": verify["finding"],
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"].append(entry)
    write_json(EXPERIMENTS_JSON, data)


def main() -> None:
    start = time.time()
    if not INPUT_PDF.exists():
        raise FileNotFoundError(INPUT_PDF)
    if not SANDWICH_OCR_PDF.exists():
        raise FileNotFoundError(SANDWICH_OCR_PDF)
    if not INSERTABLE_CACHE_DIR.exists():
        raise FileNotFoundError(INSERTABLE_CACHE_DIR)
    if not FONT_FILE.exists():
        raise FileNotFoundError(FONT_FILE)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    page_models = load_insertable_pages()
    doc_page_count = page_count(INPUT_PDF)
    cached_page_numbers = {int(page["pdf_page"]) for page in page_models}
    missing_cache_pages = [
        pdf_page
        for pdf_page in range(1, doc_page_count + 1)
        if pdf_page not in cached_page_numbers
    ]

    strip_stats = strip_text_objects(INPUT_PDF, STRIPPED_PDF)
    insert_stats = build_overlay_pdf(STRIPPED_PDF, OUTPUT_PDF, page_models)
    visual_sample = render_samples()
    text_extract_sample = text_summary()

    sizes = {
        "input_pdf": file_size(INPUT_PDF),
        "stripped_pdf": file_size(STRIPPED_PDF),
        "overlay_pdf": file_size(OUTPUT_PDF),
        "sandwich_ocr_pdf": file_size(SANDWICH_OCR_PDF),
    }
    size_ratios = {
        "overlay_vs_input": round(sizes["overlay_pdf"] / sizes["input_pdf"], 6),
        "overlay_vs_sandwich": round(
            sizes["overlay_pdf"] / sizes["sandwich_ocr_pdf"], 6
        ),
        "stripped_vs_input": round(sizes["stripped_pdf"] / sizes["input_pdf"], 6),
    }
    visual_ok = all(row["overlay_visual_identical"] for row in visual_sample)
    strip_visual_ok = all(row["stripped_visual_identical"] for row in visual_sample)
    text_totals = text_extract_sample["sample_totals"]
    text_ok = text_totals["overlay_chars"] > text_totals["stripped_chars"]
    no_duplicate_signal = text_totals["original_chars"] == text_totals["stripped_chars"]

    if visual_ok and strip_visual_ok and text_ok and insert_stats["lines_failed"] == 0:
        finding = (
            "성공: 원본 PDF에서 text object 제거 후 새 invisible OCR layer를 얹어도 샘플 렌더가 "
            "원본과 동일했고, 추출 텍스트는 overlay 후 생겼다. "
            f"출력 PDF는 {sizes['overlay_pdf']:,} bytes로 sandwich OCR PDF "
            f"{sizes['sandwich_ocr_pdf']:,} bytes의 {size_ratios['overlay_vs_sandwich']:.2%}다. "
            f"원본/strip 샘플 텍스트 길이 동일 여부={no_duplicate_signal}, "
            f"제거된 text op={strip_stats['removed_ops']}, 삽입 line={insert_stats['lines_inserted']}."
        )
    else:
        finding = (
            "추가 검토 필요: strip 또는 overlay 과정에서 샘플 렌더/텍스트 조건 일부가 맞지 않았다. "
            f"strip_visual_ok={strip_visual_ok}, overlay_visual_ok={visual_ok}, "
            f"text_ok={text_ok}, failed_lines={insert_stats['lines_failed']}, "
            f"removed_text_ops={strip_stats['removed_ops']}."
        )

    verify = {
        "experiment_id": EXPERIMENT_ID,
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "stripped_pdf": str(STRIPPED_PDF.relative_to(ROOT_DIR)),
        "output_pdf": str(OUTPUT_PDF.relative_to(ROOT_DIR)),
        "sandwich_ocr_pdf": str(SANDWICH_OCR_PDF.relative_to(ROOT_DIR)),
        "page_count": doc_page_count,
        "cache_page_count": len(page_models),
        "missing_cache_pages": missing_cache_pages,
        "font_file": str(FONT_FILE),
        "elapsed_sec": round(time.time() - start, 3),
        "sizes": sizes,
        "size_ratios": size_ratios,
        "strip_stats": strip_stats,
        "insert_stats": insert_stats,
        "visual_sample": visual_sample,
        "text_extract_sample": text_extract_sample,
        "finding": finding,
    }
    write_json(OUTPUT_DIR / "verify.json", verify)
    append_experiment_record(verify)
    print(json.dumps(verify, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
