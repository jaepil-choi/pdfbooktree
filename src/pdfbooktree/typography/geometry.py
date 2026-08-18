"""font text coverage와 반복 anchor pattern으로 heading 후보를 추출한다."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from math import ceil
from statistics import median
import numpy as np

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import Tier, TierSet, TypographyLine
from pdfbooktree.typography.bpe import BpeHeading
from pdfbooktree.typography.tiers import assign_tier
from pdfbooktree.utils.text_normalize import normalize_text


@dataclass(frozen=True)
class FontCoverageProfile:
    """font tier별 text length와 본문/후보 분류 결과다."""

    body_tiers: frozenset[int]
    candidate_tiers: frozenset[int]
    total_text_length: int
    body_text_length: int
    body_text_ratio: float
    candidate_text_ratio: float
    representative_body_font_size: float
    tier_text_lengths: dict[int, int]


@dataclass(frozen=True)
class _Chunk:
    chunk_id: int
    pdf_page: int
    lines: tuple[TypographyLine, ...]
    x0: float
    y0: float
    page_width: float
    page_height: float
    font_size: float
    text: str

    @property
    def y1(self) -> float:
        return max(line.y1 for line in self.lines)


@dataclass(frozen=True)
class _AnchorPattern:
    current: _Chunk
    following: _Chunk
    values: tuple[float, ...]


@dataclass(frozen=True)
class GeometryContext:
    """chunk/font coverage/본문 line spacing 등 geometry 중간 결과를 공유한다.

    font 골격 추출(`extract_geometry_headings`)과 body-tier position fallback
    (`typography.position_fallback`)이 같은 chunk 분할·본문 tier 판정을 두 번
    계산하지 않도록 한 번만 만들어 재사용한다.
    """

    chunks: tuple[_Chunk, ...]
    font_tiers: TierSet
    profile: FontCoverageProfile
    body_spacing: float
    continuation_upper: float


def compute_geometry_font_tier_set(lines: list[TypographyLine]) -> TierSet:
    """강건한 font-size density valley를 보존해 geometry용 tier를 만든다."""

    values = [float(line.font_size) for line in lines if line.font_size > 0]
    if not values:
        return TierSet(
            signal="font_size",
            cut_points=[],
            tiers=[],
            raw_tier_count=0,
            final_tier_count=0,
        )

    cuts = _font_density_cuts(values)
    assigned: dict[int, list[float]] = defaultdict(list)
    for value in values:
        assigned[assign_tier(value, cuts)].append(value)
    descending_cuts = sorted(cuts, reverse=True)
    tiers = []
    for tier in range(1, len(cuts) + 2):
        tier_values = assigned.get(tier, [])
        lower = descending_cuts[tier - 1] if tier - 1 < len(cuts) else None
        upper = descending_cuts[tier - 2] if tier >= 2 else None
        tiers.append(
            Tier(
                tier=tier,
                lower_bound=lower,
                upper_bound=upper,
                peak=float(median(tier_values)) if tier_values else 0.0,
                count=len(tier_values),
            )
        )
    return TierSet(
        signal="font_size",
        cut_points=cuts,
        tiers=tiers,
        raw_tier_count=len(tiers),
        final_tier_count=len(tiers),
    )


def _font_density_cuts(values: list[float]) -> list[float]:
    """강건한 Silverman bandwidth와 density valley로 font 경계를 찾는다."""

    array = np.asarray(values, dtype=float)
    unique = sorted(float(value) for value in np.unique(array))
    if len(unique) == 1:
        return []
    if len(unique) <= 8:
        return [
            (left + right) / 2.0
            for left, right in zip(unique, unique[1:], strict=False)
        ]

    q1, q3 = np.percentile(array, [25, 75])
    robust_scale = min(float(np.std(array, ddof=1)), float((q3 - q1) / 1.34))
    bandwidth = 0.9 * robust_scale * (len(array) ** -0.2)
    if bandwidth <= 0.0 or not np.isfinite(bandwidth):
        return [
            (left + right) / 2.0
            for left, right in zip(unique, unique[1:], strict=False)
        ]

    grid = np.linspace(float(array.min()), float(array.max()), 2048)
    density = np.zeros_like(grid)
    for batch in np.array_split(array, max(1, ceil(len(array) / 4096))):
        z = (grid[:, None] - batch[None, :]) / bandwidth
        density += np.exp(-0.5 * z * z).sum(axis=1)
    return [
        float(grid[index])
        for index in range(1, len(density) - 1)
        if density[index - 1] > density[index] < density[index + 1]
    ]


def classify_font_tiers_by_text_coverage(
    lines: list[TypographyLine],
    font_tiers: TierSet,
    coverage: float,
) -> FontCoverageProfile:
    """text length가 큰 font tier부터 coverage까지를 본문 tier로 분류한다."""

    if not 0.0 < coverage <= 1.0:
        raise ValueError("body font text coverage는 0보다 크고 1 이하여야 한다.")
    if not lines:
        return FontCoverageProfile(
            body_tiers=frozenset(),
            candidate_tiers=frozenset(),
            total_text_length=0,
            body_text_length=0,
            body_text_ratio=0.0,
            candidate_text_ratio=0.0,
            representative_body_font_size=0.0,
            tier_text_lengths={},
        )

    text_lengths: Counter[int] = Counter()
    line_counts: Counter[int] = Counter()
    tiers_by_line: list[int] = []
    for line in lines:
        tier = assign_tier(line.font_size, font_tiers.cut_points)
        tiers_by_line.append(tier)
        text_lengths[tier] += len(re.sub(r"\s+", "", line.text))
        line_counts[tier] += 1

    total_text_length = sum(text_lengths.values())
    ordered_tiers = sorted(
        text_lengths,
        key=lambda tier: (text_lengths[tier], line_counts[tier], -tier),
        reverse=True,
    )
    body_tiers: set[int] = set()
    body_text_length = 0
    for tier in ordered_tiers:
        body_tiers.add(tier)
        body_text_length += text_lengths[tier]
        if total_text_length == 0 or body_text_length / total_text_length >= coverage:
            break

    all_tiers = set(text_lengths)
    body_sizes = [
        line.font_size
        for line, tier in zip(lines, tiers_by_line, strict=True)
        if tier in body_tiers
    ]
    body_ratio = body_text_length / total_text_length if total_text_length else 0.0
    return FontCoverageProfile(
        body_tiers=frozenset(body_tiers),
        candidate_tiers=frozenset(all_tiers - body_tiers),
        total_text_length=total_text_length,
        body_text_length=body_text_length,
        body_text_ratio=body_ratio,
        candidate_text_ratio=1.0 - body_ratio if total_text_length else 0.0,
        representative_body_font_size=(
            float(median(body_sizes)) if body_sizes else 0.0
        ),
        tier_text_lengths=dict(sorted(text_lengths.items())),
    )


def build_geometry_context(
    lines: list[TypographyLine],
    font_tiers: TierSet,
    config: TypographyConfig | None = None,
) -> GeometryContext:
    """chunk 분할과 본문 tier/line spacing 추론을 한 번만 수행한다."""

    resolved = config or TypographyConfig()
    profile = classify_font_tiers_by_text_coverage(
        lines,
        font_tiers,
        resolved.body_font_text_coverage,
    )
    restored_lines = _merge_printed_line_fragments(lines)
    body_spacing, continuation_upper = _body_spacing_band(
        restored_lines,
        font_tiers,
        profile,
    )
    initial_chunks = _build_chunks(restored_lines, continuation_upper)
    chunks = _merge_adjacent_non_body_chunks(
        initial_chunks,
        font_tiers,
        profile,
        body_spacing,
    )
    return GeometryContext(
        chunks=tuple(chunks),
        font_tiers=font_tiers,
        profile=profile,
        body_spacing=body_spacing,
        continuation_upper=continuation_upper,
    )


def extract_geometry_headings(
    lines: list[TypographyLine],
    font_tiers: TierSet,
    config: TypographyConfig | None = None,
) -> list[BpeHeading]:
    """font coverage와 반복 chunk anchor를 독립적으로 계산해 후보를 선택한다."""

    resolved = config or TypographyConfig()
    if not lines or not font_tiers.tiers:
        return []
    context = build_geometry_context(lines, font_tiers, resolved)
    return select_geometry_headings(context, resolved)


def select_geometry_headings(
    context: GeometryContext,
    config: TypographyConfig | None = None,
) -> list[BpeHeading]:
    """이미 계산된 GeometryContext에서 heading 후보를 선택한다."""

    resolved = config or TypographyConfig()
    chunks = context.chunks
    font_tiers = context.font_tiers
    profile = context.profile
    body_spacing = context.body_spacing
    patterns = _build_anchor_patterns(
        chunks, body_spacing, pattern_mode="following_anchor_4d"
    )
    position_ids = _select_position_candidates(
        patterns,
        resolved.position_min_repeated_pages,
        tolerance=1.0,
    )
    # size_class_depth는 책 내부 상대값이다: 절대 font size나 tier 번호는
    # OCR overlay가 책마다 다른 지점에서 clamp하기 때문에 책 사이에서 의미가
    # 다르지만(실험 117), "이 책에서 큰 순서로 몇 번째 size class인가"는 책
    # 내부에서만 비교하는 상대 서수다(실험 118). tier 번호는 이미 책 안에서
    # 큰 순서로 매겨지므로 tier <= depth가 곧 "상위 depth개 class"다. 0(기본값)은
    # 비활성화이며 기존 candidate_tiers 전체를 그대로 쓴다.
    eligible_font_tiers = profile.candidate_tiers
    if resolved.size_class_depth > 0:
        # tier 번호는 책 안에서 큰 순서로 매겨지지만 body_tiers가 candidate_tiers
        # 사이에 끼어 번호가 듬성듬성할 수 있다. 그래서 depth는 tier 번호 자체가
        # 아니라 candidate_tiers를 크기 순으로 정렬했을 때의 순위로 센다.
        ranked_candidate_tiers = sorted(profile.candidate_tiers)
        eligible_font_tiers = frozenset(
            ranked_candidate_tiers[: resolved.size_class_depth]
        )
    font_ids = {
        chunk.chunk_id
        for chunk in chunks
        if _tier_for_size(chunk.font_size, font_tiers) in eligible_font_tiers
        and chunk.font_size > profile.representative_body_font_size
        and len(chunk.text.split()) <= resolved.body_font_max_words
    }
    if resolved.max_headings_per_page > 0:
        # 한 page에 top-size-class 후보가 너무 많으면 chapter 시작이 아니라
        # 표/배너 page일 가능성이 높다(실험 118: chapter 시작 1~3개 vs
        # 표/배너 7~20개). page 희소성은 어떤 overlay든 주는 일반 정보이므로
        # book-relative 상대 count로만 판정한다. 0(기본값)은 비활성화이며 제한을
        # 걸지 않는다.
        chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        page_counts = Counter(chunk_by_id[chunk_id].pdf_page for chunk_id in font_ids)
        font_ids = {
            chunk_id
            for chunk_id in font_ids
            if page_counts[chunk_by_id[chunk_id].pdf_page]
            <= resolved.max_headings_per_page
        }
    if resolved.heading_candidate_mode == "position":
        selected_ids = position_ids
    elif resolved.heading_candidate_mode == "font":
        selected_ids = font_ids
    elif resolved.heading_candidate_mode == "position_and_font":
        selected_ids = position_ids & font_ids
    else:
        raise ValueError(
            f"지원하지 않는 heading candidate mode다: {resolved.heading_candidate_mode}"
        )

    evidence = {
        "position": [
            "repeated_anchor_pattern",
            "position_tolerance_body_line_spacing",
        ],
        "font": ["font_text_coverage_candidate"],
        "position_and_font": [
            "repeated_anchor_pattern",
            "position_tolerance_body_line_spacing",
            "font_text_coverage_candidate",
        ],
    }[resolved.heading_candidate_mode]
    return [
        BpeHeading(
            title=normalize_text(chunk.text),
            pdf_page=chunk.pdf_page,
            tier=_tier_for_size(chunk.font_size, font_tiers),
            y0=chunk.y0,
            y1=chunk.y1,
            merged_line_count=len(chunk.lines),
            source="geometry_typography",
            evidence=tuple(
                [
                    *evidence,
                    f"position_min_pages_{resolved.position_min_repeated_pages}",
                    f"body_text_coverage_{resolved.body_font_text_coverage:g}",
                ]
            ),
        )
        for chunk in sorted(chunks, key=lambda item: (item.pdf_page, item.y0, item.x0))
        if chunk.chunk_id in selected_ids and normalize_text(chunk.text)
    ]


def _tier_for_size(font_size: float, font_tiers: TierSet) -> int:
    return assign_tier(font_size, font_tiers.cut_points)


def _is_body_line(
    line: TypographyLine,
    font_tiers: TierSet,
    profile: FontCoverageProfile,
) -> bool:
    return _tier_for_size(line.font_size, font_tiers) in profile.body_tiers


def _merge_printed_line_fragments(
    lines: list[TypographyLine],
) -> list[TypographyLine]:
    """세로로 겹치고 가로 영역이 분리된 OCR 조각을 같은 인쇄 line으로 합친다."""

    by_page: dict[int, list[TypographyLine]] = defaultdict(list)
    for line in lines:
        by_page[line.pdf_page].append(line)

    restored: list[TypographyLine] = []
    for page_lines in by_page.values():
        groups: list[list[TypographyLine]] = []
        for line in sorted(page_lines, key=lambda item: (item.y0, item.x0)):
            target = next(
                (
                    group
                    for group in reversed(groups)
                    if min(line.y1, max(item.y1 for item in group))
                    > max(line.y0, min(item.y0 for item in group))
                    and all(line.x1 <= item.x0 or line.x0 >= item.x1 for item in group)
                ),
                None,
            )
            if target is None:
                groups.append([line])
            else:
                target.append(line)
        restored.extend(_combine_line_group(group) for group in groups)
    return sorted(restored, key=lambda item: (item.pdf_page, item.y0, item.x0))


def _combine_line_group(group: list[TypographyLine]) -> TypographyLine:
    ordered = sorted(group, key=lambda item: item.x0)
    first = ordered[0]
    return TypographyLine(
        pdf_page=first.pdf_page,
        text=normalize_text(" ".join(item.text for item in ordered)),
        x0=min(item.x0 for item in ordered),
        y0=min(item.y0 for item in ordered),
        x1=max(item.x1 for item in ordered),
        y1=max(item.y1 for item in ordered),
        page_width=first.page_width,
        page_height=first.page_height,
        font_size=float(median(item.font_size for item in ordered)),
        height=float(median(item.height for item in ordered)),
        is_bold=any(item.is_bold for item in ordered),
        font_names=tuple(
            sorted({name for item in ordered for name in item.font_names})
        ),
    )


def _body_spacing_band(
    lines: list[TypographyLine],
    font_tiers: TierSet,
    profile: FontCoverageProfile,
) -> tuple[float, float]:
    by_page: dict[int, list[TypographyLine]] = defaultdict(list)
    for line in lines:
        if _is_body_line(line, font_tiers, profile):
            by_page[line.pdf_page].append(line)

    gaps: list[float] = []
    for page_lines in by_page.values():
        ordered = sorted(page_lines, key=lambda item: (item.y0, item.x0))
        for upper, lower in zip(ordered, ordered[1:], strict=False):
            if lower.y0 <= upper.y0:
                continue
            if max(upper.x0, lower.x0) >= min(upper.x1, lower.x1):
                continue
            gaps.append(lower.y0 - upper.y0)
    if not gaps:
        return 1.0, 1.0

    top_step = float(median(gaps))
    q1, q3 = np.percentile(gaps, [25, 75])
    upper_fence = float(q3 + 1.5 * (q3 - q1))
    core = [gap for gap in gaps if gap <= upper_fence]
    valleys = _density_valleys(core)
    upper_valleys = [cut for cut in valleys if cut >= top_step]
    continuation_upper = upper_valleys[0] if upper_valleys else float(max(core))
    return top_step, continuation_upper


def _density_valleys(values: list[float]) -> list[float]:
    array = np.asarray(values, dtype=float)
    if len(array) < 3 or np.allclose(array, array[0]):
        return []
    q1, q3 = np.percentile(array, [25, 75])
    robust_scale = min(float(np.std(array, ddof=1)), float((q3 - q1) / 1.34))
    bandwidth = 0.9 * robust_scale * (len(array) ** -0.2)
    if bandwidth <= 0.0 or not np.isfinite(bandwidth):
        return []
    grid = np.linspace(float(array.min()), float(array.max()), 1024)
    density = np.zeros_like(grid)
    for batch in np.array_split(array, max(1, ceil(len(array) / 4096))):
        z = (grid[:, None] - batch[None, :]) / bandwidth
        density += np.exp(-0.5 * z * z).sum(axis=1)
    return [
        float(grid[index])
        for index in range(1, len(density) - 1)
        if density[index - 1] > density[index] < density[index + 1]
    ]


def _build_chunks(
    lines: list[TypographyLine],
    continuation_upper: float,
) -> list[_Chunk]:
    by_page: dict[int, list[TypographyLine]] = defaultdict(list)
    for line in lines:
        by_page[line.pdf_page].append(line)

    chunks: list[_Chunk] = []
    chunk_id = 1
    for page, page_lines in sorted(by_page.items()):
        groups: list[list[TypographyLine]] = []
        for line in sorted(page_lines, key=lambda item: (item.y0, item.x0)):
            if groups and line.y0 - groups[-1][-1].y0 <= continuation_upper:
                groups[-1].append(line)
            else:
                groups.append([line])
        for group in groups:
            first = group[0]
            chunks.append(
                _Chunk(
                    chunk_id=chunk_id,
                    pdf_page=page,
                    lines=tuple(group),
                    x0=first.x0,
                    y0=first.y0,
                    page_width=first.page_width,
                    page_height=first.page_height,
                    font_size=float(median(line.font_size for line in group)),
                    text=normalize_text(" ".join(line.text for line in group)),
                )
            )
            chunk_id += 1
    return chunks


def _merge_adjacent_non_body_chunks(
    chunks: list[_Chunk],
    font_tiers: TierSet,
    profile: FontCoverageProfile,
    body_spacing: float,
) -> list[_Chunk]:
    """같은 방향의 연속 non-body chunk를 첫 anchor를 유지한 채 병합한다."""

    def font_side(chunk: _Chunk) -> int:
        tier = _tier_for_size(chunk.font_size, font_tiers)
        if tier in profile.body_tiers:
            return 0
        return -1 if chunk.font_size < profile.representative_body_font_size else 1

    merged: list[_Chunk] = []
    for chunk in sorted(chunks, key=lambda item: (item.pdf_page, item.y0, item.x0)):
        if not merged:
            merged.append(chunk)
            continue
        previous = merged[-1]
        previous_side = font_side(previous)
        should_merge = (
            previous.pdf_page == chunk.pdf_page
            and chunk.y0 > previous.y0
            and chunk.y0 - previous.y1 <= body_spacing
            and previous_side != 0
            and previous_side == font_side(chunk)
        )
        if not should_merge:
            merged.append(chunk)
            continue
        lines = tuple(
            sorted(previous.lines + chunk.lines, key=lambda item: (item.y0, item.x0))
        )
        merged[-1] = _Chunk(
            chunk_id=previous.chunk_id,
            pdf_page=previous.pdf_page,
            lines=lines,
            x0=previous.x0,
            y0=previous.y0,
            page_width=previous.page_width,
            page_height=previous.page_height,
            font_size=float(median(line.font_size for line in lines)),
            text=normalize_text(f"{previous.text} {chunk.text}"),
        )
    return merged


def _build_anchor_patterns(
    chunks: list[_Chunk],
    body_spacing: float,
    *,
    pattern_mode: str = "following_anchor_4d",
) -> list[_AnchorPattern]:
    """반복 anchor 좌표를 만든다.

    ``following_anchor_4d``는 production 기본값으로 현재+다음 chunk의 (x0,y0)
    4개 값을 anchor로 쓴다. ``current_anchor_2d``는 실험 098/101에서 검증한
    대안으로, 다음 chunk 없이 현재 chunk의 (x0,y0)만 쓴다 — scanned/OCR 책에서
    heading font가 본문 tier에 흡수돼 다음 chunk의 layout이 불안정할 때 4D보다
    반복 위치를 더 잘 잡아낸다(실험 098: 11/11 vs 7/11 chapter 복구).
    """

    if pattern_mode not in {"following_anchor_4d", "current_anchor_2d"}:
        raise ValueError(f"지원하지 않는 anchor pattern mode다: {pattern_mode}")
    by_page: dict[int, list[_Chunk]] = defaultdict(list)
    for chunk in chunks:
        by_page[chunk.pdf_page].append(chunk)

    patterns: list[_AnchorPattern] = []
    for page_chunks in by_page.values():
        ordered = sorted(page_chunks, key=lambda item: (item.y0, item.x0))
        for current, following in zip(ordered, ordered[1:], strict=False):
            if pattern_mode == "current_anchor_2d":
                values = (current.x0 / body_spacing, current.y0 / body_spacing)
            else:
                values = (
                    current.x0 / body_spacing,
                    current.y0 / body_spacing,
                    following.x0 / body_spacing,
                    following.y0 / body_spacing,
                )
            patterns.append(
                _AnchorPattern(current=current, following=following, values=values)
            )
    return patterns


def _select_position_candidates(
    patterns: list[_AnchorPattern],
    minimum_pages: int,
    *,
    tolerance: float = 1.0,
) -> set[int]:
    if minimum_pages < 1:
        raise ValueError("position 최소 반복 page 수는 1 이상이어야 한다.")
    if not patterns:
        return set()
    # anchor 좌표는 이미 본문 top-to-top line spacing으로 정규화되어 있다.
    # 따라서 1.0은 책마다 추론된 본문 line spacing 한 칸의 실제 PDF 좌표 폭이다.
    clusters = _cluster_patterns(patterns, tolerance=tolerance)
    return {
        pattern.current.chunk_id
        for cluster in clusters
        if len({pattern.current.pdf_page for pattern in cluster}) >= minimum_pages
        for pattern in cluster
    }


def _cluster_patterns(
    patterns: list[_AnchorPattern],
    tolerance: float,
) -> list[list[_AnchorPattern]]:
    clusters: list[list[_AnchorPattern]] = []
    for pattern in sorted(patterns, key=lambda item: item.values):
        target = next(
            (
                cluster
                for cluster in clusters
                if all(
                    max(values) - min(values) <= tolerance
                    for values in zip(
                        *(item.values for item in cluster + [pattern]),
                        strict=True,
                    )
                )
            ),
            None,
        )
        if target is None:
            clusters.append([pattern])
        else:
            target.append(pattern)
    return clusters
