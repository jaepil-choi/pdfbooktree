"""bookmark plan 정규화 helper다."""

from __future__ import annotations

from dataclasses import dataclass

from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.typography.position_fallback import PositionFallbackCandidate
from pdfbooktree.utils.text_normalize import normalize_text


def normalize_bookmark_plan(plan: list[BookmarkPlanItem]) -> list[BookmarkPlanItem]:
    """title 공백을 정리하고 같은 page/title 중복을 제거한 뒤 계층을 잇는다."""

    normalized: list[BookmarkPlanItem] = []
    seen: set[tuple[int, str]] = set()
    active_raw_tiers: list[int] = []
    for item in plan:
        title = normalize_text(item.title)
        key = (item.pdf_page, title.lower())
        if not title or key in seen:
            continue
        seen.add(key)
        raw_tier = max(1, item.level)
        if raw_tier in active_raw_tiers:
            active_raw_tiers = active_raw_tiers[: active_raw_tiers.index(raw_tier) + 1]
        else:
            # 새 tier가 현재보다 상위면 종료된 하위 tier를 걷어 낸다.
            while active_raw_tiers and raw_tier < active_raw_tiers[-1]:
                active_raw_tiers.pop()
            active_raw_tiers.append(raw_tier)
        normalized.append(
            BookmarkPlanItem(
                title=title,
                level=len(active_raw_tiers),
                pdf_page=item.pdf_page,
                source=item.source,
                confidence=item.confidence,
                evidence=item.evidence,
            )
        )
    return normalized


@dataclass(frozen=True)
class _PlanRange:
    item: BookmarkPlanItem
    index: int
    start: int
    end: int


def insert_position_fallback(
    font_plan: list[BookmarkPlanItem],
    fallback_candidates: list[PositionFallbackCandidate],
    total_pages: int,
) -> list[BookmarkPlanItem]:
    """body-tier position fallback 후보를 가장 깊은 font parent 아래에 끼운다.

    후보의 level은 font tier 스택이 아니라, 그 page를 포함하는 가장 깊고 가까운
    font 골격 item의 page-range보다 한 단계 아래로 정한다(실험 100: page-range
    parent 삽입은 precision을 올리는 필터가 아니라 순수 level 결정 방식이라는
    결론). font 골격이 비어 있거나 해당 page를 포함하는 parent가 없으면 그
    후보는 버린다 — 어디에도 못 붙일 heading은 넣지 않는 편이 안전하다.

    같은 page에 font 항목과 fallback 후보가 함께 있으면 font 항목을 먼저
    배치한다. `BookmarkPlanItem`은 y0를 보존하지 않아 page 단위보다 세밀한
    정렬은 할 수 없지만, `_deepest_parent`가 항상 가장 안쪽 range를 고르기
    때문에 이 page 단위 병합만으로도 stack 기반 tree 구성(outline.tree)에서
    부모-자식 관계가 정확히 유지된다.
    """

    if not fallback_candidates:
        return list(font_plan)
    ranges = _plan_ranges(font_plan, total_pages)
    if not ranges:
        return list(font_plan)

    inserted: list[BookmarkPlanItem] = []
    for candidate in sorted(
        fallback_candidates, key=lambda item: (item.pdf_page, item.y0)
    ):
        parent = _deepest_parent(candidate.pdf_page, ranges)
        if parent is None:
            continue
        inserted.append(
            BookmarkPlanItem(
                title=candidate.title,
                level=parent.item.level + 1,
                pdf_page=candidate.pdf_page,
                source="geometry_position_fallback",
                confidence=candidate.confidence,
                evidence=list(candidate.evidence),
            )
        )
    if not inserted:
        return list(font_plan)

    tagged = [(0, index, item) for index, item in enumerate(font_plan)] + [
        (1, index, item) for index, item in enumerate(inserted)
    ]
    tagged.sort(key=lambda row: (row[2].pdf_page, row[0], row[1]))
    return [item for _, _, item in tagged]


def _plan_ranges(plan: list[BookmarkPlanItem], total_pages: int) -> list[_PlanRange]:
    ranges: list[_PlanRange] = []
    for index, item in enumerate(plan):
        end = total_pages
        for later in plan[index + 1 :]:
            if later.level <= item.level:
                end = max(item.pdf_page, later.pdf_page - 1)
                break
        ranges.append(_PlanRange(item=item, index=index, start=item.pdf_page, end=end))
    return ranges


def _deepest_parent(pdf_page: int, ranges: list[_PlanRange]) -> _PlanRange | None:
    eligible = [row for row in ranges if row.start <= pdf_page <= row.end]
    if not eligible:
        return None
    return max(eligible, key=lambda row: (row.item.level, row.start, row.index))
