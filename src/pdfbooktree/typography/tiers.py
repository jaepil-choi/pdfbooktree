"""font size와 bbox height tier를 계산한다."""

from __future__ import annotations

import math
from collections import Counter
from typing import Literal

import numpy as np

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import Tier, TierSet, TypographyLine


def compute_tier_set(
    lines: list[TypographyLine],
    signal: Literal["font_size", "height"],
    config: TypographyConfig | None = None,
) -> TierSet:
    """지정한 typography signal의 tier set을 만든다."""

    resolved = config or TypographyConfig()
    values = [
        float(getattr(line, signal)) for line in lines if getattr(line, signal) > 0
    ]
    if not values:
        return TierSet(
            signal=signal,
            cut_points=[],
            tiers=[],
            raw_tier_count=0,
            gap_merged_tier_count=0,
            final_tier_count=0,
        )
    raw_peaks, raw_cuts = _cluster_by_density(values)
    # 가까운 peak를 연쇄 병합하면 11pt 본문과 12pt section heading처럼 서로 다른
    # 역할의 tier가 하나로 합쳐질 수 있다. BPE body separator는 이 구분을 전제로
    # 하므로, 069/080에서 검증한 대로 희소 tier만 병합한다.
    final_peaks, final_cuts = _merge_sparse_tiers(
        values, raw_peaks, raw_cuts, resolved.min_tier_count
    )
    tiers = _build_tiers(values, final_peaks, final_cuts)
    return TierSet(
        signal=signal,
        cut_points=[round(cut, 4) for cut in final_cuts],
        tiers=tiers,
        raw_tier_count=len(raw_peaks),
        gap_merged_tier_count=len(raw_peaks),
        final_tier_count=len(tiers),
    )


def assign_tier(value: float, cut_points: list[float]) -> int:
    """값을 tier 번호로 매핑한다. 1이 가장 큰 글씨다."""

    tier = 1
    for cut in sorted(cut_points, reverse=True):
        if value >= cut:
            return tier
        tier += 1
    return tier


def _cluster_by_density(values: list[float]) -> tuple[list[float], list[float]]:
    arr = np.asarray(values, dtype=float)
    unique = sorted(float(value) for value in np.unique(arr))
    if len(unique) == 1:
        return unique, []
    if len(unique) <= 8:
        cuts = [
            (left + right) / 2.0
            for left, right in zip(unique, unique[1:], strict=False)
        ]
        return sorted(unique, reverse=True), cuts
    std = float(np.std(arr, ddof=1))
    bandwidth = 1.06 * std * (len(arr) ** -0.2)
    if bandwidth <= 0.0 or not math.isfinite(bandwidth):
        return [float(np.median(arr))], []
    grid = np.linspace(float(arr.min()) - 1.0, float(arr.max()) + 1.0, 1024)
    z = (grid[:, None] - arr[None, :]) / bandwidth
    density = np.exp(-0.5 * z * z).sum(axis=1)
    peak_idx = [
        idx
        for idx in range(1, len(density) - 1)
        if density[idx - 1] < density[idx] > density[idx + 1]
    ]
    valley_idx = [
        idx
        for idx in range(1, len(density) - 1)
        if density[idx - 1] > density[idx] < density[idx + 1]
    ]
    if not peak_idx:
        return [float(np.median(arr))], []
    peaks = [float(grid[idx]) for idx in peak_idx]
    cuts = [
        float(grid[idx])
        for idx in valley_idx
        if min(peaks) < float(grid[idx]) < max(peaks)
    ]
    return sorted(peaks, reverse=True), sorted(cuts)


def _merge_close_tiers(
    peaks: list[float], cut_points: list[float], min_gap: float
) -> tuple[list[float], list[float]]:
    if len(peaks) <= 1:
        return peaks, []
    ascending = sorted(peaks)
    merged = [ascending[0]]
    for peak in ascending[1:]:
        if peak - merged[-1] < min_gap:
            merged[-1] = (merged[-1] + peak) / 2.0
        else:
            merged.append(peak)
    cuts = [
        (left + right) / 2.0 for left, right in zip(merged, merged[1:], strict=False)
    ]
    return sorted(merged, reverse=True), sorted(cuts)


def _merge_sparse_tiers(
    values: list[float], peaks: list[float], cut_points: list[float], min_count: int
) -> tuple[list[float], list[float]]:
    if len(peaks) <= 1:
        return peaks, cut_points
    current_peaks = sorted(peaks)
    current_cuts = sorted(cut_points)
    while len(current_peaks) > 1:
        counts = Counter(assign_tier(value, current_cuts) for value in values)
        sparse = [tier for tier, count in counts.items() if count < min_count]
        if not sparse:
            break
        sparse_tier = min(sparse, key=lambda tier: counts[tier])
        sparse_idx_desc = sparse_tier - 1
        sparse_idx = len(current_peaks) - 1 - sparse_idx_desc
        if sparse_idx == 0:
            neighbor_idx = 1
        elif sparse_idx == len(current_peaks) - 1:
            neighbor_idx = sparse_idx - 1
        else:
            left_gap = current_peaks[sparse_idx] - current_peaks[sparse_idx - 1]
            right_gap = current_peaks[sparse_idx + 1] - current_peaks[sparse_idx]
            neighbor_idx = sparse_idx - 1 if left_gap <= right_gap else sparse_idx + 1
        lo, hi = sorted([sparse_idx, neighbor_idx])
        merged_peak = (current_peaks[lo] + current_peaks[hi]) / 2.0
        current_peaks = current_peaks[:lo] + [merged_peak] + current_peaks[hi + 1 :]
        current_cuts = [
            (left + right) / 2.0
            for left, right in zip(current_peaks, current_peaks[1:], strict=False)
        ]
    return sorted(current_peaks, reverse=True), sorted(current_cuts)


def _build_tiers(
    values: list[float], peaks: list[float], cut_points: list[float]
) -> list[Tier]:
    counts = Counter(assign_tier(value, cut_points) for value in values)
    tiers: list[Tier] = []
    sorted_cuts_desc = sorted(cut_points, reverse=True)
    for index, peak in enumerate(sorted(peaks, reverse=True), start=1):
        lower = (
            sorted_cuts_desc[index - 1] if index - 1 < len(sorted_cuts_desc) else None
        )
        upper = sorted_cuts_desc[index - 2] if index >= 2 else None
        tiers.append(
            Tier(
                tier=index,
                lower_bound=lower,
                upper_bound=upper,
                peak=round(peak, 4),
                count=counts.get(index, 0),
            )
        )
    return tiers
