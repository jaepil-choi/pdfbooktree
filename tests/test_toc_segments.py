from __future__ import annotations

from pdfbooktree.models import PageFeature
from pdfbooktree.toc.segments import (
    find_best_window,
    score_toc_page,
    select_toc_segment,
)


def make_feature(
    pdf_page: int,
    final_count: int = 0,
    monotonicity: float | None = None,
    toc_entry_count: int = 0,
    keyword: bool = False,
    final_numbers: list[int] | None = None,
) -> PageFeature:
    numbers = final_numbers or list(range(1, final_count + 1))
    return PageFeature(
        pdf_page=pdf_page,
        line_count=20,
        word_count=100,
        mean_line_length=30.0,
        line_length_std=4.0,
        line_final_number_count=len(numbers),
        line_final_numbers=numbers,
        line_final_number_monotonicity=monotonicity,
        line_final_number_gap_mean=None,
        line_final_number_gap_median=None,
        line_final_number_gap_max=None,
        line_final_number_negative_gap_count=0,
        toc_entry_pattern_count=toc_entry_count,
        toc_entry_pattern_ratio=toc_entry_count / 20,
        chapter_or_part_line_count=0,
        page_position=pdf_page / 100,
        toc_keyword_presence=keyword,
    )


def test_score_toc_page_counts_independent_votes() -> None:
    score = score_toc_page(
        make_feature(
            pdf_page=5,
            final_count=10,
            monotonicity=1.0,
            toc_entry_count=3,
        )
    )

    assert score.vote_count == 3
    assert score.voters == [
        "printed_page_sequence",
        "toc_entry_pattern",
        "window_mass",
    ]


def test_select_toc_segment_prefers_contiguous_strong_pages() -> None:
    features = [
        make_feature(1),
        make_feature(2),
        make_feature(3, final_count=10, monotonicity=1.0, toc_entry_count=3),
        make_feature(4, final_count=11, monotonicity=1.0, toc_entry_count=3),
        make_feature(5, final_count=10, monotonicity=1.0, toc_entry_count=3),
        make_feature(6),
    ]

    segment = select_toc_segment([score_toc_page(feature) for feature in features])

    assert segment is not None
    assert segment.pages == [3, 4, 5]


def test_find_best_window_uses_mass_and_boundary_contrast() -> None:
    segment = find_best_window(
        {
            1: 0.1,
            2: 1.0,
            3: 3.0,
            4: 3.2,
            5: 2.8,
            6: 0.4,
        },
        min_length=2,
        max_length=4,
    )

    assert segment is not None
    assert segment.pages == [2, 3, 4, 5]


def test_select_toc_segment_rejects_edge_that_breaks_segment_number_flow() -> None:
    features = [
        make_feature(
            2,
            monotonicity=1.0,
            toc_entry_count=0,
            final_numbers=[1996, 1997],
        ),
        make_feature(
            3,
            monotonicity=1.0,
            toc_entry_count=3,
            final_numbers=[1, 11, 16],
        ),
        make_feature(
            4,
            monotonicity=1.0,
            toc_entry_count=3,
            final_numbers=[22, 30, 40],
        ),
    ]

    segment = select_toc_segment([score_toc_page(feature) for feature in features])

    assert segment is not None
    assert segment.pages == [3, 4]
