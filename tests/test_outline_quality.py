"""기존 outline low-quality 판정 신호 3종을 검증한다."""

from __future__ import annotations

from pdfbooktree.config import OutlineQualityConfig
from pdfbooktree.models import ExistingOutlineItem
from pdfbooktree.pdf.outline_quality import assess_outline_quality


def _items(titles: list[str]) -> list[ExistingOutlineItem]:
    return [
        ExistingOutlineItem(order=index + 1, title=title, level=1, pdf_page=index + 1)
        for index, title in enumerate(titles)
    ]


def test_assess_outline_quality_flags_too_few_items() -> None:
    items = _items(["Chapter 1", "Chapter 2"])

    assessment = assess_outline_quality(items, total_pages=200)

    assert assessment.is_low_quality
    assert "too_few_items" in assessment.reasons


def test_assess_outline_quality_allows_enough_distinct_items() -> None:
    items = _items([f"Chapter {index}" for index in range(1, 6)])

    assessment = assess_outline_quality(items, total_pages=200)

    assert not assessment.is_low_quality
    assert assessment.reasons == []


def test_assess_outline_quality_flags_near_one_bookmark_per_page() -> None:
    items = _items([f"Scan page {index}" for index in range(1, 46)])

    assessment = assess_outline_quality(items, total_pages=48)

    assert assessment.is_low_quality
    assert assessment.reasons == ["near_one_bookmark_per_page"]


def test_assess_outline_quality_flags_numeric_only_title() -> None:
    items = _items(["Chapter 1", "Chapter 2", "3", "Chapter 4", "Chapter 5"])

    assessment = assess_outline_quality(items, total_pages=200)

    assert assessment.is_low_quality
    assert "numeric_only_title" in assessment.reasons


def test_assess_outline_quality_numeric_only_titles_can_be_disabled() -> None:
    items = _items(["Chapter 1", "Chapter 2", "3", "Chapter 4", "Chapter 5"])

    assessment = assess_outline_quality(
        items,
        total_pages=200,
        config=OutlineQualityConfig(flag_numeric_only_titles=False),
    )

    assert not assessment.is_low_quality
    assert "numeric_only_title" not in assessment.reasons


def test_assess_outline_quality_min_item_count_is_configurable() -> None:
    items = _items(["Chapter 1", "Chapter 2"])

    assessment = assess_outline_quality(
        items, total_pages=200, config=OutlineQualityConfig(min_item_count=1)
    )

    assert not assessment.is_low_quality
