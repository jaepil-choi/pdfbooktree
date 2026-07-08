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


def has_meaningful_bookmark(bookmarks: list[dict[str, Any]]) -> bool:
    """진짜 목차로 볼 만한 level 구조가 있는지 판단한다.

    병합/분할 도구가 파일명을 그대로 옮겨 만든 bookmark는 전부 level 1인 flat
    목록이라 실제 목차가 아니다. `is_clean_bookmark_set`은 훈련용 gold label
    후보를 고르는 훨씬 엄격한 기준(>=10개, 페이지 단조 증가, keyword 존재 등)
    이라 짧지만 진짜인 목차를 걸러낼 수 있다. 이 함수는 "OCR overwrite로 기존
    bookmark를 지워도 되는가"라는 다른 질문에 쓰는 완화된 기준이다.
    """

    if not bookmarks:
        return False
    level_count = len({bookmark["level"] for bookmark in bookmarks})
    return level_count >= 2


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
