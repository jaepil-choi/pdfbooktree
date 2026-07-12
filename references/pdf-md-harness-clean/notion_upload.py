#!/usr/bin/env python3
"""Upload Markdown to Notion, chunking long documents into child pages."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


NOTION_API_BASE = "https://api.notion.com/v1"
DEFAULT_NOTION_VERSION = "2026-03-11"
DEFAULT_CHUNK_CHARS = 420_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown_file", type=Path)
    parser.add_argument("--title", help="Notion page title. Defaults to Markdown filename.")
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=DEFAULT_CHUNK_CHARS,
        help="Approximate max Markdown characters per Notion page.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print upload plan only.")
    parser.add_argument(
        "--notion-version",
        default=os.environ.get("NOTION_VERSION", DEFAULT_NOTION_VERSION),
    )
    return parser.parse_args()


def env_parent() -> tuple[dict[str, str], str]:
    parent_page_id = os.environ.get("NOTION_PARENT_PAGE_ID", "").strip()
    data_source_id = os.environ.get("NOTION_DATA_SOURCE_ID", "").strip()

    if parent_page_id:
        return {"page_id": parent_page_id}, "page"
    if data_source_id:
        return {"data_source_id": data_source_id}, "data_source"
    raise SystemExit("Set NOTION_PARENT_PAGE_ID or NOTION_DATA_SOURCE_ID.")


def title_properties(title: str, parent_kind: str) -> dict[str, Any]:
    rich_title = [{"text": {"content": title[:1900]}}]
    if parent_kind == "data_source":
        prop_name = os.environ.get("NOTION_TITLE_PROPERTY", "Name")
        return {prop_name: {"title": rich_title}}
    return {"title": rich_title}


def split_markdown(markdown: str, max_chars: int) -> list[str]:
    if max_chars < 10_000:
        raise SystemExit("--chunk-chars should be at least 10000")
    if len(markdown) <= max_chars:
        return [markdown]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("\n".join(current).strip() + "\n")
            current = []
            current_len = 0

    for block in markdown.split("\n\n"):
        block_len = len(block) + 2
        if current and current_len + block_len > max_chars:
            flush()
        if block_len > max_chars:
            for start in range(0, len(block), max_chars):
                chunks.append(block[start : start + max_chars].strip() + "\n")
            continue
        current.append(block)
        current_len += block_len
    flush()
    return chunks


def notion_request(
    method: str,
    path: str,
    payload: dict[str, Any],
    token: str,
    notion_version: str,
    max_attempts: int = 5,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    url = f"{NOTION_API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": notion_version,
        "Content-Type": "application/json",
    }

    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if exc.code in {429, 529} and attempt < max_attempts:
                retry_after = int(exc.headers.get("Retry-After", "2"))
                time.sleep(max(retry_after, 2))
                continue
            raise SystemExit(f"Notion API error {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            if attempt < max_attempts:
                time.sleep(2 * attempt)
                continue
            raise SystemExit(f"Network error calling Notion: {exc}") from exc

    raise SystemExit("Notion request failed after retries")


def create_page(
    title: str,
    markdown: str,
    parent: dict[str, str],
    parent_kind: str,
    token: str,
    notion_version: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "parent": parent,
        "properties": title_properties(title, parent_kind),
    }
    if markdown.strip():
        payload["markdown"] = markdown
    return notion_request("POST", "/pages", payload, token, notion_version)


def upload(markdown: str, title: str, chunks: list[str], args: argparse.Namespace) -> None:
    parent, parent_kind = env_parent()
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set NOTION_TOKEN for real upload, or pass --dry-run.")

    if len(chunks) == 1:
        page = create_page(title, chunks[0], parent, parent_kind, token, args.notion_version)
        print(f"Created page: {page.get('url', page.get('id'))}")
        return

    index_md = (
        f"Imported from Markdown.\n\n"
        f"Total parts: {len(chunks)}\n\n"
        "Open child pages below in order."
    )
    root = create_page(title, index_md, parent, parent_kind, token, args.notion_version)
    root_id = root["id"]
    root_parent = {"page_id": root_id}
    print(f"Created root page: {root.get('url', root_id)}")

    width = len(str(len(chunks)))
    for index, chunk in enumerate(chunks, start=1):
        part_title = f"{title} - Part {index:0{width}d}"
        page = create_page(part_title, chunk, root_parent, "page", token, args.notion_version)
        print(f"Created part {index}/{len(chunks)}: {page.get('url', page.get('id'))}")


def main() -> int:
    args = parse_args()
    if not args.markdown_file.exists():
        raise SystemExit(f"Markdown file not found: {args.markdown_file}")

    markdown = args.markdown_file.read_text(encoding="utf-8")
    title = args.title or args.markdown_file.stem
    chunks = split_markdown(markdown, args.chunk_chars)

    if args.dry_run:
        print(f"Title: {title}")
        print(f"Markdown chars: {len(markdown):,}")
        print(f"Chunk chars: {args.chunk_chars:,}")
        print(f"Notion pages to create: {1 if len(chunks) == 1 else len(chunks) + 1}")
        for index, chunk in enumerate(chunks, start=1):
            print(f"  chunk {index}: {len(chunk):,} chars")
        return 0

    upload(markdown, title, chunks, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
