#!/usr/bin/env python3
"""Split Vision-OCR chapter Markdown using a subsection report."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PAGE_RE = re.compile(r"(?=<!-- page (\d+) -->\n)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("book_dir", type=Path, help="Vision-OCR book directory containing ch-XX.md files")
    parser.add_argument("subsection_report", type=Path, help="Existing subsection-report.json")
    parser.add_argument("--output-dir", type=Path, help="Defaults to book_dir")
    return parser.parse_args()


def page_blocks(path: Path) -> dict[int, str]:
    text = path.read_text(encoding="utf-8")
    blocks: dict[int, str] = {}
    matches = list(re.finditer(r"<!-- page (\d+) -->\n", text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks[int(match.group(1))] = text[match.start() : end].rstrip() + "\n"
    return blocks


def page_body(block: str) -> str:
    match = re.match(r"<!-- page \d+ -->\n", block)
    return block[match.end() :] if match else block


def write_range(
    path: Path,
    title: str,
    pages: dict[int, str],
    start: int,
    end: int,
    start_offset: int = 0,
    end_offset: int | None = None,
) -> None:
    blocks: list[str] = []
    for page in range(start, end + 1):
        body = page_body(pages.get(page, f"<!-- page {page} -->\n"))
        left = start_offset if page == start else 0
        right = end_offset if page == end and end_offset is not None else len(body)
        blocks.append(f"<!-- page {page} -->\n\n{body[left:right].lstrip()}".rstrip() + "\n")
    note = f"> OCR engine: macOS Vision (`ko-KR,en-US`)\n> Original PDF pages: {start}-{end}\n\n"
    content = f"# {title}\n\n{note}" + "\n".join(blocks).rstrip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def compact(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value).lower()


def compact_offset(text: str, needle: str) -> int | None:
    compact_text: list[str] = []
    original_offsets: list[int] = []
    for index, char in enumerate(text):
        if re.match(r"[0-9A-Za-z가-힣]", char):
            compact_text.append(char.lower())
            original_offsets.append(index)
    position = "".join(compact_text).find(needle)
    return original_offsets[position] if position >= 0 else None


def resolve_boundary(
    title: str,
    reported_page: int,
    pages: dict[int, str],
    start: int,
    end: int,
) -> tuple[int, int]:
    needle = compact(title)
    if len(needle) < 4:
        return reported_page, 0
    candidates = sorted(
        (page for page in pages if start <= page <= end),
        key=lambda page: (abs(page - reported_page), page),
    )
    for page in candidates:
        offset = compact_offset(page_body(pages[page]), needle)
        if offset is not None:
            return page, offset
    return reported_page, 0


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir or args.book_dir
    report = json.loads(args.subsection_report.read_text(encoding="utf-8"))
    report["ocr_engine"] = "macOS Vision"
    report["source_subsection_report"] = str(args.subsection_report)
    total = 0

    for chapter in report["chapters"]:
        number = int(chapter["chapter"])
        chapter_path = args.book_dir / f"ch-{number:02d}.md"
        if not chapter["subsections"] or not chapter_path.exists():
            continue
        pages = page_blocks(chapter_path)
        chapter_dir = output_dir / f"ch-{number:02d}"
        chapter_start = int(chapter["start_page"])
        chapter_end = int(chapter["end_page"])
        sections = [dict(section) for section in chapter["subsections"]]
        previous_boundary = (chapter_start, 0)
        for index, section in enumerate(sections):
            original_page = int(chapter["subsections"][index]["page"])
            resolved_page, resolved_offset = resolve_boundary(
                str(section["title"]),
                int(section["page"]),
                pages,
                chapter_start,
                chapter_end,
            )
            if (resolved_page, resolved_offset) < previous_boundary:
                resolved_page, resolved_offset = previous_boundary
            section["page"] = resolved_page
            section["_offset"] = resolved_offset
            if section["page"] != original_page or resolved_offset:
                section["source"] = "vision-title"
            previous_boundary = (resolved_page, resolved_offset)
        chapter["subsections"] = sections
        first_start = int(sections[0]["page"])
        if chapter_start < first_start:
            write_range(
                chapter_dir / "intro.md",
                f"{number}. 도입부",
                pages,
                chapter_start,
                first_start - 1,
            )

        for index, section in enumerate(sections):
            start = int(section["page"])
            start_offset = int(section.get("_offset", 0))
            if index + 1 < len(sections):
                end = int(sections[index + 1]["page"])
                end_offset = int(sections[index + 1].get("_offset", 0))
            else:
                end = chapter_end
                end_offset = None
            section_id = str(section["number"])
            title = str(section["title"])
            write_range(
                chapter_dir / f"section-{section_id.replace('.', '-')}.md",
                f"{section_id} {title}",
                pages,
                start,
                end,
                start_offset,
                end_offset,
            )
            total += 1

        for section in chapter["subsections"]:
            section.pop("_offset", None)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "subsection-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["# Subsection Report", "", f"- OCR engine: macOS Vision", f"- Subsections: {total}", ""]
    for chapter in report["chapters"]:
        lines.append(f"## Chapter {chapter['chapter']}")
        for section in chapter["subsections"]:
            lines.append(f"- `{section['number']}` {section['title']} - PDF page {section['page']}")
        lines.append("")
    (output_dir / "subsection-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Total subsections: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
