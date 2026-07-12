#!/usr/bin/env python3
"""Extract named subsection entries from a PDF table of contents."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pdf_to_chapters import Candidate, parse_chapter_line
from pdf_to_markdown import looks_like_page_number


TOC_RE = re.compile(r"(?:목차|contents|table\s+of\s+contents)", re.IGNORECASE)
BULLET_RE = re.compile(r"^\s*[•·]\s*")
SEPARATOR_RE = re.compile(
    r"\s+(?:\||｜|I|\[)\s+|\s+(?=\d+\s+[가-힣])"
)
PAGE_AT_END_RE = re.compile(
    r"(?P<title>.*?)\s*[•·]\s*(?P<page>[^\s]+)\s*$"
)


@dataclass(frozen=True)
class TocSection:
    chapter: int
    number: str
    title: str
    page: int
    line: int
    raw_line: str
    source: str = "toc"


def _clean_title(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" -:|_•·")
    value = re.sub(r"^(?:I|\[)\s+", "", value)
    value = re.sub(r"^\d+\s+(?=[가-힣])", "", value)
    return value.strip()


def _compact(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value).lower()


def printed_page_map(pages: list[str]) -> dict[int, list[int]]:
    """Map printed page numbers in footers to physical PDF page numbers."""
    mapping: dict[int, list[int]] = {}
    for physical_page, page in enumerate(pages, start=1):
        candidates = [
            int(line.strip())
            for line in page.splitlines()[-12:]
            if looks_like_page_number(line) and line.strip().isdigit()
        ]
        if candidates:
            mapping.setdefault(candidates[-1], []).append(physical_page)
    return mapping


def _mapped_page(
    printed_page: int,
    page_map: dict[int, list[int]],
    start_page: int | None = None,
    end_page: int | None = None,
) -> int:
    # OCR can turn a three-digit footer such as 434 into "4". Never use a
    # duplicate low-number footer from a later chapter as a real mapping.
    if start_page is not None and printed_page < max(1, start_page - 50):
        return printed_page
    candidates = page_map.get(printed_page, [])
    if start_page is not None and end_page is not None:
        in_range = [page for page in candidates if start_page <= page <= end_page]
        if in_range:
            return in_range[0]
    return printed_page


def _toc_lines(pages: list[str], first_body_page: int) -> list[str]:
    marker_page = next(
        (index for index, page in enumerate(pages, start=1) if TOC_RE.search(page)),
        None,
    )
    if marker_page is None:
        # OCR often drops the word "목차" while preserving the bullet and
        # page-number layout. Find the first page that looks like a TOC page.
        marker_page = next(
            (
                index
                for index, page in enumerate(pages[: first_body_page - 1], start=1)
                if sum(
                    1 for line in page.splitlines() if PAGE_AT_END_RE.search(line.strip())
                ) >= 2
            ),
            None,
        )
    if marker_page is None or marker_page >= first_body_page:
        return []
    lines: list[str] = []
    for page in pages[marker_page - 1 : first_body_page - 1]:
        lines.extend(page.splitlines())
    return lines


def _bullet_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for raw_line in lines:
        line = raw_line.rstrip()
        if BULLET_RE.match(line):
            if current:
                blocks.append(current)
            current = [BULLET_RE.sub("", line, count=1)]
        elif current is not None:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _preamble_lines(lines: list[str]) -> list[str]:
    for index, line in enumerate(lines):
        if BULLET_RE.match(line):
            return lines[:index]
    return lines


def _numbered_blocks(lines: list[str]) -> list[tuple[int, list[str]]]:
    blocks: list[tuple[int, list[str]]] = []
    current_number: int | None = None
    current: list[str] = []
    for line in lines:
        parsed = parse_chapter_line(line.strip())
        if parsed:
            if current_number is not None:
                blocks.append((current_number, current))
            current_number = parsed[0]
            current = []
        elif current_number is not None:
            current.append(line)
    if current_number is not None:
        blocks.append((current_number, current))
    return blocks


def _entries_from_lines(lines: list[str]) -> list[tuple[str, int, str]]:
    entries: list[tuple[str, int, str]] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        for piece in SEPARATOR_RE.split(line):
            match = PAGE_AT_END_RE.search(piece.strip())
            if not match:
                continue
            title = _clean_title(match.group("title"))
            page_token = match.group("page")
            page_text = re.sub(r"\D", "", page_token)
            if not page_text:
                if not re.search(r"[A-Za-z가-힣]", page_token):
                    continue
            if len(title) < 2 or not any(char.isalpha() or "가" <= char <= "힣" for char in title):
                continue
            entries.append((title, int(page_text) if page_text else 0, raw_line.strip()))
    return entries


def _entry_page_and_line(
    pages: list[str],
    title: str,
    printed_page: int,
    page_map: dict[int, list[int]],
) -> tuple[int, int]:
    physical_page = _mapped_page(printed_page, page_map)
    if physical_page < 1 or physical_page > len(pages):
        return printed_page, 0
    needle = _compact(title)
    for line_number, line in enumerate(pages[physical_page - 1].splitlines()):
        if needle and needle in _compact(line):
            return physical_page, line_number
    return physical_page, 0


def _find_heading_page(
    pages: list[str],
    title: str,
    start_page: int,
    end_page: int,
    hint_page: int,
) -> tuple[int, int] | None:
    tokens = re.findall(r"[가-힣A-Za-z]{2,}", title)
    if len(tokens) < 2:
        return None
    matches: list[tuple[int, int, int]] = []
    for page in range(start_page, end_page + 1):
        for line_number, line in enumerate(pages[page - 1].splitlines()):
            compact_line = _compact(line)
            score = sum(token in compact_line for token in tokens)
            if score >= 2:
                matches.append((score, page, line_number))
    if not matches:
        return None
    _, page, line = min(
        matches, key=lambda item: (-item[0], abs(item[1] - hint_page), item[1], item[2])
    )
    return page, line


def _sections_for_block(
    pages: list[str],
    chapter: int,
    entries: list[tuple[str, int, str]],
    page_map: dict[int, list[int]],
    start_page: int,
    end_page: int,
) -> list[TocSection]:
    entries = [
        entry
        for entry in entries
        if _mapped_page(entry[1], page_map, start_page, end_page) <= end_page
    ]
    raw_pages = [
        _mapped_page(printed_page, page_map, start_page, end_page)
        for _, printed_page, _ in entries
    ]
    valid_indices = {
        index
        for index, page in enumerate(raw_pages)
        if start_page <= page <= end_page and page > 0
    }
    inferred_pages: dict[int, int] = {
        index: raw_pages[index] for index in valid_indices
    }
    for index, page in enumerate(raw_pages):
        if index in valid_indices:
            continue
        previous = next(
            (inferred_pages[item] for item in range(index - 1, -1, -1) if item in inferred_pages),
            None,
        )
        following = next(
            (inferred_pages[item] for item in range(index + 1, len(entries)) if item in inferred_pages),
            None,
        )
        if previous is not None and following is not None:
            inferred_pages[index] = (previous + following + 1) // 2
        elif previous is not None:
            inferred_pages[index] = min(previous + 1, end_page)
        elif following is not None:
            inferred_pages[index] = max(start_page, following - 1)
        else:
            inferred_pages[index] = start_page

    ordered_entries = sorted(
        (
            (inferred_pages[index], index, entry)
            for index, entry in enumerate(entries)
        ),
        key=lambda item: item[0],
    )

    sections: list[TocSection] = []
    for index, (page, original_index, (title, _printed_page, raw_line)) in enumerate(
        ordered_entries, start=1
    ):
        if original_index not in valid_indices:
            located = _find_heading_page(pages, title, start_page, end_page, page)
            if located:
                page, line = located
            else:
                line = 0
        else:
            needle = _compact(title)
            line = next(
                (
                    line_number
                    for line_number, line_text in enumerate(pages[page - 1].splitlines())
                    if needle and needle in _compact(line_text)
                ),
                0,
            )
        sections.append(
            TocSection(
                chapter=chapter,
                number=f"{chapter}.{index}",
                title=title,
                page=page,
                line=line,
                raw_line=raw_line,
            )
        )
    return sorted(sections, key=lambda section: (section.page, section.line))


def parse_toc_subsections(pages: list[str], boundaries: list[Candidate]) -> dict[int, list[TocSection]]:
    """Parse pipe-separated TOC entries and map their printed pages to PDF pages."""
    if not boundaries:
        return {}
    lines = _toc_lines(pages, boundaries[0].page)
    if not lines:
        return {}
    page_map = printed_page_map(pages)

    result: dict[int, list[TocSection]] = {}

    def boundary_for_page(page: int) -> Candidate | None:
        for index, boundary in enumerate(boundaries):
            end_page = boundaries[index + 1].page - 1 if index + 1 < len(boundaries) else len(pages)
            if boundary.page <= page <= end_page:
                return boundary
        return None

    preamble_entries = _entries_from_lines(_preamble_lines(lines))
    preamble_by_chapter: dict[int, list[tuple[str, int, str]]] = {}
    for entry in preamble_entries:
        physical_page = _mapped_page(entry[1], page_map)
        boundary = boundary_for_page(physical_page)
        if boundary:
            preamble_by_chapter.setdefault(boundary.number, []).append(entry)

    for chapter, entries in preamble_by_chapter.items():
        boundary = next(item for item in boundaries if item.number == chapter)
        index = boundaries.index(boundary)
        end_page = boundaries[index + 1].page - 1 if index + 1 < len(boundaries) else len(pages)
        result[chapter] = _sections_for_block(
            pages, chapter, entries, page_map, boundary.page, end_page
        )

    for block in _bullet_blocks(lines):
        entries = _entries_from_lines(block)
        if not entries:
            continue
        counts: dict[int, int] = {}
        for entry in entries:
            boundary = boundary_for_page(_mapped_page(entry[1], page_map))
            if boundary:
                counts[boundary.number] = counts.get(boundary.number, 0) + 1
        if not counts:
            continue
        chapter = max(counts, key=counts.get)
        boundary = next(item for item in boundaries if item.number == chapter)
        index = boundaries.index(boundary)
        end_page = boundaries[index + 1].page - 1 if index + 1 < len(boundaries) else len(pages)
        result.setdefault(chapter, []).extend(
            _sections_for_block(pages, chapter, entries, page_map, boundary.page, end_page)
        )

    for chapter, sections in result.items():
        result[chapter] = [
            TocSection(
                chapter=section.chapter,
                number=f"{chapter}.{index}",
                title=section.title,
                page=section.page,
                line=section.line,
                raw_line=section.raw_line,
                source=section.source,
            )
            for index, section in enumerate(
                sorted(sections, key=lambda item: (item.page, item.line)), start=1
            )
        ]
    if result:
        return result

    result = {}
    for chapter, block in _numbered_blocks(lines):
        boundary = next((item for item in boundaries if item.number == chapter), None)
        if boundary is None:
            continue
        entries = _entries_from_lines(block)
        if entries:
            index = boundaries.index(boundary)
            end_page = boundaries[index + 1].page - 1 if index + 1 < len(boundaries) else len(pages)
            result[chapter] = _sections_for_block(
                pages, chapter, entries, page_map, boundary.page, end_page
            )
    return result
