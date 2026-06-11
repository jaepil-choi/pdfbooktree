from __future__ import annotations

from pdfbooktree.models import PageFeature
from pdfbooktree.toc.detect import detect_toc_pages


def make_feature(
    pdf_page: int,
    final_count: int = 0,
    monotonicity: float | None = None,
    toc_entry_count: int = 0,
) -> PageFeature:
    return PageFeature(
        pdf_page=pdf_page,
        line_count=20,
        word_count=100,
        mean_line_length=30.0,
        line_length_std=4.0,
        line_final_number_count=final_count,
        line_final_numbers=list(range(1, final_count + 1)),
        line_final_number_monotonicity=monotonicity,
        line_final_number_gap_mean=None,
        line_final_number_gap_median=None,
        line_final_number_gap_max=None,
        line_final_number_negative_gap_count=0,
        toc_entry_pattern_count=toc_entry_count,
        toc_entry_pattern_ratio=toc_entry_count / 20,
        chapter_or_part_line_count=0,
        page_position=pdf_page / 100,
        toc_keyword_presence=False,
    )


def test_detect_toc_pages_returns_segment_and_candidates() -> None:
    features = [
        make_feature(1),
        make_feature(2, final_count=9, monotonicity=1.0, toc_entry_count=3),
        make_feature(3, final_count=10, monotonicity=1.0, toc_entry_count=3),
        make_feature(4, final_count=9, monotonicity=1.0, toc_entry_count=3),
        make_feature(5),
    ]

    result = detect_toc_pages(features)

    assert result.pages == [2, 3, 4]
    assert result.start_page == 2
    assert result.end_page == 4
    assert result.confidence > 0
    assert result.method == "feature_vote_segment"
    assert result.candidates[1]["vote_count"] == 3


def test_detect_toc_pages_returns_empty_when_no_page_has_evidence() -> None:
    result = detect_toc_pages([make_feature(1), make_feature(2), make_feature(3)])

    assert result.pages == []
    assert result.confidence == 0.0
