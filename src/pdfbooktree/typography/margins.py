"""반복 header/footer를 typography 분석 전에 제거한다."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import TypographyLine

_NUMBER = re.compile(r"(?<!\d)\d{1,4}(?!\d)")


def exclude_margin_artifacts(
    lines: list[TypographyLine], config: TypographyConfig | None = None
) -> list[TypographyLine]:
    """반복 margin text와 연속 printed page number가 있는 margin 위치를 제외한다.

    실험 015의 offset 방식처럼 각 숫자에 ``pdf_page - printed_page``를 계산한다.
    같은 offset이 연속 page에 유지될 때, 그 수열에 속하는 page number를 포함한
    margin line을 running header/footer로 본다. 따라서 page number와 한 줄로 합쳐진
    chapter header는 제거하면서 같은 y 좌표의 본문은 보존한다.
    """

    resolved = config or TypographyConfig()
    if not lines:
        return []

    offsets_all: dict[int, set[int]] = defaultdict(set)
    repeated_texts: Counter[tuple[tuple[str, int], str]] = Counter()
    slots_by_line: dict[TypographyLine, tuple[str, int]] = {}
    for line in lines:
        slot = _margin_slot(line, resolved)
        if slot is None:
            continue
        slots_by_line[line] = slot
        repeated_texts[(slot, _normalized_text(line.text))] += 1
        for number in _numbers(line.text, resolved.margin_max_page_number):
            offset = line.pdf_page - number
            offsets_all[offset].add(line.pdf_page)

    repeated_lines = {
        (slot, text)
        for (slot, text), count in repeated_texts.items()
        if count >= resolved.margin_min_repeated_lines
    }
    reliable_offset_pages = {
        offset: _pages_in_consecutive_runs(pages, resolved.margin_min_consecutive_pages)
        for offset, pages in offsets_all.items()
    }
    return [
        line
        for line in lines
        if (
            (slot := slots_by_line.get(line)) is None
            or (slot, _normalized_text(line.text)) not in repeated_lines
            and not _has_reliable_page_number(line, reliable_offset_pages, resolved)
        )
    ]


def _margin_slot(
    line: TypographyLine, config: TypographyConfig
) -> tuple[str, int] | None:
    """상·하단 margin line의 y 좌표를 겹칠 수 있는 slot으로 바꾼다."""

    y_ratio = line.y_center_ratio
    if y_ratio <= config.margin_band_ratio:
        band = "top"
    elif y_ratio >= 1.0 - config.margin_band_ratio:
        band = "bottom"
    else:
        return None
    bucket = round(y_ratio / config.margin_position_tolerance_ratio)
    return band, bucket


def _numbers(text: str, maximum: int) -> list[int]:
    return [
        number
        for match in _NUMBER.findall(text)
        if 0 < (number := int(match)) <= maximum
    ]


def _pages_in_consecutive_runs(pages: set[int], minimum_length: int) -> set[int]:
    """minimum_length 이상 연속된 page run에 속한 page만 돌려준다."""

    accepted: set[int] = set()
    current: list[int] = []
    previous: int | None = None
    for page in sorted(pages):
        if previous is None or page == previous + 1:
            current.append(page)
        else:
            if len(current) >= minimum_length:
                accepted.update(current)
            current = [page]
        previous = page
    if len(current) >= minimum_length:
        accepted.update(current)
    return accepted


def _has_reliable_page_number(
    line: TypographyLine,
    reliable_offset_pages: dict[int, set[int]],
    config: TypographyConfig,
) -> bool:
    """긴 offset run에 속한 page number가 있는 margin line만 제거한다."""

    return any(
        line.pdf_page in reliable_offset_pages.get(line.pdf_page - number, set())
        for number in _numbers(line.text, config.margin_max_page_number)
    )


def _normalized_text(text: str) -> str:
    return " ".join(text.lower().split())
