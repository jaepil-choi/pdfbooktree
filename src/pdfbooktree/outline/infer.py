"""heading 후보 sequence를 bookmark plan으로 변환한다."""

from __future__ import annotations

from pdfbooktree.models import BookmarkPlanItem, HeadingCandidate


def infer_outline(candidates: list[HeadingCandidate]) -> list[BookmarkPlanItem]:
    """heading 후보를 순서 있는 bookmark plan으로 변환한다."""

    plan: list[BookmarkPlanItem] = []
    previous_level = 1
    seen: set[tuple[int, str]] = set()
    for candidate in sorted(candidates, key=lambda item: (item.pdf_page, item.y0)):
        key = (candidate.pdf_page, candidate.title.lower())
        if key in seen:
            continue
        seen.add(key)
        level = _infer_level(candidate)
        if plan and level > previous_level + 1:
            level = previous_level + 1
        previous_level = level
        plan.append(
            BookmarkPlanItem(
                title=candidate.title,
                level=level,
                pdf_page=candidate.pdf_page,
                source="typography",
                confidence=candidate.confidence,
                evidence=candidate.evidence,
            )
        )
    return plan


def _infer_level(candidate: HeadingCandidate) -> int:
    if candidate.numbering_depth is not None:
        return max(1, min(candidate.numbering_depth, 6))
    tiers = [
        tier
        for tier in [candidate.font_tier, candidate.height_tier]
        if tier is not None
    ]
    if not tiers:
        return 1
    return max(1, min(min(tiers), 6))
