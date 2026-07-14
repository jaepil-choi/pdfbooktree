"""geometry와 font coverage 기반 heading 후보 추출을 검증한다."""

from dataclasses import replace

import pytest

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import Tier, TierSet, TypographyLine
from pdfbooktree.typography.geometry import (
    classify_font_tiers_by_text_coverage,
    compute_geometry_font_tier_set,
    extract_geometry_headings,
)


def _tiers() -> TierSet:
    return TierSet(
        signal="font_size",
        cut_points=[15.0],
        tiers=[
            Tier(tier=1, lower_bound=15.0, upper_bound=None, peak=20.0, count=6),
            Tier(tier=2, lower_bound=None, upper_bound=15.0, peak=10.0, count=12),
        ],
        raw_tier_count=2,
        gap_merged_tier_count=2,
        final_tier_count=2,
    )


def _line(
    page: int,
    text: str,
    font_size: float,
    y0: float,
    *,
    x0: float = 72.0,
) -> TypographyLine:
    return TypographyLine(
        pdf_page=page,
        text=text,
        x0=x0,
        y0=y0,
        x1=x0 + 300.0,
        y1=y0 + 8.0,
        page_width=600.0,
        page_height=800.0,
        font_size=font_size,
        height=8.0,
        is_bold=font_size > 15.0,
        font_names=("Test",),
    )


def _pattern_lines() -> list[TypographyLine]:
    lines: list[TypographyLine] = []
    body = "본문" * 100
    for page in range(1, 7):
        heading_y = 20.0 if page <= 5 else 100.0
        lines.extend(
            [
                _line(page, f"제목 {page}", 20.0, heading_y),
                _line(page, body, 10.0, heading_y + 30.0),
                _line(page, body, 10.0, heading_y + 40.0),
            ]
        )
    return lines


def test_geometry_font_tier는_sparse_merge없이_density_band를_보존한다():
    lines = [
        _line(1, "가" * 90, 10.0, 20.0),
        _line(1, "나" * 6, 14.0, 40.0),
        _line(1, "다" * 4, 18.0, 60.0),
    ]

    tiers = compute_geometry_font_tier_set(lines)
    profile = classify_font_tiers_by_text_coverage(lines, tiers, 0.95)

    assert tiers.final_tier_count == 3
    assert len(profile.body_tiers) == 2
    assert len(profile.candidate_tiers) == 1
    assert profile.body_text_ratio == pytest.approx(0.96)


def test_font_coverage는_95_percent를_넘기는_tier_전체를_본문으로_포함한다():
    lines = [
        _line(1, "가" * 90, 10.0, 20.0),
        _line(1, "나" * 6, 20.0, 40.0),
    ]

    profile = classify_font_tiers_by_text_coverage(lines, _tiers(), 0.95)

    assert profile.body_tiers == frozenset({1, 2})
    assert profile.candidate_tiers == frozenset()
    assert profile.body_text_ratio == 1.0


def test_font_coverage는_95_percent_밖의_tier를_candidate로_남긴다():
    lines = [
        _line(1, "가" * 99, 10.0, 20.0),
        _line(1, "나", 20.0, 40.0),
    ]

    profile = classify_font_tiers_by_text_coverage(lines, _tiers(), 0.95)

    assert profile.body_tiers == frozenset({2})
    assert profile.candidate_tiers == frozenset({1})
    assert profile.body_text_ratio == pytest.approx(0.99)


def test_position_font_and는_동일_chunk_id의_교집합만_선택한다():
    lines = _pattern_lines()
    base = TypographyConfig(
        body_font_text_coverage=0.95,
        position_min_repeated_pages=5,
    )

    position = extract_geometry_headings(
        lines, _tiers(), replace(base, heading_candidate_mode="position")
    )
    font = extract_geometry_headings(
        lines, _tiers(), replace(base, heading_candidate_mode="font")
    )
    combined = extract_geometry_headings(
        lines,
        _tiers(),
        replace(base, heading_candidate_mode="position_and_font"),
    )

    assert [item.pdf_page for item in position] == [1, 2, 3, 4, 5]
    assert [item.pdf_page for item in font] == [1, 2, 3, 4, 5, 6]
    assert [item.pdf_page for item in combined] == [1, 2, 3, 4, 5]
    assert all(item.source == "geometry_typography" for item in combined)
    assert all("position_min_pages_5" in item.evidence for item in combined)


def test_position_pattern은_본문_line_spacing_범위의_anchor_jitter를_허용한다():
    lines: list[TypographyLine] = []
    body = "본문" * 100
    for page, jitter in enumerate([0.0, 2.0, 4.0, 6.0, 9.0], start=1):
        lines.extend(
            [
                _line(page, f"제목 {page}", 20.0, 20.0 + jitter),
                _line(page, body, 10.0, 50.0 + jitter),
                _line(page, body, 10.0, 60.0 + jitter),
            ]
        )

    headings = extract_geometry_headings(
        lines,
        _tiers(),
        TypographyConfig(
            heading_candidate_mode="position_and_font",
            body_font_text_coverage=0.95,
            position_min_repeated_pages=5,
        ),
    )

    assert [item.pdf_page for item in headings] == [1, 2, 3, 4, 5]
    assert all(
        "position_tolerance_body_line_spacing" in item.evidence for item in headings
    )


def test_position_pattern은_config의_최소_page_반복수를_지킨다():
    headings = extract_geometry_headings(
        _pattern_lines(),
        _tiers(),
        TypographyConfig(
            heading_candidate_mode="position",
            body_font_text_coverage=0.95,
            position_min_repeated_pages=6,
        ),
    )

    assert headings == []


def test_heading_candidate_mode가_잘못되면_실패한다():
    config = replace(TypographyConfig(), heading_candidate_mode="unknown")

    with pytest.raises(ValueError, match="heading candidate mode"):
        extract_geometry_headings(_pattern_lines(), _tiers(), config)
