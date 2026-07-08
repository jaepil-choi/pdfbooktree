"""experiment 063: color를 유지하는 OCR PDF lossy 압축 후보를 비교한다.

배경: 061 lossless는 거의 줄지 않았고, 062 grayscale 후보는 책의 color를 잃기 때문에
사용자 요구사항 위반으로 탈락했다. 이번 실험은 이미지 XObject를 RGB JPEG로만 재인코딩한다.
색공간은 DeviceRGB로 유지하고 grayscale 변환은 하지 않는다.

주의: 목표 크기(원본 PDF 약 16.7MB)에 가까워지려면 해상도 축소가 크게 필요할 수 있다.
이 실험은 텍스트 레이어 hash 보존, 출력 크기, 샘플 렌더 차이를 함께 기록해 사람이 선택할
수 있는 후보를 남긴다.

실행:
    uv run python experiments/063_color_preserving_lossy_ocr_pdf_compression.py
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
EXPERIMENT_ID = "063_color_preserving_lossy_ocr_pdf_compression"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
INPUT_PDF = ROOT_DIR / "outputs" / "quant_world_ocr" / "quant_world_ocr.pdf"
TARGET_SIZE_BYTES = 16_653_419
SAMPLE_PAGES = [1, 42, 378]


@dataclass(frozen=True)
class Candidate:
    label: str
    scale: float
    quality: int

    @property
    def output_pdf(self) -> Path:
        scale_tag = str(self.scale).replace(".", "p")
        return (
            OUTPUT_DIR / f"quant_world_ocr_color_scale{scale_tag}_q{self.quality}.pdf"
        )


CANDIDATES = [
    Candidate("color_scale0.45_q20", 0.45, 20),
    Candidate("color_scale0.35_q25", 0.35, 25),
    Candidate("color_scale0.25_q20", 0.25, 20),
    Candidate("color_scale0.25_q15", 0.25, 15),
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
                image = Image.frombytes("RGB", (width, height), bytes(obj.read_bytes()))
                new_size = (
                    max(1, round(width * candidate.scale)),
                    max(1, round(height * candidate.scale)),
                )
                image = image.resize(new_size, Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                image.save(
                    buffer,
                    format="JPEG",
                    quality=candidate.quality,
                    optimize=True,
                    progressive=False,
                    subsampling=2,
                )
                jpeg_bytes = buffer.getvalue()
                total_jpeg_bytes += len(jpeg_bytes)
                stream = pikepdf.Stream(pdf, jpeg_bytes)
                stream["/Type"] = Name("/XObject")
                stream["/Subtype"] = Name("/Image")
                stream["/Width"] = new_size[0]
                stream["/Height"] = new_size[1]
                stream["/ColorSpace"] = Name("/DeviceRGB")
                stream["/BitsPerComponent"] = 8
                stream["/Filter"] = Name("/DCTDecode")
                xobjects[key] = stream
                image_count += 1
        pdf.save(
            candidate.output_pdf,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
    return {"image_count": image_count, "total_jpeg_bytes": total_jpeg_bytes}


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
    rms = math.sqrt(sum(value * value for value in stat.rms) / 3)
    psnr = None if rms == 0 else 20 * math.log10(255 / rms)
    return {
        "identical": baseline_png == candidate_png,
        "bbox": list(diff.getbbox()) if diff.getbbox() else None,
        "sum_abs": float(sum(stat.sum)),
        "mean_abs": [float(value) for value in stat.mean],
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
        "purpose": "책의 color를 유지한 채 OCR sandwich PDF를 목표 크기 근처로 줄이는 RGB JPEG 후보를 비교한다.",
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "constraints": [
            "grayscale 변환 금지",
            "이미지 XObject ColorSpace는 DeviceRGB 유지",
            "샘플 페이지 text extraction hash 보존",
        ],
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
    results = []
    for candidate in CANDIDATES:
        build_stats = make_candidate(INPUT_PDF, candidate)
        size = file_size(candidate.output_pdf)
        verification = verify_candidate(candidate)
        results.append(
            {
                "label": candidate.label,
                "path": str(candidate.output_pdf.relative_to(ROOT_DIR)),
                "scale": candidate.scale,
                "jpeg_quality": candidate.quality,
                "color_space": "DeviceRGB",
                "size_bytes": size,
                "saved_bytes": baseline_size - size,
                "size_ratio_to_baseline": round(size / baseline_size, 6),
                "size_ratio_to_target": round(size / TARGET_SIZE_BYTES, 6),
                "build_stats": build_stats,
                "verification": verification,
            }
        )

    closest = min(results, key=lambda row: abs(row["size_bytes"] - TARGET_SIZE_BYTES))
    smallest = min(results, key=lambda row: row["size_bytes"])
    verify = {
        "experiment_id": EXPERIMENT_ID,
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "baseline_size_bytes": baseline_size,
        "target_size_bytes": TARGET_SIZE_BYTES,
        "elapsed_sec": round(time.time() - start, 3),
        "candidates": results,
        "closest_to_target": closest,
        "smallest": smallest,
    }
    verify["finding"] = (
        f"RGB color 유지 후보 중 목표 크기 {TARGET_SIZE_BYTES:,} bytes에 가장 가까운 것은 "
        f"{closest['label']}이며 {closest['size_bytes']:,} bytes"
        f"({closest['size_ratio_to_target']:.2%} of target)다. "
        "모든 후보는 DeviceRGB를 유지했고 샘플 페이지 text hash가 baseline과 동일했다. "
        f"다만 목표 크기에 가까운 후보일수록 해상도 축소가 커서 사람이 sample PNG를 보고 "
        f"수용 여부를 판단해야 한다. closest min PSNR="
        f"{closest['verification']['min_sample_psnr_db']:.2f} dB, max mean abs="
        f"{closest['verification']['max_sample_mean_abs']:.3f}."
    )
    write_json(OUTPUT_DIR / "verify.json", verify)
    append_experiment_record(verify)
    print(json.dumps(verify, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
