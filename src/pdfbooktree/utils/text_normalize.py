"""OCR text와 제목 비교용 문자열 정규화를 제공한다."""

from __future__ import annotations

import re


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


def extract_lines(text: str) -> list[str]:
    """빈 줄을 제외한 정규화 line 목록을 반환한다."""

    return [
        line for raw_line in text.splitlines() if (line := normalize_text(raw_line))
    ]
