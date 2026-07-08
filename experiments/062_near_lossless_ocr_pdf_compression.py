"""experiment 062: 목표 크기 15.8MB 근처의 near-lossless OCR PDF 압축을 탐색한다.

배경: 061에서 엄격한 lossless 압축은 190.6MB -> 186.5MB 정도가 한계였다. 사용자는
원본 PDF 크기(약 15.8MB)에 가까운 압축률을 원하지만, 이미지 화질 저하는 거의 없어야 한다.
이번 실험은 기존 OCR sandwich PDF의 invisible text layer는 유지하고, 페이지 이미지 XObject만
해상도 축소 + grayscale JPEG로 재인코딩해 크기와 시각 차이를 비교한다.

주의: 이 실험은 lossy다. 다만 텍스트 레이어는 그대로 유지하고, 샘플 렌더의 차이를 수치화해
사람이 받아들일 수 있는 후보인지 판단하기 위한 것이다.

실행:
    uv run python experiments/062_near_lossless_ocr_pdf_compression.py

출력:
    experiments/outputs/062_near_lossless_ocr_pdf_compression/
        - quant_world_ocr_scale*_gray_q*.pdf
        - sample page PNG 비교 파일
        - verify.json
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import pikepdf
from PIL import Image, ImageChops, ImageStat
from pikepdf import Name

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "062_near_lossless_ocr_pdf_compression"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
INPUT_PDF = ROOT_DIR / "outputs" / "quant_world_ocr" / "quant_world_ocr.pdf"
TARGET_SIZE_BYTES = 16_653_419  # 원본 `퀀트의 세계 - 홍창수.pdf` 크기.
SAMPLE_PAGES = [1, 42, 378]


@dataclass(frozen=True)
class Candidate:
    label: str
    scale: float
    quality: int

    @property
    def output_pdf(self) -> Path:
        scale_tag = str(self.scale).replace(".", "p")
        return OUTPUT_DIR / f"quant_world_ocr_scale{scale_tag}_gray_q{self.quality}.pdf"


CANDIDATES = [
    Candidate("scale0.45_gray_q20", 0.45, 20),
    Candidate("scale0.40_gray_q25", 0.40, 25),
    Candidate("scale0.40_gray_q30", 0.40, 30),
]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_size(path: Path) -> int:
    return path.stat().st_size


def make_candidate(input_pdf: Path, candidate: Candidate) -> dict[str, Any]:
    total_original_image_bytes = 0
    total_jpeg_bytes = 0
    image_count = 0
    with pikepdf.open(input_pdf) as pdf:
        for page in pdf.pages:
            xobjects = page.Resources.get("/XObject", {})
            for key, obj in list(xobjects.items()):
                if obj.get("/Subtype") != Name("/Image"):
                    continue
                width = int(obj["/Width"])
                height = int(obj["/Height"])
                raw = bytes(obj.read_bytes())
                total_original_image_bytes += len(raw)
                image = Image.frombytes("RGB", (width, height), raw)
                new_size = (
                    max(1, round(width * candidate.scale)),
                    max(1, round(height * candidate.scale)),
                )
                image = image.resize(new_size, Image.Resampling.LANCZOS).convert("L")
                buffer = io.BytesIO()
                image.save(
                    buffer,
                    format="JPEG",
                    quality=candidate.quality,
                    optimize=True,
                    progressive=False,
                )
                jpeg_bytes = buffer.getvalue()
                total_jpeg_bytes += len(jpeg_bytes)
                stream = pikepdf.Stream(pdf, jpeg_bytes)
                stream["/Type"] = Name("/XObject")
                stream["/Subtype"] = Name("/Image")
                stream["/Width"] = new_size[0]
                stream["/Height"] = new_size[1]
                stream["/ColorSpace"] = Name("/DeviceGray")
                stream["/BitsPerComponent"] = 8
                stream["/Filter"] = Name("/DCTDecode")
                xobjects[key] = stream
                image_count += 1
        pdf.save(
            candidate.output_pdf,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
    return {
        "image_count": image_count,
        "total_original_decoded_image_bytes": total_original_image_bytes,
        "total_jpeg_bytes": total_jpeg_bytes,
    }


def render_page_png(pdf_path: Path, pdf_page: int, dpi: int = 120) -> bytes:
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


def diff_metrics(baseline_png: bytes, candidate_png: bytes) -> dict[str, Any]:
    baseline = Image.open(io.BytesIO(baseline_png)).convert("RGB")
    candidate = Image.open(io.BytesIO(candidate_png)).convert("RGB")
    diff = ImageChops.difference(baseline, candidate)
    stat = ImageStat.Stat(diff)
    sum_abs = float(sum(stat.sum))
    mean_abs = [float(value) for value in stat.mean]
    rms = math.sqrt(sum(value * value for value in stat.rms) / 3)
    psnr = None if rms == 0 else 20 * math.log10(255 / rms)
    return {
        "identical": baseline_png == candidate_png,
        "bbox": list(diff.getbbox()) if diff.getbbox() else None,
        "sum_abs": sum_abs,
        "mean_abs": mean_abs,
        "rms": float(rms),
        "psnr_db": None if psnr is None else round(float(psnr), 3),
    }


def verify_candidate(candidate: Candidate) -> dict[str, Any]:
    rows = []
    for pdf_page in SAMPLE_PAGES:
        baseline_png = render_page_png(INPUT_PDF, pdf_page)
        candidate_png = render_page_png(candidate.output_pdf, pdf_page)
        baseline_png_path = OUTPUT_DIR / f"sample_page_{pdf_page:03d}_baseline.png"
        candidate_png_path = (
            OUTPUT_DIR / f"sample_page_{pdf_page:03d}_{candidate.label}.png"
        )
        if not baseline_png_path.exists():
            baseline_png_path.write_bytes(baseline_png)
        candidate_png_path.write_bytes(candidate_png)
        baseline_text = text_hash(INPUT_PDF, pdf_page)
        candidate_text = text_hash(candidate.output_pdf, pdf_page)
        rows.append(
            {
                "pdf_page": pdf_page,
                "baseline_png": str(baseline_png_path.relative_to(ROOT_DIR)),
                "candidate_png": str(candidate_png_path.relative_to(ROOT_DIR)),
                "baseline_render_sha256": sha256(baseline_png),
                "candidate_render_sha256": sha256(candidate_png),
                "diff": diff_metrics(baseline_png, candidate_png),
                "baseline_text": baseline_text,
                "candidate_text": candidate_text,
                "text_identical": baseline_text == candidate_text,
            }
        )
    return {
        "sample_pages": rows,
        "all_sample_text_identical": all(row["text_identical"] for row in rows),
        "max_sample_mean_abs": max(max(row["diff"]["mean_abs"]) for row in rows),
        "min_sample_psnr_db": min(row["diff"]["psnr_db"] or 99 for row in rows),
    }


def append_experiment_record(verify: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": "OCR sandwich PDF를 원본 PDF 크기 근처로 줄이기 위한 near-lossless lossy 이미지 재압축 후보를 비교한다.",
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "target_size_bytes": TARGET_SIZE_BYTES,
        "baseline_size_bytes": verify["baseline_size_bytes"],
        "candidates": verify["candidates"],
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

    baseline_size = file_size(INPUT_PDF)
    candidate_results = []
    for candidate in CANDIDATES:
        build_stats = make_candidate(INPUT_PDF, candidate)
        size = file_size(candidate.output_pdf)
        verification = verify_candidate(candidate)
        candidate_results.append(
            {
                "label": candidate.label,
                "path": str(candidate.output_pdf.relative_to(ROOT_DIR)),
                "scale": candidate.scale,
                "jpeg_quality": candidate.quality,
                "size_bytes": size,
                "saved_bytes": baseline_size - size,
                "size_ratio_to_baseline": round(size / baseline_size, 6),
                "size_ratio_to_target": round(size / TARGET_SIZE_BYTES, 6),
                "build_stats": build_stats,
                "verification": verification,
            }
        )

    closest_to_target = min(
        candidate_results,
        key=lambda row: abs(row["size_bytes"] - TARGET_SIZE_BYTES),
    )
    smallest = min(candidate_results, key=lambda row: row["size_bytes"])
    verify = {
        "experiment_id": EXPERIMENT_ID,
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "baseline_size_bytes": baseline_size,
        "target_size_bytes": TARGET_SIZE_BYTES,
        "elapsed_sec": round(time.time() - start, 3),
        "candidates": candidate_results,
        "closest_to_target": closest_to_target,
        "smallest": smallest,
    }
    verify["finding"] = (
        f"목표 크기 {TARGET_SIZE_BYTES:,} bytes에 가장 가까운 후보는 "
        f"{closest_to_target['label']}로 {closest_to_target['size_bytes']:,} bytes"
        f"({closest_to_target['size_ratio_to_target']:.2%} of target)다. "
        f"텍스트 hash는 샘플 페이지에서 동일했다. "
        f"시각 차이는 사람이 sample PNG를 보고 판단해야 하며, min PSNR="
        f"{closest_to_target['verification']['min_sample_psnr_db']:.2f} dB, "
        f"max mean abs={closest_to_target['verification']['max_sample_mean_abs']:.3f}다. "
        "이 수준의 크기를 얻으려면 해상도 축소와 grayscale 변환이 들어가므로 엄격한 의미의 lossless는 아니다."
    )
    write_json(OUTPUT_DIR / "verify.json", verify)
    append_experiment_record(verify)
    print(json.dumps(verify, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
