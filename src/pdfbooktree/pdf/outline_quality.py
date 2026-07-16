"""기존 PDF outline이 실제 목차가 아닐 가능성을 판정한다.

실험 102(`experiments/102_engine_bookmark_fuzzy_eval.py`)가 300STUDY 400권을
훑어본 결과, embedded bookmark 자체가 진짜 목차가 아닌 경우가 흔했다:
item 수가 총 page 수와 거의 같으면 스캔 배치가 매 page에 붙인 일련번호
파일명이고, item 수가 3개 이하면 PDF 분할/병합 도구가 남긴 자리표시자인
경우가 대부분이었다. 이 모듈은 그 두 신호와, title이 숫자로만 이뤄진
item이 있는지를 함께 보는 세 번째 신호로 low quality 여부를 판정한다.
"""

from __future__ import annotations

from pdfbooktree.config import OutlineQualityConfig
from pdfbooktree.models import ExistingOutlineItem, OutlineQualityAssessment


def assess_outline_quality(
    items: list[ExistingOutlineItem],
    total_pages: int,
    config: OutlineQualityConfig | None = None,
) -> OutlineQualityAssessment:
    """outline item 수·비율·title 패턴으로 low quality 여부를 판정한다."""

    resolved = config or OutlineQualityConfig()
    reasons: list[str] = []
    evidence: list[str] = []
    item_count = len(items)

    if item_count < resolved.min_item_count:
        reasons.append("too_few_items")
        evidence.append(
            f"item_count={item_count} < min_item_count={resolved.min_item_count}"
        )

    if total_pages > 0 and item_count >= total_pages * resolved.max_item_to_page_ratio:
        reasons.append("near_one_bookmark_per_page")
        evidence.append(
            f"item_count={item_count} >= total_pages({total_pages}) * "
            f"max_item_to_page_ratio({resolved.max_item_to_page_ratio})"
        )

    if resolved.flag_numeric_only_titles:
        numeric_titles = [
            item.title.strip() for item in items if item.title.strip().isdigit()
        ]
        if numeric_titles:
            reasons.append("numeric_only_title")
            evidence.append(f"numeric_only_titles={numeric_titles[:5]}")

    return OutlineQualityAssessment(
        is_low_quality=bool(reasons),
        item_count=item_count,
        reasons=reasons,
        evidence=evidence,
    )
