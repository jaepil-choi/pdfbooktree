"""typography line에서 heading 후보를 추출한다."""

from __future__ import annotations

import re
from collections import Counter

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import HeadingCandidate, TierSet, TypographyLine
from pdfbooktree.typography.tiers import assign_tier

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
    candidates: list[HeadingCandidate] = []
    for line in lines:
        text = line.text.strip()
        if not _has_title_shape(text, resolved.max_heading_length):
            continue
        if _is_repeated_margin_line(line, repeated):
            continue
        font_tier = (
            assign_tier(line.font_size, font_tiers.cut_points)
            if font_tiers.tiers
            else None
        )
        height_tier = (
            assign_tier(line.height, height_tiers.cut_points)
            if height_tiers.tiers
            else None
        )
        evidence: list[str] = []
        if font_tier is not None and font_tier <= resolved.max_heading_tier:
            evidence.append("large_font_tier")
        if height_tier is not None and height_tier <= resolved.max_heading_tier:
            evidence.append("large_height_tier")
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
    score += 0.25 if "large_font_tier" in evidence else 0.0
    score += 0.2 if "large_height_tier" in evidence else 0.0
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
