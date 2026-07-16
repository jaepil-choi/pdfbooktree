"""OCR text와 제목 비교용 문자열 정규화를 제공한다."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


LIGATURE_REPLACEMENTS = {
    "ﬁ": "fi",
    "ﬂ": "fl",
    "–": "-",
    "—": "-",
    "’": "'",
    "“": '"',
    "”": '"',
}


def normalize_text(text: str) -> str:
    """제어 문자와 반복 공백을 정리한다."""

    text = text.replace("\x00", " ")
    text = text.replace("\x08", " ")
    text = text.replace("\u0001", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_match(text: str) -> str:
    """제목 fuzzy matching에 쓰기 좋은 형태로 문자열을 정규화한다."""

    for source, target in LIGATURE_REPLACEMENTS.items():
        text = text.replace(source, target)

    text = normalize_text(text).lower()
    text = re.sub(r"\.{2,}", " ", text)
    text = re.sub(r"[\s.·•_=-]{4,}", " ", text)
    text = re.sub(r"\b\d{1,4}\s*$", " ", text)
    text = re.sub(r"[^0-9a-z가-힣]+", " ", text)
    return normalize_text(text)


def title_similarity(left: str, right: str) -> float:
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


def extract_lines(text: str) -> list[str]:
    """빈 줄을 제외한 정규화 line 목록을 반환한다."""

    return [
        line for raw_line in text.splitlines() if (line := normalize_text(raw_line))
    ]
