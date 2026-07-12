#!/usr/bin/env python3
"""Split PDF chapters into numbered or table-of-contents subsections."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from pdf_to_chapters import (
    Candidate,
    boundaries_from_map,
    choose_boundaries,
    detect_candidates,
    extract_pages,
    find_binary,
)
from pdf_to_markdown import PAGE_BREAK, join_wrapped_lines, normalize_text
from pdf_toc import TocSection, parse_toc_subsections


SUBSECTION_RE = re.compile(
    r"^\s*(?P<chapter>\d{1,3})\s*(?:[.-]\s*)"
    r"(?P<sub>\d{1,3}(?:\s*[.-]\s*\d{1,3})?)\s*(?P<title>.*)$"
)
EXERCISE_HEADING_RE = re.compile(r"^\s*(?:[<〈]?\s*)연습문제", re.IGNORECASE)


@dataclass
class Subsection:
    chapter: int
    number: str
    title: str
    page: int
    line: int
    raw_line: str
    source: str = "body-number"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--boundary-map", type=Path)
    parser.add_argument("--title-map", type=Path)
    parser.add_argument(
        "--subsection-map",
        type=Path,
        help="Optional JSON map of expected subsection IDs by chapter.",
    )
    parser.add_argument("--last-page", type=int)
    parser.add_argument("--pdftotext", default="pdftotext")
    parser.add_argument("--min-confidence", type=int, default=5)
    parser.add_argument(
        "--no-toc-subsections",
        action="store_true",
        help="Disable automatic parsing of pipe-separated named subsections in the TOC.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip(" -:|_")
    title = re.sub(r"\s+(?:page\s*)?\d{1,4}\s*$", "", title, flags=re.IGNORECASE)
    return title.strip(" -:|_")


def following_title(lines: list[str], index: int, title: str) -> str:
    if title.strip():
        return clean_title(title)
    parts: list[str] = []
    for line in lines[index + 1 : index + 3]:
        stripped = line.strip()
        if not stripped or len(stripped) > 100:
            break
        if SUBSECTION_RE.match(stripped):
            break
        parts.append(stripped)
    return clean_title(" ".join(parts)) or "Untitled subsection"


def find_subsections(
    pages: list[str],
    boundary: Candidate,
    end_page: int,
    allowed_numbers: set[str] | None = None,
) -> list[Subsection]:
    found: list[Subsection] = []
    exercise_started = False
    seen_numbers: set[str] = set()
    for page_number in range(boundary.page, end_page + 1):
        lines = [line.rstrip() for line in pages[page_number - 1].splitlines()]
        for line_number, line in enumerate(lines):
            if EXERCISE_HEADING_RE.match(line):
                exercise_started = True
                continue
            if exercise_started:
                continue
            match = SUBSECTION_RE.match(line.strip())
            if not match or int(match.group("chapter")) != boundary.number:
                continue
            title = following_title(lines, line_number, match.group("title"))
            if len(title) < 2 or len(title) > 100:
                continue
            if not any(char.isalpha() or "가" <= char <= "힣" for char in title):
                continue
            if re.search(r"\d", title) or re.search(r"[.!?]$", title):
                continue
            if re.match(r"^(?:의|에서|을|를|이|가|그|과)\s", title):
                continue
            number = f"{match.group('chapter')}.{re.sub(r'\s+', '', match.group('sub'))}"
            if allowed_numbers is not None and number not in allowed_numbers:
                continue
            if allowed_numbers is not None and number in seen_numbers:
                continue
            seen_numbers.add(number)
            found.append(
                Subsection(
                    chapter=boundary.number,
                    number=number,
                    title=title,
                    page=page_number,
                    line=line_number,
                    raw_line=line.strip(),
                    source="body-number",
                )
            )

    deduped: list[Subsection] = []
    seen: set[tuple[str, int]] = set()
    for item in found:
        key = (item.number, item.page)
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


def convert_toc_sections(sections: list[TocSection]) -> list[Subsection]:
    return [
        Subsection(
            chapter=section.chapter,
            number=section.number,
            title=section.title,
            page=section.page,
            line=section.line,
            raw_line=section.raw_line,
            source=section.source,
        )
        for section in sections
    ]


def render_lines(title: str, chunks: list[tuple[int, list[str]]]) -> str:
    output: list[str] = [f"# {title}", ""]
    for page_number, lines in chunks:
        if not any(line.strip() for line in lines):
            continue
        output.extend([f"<!-- page {page_number} -->", ""])
        for block in join_wrapped_lines(lines):
            output.extend([block, ""])
    return "\n".join(output).strip() + "\n"


def write_section(path: Path, markdown: str, start_page: int, end_page: int) -> None:
    note = (
        "> PDF 텍스트 레이어에서 자동 추출한 Markdown입니다. "
        "원본 PDF의 OCR 품질에 따라 일부 오탈자나 수식 변환 오류가 남을 수 있습니다.\n"
        f"> 원본 PDF 페이지: {start_page}-{end_page}\n\n"
    )
    lines = markdown.split("\n", 2)
    if len(lines) == 3:
        markdown = f"{lines[0]}\n\n{note}{lines[2]}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")


def chunks_between(
    pages: list[str],
    start: tuple[int, int],
    end: tuple[int, int],
) -> list[tuple[int, list[str]]]:
    chunks: list[tuple[int, list[str]]] = []
    for page_number in range(start[0], end[0] + 1):
        lines = pages[page_number - 1].splitlines()
        first = start[1] if page_number == start[0] else 0
        last = end[1] if page_number == end[0] else len(lines)
        chunks.append((page_number, lines[first:last]))
    return chunks


def load_title_map(path: Path | None) -> dict[str, str]:
    if not path:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("--title-map must contain a JSON object")
    return {str(key): str(value) for key, value in data.items()}


def load_subsection_map(path: Path | None) -> dict[str, set[str]]:
    if not path:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("--subsection-map must contain a JSON object")
    return {str(key): {str(value) for value in values} for key, values in data.items()}


def main() -> int:
    args = parse_args()
    pages = extract_pages(args.input_pdf, find_binary(args.pdftotext))
    last_page = args.last_page or len(pages)
    if last_page > len(pages):
        raise SystemExit(f"--last-page exceeds PDF page count ({len(pages)})")

    if args.boundary_map:
        boundaries = boundaries_from_map(args.boundary_map)
    else:
        boundaries = choose_boundaries(
            detect_candidates(pages[:last_page]), args.min_confidence
        )
    if not boundaries:
        raise SystemExit("No chapter boundaries found")

    title_map = load_title_map(args.title_map)
    subsection_map = load_subsection_map(args.subsection_map)
    toc_subsections = (
        {} if args.no_toc_subsections else parse_toc_subsections(pages, boundaries)
    )
    report: dict[str, object] = {"page_count": last_page, "chapters": []}
    total_subsections = 0
    for index, boundary in enumerate(boundaries):
        end_page = boundaries[index + 1].page - 1 if index + 1 < len(boundaries) else last_page
        sections = find_subsections(
            pages,
            boundary,
            end_page,
            subsection_map.get(str(boundary.number)),
        )
        if not sections:
            sections = convert_toc_sections(toc_subsections.get(boundary.number, []))
        chapter_report = {
            "chapter": boundary.number,
            "start_page": boundary.page,
            "end_page": end_page,
            "subsections": [asdict(section) for section in sections],
        }
        report["chapters"].append(chapter_report)
        total_subsections += len(sections)
        print(f"Chapter {boundary.number}: {len(sections)} subsections ({boundary.page}-{end_page})")

        if args.dry_run or not sections:
            continue

        chapter_title = title_map.get(str(boundary.number), boundary.title)
        chapter_dir = args.output_dir / f"ch-{boundary.number:02d}"
        first = sections[0]
        intro_chunks = chunks_between(
            pages,
            (boundary.page, 0),
            (first.page, first.line),
        )
        if any(line.strip() for _, lines in intro_chunks for line in lines):
            write_section(
                chapter_dir / "intro.md",
                render_lines(f"{boundary.number}. {chapter_title} - 도입부", intro_chunks),
                boundary.page,
                first.page,
            )

        for subsection_index, section in enumerate(sections):
            next_section = sections[subsection_index + 1] if subsection_index + 1 < len(sections) else None
            end = (next_section.page, next_section.line) if next_section else (end_page, len(pages[end_page - 1].splitlines()))
            chunks = chunks_between(pages, (section.page, section.line), end)
            section_title = f"{section.number} {section.title}"
            write_section(
                chapter_dir / f"section-{section.number.replace('.', '-')}.md",
                render_lines(section_title, chunks),
                section.page,
                end[0],
            )

    if not args.dry_run:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "subsection-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        report_lines = [
            "# Subsection Report",
            "",
            f"- PDF pages scanned: {last_page}",
            f"- Subsections detected: {total_subsections}",
            "",
        ]
        for chapter in report["chapters"]:
            report_lines.append(
                f"## Chapter {chapter['chapter']} ({chapter['start_page']}-{chapter['end_page']})"
            )
            if not chapter["subsections"]:
                report_lines.append("\nNo subsections detected.\n")
                continue
            for section in chapter["subsections"]:
                report_lines.append(
                    f"- `{section['number']}` {section['title']} - PDF page {section['page']} ({section['source']})"
                )
            report_lines.append("")
        (args.output_dir / "subsection-report.md").write_text(
            "\n".join(report_lines) + "\n", encoding="utf-8"
        )
    print(f"Total subsections: {total_subsections}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
