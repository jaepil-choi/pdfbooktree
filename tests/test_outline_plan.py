"""bookmark plan 정규화와 position fallback 병합을 검증한다."""

from __future__ import annotations

import pytest

from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.outline.plan import insert_position_fallback, normalize_bookmark_plan
from pdfbooktree.outline.tree import build_outline_tree
from pdfbooktree.outline.validate import validate_bookmark_plan
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


@pytest.mark.parametrize(
    ("raw_levels", "expected_levels"),
    [
        ([1, 5, 5], [1, 2, 2]),
        ([2, 4], [1, 2]),
        ([3, 5], [1, 2]),
        ([4, 6], [1, 2]),
        ([5, 7], [1, 2]),
        ([1, 4, 6, 4, 1], [1, 2, 3, 2, 1]),
    ],
)
def test_normalize_bookmark_plan_makes_raw_tier_hierarchy_contiguous(
    raw_levels: list[int], expected_levels: list[int]
) -> None:
    plan = [
        _plan_item(f"Heading {index}", level, index)
        for index, level in enumerate(raw_levels, start=1)
    ]

    normalized = normalize_bookmark_plan(plan)

    assert [item.level for item in normalized] == expected_levels
    assert validate_bookmark_plan(normalized, total_pages=len(plan)).valid


def test_normalize_bookmark_plan_preserves_siblings_ancestors_and_metadata() -> None:
    plan = [
        BookmarkPlanItem(
            title="  Book  ",
            level=1,
            pdf_page=1,
            source="first",
            confidence=0.1,
            evidence=["book"],
        ),
        BookmarkPlanItem(
            title="  Chapter A  ",
            level=4,
            pdf_page=2,
            source="second",
            confidence=0.2,
            evidence=["chapter-a"],
        ),
        BookmarkPlanItem(
            title="Section A.1",
            level=6,
            pdf_page=3,
            source="third",
            confidence=0.3,
            evidence=["section"],
        ),
        BookmarkPlanItem(
            title="Chapter B",
            level=4,
            pdf_page=4,
            source="fourth",
            confidence=0.4,
            evidence=["chapter-b"],
        ),
        BookmarkPlanItem(
            title="Appendix",
            level=1,
            pdf_page=5,
            source="fifth",
            confidence=0.5,
            evidence=["appendix"],
        ),
    ]

    normalized = normalize_bookmark_plan(plan)

    assert [item.level for item in normalized] == [1, 2, 3, 2, 1]
    assert [item.title for item in normalized] == [
        "Book",
        "Chapter A",
        "Section A.1",
        "Chapter B",
        "Appendix",
    ]
    assert [
        (item.pdf_page, item.source, item.confidence, item.evidence)
        for item in normalized
    ] == [(item.pdf_page, item.source, item.confidence, item.evidence) for item in plan]
    assert validate_bookmark_plan(normalized, total_pages=5).valid


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
