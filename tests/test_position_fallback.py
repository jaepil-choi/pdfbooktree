"""font tier에 흡수된 body-tier heading의 position fallback을 검증한다."""

from __future__ import annotations

from dataclasses import replace

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import BookmarkPlanItem, TypographyLine
from pdfbooktree.typography.geometry import (
    build_geometry_context,
    compute_geometry_font_tier_set,
)
from pdfbooktree.typography.position_fallback import select_body_tier_position_fallback

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
BODY_FONT_SIZE = 10.0
BODY_SENTENCE = (
    "This is ordinary body text repeated many times to dominate coverage. " * 3
)


def _line(
    page: int, text: str, font_size: float, y0: float, *, x0: float = 72.0
) -> TypographyLine:
    return TypographyLine(
        pdf_page=page,
        text=text,
        x0=x0,
        y0=y0,
        x1=x0 + 300.0,
        y1=y0 + font_size,
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
        font_size=font_size,
        height=font_size,
        is_bold=False,
        font_names=("Test",),
    )


def _book_lines(chapter_pages: int = 7) -> list[TypographyLine]:
    """chapter marker가 본문과 같은 font size로 매 page 같은 위치에 반복되는 책이다.

    실험 098(통계학원론 OCR)의 실제 실패 패턴을 재현한다: font tier만으로는
    chapter marker와 본문을 구분할 수 없고, 반복 위치만이 유일한 단서다.
    """

    lines = [_line(1, "Book Title", 20.0, 20.0)]
    for page in range(1, chapter_pages + 1):
        lines.append(_line(page, f"Chapter {page}", BODY_FONT_SIZE, 80.0))
        for row in range(6):
            lines.append(_line(page, BODY_SENTENCE, BODY_FONT_SIZE, 140.0 + row * 12.0))
    return lines


def _title_only_font_plan() -> list[BookmarkPlanItem]:
    return [
        BookmarkPlanItem(
            title="Book Title", level=1, pdf_page=1, source="geometry_typography"
        )
    ]


def test_select_body_tier_position_fallback_rescues_repeated_chapter_marker() -> None:
    lines = _book_lines()
    font_tiers = compute_geometry_font_tier_set(lines)
    config = TypographyConfig(position_min_repeated_pages=5)
    context = build_geometry_context(lines, font_tiers, config)

    fallback = select_body_tier_position_fallback(
        context, _title_only_font_plan(), config
    )

    titles = {candidate.title for candidate in fallback}
    assert {f"Chapter {page}" for page in range(1, 8)} <= titles
    assert all(candidate.support_pages >= 5 for candidate in fallback)
    assert all(candidate.font_ratio == 1.0 for candidate in fallback)


def test_select_body_tier_position_fallback_drops_below_min_support_pages() -> None:
    lines = _book_lines(chapter_pages=3)
    font_tiers = compute_geometry_font_tier_set(lines)
    config = TypographyConfig(position_min_repeated_pages=5)
    context = build_geometry_context(lines, font_tiers, config)

    fallback = select_body_tier_position_fallback(
        context, _title_only_font_plan(), config
    )

    assert fallback == []


def test_select_body_tier_position_fallback_respects_font_ratio_band() -> None:
    lines = _book_lines()
    font_tiers = compute_geometry_font_tier_set(lines)
    config = replace(
        TypographyConfig(position_min_repeated_pages=5),
        position_fallback_body_font_ratio_high=0.99,
    )
    context = build_geometry_context(lines, font_tiers, config)

    fallback = select_body_tier_position_fallback(
        context, _title_only_font_plan(), config
    )

    assert fallback == []


def test_select_body_tier_position_fallback_respects_min_isolation_ratio() -> None:
    lines = _book_lines()
    font_tiers = compute_geometry_font_tier_set(lines)
    config = replace(
        TypographyConfig(position_min_repeated_pages=5),
        position_fallback_min_isolation_ratio=1000.0,
    )
    context = build_geometry_context(lines, font_tiers, config)

    fallback = select_body_tier_position_fallback(
        context, _title_only_font_plan(), config
    )

    assert fallback == []


def test_select_body_tier_position_fallback_skips_multi_line_chunks() -> None:
    lines = [_line(1, "Book Title", 20.0, 20.0)]
    for page in range(1, 8):
        lines.append(_line(page, "Chapter", BODY_FONT_SIZE, 80.0))
        lines.append(_line(page, f"{page}", BODY_FONT_SIZE, 88.0))
        for row in range(6):
            lines.append(_line(page, BODY_SENTENCE, BODY_FONT_SIZE, 140.0 + row * 12.0))
    font_tiers = compute_geometry_font_tier_set(lines)
    config = TypographyConfig(position_min_repeated_pages=5)
    context = build_geometry_context(lines, font_tiers, config)

    fallback = select_body_tier_position_fallback(
        context, _title_only_font_plan(), config
    )

    assert fallback == []


def test_select_body_tier_position_fallback_skips_titles_already_in_font_plan() -> None:
    lines = _book_lines()
    font_tiers = compute_geometry_font_tier_set(lines)
    config = TypographyConfig(position_min_repeated_pages=5)
    context = build_geometry_context(lines, font_tiers, config)
    font_plan = [
        *_title_only_font_plan(),
        BookmarkPlanItem(
            title="Chapter 1", level=2, pdf_page=1, source="geometry_typography"
        ),
    ]

    fallback = select_body_tier_position_fallback(context, font_plan, config)

    titles = {candidate.title for candidate in fallback}
    assert "Chapter 1" not in titles
    assert "Chapter 2" in titles
