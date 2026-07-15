"""bookmark plan 정규화와 position fallback 병합을 검증한다."""

from __future__ import annotations

from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.outline.plan import insert_position_fallback
from pdfbooktree.outline.tree import build_outline_tree
from pdfbooktree.typography.position_fallback import PositionFallbackCandidate


def _plan_item(title: str, level: int, pdf_page: int) -> BookmarkPlanItem:
    return BookmarkPlanItem(
        title=title, level=level, pdf_page=pdf_page, source="geometry_typography"
    )


def _candidate(
    title: str, pdf_page: int, y0: float = 100.0
) -> PositionFallbackCandidate:
    return PositionFallbackCandidate(
        title=title,
        pdf_page=pdf_page,
        y0=y0,
        y1=y0 + 10.0,
        support_pages=6,
        isolation_ratio=1.5,
        font_ratio=1.0,
        confidence=0.6,
        evidence=("repeated_body_tier_position",),
    )


def test_insert_position_fallback_places_candidate_as_child_of_deepest_parent() -> None:
    font_plan = [
        _plan_item("Book Title", 1, 1),
        _plan_item("Part I", 2, 5),
        _plan_item("Part II", 2, 50),
    ]
    candidates = [_candidate("Chapter 3", 20), _candidate("Chapter 8", 60)]

    merged = insert_position_fallback(font_plan, candidates, total_pages=100)

    by_title = {item.title: item for item in merged}
    assert by_title["Chapter 3"].level == 3
    assert by_title["Chapter 8"].level == 3
    assert by_title["Chapter 3"].source == "geometry_position_fallback"

    trees = build_outline_tree(merged, total_pages=100)
    part_one = next(node for node in trees[0].children if node.title == "Part I")
    part_two = next(node for node in trees[0].children if node.title == "Part II")
    assert [child.title for child in part_one.children] == ["Chapter 3"]
    assert [child.title for child in part_two.children] == ["Chapter 8"]


def test_insert_position_fallback_drops_candidate_without_parent() -> None:
    font_plan = [_plan_item("Book Title", 1, 10)]
    candidates = [_candidate("Preface", pdf_page=1)]

    merged = insert_position_fallback(font_plan, candidates, total_pages=50)

    assert [item.title for item in merged] == ["Book Title"]


def test_insert_position_fallback_returns_font_plan_when_no_candidates() -> None:
    font_plan = [_plan_item("Book Title", 1, 1)]

    merged = insert_position_fallback(font_plan, [], total_pages=10)

    assert merged == font_plan


def test_insert_position_fallback_returns_font_plan_when_font_plan_empty() -> None:
    merged = insert_position_fallback([], [_candidate("Chapter 1", 1)], total_pages=10)

    assert merged == []
