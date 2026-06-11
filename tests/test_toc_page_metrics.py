from __future__ import annotations

import pytest

from pdfbooktree.metrics.toc_pages import (
    boundary_error,
    compare_toc_pages,
    segment_iou,
)


def test_compare_toc_pages_reports_page_set_and_boundary_metrics() -> None:
    comparison = compare_toc_pages([5, 6, 7, 8], [6, 7, 8, 9])

    assert comparison.true_positive_pages == [6, 7, 8]
    assert comparison.missing_pages == [9]
    assert comparison.extra_pages == [5]
    assert comparison.precision == 0.75
    assert comparison.recall == 0.75
    assert comparison.segment_iou == 3 / 5
    assert comparison.start_page_error == -1
    assert comparison.end_page_error == -1


def test_segment_iou_returns_none_when_both_ranges_are_empty() -> None:
    assert segment_iou([], []) is None


def test_boundary_error_rejects_unknown_boundary() -> None:
    with pytest.raises(ValueError, match="알 수 없는 boundary"):
        boundary_error([1], [1], "middle")
