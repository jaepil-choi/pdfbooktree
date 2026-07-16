"""production bookmark plan을 gold reference와 비교해 평가 지표를 만든다.

실험 102(`experiments/102_engine_bookmark_fuzzy_eval.py`)가 data/300STUDY
400권에서 검증한 fuzzy title 유사도 + page tolerance 매칭을 그대로 승격한다.
title+page만 비교하고 level은 비교하지 않는다 — gold의 level은 원서 편집
방침을, 예측 level은 font tier/geometry를 반영해 서로 다른 기준이라 직접
비교가 무의미하다(실험 102 결론).

gold 자체가 진짜 목차가 아닌 경우(스캔 배치가 매 page에 붙인 일련번호,
분할 도구가 남긴 자리표시자 등)를 가려내는 판정은 여기서 새로 만들지
않는다. `pdfbooktree.pdf.outline_quality.assess_outline_quality()`가 이미
실험 102와 같은 임계값으로 그 판정을 하고 있으므로, gold 품질을 보려면
그 함수를 그대로 재사용하면 된다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.utils.text_normalize import title_similarity

DEFAULT_PAGE_TOLERANCE = 1
DEFAULT_TITLE_SIMILARITY_THRESHOLD = 0.7
DEFAULT_COMPARE_PAGE_TOLERANCE = 0

PlanDiffStatus = Literal["added", "removed", "matched"]


@dataclass(frozen=True)
class MatchMetrics:
    """gold와 예측 bookmark plan을 비교한 집계 지표다."""

    ground_truth_count: int
    predicted_count: int
    true_positive_count: int
    precision: float
    recall: float
    f1: float
    accuracy_jaccard: float
    exact_page_match_rate: float


@dataclass(frozen=True)
class MatchedPair:
    """gold 항목 하나와 그에 매칭된 예측 항목이다."""

    gold: BookmarkPlanItem
    predicted: BookmarkPlanItem
    title_similarity: float
    exact_page_match: bool


@dataclass(frozen=True)
class PlanMatchResult:
    """bookmark plan 매칭의 집계 지표와 item 단위 상세다."""

    metrics: MatchMetrics
    matched: list[MatchedPair] = field(default_factory=list)
    missed: list[BookmarkPlanItem] = field(default_factory=list)
    extra: list[BookmarkPlanItem] = field(default_factory=list)


def match_bookmark_plans(
    gold: list[BookmarkPlanItem],
    predicted: list[BookmarkPlanItem],
    *,
    page_tolerance: int = DEFAULT_PAGE_TOLERANCE,
    title_similarity_threshold: float = DEFAULT_TITLE_SIMILARITY_THRESHOLD,
) -> PlanMatchResult:
    """title 유사도 + page tolerance로 gold-예측 bookmark plan을 그리디 1:1 매칭한다."""

    predicted_by_page: dict[int, list[int]] = defaultdict(list)
    for index, item in enumerate(predicted):
        predicted_by_page[item.pdf_page].append(index)

    scored_pairs: list[tuple[float, int, int]] = []
    for gold_index, gold_item in enumerate(gold):
        candidate_indices: set[int] = set()
        for page in range(
            gold_item.pdf_page - page_tolerance,
            gold_item.pdf_page + page_tolerance + 1,
        ):
            candidate_indices.update(predicted_by_page.get(page, []))
        for predicted_index in candidate_indices:
            score = title_similarity(gold_item.title, predicted[predicted_index].title)
            if score >= title_similarity_threshold:
                scored_pairs.append((score, gold_index, predicted_index))

    scored_pairs.sort(key=lambda row: row[0], reverse=True)
    matched_gold_indices: set[int] = set()
    matched_predicted_indices: set[int] = set()
    matched: list[MatchedPair] = []
    exact_page_matches = 0
    for score, gold_index, predicted_index in scored_pairs:
        if (
            gold_index in matched_gold_indices
            or predicted_index in matched_predicted_indices
        ):
            continue
        matched_gold_indices.add(gold_index)
        matched_predicted_indices.add(predicted_index)
        gold_item = gold[gold_index]
        predicted_item = predicted[predicted_index]
        exact_page_match = gold_item.pdf_page == predicted_item.pdf_page
        if exact_page_match:
            exact_page_matches += 1
        matched.append(
            MatchedPair(
                gold=gold_item,
                predicted=predicted_item,
                title_similarity=score,
                exact_page_match=exact_page_match,
            )
        )

    missed = [
        item for index, item in enumerate(gold) if index not in matched_gold_indices
    ]
    extra = [
        item
        for index, item in enumerate(predicted)
        if index not in matched_predicted_indices
    ]

    true_positive_count = len(matched)
    precision = true_positive_count / len(predicted) if predicted else 0.0
    recall = true_positive_count / len(gold) if gold else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    union = len(predicted) + len(gold) - true_positive_count
    accuracy_jaccard = true_positive_count / union if union > 0 else 0.0
    metrics = MatchMetrics(
        ground_truth_count=len(gold),
        predicted_count=len(predicted),
        true_positive_count=true_positive_count,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        accuracy_jaccard=round(accuracy_jaccard, 4),
        exact_page_match_rate=round(
            exact_page_matches / true_positive_count if true_positive_count else 0.0,
            4,
        ),
    )
    return PlanMatchResult(metrics=metrics, matched=matched, missed=missed, extra=extra)


@dataclass(frozen=True)
class PlanDiffEntry:
    """두 bookmark plan을 비교한 항목 하나다."""

    status: PlanDiffStatus
    before: BookmarkPlanItem | None
    after: BookmarkPlanItem | None
    title_similarity: float | None
    page_changed: bool = False
    level_changed: bool = False
    source_changed: bool = False


@dataclass(frozen=True)
class PlanDiffResult:
    """두 bookmark plan 비교의 집계와 item 단위 상세다."""

    entries: list[PlanDiffEntry]
    added_count: int
    removed_count: int
    matched_count: int
    unchanged_count: int
    moved_count: int
    level_changed_count: int
    source_changed_count: int


def compare_bookmark_plans(
    before: list[BookmarkPlanItem],
    after: list[BookmarkPlanItem],
    *,
    page_tolerance: int = DEFAULT_COMPARE_PAGE_TOLERANCE,
    title_similarity_threshold: float = DEFAULT_TITLE_SIMILARITY_THRESHOLD,
) -> PlanDiffResult:
    """title 유사도 + page tolerance로 두 bookmark plan을 added/removed/moved/level/source로 비교한다.

    같은 pipeline이 만든 두 실행 결과를 비교하는 용도라, 서로 다른 출처를
    비교하는 ``match_bookmark_plans()``의 기본 page tolerance(1)와 달리
    기본값을 0으로 둔다 - page가 달라졌다면 그 자체가 흥미로운 신호(moved)다.
    """

    match = match_bookmark_plans(
        before,
        after,
        page_tolerance=page_tolerance,
        title_similarity_threshold=title_similarity_threshold,
    )

    entries: list[PlanDiffEntry] = []
    moved_count = 0
    level_changed_count = 0
    source_changed_count = 0
    unchanged_count = 0
    for pair in match.matched:
        page_changed = not pair.exact_page_match
        level_changed = pair.gold.level != pair.predicted.level
        source_changed = pair.gold.source != pair.predicted.source
        if page_changed:
            moved_count += 1
        if level_changed:
            level_changed_count += 1
        if source_changed:
            source_changed_count += 1
        if not (page_changed or level_changed or source_changed):
            unchanged_count += 1
        entries.append(
            PlanDiffEntry(
                status="matched",
                before=pair.gold,
                after=pair.predicted,
                title_similarity=pair.title_similarity,
                page_changed=page_changed,
                level_changed=level_changed,
                source_changed=source_changed,
            )
        )
    for item in match.missed:
        entries.append(
            PlanDiffEntry(
                status="removed", before=item, after=None, title_similarity=None
            )
        )
    for item in match.extra:
        entries.append(
            PlanDiffEntry(
                status="added", before=None, after=item, title_similarity=None
            )
        )

    return PlanDiffResult(
        entries=entries,
        added_count=len(match.extra),
        removed_count=len(match.missed),
        matched_count=len(match.matched),
        unchanged_count=unchanged_count,
        moved_count=moved_count,
        level_changed_count=level_changed_count,
        source_changed_count=source_changed_count,
    )
