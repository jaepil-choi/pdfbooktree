"""typography line에서 heading 후보를 추출한다."""

from __future__ import annotations

import re
from collections import Counter
from statistics import median

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import HeadingCandidate, TierSet, TypographyLine
from pdfbooktree.typography.tiers import assign_tier
from pdfbooktree.utils.text_normalize import normalize_text

_NUMBERING = re.compile(
    r"^(chapter\s+\d+|part\s+\d+|appendix\s+[a-z]|\d+(?:\.\d+)*|제\s*\d+\s*장)\b",
    re.IGNORECASE,
)
_SECTION_NUMBER = re.compile(r"^\d+(?:\.\d+)+\b")
_WORD = re.compile(r"[A-Za-z가-힣]")


def extract_heading_candidates(
    lines: list[TypographyLine],
    font_tiers: TierSet,
    height_tiers: TierSet,
    config: TypographyConfig | None = None,
) -> list[HeadingCandidate]:
    """상위 typography tier와 텍스트 패턴으로 heading 후보를 만든다."""

    resolved = config or TypographyConfig()
    repeated = _repeated_margin_text(lines)
    kept_lines = [
        line for line in lines if not _is_repeated_margin_line(line, repeated)
    ]
    merged_lines = _merge_adjacent_same_tier_lines(
        kept_lines, font_tiers, resolved.heading_merge_gap_ratio
    )
    candidates: list[HeadingCandidate] = []
    for line in merged_lines:
        text = line.text.strip()
        if not _has_title_shape(text, resolved.max_heading_length):
            continue
        font_tier = (
            assign_tier(line.font_size, font_tiers.cut_points)
            if font_tiers.tiers
            else None
        )
        # height_tier는 font_tier와 독립적인 증거가 아니다: OCR overlay는 폰트
        # 하나로 line마다 font_size를 bbox에 맞춰 정하므로 font_size와 height는
        # 사실상 같은 측정값이다(실험 117 실측: 상관계수 0.9988~1.0, 두 tier
        # 집합의 최상위 tier가 표본 전 권에서 100% 동일). 그래서 large_height_tier를
        # large_font_tier와 별도 evidence로 세면 같은 신호를 두 번 세는 것이다.
        # height_tier 값 자체는 HeadingCandidate.tier 계산 하위 호환을 위해
        # 계속 계산해 둔다.
        height_tier = (
            assign_tier(line.height, height_tiers.cut_points)
            if height_tiers.tiers
            else None
        )
        evidence: list[str] = []
        if font_tier is not None and font_tier <= resolved.max_heading_tier:
            evidence.append("large_font_tier")
        numbering_depth = _numbering_depth(text)
        if numbering_depth is not None:
            evidence.append("numbering_pattern")
        if line.y_center_ratio < 0.28:
            evidence.append("top_page_position")
        if line.is_bold:
            evidence.append("bold")
        if not evidence or not any(item.startswith("large_") for item in evidence):
            continue
        confidence = _score_candidate(evidence, line)
        if confidence < resolved.min_heading_confidence:
            continue
        candidates.append(
            HeadingCandidate(
                title=text,
                pdf_page=line.pdf_page,
                font_tier=font_tier,
                height_tier=height_tier,
                y0=line.y0,
                y1=line.y1,
                numbering_depth=numbering_depth,
                confidence=confidence,
                evidence=evidence,
            )
        )
    return _dedupe_page_titles(candidates)


def _has_title_shape(text: str, max_length: int) -> bool:
    if len(text) > max_length:
        return False
    if not _WORD.search(text):
        return False
    if len(text.split()) > 20:
        return False
    return True


def _numbering_depth(text: str) -> int | None:
    lowered = text.lower().strip()
    if re.match(r"^(chapter|part)\s+\d+\b", lowered) or re.match(
        r"^제\s*\d+\s*장", text
    ):
        return 1
    if re.match(r"^appendix\s+[a-z]\b", lowered):
        return 1
    match = _SECTION_NUMBER.match(text)
    if match:
        return match.group(0).count(".") + 1
    if _NUMBERING.match(text):
        return 1
    return None


def _merge_adjacent_same_tier_lines(
    lines: list[TypographyLine], font_tiers: TierSet, gap_ratio: float
) -> list[TypographyLine]:
    """같은 page + 같은 font tier + 수직으로 인접한 line을 하나로 합친다.

    heading이 'CHAPTER' / '1' / 'The Investment Environment'처럼 여러 line에
    걸쳐 렌더링되면, line 단위로 후보를 만들 때 title 매칭과 계층 추론이 그 중
    fragment 하나에만 꽂혀 나머지 구조가 틀어진다(실험 072/073, Zvi Bodie
    Investments에서 실측: chapter 배너 fragment가 잘못 매칭되면 그 하위 섹션
    전체의 parent 추론이 연쇄로 어긋남). 인접 여부는 수직 gap이
    `max(두 line height) * gap_ratio`를 넘지 않는지로 판단한다 — 같은 tier라도
    페이지 안에서 멀리 떨어진 무관한 텍스트(예: 서로 다른 pull quote)까지
    합쳐지는 것을 막기 위한 gate다. gap_ratio=1.5는 실험 073에서 검증한 값이다.
    """

    if not font_tiers.tiers:
        return lines
    merged: list[TypographyLine] = []
    current: TypographyLine | None = None
    current_tier: int | None = None
    for line in lines:
        tier = assign_tier(line.font_size, font_tiers.cut_points)
        can_merge = (
            current is not None
            and current_tier == tier
            and current.pdf_page == line.pdf_page
            and (line.y0 - current.y1) <= max(current.height, line.height) * gap_ratio
        )
        if can_merge and current is not None:
            current = _combine_lines(current, line)
        else:
            if current is not None:
                merged.append(current)
            current = line
        current_tier = tier
    if current is not None:
        merged.append(current)
    return merged


def _combine_lines(first: TypographyLine, second: TypographyLine) -> TypographyLine:
    return TypographyLine(
        pdf_page=first.pdf_page,
        text=normalize_text(f"{first.text} {second.text}"),
        x0=min(first.x0, second.x0),
        y0=min(first.y0, second.y0),
        x1=max(first.x1, second.x1),
        y1=max(first.y1, second.y1),
        page_width=first.page_width,
        page_height=first.page_height,
        font_size=round(median([first.font_size, second.font_size]), 2),
        height=round(median([first.height, second.height]), 2),
        is_bold=first.is_bold or second.is_bold,
        font_names=tuple(sorted(set(first.font_names) | set(second.font_names))),
    )


def _repeated_margin_text(lines: list[TypographyLine]) -> set[str]:
    counter = Counter(
        line.text.strip().lower()
        for line in lines
        if line.y_center_ratio < 0.08 or line.y_center_ratio > 0.92
    )
    return {text for text, count in counter.items() if count >= 3}


def _is_repeated_margin_line(line: TypographyLine, repeated: set[str]) -> bool:
    return line.text.strip().lower() in repeated and (
        line.y_center_ratio < 0.10 or line.y_center_ratio > 0.90
    )


def _score_candidate(evidence: list[str], line: TypographyLine) -> float:
    score = 0.25
    # large_height_tier는 더 이상 evidence에 없다 - font_size와 height는 같은
    # 측정값의 중복 표현이라 별도로 점수를 주지 않는다(위 extract_heading_candidates
    # 주석 참고).
    score += 0.25 if "large_font_tier" in evidence else 0.0
    score += 0.18 if "numbering_pattern" in evidence else 0.0
    score += 0.07 if "top_page_position" in evidence else 0.0
    score += 0.05 if line.is_bold else 0.0
    return min(round(score, 4), 1.0)


def _dedupe_page_titles(candidates: list[HeadingCandidate]) -> list[HeadingCandidate]:
    best: dict[tuple[int, str], HeadingCandidate] = {}
    for candidate in candidates:
        key = (candidate.pdf_page, candidate.title.lower())
        current = best.get(key)
        if current is None or candidate.confidence > current.confidence:
            best[key] = candidate
    return sorted(
        best.values(),
        key=lambda item: (
            item.pdf_page,
            item.y0,
            item.level if hasattr(item, "level") else 0,
        ),
    )
