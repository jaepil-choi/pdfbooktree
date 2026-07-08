"""experiment 061: OCR sandwich PDF를 화질 손실 없이 압축할 수 있는지 검증한다.

배경: 060에서 원본 page content 보존 방식은 용량은 작았지만 기존 visible text와 새 OCR
text가 중복되어 production 반영이 불가능하다고 판단했다. 사용자는 화질 저하 없는 압축을
원한다. 따라서 이번 실험은 기존 `outputs/quant_world_ocr/quant_world_ocr.pdf`를 대상으로
lossless 재압축만 비교한다.

lossless 기준:
- 이미지 픽셀을 grayscale/JPEG/JBIG2 등으로 바꾸지 않는다.
- 샘플 페이지 렌더 PNG hash가 baseline과 동일해야 한다.
- 샘플 페이지 text extraction hash도 baseline과 동일해야 한다.
- RGB 채널이 정확히 같은 페이지는 DeviceGray 변환이 이론적으로 lossless지만, 실제 전체
  378개 이미지 중 몇 개나 가능한지만 확인하고 이번 출력 후보에는 적용하지 않는다.

실행:
    uv run python experiments/061_lossless_ocr_pdf_compression.py

출력:
    experiments/outputs/061_lossless_ocr_pdf_compression/
        - quant_world_ocr_pikepdf_lossless.pdf
        - quant_world_ocr_pymupdf_lossless.pdf
        - verify.json
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import pikepdf
from PIL import Image, ImageChops, ImageStat

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "061_lossless_ocr_pdf_compression"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
INPUT_PDF = ROOT_DIR / "outputs" / "quant_world_ocr" / "quant_world_ocr.pdf"
PIKEPDF_OUTPUT = OUTPUT_DIR / "quant_world_ocr_pikepdf_lossless.pdf"
PYMUPDF_OUTPUT = OUTPUT_DIR / "quant_world_ocr_pymupdf_lossless.pdf"
SAMPLE_PAGES = [1, 42, 378]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_size(path: Path) -> int:
    return path.stat().st_size


def analyze_images(pdf_path: Path) -> dict[str, Any]:
    doc = fitz.open(pdf_path)
    try:
        total_image_bytes = 0
        exact_gray_pages: list[int] = []
        exact_bw_pages: list[int] = []
        image_ext_counts: dict[str, int] = {}
        filter_counts: dict[str, int] = {}
        image_count = 0
        for page_index in range(doc.page_count):
            for image in doc.get_page_images(page_index, full=True):
                image_count += 1
                xref = image[0]
                filter_name = str(image[8])
                filter_counts[filter_name] = filter_counts.get(filter_name, 0) + 1
                info = doc.extract_image(xref)
                image_bytes = info.get("image", b"")
                total_image_bytes += len(image_bytes)
                ext = str(info.get("ext", "?"))
                image_ext_counts[ext] = image_ext_counts.get(ext, 0) + 1
                pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                r, g, b = pil.split()
                r_bytes = r.tobytes()
                exact_gray = r_bytes == g.tobytes() == b.tobytes()
                if exact_gray:
                    exact_gray_pages.append(page_index + 1)
                    if set(r_bytes) <= {0, 255}:
                        exact_bw_pages.append(page_index + 1)
        return {
            "page_count": doc.page_count,
            "image_count": image_count,
            "total_extracted_image_bytes": total_image_bytes,
            "image_ext_counts": image_ext_counts,
            "filter_counts": filter_counts,
            "exact_gray_image_count": len(exact_gray_pages),
            "exact_gray_pages": exact_gray_pages,
            "exact_bw_image_count": len(exact_bw_pages),
            "exact_bw_pages": exact_bw_pages,
        }
    finally:
        doc.close()


def render_page_png(pdf_path: Path, pdf_page: int, dpi: int = 96) -> bytes:
    doc = fitz.open(pdf_path)
    try:
        return doc[pdf_page - 1].get_pixmap(dpi=dpi, alpha=False).tobytes("png")
    finally:
        doc.close()


def text_hash(pdf_path: Path, pdf_page: int) -> dict[str, Any]:
    doc = fitz.open(pdf_path)
    try:
        text = doc[pdf_page - 1].get_text()
        return {"chars": len(text), "sha256": sha256(text.encode("utf-8"))}
    finally:
        doc.close()


def image_diff_summary(left_png: bytes, right_png: bytes) -> dict[str, Any]:
    if left_png == right_png:
        return {
            "identical": True,
            "bbox": None,
            "sum_abs": 0.0,
            "mean_abs": [0.0, 0.0, 0.0],
        }
    left = Image.open(io.BytesIO(left_png)).convert("RGB")
    right = Image.open(io.BytesIO(right_png)).convert("RGB")
    diff = ImageChops.difference(left, right)
    stat = ImageStat.Stat(diff)
    return {
        "identical": False,
        "bbox": list(diff.getbbox()) if diff.getbbox() else None,
        "sum_abs": float(sum(stat.sum)),
        "mean_abs": [float(value) for value in stat.mean],
    }


def verify_candidate(candidate: Path, baseline: Path) -> dict[str, Any]:
    pages = []
    for pdf_page in SAMPLE_PAGES:
        baseline_png = render_page_png(baseline, pdf_page)
        candidate_png = render_page_png(candidate, pdf_page)
        baseline_text = text_hash(baseline, pdf_page)
        candidate_text = text_hash(candidate, pdf_page)
        pages.append(
            {
                "pdf_page": pdf_page,
                "render": image_diff_summary(baseline_png, candidate_png),
                "baseline_render_sha256": sha256(baseline_png),
                "candidate_render_sha256": sha256(candidate_png),
                "baseline_text": baseline_text,
                "candidate_text": candidate_text,
                "text_identical": baseline_text == candidate_text,
            }
        )
    return {
        "sample_pages": pages,
        "all_sample_renders_identical": all(
            row["render"]["identical"] for row in pages
        ),
        "all_sample_text_identical": all(row["text_identical"] for row in pages),
    }


def make_pikepdf_lossless(input_pdf: Path, output_pdf: Path) -> None:
    with pikepdf.open(input_pdf) as pdf:
        pdf.remove_unreferenced_resources()
        pdf.save(
            output_pdf,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            recompress_flate=True,
        )


def make_pymupdf_lossless(input_pdf: Path, output_pdf: Path) -> None:
    doc = fitz.open(input_pdf)
    try:
        doc.save(
            output_pdf,
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            use_objstms=1,
            compression_effort=100,
        )
    finally:
        doc.close()


def append_experiment_record(verify: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    candidates = verify["candidates"]
    best = min(candidates, key=lambda item: item["size_bytes"])
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": "기존 OCR sandwich PDF를 이미지 화질 손실 없이 줄일 수 있는 lossless 압축 후보를 비교한다.",
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "lossless_criteria": [
            "이미지 색공간이나 픽셀 값을 바꾸지 않는다.",
            "샘플 페이지 렌더 PNG hash가 baseline과 같아야 한다.",
            "샘플 페이지 text extraction hash가 baseline과 같아야 한다.",
        ],
        "baseline_size_bytes": verify["baseline_size_bytes"],
        "image_analysis": verify["image_analysis"],
        "candidates": candidates,
        "best_candidate": best,
        "finding": verify["finding"],
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"].append(entry)
    write_json(EXPERIMENTS_JSON, data)


def main() -> None:
    start = time.time()
    if not INPUT_PDF.exists():
        raise FileNotFoundError(INPUT_PDF)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    image_analysis = analyze_images(INPUT_PDF)
    make_pikepdf_lossless(INPUT_PDF, PIKEPDF_OUTPUT)
    make_pymupdf_lossless(INPUT_PDF, PYMUPDF_OUTPUT)

    baseline_size = file_size(INPUT_PDF)
    candidates = []
    for label, path in [
        ("pikepdf_lossless", PIKEPDF_OUTPUT),
        ("pymupdf_lossless", PYMUPDF_OUTPUT),
    ]:
        size = file_size(path)
        verification = verify_candidate(path, INPUT_PDF)
        candidates.append(
            {
                "label": label,
                "path": str(path.relative_to(ROOT_DIR)),
                "size_bytes": size,
                "saved_bytes": baseline_size - size,
                "size_ratio": round(size / baseline_size, 6),
                "verification": verification,
            }
        )

    best = min(candidates, key=lambda item: item["size_bytes"])
    verify = {
        "experiment_id": EXPERIMENT_ID,
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "baseline_size_bytes": baseline_size,
        "elapsed_sec": round(time.time() - start, 3),
        "image_analysis": image_analysis,
        "candidates": candidates,
    }
    if (
        best["verification"]["all_sample_renders_identical"]
        and best["verification"]["all_sample_text_identical"]
    ):
        verify["finding"] = (
            f"lossless 후보 중 {best['label']}가 가장 작았다. "
            f"{baseline_size:,} bytes -> {best['size_bytes']:,} bytes "
            f"({best['size_ratio']:.2%}, {best['saved_bytes']:,} bytes 감소). "
            "샘플 렌더와 텍스트 hash는 baseline과 동일했다. 다만 내부 이미지는 이미 "
            "FlateDecode+PNG predictor 15이고 RGB 채널이 정확히 같은 이미지는 "
            f"{image_analysis['exact_gray_image_count']}개뿐이라, 엄격한 lossless만으로는 큰 폭의 압축은 어렵다."
        )
    else:
        verify["finding"] = (
            "가장 작은 후보가 샘플 렌더 또는 텍스트 hash 동일성 검증을 통과하지 못했다. "
            "lossless 후보로 채택하면 안 된다."
        )

    write_json(OUTPUT_DIR / "verify.json", verify)
    append_experiment_record(verify)
    print(json.dumps(verify, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
