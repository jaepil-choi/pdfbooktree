from __future__ import annotations

from pdfbooktree.alignment.ranges import calculate_content_ranges
from pdfbooktree.models import AlignedTocItem


def item(title: str, level: int, page: int) -> AlignedTocItem:
    return AlignedTocItem(
        title=title,
        level=level,
        printed_page=page,
        estimated_pdf_page=page,
        matched_pdf_page=page,
        confidence=1.0,
        method="test",
        source_pdf_page=1,
    )


def test_calculate_content_ranges_uses_next_same_or_upper_level_boundary() -> None:
    ranges = calculate_content_ranges(
        [
            item("1 Introduction", 1, 10),
            item("1.1 Motivation", 2, 12),
            item("1.2 Background", 2, 20),
            item("2 Probability", 1, 30),
        ],
        total_pages=100,
    )

    assert [(row.title, row.start_pdf_page, row.end_pdf_page) for row in ranges] == [
        ("1 Introduction", 10, 29),
        ("1.1 Motivation", 12, 19),
        ("1.2 Background", 20, 29),
        ("2 Probability", 30, 100),
    ]
