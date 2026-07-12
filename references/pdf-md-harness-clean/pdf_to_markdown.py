#!/usr/bin/env python3
"""Convert a text-backed PDF into practical Markdown for Notion import."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PAGE_BREAK = "\f"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("output_md", type=Path)
    parser.add_argument("--title", help="Markdown H1 title. Defaults to PDF filename.")
    parser.add_argument("--start-page", type=int, help="First page to extract, 1-based.")
    parser.add_argument("--end-page", type=int, help="Last page to extract, inclusive.")
    parser.add_argument(
        "--keep-page-markers",
        action="store_true",
        help="Render page markers as visible Markdown headings instead of comments.",
    )
    parser.add_argument(
        "--pdftotext",
        default="pdftotext",
        help="Path to Poppler pdftotext binary.",
    )
    return parser.parse_args()


def run_pdftotext(
    input_pdf: Path,
    pdftotext: str,
    start_page: int | None,
    end_page: int | None,
) -> str:
    binary = shutil.which(pdftotext) or (pdftotext if Path(pdftotext).exists() else None)
    if not binary:
        raise SystemExit(
            "pdftotext was not found. Install Poppler, or pass --pdftotext /path/to/pdftotext."
        )

    with tempfile.NamedTemporaryFile(suffix=".txt") as tmp:
        cmd = [binary, "-layout", "-enc", "UTF-8"]
        if start_page is not None:
            cmd += ["-f", str(start_page)]
        if end_page is not None:
            cmd += ["-l", str(end_page)]
        cmd += [str(input_pdf), tmp.name]
        proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
        if proc.returncode != 0:
            raise SystemExit(proc.stderr.strip() or "pdftotext failed")
        return Path(tmp.name).read_text(encoding="utf-8", errors="replace")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    return text


def looks_like_page_number(line: str) -> bool:
    stripped = line.strip()
    return bool(re.fullmatch(r"[-\s]*\d{1,4}[-\s]*", stripped))


def ascii_upper_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha() and char.isascii()]
    if not letters:
        return 0.0
    upper = [char for char in letters if char.isupper()]
    return len(upper) / len(letters)


def looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 90:
        return False
    if re.search(r"[=<>≤≥]|\b(?:lim|log|sin|cos|cdf)\b", stripped, flags=re.IGNORECASE):
        return False
    if re.match(r"^(chapter|part|appendix)\b", stripped, flags=re.IGNORECASE):
        return True
    if re.match(r"^\d{1,3}\s*[.-]\s*\d{1,3}(?:\s*[.-]\s*\d{1,3})?\s+\S+", stripped):
        return True
    if re.match(r"^(\d+|[IVXLCDM]+)[.)]\s+\S+", stripped):
        return True
    if ascii_upper_ratio(stripped) >= 0.75 and len(stripped.split()) <= 10:
        return True
    return False


def join_wrapped_lines(lines: list[str]) -> list[str]:
    blocks: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(" ".join(part.strip() for part in paragraph).strip())
            paragraph.clear()

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if looks_like_page_number(stripped):
            continue
        if looks_like_heading(stripped):
            flush()
            blocks.append(f"## {stripped}")
            continue
        if re.match(r"^([-*+]|\d+[.)])\s+", stripped):
            flush()
            blocks.append(stripped)
            continue
        if re.search(r"\s{3,}", line) and len(stripped) > 20:
            flush()
            blocks.append(stripped)
            continue
        paragraph.append(stripped)

    flush()
    return blocks


def pages_to_markdown(
    raw_text: str,
    title: str,
    keep_page_markers: bool,
    start_page: int | None,
) -> str:
    raw_pages = normalize_text(raw_text).split(PAGE_BREAK)
    pages = [page for page in raw_pages if page.strip()]
    md: list[str] = [f"# {title}", ""]
    first_page = start_page or 1

    for index, page in enumerate(pages, start=first_page):
        if keep_page_markers:
            md.extend([f"### Page {index}", ""])
        else:
            md.extend([f"<!-- page {index} -->", ""])
        blocks = join_wrapped_lines(page.splitlines())
        for block in blocks:
            md.extend([block, ""])

    return "\n".join(md).strip() + "\n"


def main() -> int:
    args = parse_args()
    if not args.input_pdf.exists():
        raise SystemExit(f"Input PDF not found: {args.input_pdf}")
    if args.start_page is not None and args.start_page < 1:
        raise SystemExit("--start-page must be >= 1")
    if (
        args.start_page is not None
        and args.end_page is not None
        and args.end_page < args.start_page
    ):
        raise SystemExit("--end-page must be >= --start-page")

    title = args.title or args.input_pdf.stem
    raw_text = run_pdftotext(args.input_pdf, args.pdftotext, args.start_page, args.end_page)
    markdown = pages_to_markdown(raw_text, title, args.keep_page_markers, args.start_page)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(markdown, encoding="utf-8")
    print(f"Wrote {args.output_md} ({len(markdown):,} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
