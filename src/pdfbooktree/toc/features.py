"""TOC page 탐지에 쓰는 objective feature를 계산한다."""

from __future__ import annotations

import re
import statistics

from pdfbooktree.models import PageFeature, PdfPageText
from pdfbooktree.utils.text_normalize import normalize_text


TOC_KEYWORDS = (
    "contents",
    "table of contents",
    "목차",
    "차례",
)


def extract_line_final_number(line: str) -> int | None:
    """line 끝에 있는 page number 후보를 추출한다."""

    match = re.search(r"(?<![\w.])(\d{1,4})[\s.)\]]*$", line.strip())
    if not match:
        return None
    return int(match.group(1))


def extract_page_number_candidates(text: str) -> list[int]:
    """text 안의 standalone page number 후보를 순서대로 추출한다."""

    candidates: list[int] = []
    for match in re.finditer(r"(?<![\w.])(\d{1,4})(?![\w.])", text):
        number = int(match.group(1))
        if number <= 0 or number > 2000:
            continue
        candidates.append(number)
    return candidates


def monotonicity(numbers: list[int]) -> float | None:
    """숫자열이 거의 증가하는 정도를 0.0-1.0으로 계산한다."""

    if len(numbers) < 2:
        return None
    non_decreasing_count = sum(
        1 for left, right in zip(numbers, numbers[1:], strict=False) if right >= left
    )
    return non_decreasing_count / (len(numbers) - 1)


def gap_stats(numbers: list[int]) -> dict[str, float | int | None]:
    """line-final number gap 통계를 계산한다."""

    if len(numbers) < 2:
        return {
            "mean_gap": None,
            "median_gap": None,
            "max_gap": None,
            "negative_gap_count": 0,
        }

    gaps = [right - left for left, right in zip(numbers, numbers[1:], strict=False)]
    return {
        "mean_gap": statistics.mean(gaps),
        "median_gap": statistics.median(gaps),
        "max_gap": max(gaps),
        "negative_gap_count": sum(1 for gap in gaps if gap < 0),
    }


def has_toc_keyword(text: str) -> bool:
    """TOC keyword 존재 여부를 약한 feature로 계산한다."""

    lowered = text.lower()
    return any(keyword in lowered for keyword in TOC_KEYWORDS)


def is_toc_entry_like(line: str) -> bool:
    """TOC 항목처럼 보이는 line인지 판단한다."""

    normalized = normalize_text(line)
    if len(normalized) < 8:
        return False
    if extract_line_final_number(normalized) is None:
        return False

    lowered = normalized.lower()
    patterns = (
        r"^\d+(\.\d+)*\s+\S+",
        r"^chapter\s+\d+",
        r"^part\s+[ivx0-9]+",
        r"^appendix\s+[a-z0-9]+",
        r"^[a-z]\.\d+\s+\S+",
    )
    return any(re.search(pattern, lowered) for pattern in patterns)


def calculate_page_feature(page: PdfPageText, total_pages: int) -> PageFeature:
    """단일 page의 TOC 탐지 feature를 계산한다."""

    line_lengths = [len(line) for line in page.lines]
    final_numbers = [
        final_number
        for line in page.lines
        if (final_number := extract_line_final_number(line)) is not None
    ]
    gaps = gap_stats(final_numbers)
    toc_entry_lines = [line for line in page.lines if is_toc_entry_like(line)]
    return PageFeature(
        pdf_page=page.pdf_page,
        line_count=len(page.lines),
        word_count=len(normalize_text(page.text).split()),
        mean_line_length=statistics.mean(line_lengths) if line_lengths else 0.0,
        line_length_std=statistics.pstdev(line_lengths)
        if len(line_lengths) > 1
        else 0.0,
        line_final_number_count=len(final_numbers),
        line_final_numbers=final_numbers,
        line_final_number_monotonicity=monotonicity(final_numbers),
        line_final_number_gap_mean=gaps["mean_gap"],
        line_final_number_gap_median=gaps["median_gap"],
        line_final_number_gap_max=gaps["max_gap"],
        line_final_number_negative_gap_count=gaps["negative_gap_count"],
        toc_entry_pattern_count=len(toc_entry_lines),
        toc_entry_pattern_ratio=len(toc_entry_lines) / len(page.lines)
        if page.lines
        else 0.0,
        chapter_or_part_line_count=sum(
            1
            for line in page.lines
            if re.search(r"\b(chapter|part|appendix)\b", line, re.I)
        ),
        page_position=page.pdf_page / total_pages,
        toc_keyword_presence=has_toc_keyword(page.text),
    )


def calculate_page_features(
    pages: list[PdfPageText], total_pages: int
) -> list[PageFeature]:
    """여러 page의 feature를 계산한다."""

    return [calculate_page_feature(page, total_pages) for page in pages]
