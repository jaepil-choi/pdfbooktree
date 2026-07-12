"""본문 separator와 line spacing을 이용해 heading BPE를 만든다."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import BookmarkPlanItem, TierSet, TypographyLine
from pdfbooktree.typography.tiers import assign_tier
from pdfbooktree.utils.text_normalize import normalize_text


@dataclass(frozen=True)
class BpeHeading:
    """BPE 병합 뒤 stack hierarchy에 입력할 heading token이다."""

    title: str
    pdf_page: int
    tier: int
    y0: float
    y1: float
    merged_line_count: int
    is_pollution: bool = False
    confidence: float = 0.8


@dataclass
class _Token:
    kind: str
    pdf_page: int
    text: str
    tier_sequence: tuple[int, ...]
    tier: int | None
    y0: float
    y1: float
    height: float
    merged_line_count: int = 1
    is_pollution: bool = False


def extract_bpe_headings(
    lines: list[TypographyLine],
    font_tiers: TierSet,
    config: TypographyConfig | None = None,
) -> list[BpeHeading]:
    """본문 tier는 separator로 남기고 non-body heading token만 BPE 병합한다."""

    resolved = config or TypographyConfig()
    if not lines or not font_tiers.tiers:
        return []
    ordered = sorted(lines, key=lambda line: (line.pdf_page, line.y0, line.x0))
    tiers = [assign_tier(line.font_size, font_tiers.cut_points) for line in ordered]
    body_tier = _body_tier(tiers)
    body_flags = [tier >= body_tier for tier in tiers]
    page_spacing, fallback_spacing = _body_spacing(ordered, body_flags)
    tokens = [
        _Token(
            kind="separator" if is_body else "heading",
            pdf_page=line.pdf_page,
            text=normalize_text(line.text),
            tier_sequence=() if is_body else (tier,),
            tier=None if is_body else tier,
            y0=line.y0,
            y1=line.y1,
            height=line.height,
        )
        for line, tier, is_body in zip(ordered, tiers, body_flags, strict=True)
    ]
    merged = _merge_bpe(
        tokens,
        page_spacing,
        fallback_spacing,
        min_pair_count=resolved.bpe_min_pair_count,
        max_iterations=resolved.bpe_max_iterations,
    )
    filtered = _apply_pollution_policy(
        merged,
        max_node_words=resolved.bpe_max_node_words,
    )
    return [
        BpeHeading(
            title=token.text,
            pdf_page=token.pdf_page,
            tier=token.tier or min(token.tier_sequence),
            y0=token.y0,
            y1=token.y1,
            merged_line_count=token.merged_line_count,
            is_pollution=token.is_pollution,
        )
        for token in filtered
        if token.kind == "heading" and token.text
    ]


def infer_bpe_outline(
    headings: list[BpeHeading], config: TypographyConfig | None = None
) -> list[BookmarkPlanItem]:
    """font tier stack으로 BPE heading의 bookmark level을 결정한다."""

    resolved = config or TypographyConfig()
    plan: list[BookmarkPlanItem] = []
    polluted_by_level: Counter[int] = Counter()
    counts_by_level: Counter[int] = Counter()
    stack: list[BpeHeading] = []
    for heading in headings:
        while stack and stack[-1].tier > heading.tier:
            stack.pop()
        if stack and stack[-1].tier == heading.tier:
            level = len(stack)
            stack[-1] = heading
        else:
            stack.append(heading)
            level = len(stack)
        item_level = level + int(heading.is_pollution)
        counts_by_level[item_level] += 1
        polluted_by_level[item_level] += heading.is_pollution
        plan.append(
            BookmarkPlanItem(
                title=heading.title,
                level=item_level,
                pdf_page=heading.pdf_page,
                source="bpe_typography",
                confidence=0.8,
                evidence=[
                    "body_separator",
                    "body_line_spacing",
                    f"font_tier_{heading.tier}",
                ],
            )
        )
    body_levels = {
        level
        for level, count in counts_by_level.items()
        if polluted_by_level[level] / count > resolved.bpe_level_pollution_ratio
    }
    return [item for item in plan if item.level not in body_levels]


def _body_tier(tiers: list[int]) -> int:
    counts = Counter(tiers)
    # 짧은 PDF처럼 빈도가 동률이면 더 작은 글씨(큰 tier 번호)를 본문으로 택한다.
    # 그렇지 않으면 source 순서상 먼저 나온 큰 chapter title이 body가 될 수 있다.
    return max(counts, key=lambda tier: (counts[tier], tier))


def _body_spacing(
    lines: list[TypographyLine], body_flags: list[bool]
) -> tuple[dict[int, float], float]:
    by_page: dict[int, list[TypographyLine]] = defaultdict(list)
    for line, is_body in zip(lines, body_flags, strict=True):
        if is_body:
            by_page[line.pdf_page].append(line)
    page_values: dict[int, float] = {}
    all_values: list[float] = []
    for page, page_lines in by_page.items():
        values = [
            value
            for upper, lower in zip(page_lines, page_lines[1:], strict=False)
            if (
                value := _relative_spacing(
                    upper.y0, upper.height, lower.y0, lower.height
                )
            )
            is not None
        ]
        if values:
            page_values[page] = float(median(values))
            all_values.extend(values)
    return page_values, float(median(all_values)) if all_values else 1.0


def _relative_spacing(
    upper_y0: float, upper_height: float, lower_y0: float, lower_height: float
) -> float | None:
    delta = lower_y0 - upper_y0
    if delta <= 0:
        return None
    return delta / max(upper_height, lower_height, 1e-6)


def _apply_pollution_policy(
    tokens: list[_Token],
    max_node_words: int,
) -> list[_Token]:
    """장문 BPE node를 표시해 최종 bookmark level을 한 단계 낮춘다."""

    for token in tokens:
        if token.kind != "heading" or token.tier is None:
            continue
        if _word_count(token.text) > max_node_words:
            token.is_pollution = True
    return tokens


def _word_count(text: str) -> int:
    return len(text.split())


def _merge_bpe(
    tokens: list[_Token],
    page_spacing: dict[int, float],
    fallback_spacing: float,
    min_pair_count: int,
    max_iterations: int,
) -> list[_Token]:
    nodes = list(tokens)
    for _ in range(max_iterations):
        pair_counts: Counter[tuple[tuple[int, ...], tuple[int, ...]]] = Counter()
        pair_positions: dict[tuple[tuple[int, ...], tuple[int, ...]], list[int]] = (
            defaultdict(list)
        )
        for index, (upper, lower) in enumerate(zip(nodes, nodes[1:], strict=False)):
            if upper.kind != "heading" or lower.kind != "heading":
                continue
            if upper.pdf_page != lower.pdf_page:
                continue
            spacing = _relative_spacing(upper.y0, upper.height, lower.y0, lower.height)
            if spacing is None or spacing > page_spacing.get(
                upper.pdf_page, fallback_spacing
            ):
                continue
            pair = (upper.tier_sequence, lower.tier_sequence)
            pair_counts[pair] += 1
            pair_positions[pair].append(index)
        if not pair_counts:
            break
        pair, count = pair_counts.most_common(1)[0]
        if count < min_pair_count:
            break
        merge_at = set(pair_positions[pair])
        merged: list[_Token] = []
        index = 0
        while index < len(nodes):
            if index in merge_at and index + 1 < len(nodes):
                upper, lower = nodes[index], nodes[index + 1]
                merged.append(
                    _Token(
                        kind="heading",
                        pdf_page=upper.pdf_page,
                        text=normalize_text(f"{upper.text} {lower.text}"),
                        tier_sequence=upper.tier_sequence + lower.tier_sequence,
                        tier=min(upper.tier_sequence + lower.tier_sequence),
                        y0=upper.y0,
                        y1=lower.y1,
                        height=upper.height + lower.height,
                        merged_line_count=upper.merged_line_count
                        + lower.merged_line_count,
                    )
                )
                index += 2
            else:
                merged.append(nodes[index])
                index += 1
        nodes = merged
    return nodes
