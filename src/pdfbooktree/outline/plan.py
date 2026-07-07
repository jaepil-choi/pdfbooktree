"""bookmark plan 정규화 helper다."""

from __future__ import annotations

from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.utils.text_normalize import normalize_text


def normalize_bookmark_plan(plan: list[BookmarkPlanItem]) -> list[BookmarkPlanItem]:
    """title 공백을 정리하고 같은 page/title 중복을 제거한다."""

    normalized: list[BookmarkPlanItem] = []
    seen: set[tuple[int, str]] = set()
    for item in plan:
        title = normalize_text(item.title)
        key = (item.pdf_page, title.lower())
        if not title or key in seen:
            continue
        seen.add(key)
        normalized.append(
            BookmarkPlanItem(
                title=title,
                level=max(1, item.level),
                pdf_page=item.pdf_page,
                source=item.source,
                confidence=item.confidence,
                evidence=item.evidence,
            )
        )
    return normalized
