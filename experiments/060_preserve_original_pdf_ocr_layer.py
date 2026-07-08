"""experiment 060: 원본 PDF 페이지를 보존한 채 invisible OCR text layer만 추가한다.

배경: `outputs/quant_world_ocr/quant_world_ocr.pdf`는 각 페이지를 300dpi RGB PNG로
다시 렌더링한 뒤 invisible text layer와 합친 PDF라 원본 16.7MB가 190.6MB로 커졌다.
이번 실험은 원본 PDF의 기존 page content stream과 이미지 압축을 그대로 유지하고,
기존 Document Parse insertable cache의 좌표와 텍스트만 PyMuPDF로 얹는 방식을 검증한다.

중요한 구현 선택:
- `Page.insert_textbox(..., render_mode=3)`는 한글을 `???`로 재추출하는 문제가 있었다.
- `Page.insert_htmlbox(..., opacity=0)`는 한글 재추출은 되지만 line마다 호출하면 메모리가 크게 늘었다.
- `TextWriter + Font(fontfile=...) + render_mode=3`는 한글 재추출과 invisible rendering이 모두 되고,
  page마다 한 번만 write하면 되어 전체 책 실험에 더 적합하다.

실행:
    uv run python experiments/060_preserve_original_pdf_ocr_layer.py

출력:
    experiments/outputs/060_preserve_original_pdf_ocr_layer/
        - quant_world_original_preserved_ocr.pdf
        - verify.json
        - sample_page_001_input.png / sample_page_001_output.png
        - sample_page_042_input.png / sample_page_042_output.png
        - sample_page_378_input.png / sample_page_378_output.png
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "060_preserve_original_pdf_ocr_layer"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

INPUT_PDF = ROOT_DIR / "data" / "scanned-pdf-not-indexed" / "퀀트의 세계 - 홍창수.pdf"
PREVIOUS_OCR_PDF = ROOT_DIR / "outputs" / "quant_world_ocr" / "quant_world_ocr.pdf"
INSERTABLE_CACHE_DIR = (
    ROOT_DIR / "outputs" / "quant_world_ocr" / "document_parse_cache" / "insertable"
)
OUTPUT_PDF = OUTPUT_DIR / "quant_world_original_preserved_ocr.pdf"

FONT_FILE = Path(r"C:\Windows\Fonts\malgun.ttf")
SAMPLE_PAGES = [1, 42, 378]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def insert_invisible_lines(doc: fitz.Document, page_models: list[dict[str, Any]]) -> dict[str, Any]:
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
            except Exception as exc:
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

def render_sample_pngs(input_pdf: Path, output_pdf: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    src = fitz.open(input_pdf)
    out = fitz.open(output_pdf)
    try:
        for pdf_page in SAMPLE_PAGES:
            if pdf_page > src.page_count or pdf_page > out.page_count:
                continue
            input_pix = src[pdf_page - 1].get_pixmap(dpi=96, alpha=False)
            output_pix = out[pdf_page - 1].get_pixmap(dpi=96, alpha=False)
            input_png = input_pix.tobytes("png")
            output_png = output_pix.tobytes("png")
            input_path = OUTPUT_DIR / f"sample_page_{pdf_page:03d}_input.png"
            output_path = OUTPUT_DIR / f"sample_page_{pdf_page:03d}_output.png"
            input_path.write_bytes(input_png)
            output_path.write_bytes(output_png)
            rows.append(
                {
                    "pdf_page": pdf_page,
                    "input_png": str(input_path.relative_to(ROOT_DIR)),
                    "output_png": str(output_path.relative_to(ROOT_DIR)),
                    "input_sha256": sha256_bytes(input_png),
                    "output_sha256": sha256_bytes(output_png),
                    "render_identical": input_png == output_png,
                }
            )
    finally:
        src.close()
        out.close()
    return rows


def extracted_text_summary(input_pdf: Path, output_pdf: Path) -> dict[str, Any]:
    before = fitz.open(input_pdf)
    after = fitz.open(output_pdf)
    try:
        before_chars = 0
        after_chars = 0
        samples: list[dict[str, Any]] = []
        for pdf_page in SAMPLE_PAGES:
            if pdf_page > before.page_count or pdf_page > after.page_count:
                continue
            before_text = before[pdf_page - 1].get_text()
            after_text = after[pdf_page - 1].get_text()
            before_chars += len(before_text)
            after_chars += len(after_text)
            samples.append(
                {
                    "pdf_page": pdf_page,
                    "before_chars": len(before_text),
                    "after_chars": len(after_text),
                    "after_preview": " ".join(after_text.split())[:300],
                }
            )
        return {
            "sample_before_chars": before_chars,
            "sample_after_chars": after_chars,
            "sample_pages": samples,
        }
    finally:
        before.close()
        after.close()


def append_experiment_record(verify: dict[str, Any]) -> None:
    data = read_json(EXPERIMENTS_JSON)
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "퀀트의 세계 PDF에 대해 원본 page content stream과 이미지 압축을 보존한 채 "
            "Document Parse 기반 invisible OCR text layer만 추가할 수 있는지 검증한다."
        ),
        "inputs": [
            str(INPUT_PDF.relative_to(ROOT_DIR)),
            str(INSERTABLE_CACHE_DIR.relative_to(ROOT_DIR)),
        ],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "PyMuPDF TextWriter(render_mode=3)로 line 단위 invisible text를 추가했다. "
            "insert_textbox(render_mode=3)는 한글이 ???로 재추출되어 제외했다."
        ),
        "output_pdf_size": verify["sizes"]["output_pdf"],
        "previous_sandwich_pdf_size": verify["sizes"]["previous_sandwich_pdf"],
        "input_pdf_size": verify["sizes"]["input_pdf"],
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
    if not INSERTABLE_CACHE_DIR.exists():
        raise FileNotFoundError(INSERTABLE_CACHE_DIR)
    if not FONT_FILE.exists():
        raise FileNotFoundError(
            f"한글 invisible text 삽입에 필요한 폰트를 찾을 수 없다: {FONT_FILE}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    page_models = load_insertable_pages()
    input_doc = fitz.open(INPUT_PDF)
    try:
        doc_page_count = input_doc.page_count
    finally:
        input_doc.close()

    cached_page_numbers = {int(page["pdf_page"]) for page in page_models}
    missing_cache_pages = [
        pdf_page
        for pdf_page in range(1, doc_page_count + 1)
        if pdf_page not in cached_page_numbers
    ]

    doc = fitz.open(INPUT_PDF)
    try:
        insert_stats = insert_invisible_lines(doc, page_models)
        doc.save(
            OUTPUT_PDF,
            garbage=4,
            deflate=True,
            deflate_fonts=True,
            use_objstms=1,
            compression_effort=100,
        )
    finally:
        doc.close()

    visual_sample = render_sample_pngs(INPUT_PDF, OUTPUT_PDF)
    text_extract_sample = extracted_text_summary(INPUT_PDF, OUTPUT_PDF)
    sizes = {
        "input_pdf": file_size(INPUT_PDF),
        "previous_sandwich_pdf": file_size(PREVIOUS_OCR_PDF),
        "output_pdf": file_size(OUTPUT_PDF),
    }
    verify = {
        "experiment_id": EXPERIMENT_ID,
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "output_pdf": str(OUTPUT_PDF.relative_to(ROOT_DIR)),
        "page_count": doc_page_count,
        "cache_page_count": len(page_models),
        "missing_cache_pages": missing_cache_pages,
        "font_file": str(FONT_FILE),
        "elapsed_sec": round(time.time() - start, 3),
        "sizes": sizes,
        "size_ratios": {
            "output_vs_input": round(sizes["output_pdf"] / sizes["input_pdf"], 4),
            "output_vs_previous_sandwich": round(
                sizes["output_pdf"] / sizes["previous_sandwich_pdf"], 4
            ),
        },
        "insert_stats": insert_stats,
        "visual_sample": visual_sample,
        "text_extract_sample": text_extract_sample,
    }

    visual_ok = all(row["render_identical"] for row in visual_sample)
    before_chars = text_extract_sample["sample_before_chars"]
    after_chars = text_extract_sample["sample_after_chars"]
    duplicate_text_failure = before_chars > 0 and after_chars > before_chars
    size_ok = sizes["output_pdf"] < sizes["previous_sandwich_pdf"] * 0.5
    verify["existing_text_problem"] = {
        "sample_before_chars": before_chars,
        "sample_after_chars": after_chars,
        "is_duplicate_text_failure": duplicate_text_failure,
    }
    if duplicate_text_failure:
        verify["finding"] = (
            "원본 보존+새 invisible layer 삽입만으로는 production 반영하면 안 된다. "
            f"출력 PDF는 {sizes['output_pdf']:,} bytes로 기존 sandwich PDF의 "
            f"{verify['size_ratios']['output_vs_previous_sandwich']:.2%}까지 줄고 "
            f"샘플 렌더 동일성={visual_ok}이지만, 원본 PDF에 이미 추출 가능한 텍스트가 있어 "
            f"샘플 추출 텍스트가 {before_chars:,}자에서 {after_chars:,}자로 늘었다. "
            "기존 텍스트를 지우지 못하면 검색/복사 결과가 중복되므로 이 방식은 실패다."
        )
    elif visual_ok and size_ok and insert_stats["lines_failed"] == 0:
        verify["finding"] = (
            "원본 보존 방식은 성공으로 판단한다. "
            f"출력 PDF는 {sizes['output_pdf']:,} bytes로 기존 sandwich PDF "
            f"{sizes['previous_sandwich_pdf']:,} bytes의 "
            f"{verify['size_ratios']['output_vs_previous_sandwich']:.2%} 수준이다. "
            f"삽입 line={insert_stats['lines_inserted']}, 실패 line={insert_stats['lines_failed']}."
        )
    else:
        verify["finding"] = (
            "원본 보존 방식은 추가 검토가 필요하다. "
            f"샘플 렌더 동일성={visual_ok}, 크기 감소={size_ok}, "
            f"실패 line={insert_stats['lines_failed']}."
        )

    write_json(OUTPUT_DIR / "verify.json", verify)
    append_experiment_record(verify)
    print(json.dumps(verify, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

