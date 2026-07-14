"""Markdown split coverage가 실패했을 때 적용할 명시적 fallback 정책이다."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class MarkdownSplitFallbackDecision:
    """coverage 실패 뒤 선택한 fallback level과 사유다."""

    chosen_level: int | None
    used: bool
    reason: str | None


def choose_deepest_available_level(
    trials: Mapping[int, Sequence[object]],
) -> MarkdownSplitFallbackDecision:
    """문서가 존재하는 가장 깊은 bookmark level을 fallback으로 선택한다."""

    available_levels = [level for level, documents in trials.items() if documents]
    if not available_levels:
        return MarkdownSplitFallbackDecision(
            chosen_level=None,
            used=False,
            reason="no_documents_at_any_level",
        )
    return MarkdownSplitFallbackDecision(
        chosen_level=max(available_levels),
        used=True,
        reason="coverage_target_unsatisfied",
    )
