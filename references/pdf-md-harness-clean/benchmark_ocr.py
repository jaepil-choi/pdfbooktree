#!/usr/bin/env python3
"""Compare OCR engines on representative mixed-language book pages."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path


SAMPLES = {
    "algorithms-nine": {"pages": [5, 20, 150], "anchors": {
        5: ["추천의 글", "컴퓨팅", "컴퓨터과학", "디지털 기술"],
        20: ["위대한 알고리즘", "기발한 트릭", "영국 수학자 하디", "아름다움 시험대"],
        150: ["입력 이미지", "픽셀", "가중 합계", "신경망", "연결"],
    }},
    "computer-science-human": {"pages": [5, 30, 300], "anchors": {
        5: ["서문", "인생의 거의 모든 문제", "샌프란시스코", "아파트"],
        30: ["뛰어들기", "비서 문제", "지원자", "확률"],
        300: ["휴리스틱의 장점", "해리 마코위츠", "평균-분산", "포트폴리오"],
    }},
    "mathematical-statistics": {"pages": [5, 30, 300], "anchors": {
        5: ["5장 표본분포의 근사", "중심극한정리", "6장 추정", "최대가능도 추정법"],
        30: ["누적분포함수", "확률변수", "정리 1.5.1", "증가성", "오른쪽 연속성"],
        300: ["최대가능도비 검정", "기각역", "표본분포", "유의수준"],
    }},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", action="append", required=True, help="book-slug=pdf-path")
    parser.add_argument("--vision-helper", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tesseract", default="tesseract")
    parser.add_argument("--pdftoppm", default="pdftoppm")
    parser.add_argument("--tessdata-dir", type=Path, required=True)
    parser.add_argument("--paddle-python", type=Path, help="Optional Python executable with PaddleOCR installed.")
    parser.add_argument("--dpi", type=int, default=180)
    return parser.parse_args()


def resolve_binary(value: str) -> str:
    return shutil.which(value) or value


def parse_pdf_args(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        slug, separator, path = value.partition("=")
        if not separator or slug not in SAMPLES or not path:
            raise SystemExit(f"--pdf must look like one of {', '.join(SAMPLES)}=/path/book.pdf")
        result[slug] = Path(path).expanduser()
    missing = set(SAMPLES) - set(result)
    if missing:
        raise SystemExit(f"Missing PDFs: {', '.join(sorted(missing))}")
    return result


def render_sample(pdf: Path, page: int, output: Path, pdftoppm: str, dpi: int) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = output.with_suffix("")
    proc = subprocess.run(
        [resolve_binary(pdftoppm), "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", str(pdf), str(prefix)],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or f"pdftoppm failed for {pdf} page {page}")
    generated = sorted(output.parent.glob(prefix.name + "-*.png"))
    if not generated:
        raise SystemExit(f"No rendered image for {pdf} page {page}")
    generated[0].replace(output)
    return output


def run_vision(images: list[Path], helper: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(helper), "--output-dir", str(output), *map(str, images)],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "Vision OCR failed")


def run_tesseract(images: list[Path], tesseract: str, tessdata_dir: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for image in images:
        destination = output / f"{image.stem}.txt"
        proc = subprocess.run(
            [resolve_binary(tesseract), str(image), str(destination.with_suffix("")), "--tessdata-dir", str(tessdata_dir), "-l", "kor+eng", "--psm", "3"],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(proc.stderr.strip() or f"Tesseract failed for {image}")
        generated = destination.with_suffix(".txt")
        if not generated.exists():
            raise SystemExit(f"Tesseract did not create {generated}")


def run_paddle(images: list[Path], python: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    runner = Path(__file__).with_name("paddle_ocr_runner.py")
    proc = subprocess.run(
        [str(python), str(runner), "--output-dir", str(output), *map(str, images)],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "PaddleOCR failed")


def metrics(text: str, anchors: list[str]) -> dict[str, int | float]:
    hangul = len(re.findall(r"[가-힣]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    digits = len(re.findall(r"\d", text))
    bad = text.count("�") + len(re.findall(r"\b(?:SASH|AAS|BSS|SS|OF\})\b", text))
    compact_text = re.sub(r"[^0-9A-Za-z가-힣]+", "", text).lower()
    hits = sum(
        1
        for anchor in anchors
        if re.sub(r"[^0-9A-Za-z가-힣]+", "", anchor).lower() in compact_text
    )
    return {
        "characters": len(text),
        "hangul": hangul,
        "latin": latin,
        "digits": digits,
        "anchor_hits": hits,
        "anchor_total": len(anchors),
        "bad_markers": bad,
        "anchor_score": round(hits / len(anchors), 4) if anchors else 0.0,
    }


def main() -> int:
    args = parse_args()
    pdfs = parse_pdf_args(args.pdf)
    out = args.output_dir
    render_dir = out / "rendered"
    vision_dir = out / "vision"
    tesseract_dir = out / "tesseract"
    paddle_dir = out / "paddle"
    images: list[Path] = []
    manifest: list[dict[str, object]] = []

    for slug, config in SAMPLES.items():
        for page in config["pages"]:
            image = render_dir / slug / f"page-{page:03d}.png"
            render_sample(pdfs[slug], page, image, args.pdftoppm, args.dpi)
            images.append(image)
            manifest.append({"slug": slug, "page": page, "image": str(image)})

    for slug in SAMPLES:
        book_images = [image for image in images if f"/{slug}/" in str(image)]
        run_vision(book_images, args.vision_helper, vision_dir / slug)
        run_tesseract(book_images, args.tesseract, args.tessdata_dir, tesseract_dir / slug)
        if args.paddle_python:
            run_paddle(book_images, args.paddle_python, paddle_dir / slug)

    rows: list[dict[str, object]] = []
    for item in manifest:
        slug = str(item["slug"])
        page = int(item["page"])
        stem = f"page-{page:03d}"
        vision_text = (vision_dir / slug / f"{stem}.txt").read_text(encoding="utf-8", errors="replace")
        tesseract_text = (tesseract_dir / slug / f"{stem}.txt").read_text(encoding="utf-8", errors="replace")
        anchors = list(SAMPLES[slug]["anchors"][page])
        row = {
            "book": slug,
            "page": page,
            "vision": metrics(vision_text, anchors),
            "tesseract": metrics(tesseract_text, anchors),
        }
        if args.paddle_python:
            row["paddle"] = metrics(
                (paddle_dir / slug / f"{stem}.txt").read_text(encoding="utf-8", errors="replace"),
                anchors,
            )
        rows.append(row)

    summary: dict[str, dict[str, float]] = {}
    engines = ["vision", "tesseract"] + (["paddle"] if args.paddle_python else [])
    for engine in engines:
        scores = [float(row[engine]["anchor_score"]) for row in rows]
        bad = [float(row[engine]["bad_markers"]) for row in rows]
        summary[engine] = {
            "mean_anchor_score": round(sum(scores) / len(scores), 4),
            "total_bad_markers": int(sum(bad)),
        }

    result = {
        "status": "completed",
        "samples": rows,
        "summary": summary,
        "winner": max(engines, key=lambda engine: summary[engine]["mean_anchor_score"]),
        "method": {
            "dpi": args.dpi,
            "language_pair": ["ko-KR", "en-US"],
            "tesseract_model": "tessdata_best/kor.traineddata",
            "paddle_model": "PP-OCRv5 Korean" if args.paddle_python else None,
        },
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# OCR benchmark", "", "| Engine | Mean anchor score | Bad markers |", "| --- | ---: | ---: |"]
    for engine in engines:
        lines.append(f"| {engine} | {summary[engine]['mean_anchor_score']:.2%} | {summary[engine]['total_bad_markers']} |")
    lines += ["", f"Winner: **{result['winner']}**", ""]
    (out / "benchmark.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
