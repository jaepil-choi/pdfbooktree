"""기존 PDF bookmark 호환 API다."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from pdfbooktree.pdf.outline import read_outline


def extract_existing_bookmarks(pdf_path: Path) -> list[dict[str, Any]]:
    """기존 테스트와 OCR builder 호환을 위해 dict bookmark 목록을 반환한다."""

    return [
        {
            "order": item.order,
            "level": item.level,
            "title": item.title,
            "pdf_page": item.pdf_page,
        }
        for item in read_outline(pdf_path)
    ]


def title_has_letter(title: str) -> bool:
    """제목에 글자가 하나라도 있으면 True를 반환한다."""

    return any(char.isalpha() for char in title)


def has_letter_bookmark(bookmarks: list[dict[str, Any]]) -> bool:
    """bookmark 중 제목에 글자가 들어간 항목이 하나라도 있으면 True를 반환한다."""

    return any(title_has_letter(bookmark["title"]) for bookmark in bookmarks)


def is_clean_bookmark_set(bookmarks: list[dict[str, Any]]) -> bool:
    """평가 reference로 쓸 만큼 bookmark가 깔끔한지 판단한다."""

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
    """runtime에서 기존 bookmark 문서를 제외해야 하면 사유를 반환한다."""

    if not bookmarks:
        return None
    return f"기존 bookmark {len(bookmarks)}개가 있어서 runtime 자동 처리를 건너뛰었다."
