"""font tier에 흡수된 body-tier heading을 반복 위치로 rescue한다.

scanned/OCR 책은 chapter 제목 font가 본문 font tier에 흡수되는 경우가 흔하다
(실험 098: 통계학원론 chapter font candidate=0/11). font 골격만으로는 이런
heading을 절대 찾지 못하지만, 같은 page-local 위치에 여러 page에 걸쳐
반복되고 다른 반복 패턴과 충분히 떨어져 있으면(실험 097/098/101에서 검증한
current-anchor 2D + support + isolation 조건) heading일 가능성이 높다.

이 모듈은 후보만 찾고 level은 정하지 않는다 — level은 font 골격 plan의
page-range parent 아래에 삽입하는 문제라서 outline 쪽(`outline.plan`)의
책임이다(실험 100: page-range parent 삽입은 precision gate가 아니라 순수
level 결정 방식이라는 결론).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.typography.geometry import (
    GeometryContext,
    _AnchorPattern,
    _build_anchor_patterns,
    _cluster_patterns,
    _tier_for_size,
)
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text


@dataclass(frozen=True)
class PositionFallbackCandidate:
    """font 골격에 없는 body-tier heading 후보다."""

    title: str
    pdf_page: int
    y0: float
    y1: float
    support_pages: int
    isolation_ratio: float
    font_ratio: float
    confidence: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class _ClusterStat:
    support_pages: int
    isolation_ratio: float
    patterns: tuple[_AnchorPattern, ...]


def select_body_tier_position_fallback(
    context: GeometryContext,
    font_plan: list[BookmarkPlanItem],
    config: TypographyConfig | None = None,
) -> list[PositionFallbackCandidate]:
    """반복 위치는 강하지만 font 골격이 놓친 body-tier heading을 찾는다."""

    resolved = config or TypographyConfig()
    if not context.chunks or context.profile.representative_body_font_size <= 0:
        return []
    patterns = _build_anchor_patterns(
        list(context.chunks),
        context.body_spacing,
        pattern_mode="current_anchor_2d",
    )
    if not patterns:
        return []
    clusters = _cluster_patterns(
        patterns, tolerance=resolved.position_fallback_tolerance
    )
    stat_by_chunk_id = {
        pattern.current.chunk_id: stat
        for stat in _cluster_statistics(clusters)
        for pattern in stat.patterns
    }

    candidates: list[PositionFallbackCandidate] = []
    for chunk in context.chunks:
        if len(chunk.lines) != 1:
            continue
        stat = stat_by_chunk_id.get(chunk.chunk_id)
        if stat is None:
            continue
        if stat.support_pages < resolved.position_min_repeated_pages:
            continue
        if stat.isolation_ratio < resolved.position_fallback_min_isolation_ratio:
            continue
        if (
            _tier_for_size(chunk.font_size, context.font_tiers)
            not in context.profile.body_tiers
        ):
            continue
        font_ratio = chunk.font_size / context.profile.representative_body_font_size
        if not (
            resolved.position_fallback_body_font_ratio_low
            <= font_ratio
            <= resolved.position_fallback_body_font_ratio_high
        ):
            continue
        if _duplicates_existing_title(chunk.pdf_page, chunk.text, font_plan, resolved):
            continue
        candidates.append(
            PositionFallbackCandidate(
                title=normalize_text(chunk.text),
                pdf_page=chunk.pdf_page,
                y0=chunk.y0,
                y1=chunk.y1,
                support_pages=stat.support_pages,
                isolation_ratio=round(stat.isolation_ratio, 4),
                font_ratio=round(font_ratio, 4),
                confidence=0.6,
                evidence=(
                    "repeated_body_tier_position",
                    f"position_support_pages_{stat.support_pages}",
                    f"position_isolation_{stat.isolation_ratio:.2f}",
                ),
            )
        )
    return sorted(candidates, key=lambda item: (item.pdf_page, item.y0))


def _cluster_statistics(clusters: list[list[_AnchorPattern]]) -> list[_ClusterStat]:
    """cluster별 distinct page 지지도와 다른 cluster로부터의 isolation을 잰다."""

    if not clusters:
        return []
    centers = []
    diameters = []
    support_pages_list = []
    for cluster in clusters:
        values = np.asarray([pattern.values for pattern in cluster], dtype=float)
        centers.append(np.median(values, axis=0))
        diameters.append(
            float(np.max(np.ptp(values, axis=0))) if len(cluster) > 1 else 0.0
        )
        support_pages_list.append(
            len({pattern.current.pdf_page for pattern in cluster})
        )
    center_matrix = np.asarray(centers, dtype=float)

    stats: list[_ClusterStat] = []
    for index, cluster in enumerate(clusters):
        if len(clusters) <= 1:
            isolation_ratio = 0.0
        else:
            distances = np.max(np.abs(center_matrix - center_matrix[index]), axis=1)
            distances[index] = math.inf
            isolation_ratio = float(np.min(distances)) / max(diameters[index], 0.05)
        stats.append(
            _ClusterStat(
                support_pages=support_pages_list[index],
                isolation_ratio=isolation_ratio,
                patterns=tuple(cluster),
            )
        )
    return stats


def _duplicates_existing_title(
    pdf_page: int,
    title: str,
    font_plan: list[BookmarkPlanItem],
    config: TypographyConfig,
) -> bool:
    return any(
        item.pdf_page == pdf_page
        and _title_similarity(item.title, title)
        >= config.position_fallback_title_dedupe_threshold
        for item in font_plan
    )


def _title_similarity(left: str, right: str) -> float:
    """포함 관계, 문자 순서, token 중복 중 가장 강한 제목 유사도를 반환한다."""

    left_norm = normalize_for_match(left)
    right_norm = normalize_for_match(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if min(len(left_norm), len(right_norm)) >= 4 and (
        left_norm in right_norm or right_norm in left_norm
    ):
        return 1.0
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    overlap = (
        2.0 * len(left_tokens & right_tokens) / (len(left_tokens) + len(right_tokens))
        if left_tokens and right_tokens
        else 0.0
    )
    return max(sequence, overlap)
