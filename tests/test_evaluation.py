from __future__ import annotations

from pdfbooktree.evaluation import compare_bookmark_plans, match_bookmark_plans
from pdfbooktree.models import BookmarkPlanItem


def _item(
    title: str, page: int, level: int = 1, source: str = "typography"
) -> BookmarkPlanItem:
    return BookmarkPlanItem(title=title, level=level, pdf_page=page, source=source)


def test_match_bookmark_plans_matches_exact_title_and_page() -> None:
    gold = [_item("Chapter 1", 10), _item("Chapter 2", 40)]
    predicted = [_item("Chapter 1", 10), _item("Chapter 2", 40)]

    result = match_bookmark_plans(gold, predicted)

    assert result.metrics.true_positive_count == 2
    assert result.metrics.precision == 1.0
    assert result.metrics.recall == 1.0
    assert result.metrics.f1 == 1.0
    assert result.metrics.exact_page_match_rate == 1.0
    assert not result.missed
    assert not result.extra
    assert [pair.gold.title for pair in result.matched] == ["Chapter 1", "Chapter 2"]


def test_match_bookmark_plans_matches_within_page_tolerance() -> None:
    gold = [_item("Chapter 1", 10)]
    predicted = [_item("Chapter 1", 11)]

    result = match_bookmark_plans(gold, predicted, page_tolerance=1)

    assert result.metrics.true_positive_count == 1
    assert result.matched[0].exact_page_match is False
    assert result.metrics.exact_page_match_rate == 0.0


def test_match_bookmark_plans_rejects_match_outside_page_tolerance() -> None:
    gold = [_item("Chapter 1", 10)]
    predicted = [_item("Chapter 1", 12)]

    result = match_bookmark_plans(gold, predicted, page_tolerance=1)

    assert result.metrics.true_positive_count == 0
    assert result.missed == gold
    assert result.extra == predicted


def test_match_bookmark_plans_reports_missed_and_extra_items() -> None:
    gold = [_item("Chapter 1", 10), _item("Chapter 2", 40)]
    predicted = [_item("Chapter 1", 10), _item("Unexpected Section", 25)]

    result = match_bookmark_plans(gold, predicted)

    assert result.metrics.true_positive_count == 1
    assert [item.title for item in result.missed] == ["Chapter 2"]
    assert [item.title for item in result.extra] == ["Unexpected Section"]


def test_match_bookmark_plans_matches_each_predicted_item_at_most_once() -> None:
    gold = [_item("Chapter 1", 10), _item("Chapter 1", 10)]
    predicted = [_item("Chapter 1", 10)]

    result = match_bookmark_plans(gold, predicted)

    assert result.metrics.true_positive_count == 1
    assert len(result.matched) == 1
    assert len(result.missed) == 1
    assert not result.extra


def test_match_bookmark_plans_respects_title_similarity_threshold() -> None:
    gold = [_item("Chapter 1", 10)]
    predicted = [_item("Appendix B", 10)]

    result = match_bookmark_plans(gold, predicted, title_similarity_threshold=0.7)

    assert result.metrics.true_positive_count == 0
    assert result.missed == gold
    assert result.extra == predicted


def test_match_bookmark_plans_handles_empty_predicted() -> None:
    gold = [_item("Chapter 1", 10)]

    result = match_bookmark_plans(gold, [])

    assert result.metrics.precision == 0.0
    assert result.metrics.recall == 0.0
    assert result.metrics.accuracy_jaccard == 0.0
    assert result.missed == gold
    assert not result.extra


def test_match_bookmark_plans_handles_empty_gold() -> None:
    predicted = [_item("Chapter 1", 10)]

    result = match_bookmark_plans([], predicted)

    assert result.metrics.precision == 0.0
    assert result.metrics.recall == 0.0
    assert result.extra == predicted


def test_compare_bookmark_plans_marks_identical_items_unchanged() -> None:
    before = [_item("Chapter 1", 10), _item("Chapter 2", 40)]
    after = [_item("Chapter 1", 10), _item("Chapter 2", 40)]

    diff = compare_bookmark_plans(before, after)

    assert diff.matched_count == 2
    assert diff.unchanged_count == 2
    assert diff.moved_count == 0
    assert diff.level_changed_count == 0
    assert diff.source_changed_count == 0
    assert diff.added_count == 0
    assert diff.removed_count == 0
    assert all(entry.status == "matched" for entry in diff.entries)


def test_compare_bookmark_plans_reports_added_and_removed() -> None:
    before = [_item("Chapter 1", 10)]
    after = [_item("Chapter 2", 40)]

    diff = compare_bookmark_plans(before, after)

    assert diff.added_count == 1
    assert diff.removed_count == 1
    assert diff.matched_count == 0
    statuses = {entry.status for entry in diff.entries}
    assert statuses == {"added", "removed"}


def test_compare_bookmark_plans_detects_moved_page_beyond_default_tolerance() -> None:
    before = [_item("Chapter 1", 10)]
    after = [_item("Chapter 1", 12)]

    diff = compare_bookmark_plans(before, after)

    assert diff.added_count == 1
    assert diff.removed_count == 1
    assert diff.matched_count == 0


def test_compare_bookmark_plans_matches_moved_page_within_tolerance() -> None:
    before = [_item("Chapter 1", 10)]
    after = [_item("Chapter 1", 12)]

    diff = compare_bookmark_plans(before, after, page_tolerance=2)

    assert diff.matched_count == 1
    assert diff.moved_count == 1
    assert diff.unchanged_count == 0
    entry = diff.entries[0]
    assert entry.status == "matched"
    assert entry.page_changed is True
    assert entry.before.pdf_page == 10
    assert entry.after.pdf_page == 12


def test_compare_bookmark_plans_detects_level_change() -> None:
    before = [_item("Chapter 1", 10, level=1)]
    after = [_item("Chapter 1", 10, level=2)]

    diff = compare_bookmark_plans(before, after)

    assert diff.matched_count == 1
    assert diff.level_changed_count == 1
    assert diff.moved_count == 0
    assert diff.unchanged_count == 0
    assert diff.entries[0].level_changed is True


def test_compare_bookmark_plans_detects_source_change() -> None:
    before = [_item("Chapter 1", 10, source="typography")]
    after = [_item("Chapter 1", 10, source="existing_outline")]

    diff = compare_bookmark_plans(before, after)

    assert diff.matched_count == 1
    assert diff.source_changed_count == 1
    assert diff.unchanged_count == 0
    assert diff.entries[0].source_changed is True
