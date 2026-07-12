#!/usr/bin/env python3
"""Upload chapter/subchapter Markdown files as linked Notion data-source rows."""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from notion_upload import (
    DEFAULT_CHUNK_CHARS,
    env_parent,
    notion_request,
    split_markdown,
)


BOOK_TITLES = {
    "algorithms-nine": "미래를 바꾼 아홉 가지 알고리즘",
    "computer-science-human": "알고리즘, 인생을 계산하다",
    "mathematical-statistics": "수리통계학 개정판",
}


@dataclass(frozen=True)
class Entry:
    book: str
    chapter: int
    chapter_label: str
    path: Path
    title: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--book-dir",
        type=Path,
        default=Path("outputs/book-md-vision"),
        help="Directory containing one folder per book.",
    )
    parser.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS)
    parser.add_argument("--pause", type=float, default=0.25)
    parser.add_argument(
        "--new-version",
        action="store_true",
        help="Create fresh rows instead of reusing rows with matching book/title.",
    )
    parser.add_argument(
        "--archive-existing",
        action="store_true",
        help="After a successful upload, archive existing rows for the imported books.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--notion-version", default=os.environ.get("NOTION_VERSION", "2026-03-11"))
    return parser.parse_args()


def read_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def chapter_number(path: Path) -> int:
    match = re.search(r"ch-(\d+)", path.name)
    if not match:
        raise SystemExit(f"Could not determine chapter number from {path}")
    return int(match.group(1))


def collect_entries(book_dir: Path) -> list[Entry]:
    book_key = book_dir.name
    book_title = BOOK_TITLES.get(book_key, book_key)
    entries: list[Entry] = []
    for chapter_path in sorted(book_dir.glob("ch-*.md"), key=chapter_number):
        chapter = chapter_number(chapter_path)
        chapter_title = re.sub(r"^\d+\.\s*", "", read_title(chapter_path))
        # Store the parent chapter number separately so rows can be grouped in Notion.
        chapter_label = f"{chapter}장"
        chapter_dir = book_dir / chapter_path.stem
        subsection_paths = sorted(
            chapter_dir.glob("section-*.md"),
            key=lambda path: [int(value) for value in re.findall(r"\d+", path.stem)],
        )
        if subsection_paths:
            intro_path = chapter_dir / "intro.md"
            if intro_path.exists() and intro_path.stat().st_size > 0:
                entries.append(Entry(book_title, chapter, chapter_label, intro_path, read_title(intro_path)))
            entries.extend(
                Entry(book_title, chapter, chapter_label, path, read_title(path))
                for path in subsection_paths
            )
        else:
            entries.append(Entry(book_title, chapter, chapter_label, chapter_path, read_title(chapter_path)))
    return entries


def all_entries(book_root: Path) -> list[Entry]:
    entries: list[Entry] = []
    for book_dir in sorted(path for path in book_root.iterdir() if path.is_dir()):
        entries.extend(collect_entries(book_dir))
    return entries


def text_property(value: str) -> dict[str, Any]:
    return {"rich_text": [{"text": {"content": value[:1900]}}]}


def title_property(value: str) -> dict[str, Any]:
    return {"title": [{"text": {"content": value[:1900]}}]}


def relation_property(page_id: str) -> dict[str, Any]:
    return {"relation": [{"id": page_id}]}


def create_row(
    entry: Entry,
    markdown: str,
    data_source_id: str,
    title_property_name: str,
    book_property_name: str,
    chapter_property_name: str,
    token: str,
    notion_version: str,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        title_property_name: title_property(entry.title),
        book_property_name: text_property(entry.book),
        chapter_property_name: text_property(entry.chapter_label),
    }
    payload: dict[str, Any] = {
        "parent": {"data_source_id": data_source_id},
        "properties": properties,
        "markdown": markdown,
    }
    return notion_request("POST", "/pages", payload, token, notion_version)


def update_links(
    entry: Entry,
    page_id: str,
    previous_id: str | None,
    next_id: str | None,
    book_property_name: str,
    chapter_property_name: str,
    previous_property_name: str,
    next_property_name: str,
    token: str,
    notion_version: str,
) -> None:
    notion_request(
        "PATCH",
        f"/pages/{page_id}",
        {
            "properties": {
                book_property_name: text_property(entry.book),
                chapter_property_name: text_property(entry.chapter_label),
                # Navigation is intentionally forward-only: keep the previous
                # relation empty and put the next row in the 이후 property.
                previous_property_name: {"relation": []},
                next_property_name: {"relation": ([{"id": next_id}] if next_id else [])},
            }
        },
        token,
        notion_version,
    )


def property_text(property_value: dict[str, Any]) -> str:
    values = property_value.get("title") or property_value.get("rich_text") or []
    return "".join(item.get("plain_text", "") for item in values).strip()


def existing_rows(
    data_source_id: str,
    title_property_name: str,
    book_property_name: str,
    token: str,
    notion_version: str,
) -> dict[tuple[str, str], str]:
    rows: dict[tuple[str, str], str] = {}
    cursor: str | None = None
    while True:
        payload: dict[str, Any] = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        response = notion_request(
            "POST", f"/data_sources/{data_source_id}/query", payload, token, notion_version
        )
        for page in response.get("results", []):
            properties = page.get("properties", {})
            title = property_text(properties.get(title_property_name, {}))
            book = property_text(properties.get(book_property_name, {}))
            if title and book:
                rows.setdefault((book, title), page["id"])
        if not response.get("has_more"):
            return rows
        cursor = response.get("next_cursor")


def existing_page_records(
    data_source_id: str,
    book_property_name: str,
    token: str,
    notion_version: str,
) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    cursor: str | None = None
    while True:
        payload: dict[str, Any] = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        response = notion_request(
            "POST", f"/data_sources/{data_source_id}/query", payload, token, notion_version
        )
        for page in response.get("results", []):
            book = property_text(page.get("properties", {}).get(book_property_name, {}))
            if book:
                records.append((book, page["id"]))
        if not response.get("has_more"):
            return records
        cursor = response.get("next_cursor")


def archive_pages(
    records: list[tuple[str, str]],
    books: set[str],
    new_page_ids: set[str],
    token: str,
    notion_version: str,
) -> None:
    archived = 0
    for book, page_id in records:
        if book not in books or page_id in new_page_ids:
            continue
        notion_request(
            "PATCH",
            f"/pages/{page_id}",
            {"in_trash": True},
            token,
            notion_version,
        )
        archived += 1
    print(f"Archived existing rows: {archived}")


def dry_run(entries: list[Entry], chunk_chars: int) -> None:
    by_book: dict[str, list[Entry]] = {}
    for entry in entries:
        by_book.setdefault(entry.book, []).append(entry)
    print(f"Rows to create: {len(entries)}")
    for book, book_entries in by_book.items():
        print(f"- {book}: {len(book_entries)} rows")
        for entry in book_entries[:3]:
            size = entry.path.stat().st_size
            parts = len(split_markdown(entry.path.read_text(encoding="utf-8"), chunk_chars))
            print(f"  {entry.title} ({size:,} chars, {parts} part(s))")
        if len(book_entries) > 3:
            print(f"  ... {len(book_entries) - 3} more")


def upload(entries: list[Entry], args: argparse.Namespace) -> None:
    parent, parent_kind = env_parent()
    if parent_kind != "data_source":
        raise SystemExit("Set NOTION_DATA_SOURCE_ID for catalog row uploads.")
    data_source_id = parent["data_source_id"]
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set NOTION_TOKEN for real upload, or pass --dry-run.")

    title_property_name = os.environ.get("NOTION_TITLE_PROPERTY", "이름")
    book_property_name = os.environ.get("NOTION_BOOK_PROPERTY", "책 제목")
    previous_property_name = os.environ.get("NOTION_PREVIOUS_PROPERTY", "이전 (소)챕터")
    next_property_name = os.environ.get("NOTION_NEXT_PROPERTY", "이후 (소)챕터")
    chapter_property_name = os.environ.get("NOTION_CHAPTER_PROPERTY", "챕터")

    existing = existing_rows(
        data_source_id, title_property_name, book_property_name, token, args.notion_version
    )
    created: list[tuple[Entry, str]] = []
    for entry in entries:
        key = (entry.book, entry.title)
        existing_id = None if args.new_version else existing.get(key)
        if existing_id:
            page_id = existing_id
            print(f"Reusing {entry.book} / {entry.title}: {page_id}")
        else:
            markdown = entry.path.read_text(encoding="utf-8")
            chunks = split_markdown(markdown, args.chunk_chars)
            if len(chunks) > 1:
                raise SystemExit(
                    f"{entry.path} is too large for one row ({len(chunks)} chunks). "
                    "Increase --chunk-chars or upload this entry separately."
                )
            page = create_row(
                entry,
                chunks[0],
                data_source_id,
                title_property_name,
                book_property_name,
                chapter_property_name,
                token,
                args.notion_version,
            )
            page_id = page["id"]
            print(f"Created {entry.book} / {entry.title}: {page.get('url', page_id)}")
            time.sleep(args.pause)
        
        created.append((entry, page_id))

    # Link only adjacent rows within each book, never across books.
    by_book: dict[str, list[tuple[Entry, str]]] = {}
    for entry, page_id in created:
        by_book.setdefault(entry.book, []).append((entry, page_id))

    for book_entries in by_book.values():
        for index, (entry, page_id) in enumerate(book_entries):
            previous_id = book_entries[index - 1][1] if index > 0 else None
            next_id = book_entries[index + 1][1] if index + 1 < len(book_entries) else None
            update_links(
                entry,
                page_id,
                previous_id,
                next_id,
                book_property_name,
                chapter_property_name,
                previous_property_name,
                next_property_name,
                token,
                args.notion_version,
            )
            time.sleep(args.pause)
            print(f"Linked {entry.book} / {entry.title}: previous=False next={bool(next_id)}")

    if args.archive_existing:
        records = existing_page_records(
            data_source_id, book_property_name, token, args.notion_version
        )
        archive_pages(
            records,
            {entry.book for entry, _ in created},
            {page_id for _, page_id in created},
            token,
            args.notion_version,
        )

    print(f"Uploaded {len(created)} rows.")


def main() -> int:
    args = parse_args()
    if not args.book_dir.exists():
        raise SystemExit(f"Book directory not found: {args.book_dir}")
    entries = all_entries(args.book_dir)
    if not entries:
        raise SystemExit("No chapter or subsection Markdown files found.")
    if args.dry_run:
        dry_run(entries, args.chunk_chars)
        return 0
    upload(entries, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
