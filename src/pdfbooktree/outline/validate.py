"""bookmark plan 검증 로직이다."""

from __future__ import annotations

from pdfbooktree.models import BookmarkPlanItem, BookmarkPlanValidation


def validate_bookmark_plan(
    plan: list[BookmarkPlanItem], total_pages: int
) -> BookmarkPlanValidation:
    """bookmark plan의 level과 page target을 검증한다."""

    warnings: list[str] = []
    previous_level = 0
    previous_page = 0
    for index, item in enumerate(plan, start=1):
        if not item.title.strip():
            warnings.append(f"{index}번째 bookmark title이 비어 있다.")
        if item.level < 1:
            warnings.append(f"{index}번째 bookmark level이 1보다 작다: {item.level}")
        if previous_level and item.level > previous_level + 1:
            warnings.append(
                f"{index}번째 bookmark level jump가 크다: {previous_level} -> {item.level}"
            )
        if not 1 <= item.pdf_page <= total_pages:
            warnings.append(
                f"{index}번째 bookmark page가 범위를 벗어났다: {item.pdf_page}"
            )
        if item.pdf_page < previous_page:
            warnings.append(
                f"{index}번째 bookmark page가 이전 항목보다 앞선다: {item.pdf_page} < {previous_page}"
            )
        previous_level = item.level
        previous_page = item.pdf_page
    if not plan:
        warnings.append("bookmark plan이 비어 있다.")
    return BookmarkPlanValidation(
        valid=not warnings, item_count=len(plan), warnings=warnings
    )
