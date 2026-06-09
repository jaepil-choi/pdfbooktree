"""Aligned TOC item에서 export page range를 계산한다."""

from __future__ import annotations

from pdfbooktree.models import AlignedTocItem, ContentRange


def calculate_content_ranges(
    items: list[AlignedTocItem],
    total_pages: int,
) -> list[ContentRange]:
    """같은 level 또는 상위 level의 다음 항목 직전까지를 range로 잡는다."""

    ranges: list[ContentRange] = []
    for index, item in enumerate(items):
        if item.matched_pdf_page is None:
            continue
        next_page = _find_next_boundary_page(items, index)
        end_page = (next_page - 1) if next_page is not None else total_pages
        if end_page < item.matched_pdf_page:
            end_page = item.matched_pdf_page
        ranges.append(
            ContentRange(
                title=item.title,
                level=item.level,
                start_pdf_page=item.matched_pdf_page,
                end_pdf_page=end_page,
                source_index=index,
            )
        )
    return ranges


def _find_next_boundary_page(
    items: list[AlignedTocItem], current_index: int
) -> int | None:
    current = items[current_index]
    for candidate in items[current_index + 1 :]:
        if candidate.matched_pdf_page is None:
            continue
        if candidate.level <= current.level:
            return candidate.matched_pdf_page
    return None
