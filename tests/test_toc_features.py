from __future__ import annotations

from pdfbooktree.toc.features import (
    extract_line_final_number,
    extract_page_number_candidates,
    gap_stats,
    monotonicity,
)


def test_extract_line_final_number_reads_page_number_at_line_end() -> None:
    assert extract_line_final_number("1.1 Motivation ........ 7") == 7
    assert extract_line_final_number("Equation 1.1 is useful") is None


def test_extract_page_number_candidates_ignores_section_number_pieces() -> None:
    assert extract_page_number_candidates("1.1 Motivation page 7, examples 12") == [
        7,
        12,
    ]
    assert extract_page_number_candidates("Chapter 2 Probability p. 25") == [2, 25]


def test_monotonicity_and_gap_stats() -> None:
    assert monotonicity([3, 7, 14, 12]) == 2 / 3
    assert gap_stats([3, 7, 14]) == {
        "mean_gap": 5.5,
        "median_gap": 5.5,
        "max_gap": 7,
        "negative_gap_count": 0,
    }
