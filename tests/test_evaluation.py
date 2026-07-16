from __future__ import annotations

from pdfbooktree.evaluation import match_bookmark_plans
from pdfbooktree.models import BookmarkPlanItem


def _item(title: str, page: int, level: int = 1) -> BookmarkPlanItem:
    return BookmarkPlanItem(title=title, level=level, pdf_page=page)


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
    assert not result.missed
