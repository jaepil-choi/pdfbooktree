#!/usr/bin/env python3
"""Recreate chapter Markdown with macOS Vision OCR in page batches."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", action="append", required=True, help="slug|pdf-path|detection-report.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--vision-helper", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--chunk-size", type=int, default=60)
    return parser.parse_args()


def parse_books(values: list[str]) -> list[tuple[str, Path, Path]]:
    books = []
    for value in values:
        parts = value.split("|", 2)
        if len(parts) != 3:
            raise SystemExit("--book must look like slug|/path/book.pdf|/path/detection-report.json")
        slug, pdf, report = parts
        books.append((slug, Path(pdf), Path(report)))
    return books


def run_chunk(
    script: Path,
    pdf: Path,
    output: Path,
    start: int,
    end: int,
    helper: Path,
    dpi: int,
) -> dict[int, str]:
    command = [
        sys.executable,
        str(script),
        str(pdf),
        str(output),
        "--engine",
        "vision",
        "--vision-helper",
        str(helper),
        "--dpi",
        str(dpi),
        "--title",
        "OCR chunk",
        "--start-page",
        str(start),
        "--end-page",
        str(end),
    ]
    proc = subprocess.run(command, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or f"OCR failed for {pdf} pages {start}-{end}")
    markdown = output.read_text(encoding="utf-8")
    blocks = re.split(r"(?=<!-- page \d+ -->\n)", markdown)
    pages: dict[int, str] = {}
    for block in blocks:
        match = re.match(r"<!-- page (\d+) -->\n", block)
        if match:
            pages[int(match.group(1))] = block.rstrip() + "\n"
    return pages


def write_range(path: Path, title: str, pages: dict[int, str], start: int, end: int) -> None:
    blocks = [pages.get(page, f"<!-- page {page} -->\n") for page in range(start, end + 1)]
    path.write_text(f"# {title}\n\n" + "\n".join(blocks).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.chunk_size < 1:
        raise SystemExit("--chunk-size must be positive")
    script = Path(__file__).with_name("ocr_pdf_to_markdown.py")

    for slug, pdf, report_path in parse_books(args.book):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        boundaries = report["boundaries"]
        page_count = int(report["page_count"])
        book_output = args.output_dir / slug
        chunk_output = book_output / ".chunks"
        book_output.mkdir(parents=True, exist_ok=True)
        chunk_output.mkdir(parents=True, exist_ok=True)
        shutil.copy2(report_path, book_output / "detection-report.json")

        pages: dict[int, str] = {}
        for start in range(1, page_count + 1, args.chunk_size):
            end = min(page_count, start + args.chunk_size - 1)
            print(f"[{slug}] OCR pages {start}-{end}", flush=True)
            pages.update(run_chunk(script, pdf, chunk_output / f"{start:04d}-{end:04d}.md", start, end, args.vision_helper, args.dpi))

        first_start = int(boundaries[0]["page"])
        if first_start > 1:
            write_range(book_output / "front-matter.md", "앞부분: 머리말·목차·용어 정리", pages, 1, first_start - 1)

        index_lines = ["# PDF Chapters", "", "macOS Vision OCR로 다시 생성한 챕터별 Markdown입니다.", ""]
        for index, boundary in enumerate(boundaries):
            start = int(boundary["page"])
            end = int(boundaries[index + 1]["page"]) - 1 if index + 1 < len(boundaries) else page_count
            number = int(boundary["number"])
            title = str(boundary.get("title") or f"Chapter {number}")
            write_range(book_output / f"ch-{number:02d}.md", title, pages, start, end)
            index_lines.append(f"- `ch-{number:02d}.md`: {title} ({start}-{end}쪽)")
        (book_output / "README.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
