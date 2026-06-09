"""기존 PDF bookmark를 읽고 skip 가능성을 판단한다."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import fitz

from pdfbooktree.utils.text_normalize import normalize_text


def extract_existing_bookmarks(pdf_path: Path) -> list[dict[str, Any]]:
    """PyMuPDF TOC를 1-based page 번호 bookmark 목록으로 반환한다."""

    bookmarks: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for order, item in enumerate(document.get_toc(simple=False), start=1):
            level, title, pdf_page = item[:3]
            bookmarks.append(
                {
                    "order": order,
                    "level": int(level),
                    "title": normalize_text(str(title)),
                    "pdf_page": int(pdf_page) if int(pdf_page) > 0 else None,
                }
            )
    return bookmarks


def is_clean_bookmark_set(bookmarks: list[dict[str, Any]]) -> bool:
    """자동 처리를 skip할 만큼 기존 bookmark가 충분히 깔끔한지 판단한다."""

    if len(bookmarks) < 10:
        return False
    if any(not bookmark["title"] for bookmark in bookmarks):
        return False

    pages = [
        bookmark["pdf_page"]
        for bookmark in bookmarks
        if bookmark["pdf_page"] is not None
    ]
    if len(pages) < len(bookmarks) * 0.8:
        return False
    if len(pages) > 1:
        non_decreasing = sum(
            1 for left, right in zip(pages, pages[1:], strict=False) if right >= left
        )
        if non_decreasing / (len(pages) - 1) < 0.75:
            return False

    level_counts = Counter(bookmark["level"] for bookmark in bookmarks)
    if len(level_counts) < 2:
        return False

    title_text = " ".join(bookmark["title"].lower() for bookmark in bookmarks)
    return bool(re.search(r"\b(chapter|section|appendix|part)\b|\d+\.\d+", title_text))


def build_skip_reason(bookmarks: list[dict[str, Any]]) -> str | None:
    """기존 bookmark로 skip할 수 있으면 사용자-facing 사유를 반환한다."""

    if not is_clean_bookmark_set(bookmarks):
        return None
    return "기존 bookmark가 충분히 깔끔해서 자동 처리를 건너뛰었다."
