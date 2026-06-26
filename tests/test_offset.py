"""page offset 추정 단위 테스트.

data/ 실제 PDF 의존을 피해 fitz로 합성 PDF를 만들어 결정적으로 검증한다.
합성 PDF는 footer/header에 page number를 그려 넣어 word box 좌표 경로를 그대로 탄다.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pdfbooktree.alignment.offset import (
    OffsetEstimationError,
    estimate_page_offset,
    longest_consecutive_run,
    summarize_offsets,
)
from pdfbooktree.config import OffsetEstimationConfig
from pdfbooktree.pdf.page_numbers import extract_page_numbers

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
FOOTER_Y = 810.0  # 하위 10% band(>= 757.8) 안


def _make_pdf(path: Path, page_specs: list[list[tuple[float, float, str]]]) -> None:
    """page_specs대로 텍스트를 배치한 합성 PDF를 만든다.

    page_specs[i]는 i번째 page에 그릴 (x, y, text) 목록이다.
    """

    document = fitz.open()
    try:
        for spec in page_specs:
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            for x, y, text in spec:
                page.insert_text((x, y), text, fontsize=12)
        document.save(str(path))
    finally:
        document.close()


# --- 순수 함수 ---------------------------------------------------------------


def test_extract_page_numbers_basic() -> None:
    assert extract_page_numbers("19", 3000) == [19]
    assert extract_page_numbers("- 12 -", 3000) == [12]
    assert extract_page_numbers("", 3000) == []


def test_extract_page_numbers_keeps_all_groups_even_with_letters() -> None:
    # running header여도 \d+ 그룹을 모두 후보로 남긴다.
    assert extract_page_numbers("Part1 guide 23", 3000) == [1, 23]


def test_extract_page_numbers_respects_max_number() -> None:
    assert extract_page_numbers("9999", 3000) == []


def test_longest_consecutive_run() -> None:
    assert longest_consecutive_run(5, {6, 7, 8, 10, 11}) == 3
    assert longest_consecutive_run(0, set()) == 0


def test_summarize_offsets_dominance() -> None:
    summary = summarize_offsets([1, 1, 1, 2])
    assert summary["estimated_offset"] == 1
    assert summary["modal_count"] == 3
    assert summary["second_count"] == 1
    assert summary["dominance_ratio"] == 3.0


def test_summarize_offsets_single_offset_is_infinite_dominance() -> None:
    summary = summarize_offsets([4, 4, 4])
    assert summary["dominance_ratio"] == float("inf")


def test_summarize_offsets_empty() -> None:
    assert summarize_offsets([])["estimated_offset"] is None


# --- 합성 PDF 기반 estimate_page_offset --------------------------------------


def test_estimate_clean_offset(tmp_path: Path) -> None:
    # pdf_page 6..25에 printed 1..20을 그려 offset 5를 만든다(앞 5장은 front matter).
    specs: list[list[tuple[float, float, str]]] = []
    for pdf_page in range(1, 26):
        printed = pdf_page - 5
        specs.append([(300.0, FOOTER_Y, str(printed))] if printed >= 1 else [])
    pdf_path = tmp_path / "clean.pdf"
    _make_pdf(pdf_path, specs)

    result = estimate_page_offset(pdf_path)
    assert result.offset == 5
    assert result.evidence[0]["printed_page_1_estimated_pdf_page"] == 6


def test_estimate_recovers_split_digits(tmp_path: Path) -> None:
    # printed 10..29를 두 textbox("1","0")로 쪼개 그려도 병합해 복원한다.
    specs: list[list[tuple[float, float, str]]] = []
    for pdf_page in range(1, 21):
        printed = pdf_page + 9  # 10..29, offset -9
        tens, ones = str(printed)[0], str(printed)[1]
        specs.append([(300.0, FOOTER_Y, tens), (306.0, FOOTER_Y, ones)])
    pdf_path = tmp_path / "split.pdf"
    _make_pdf(pdf_path, specs)

    result = estimate_page_offset(pdf_path)
    assert result.offset == -9


def test_estimate_ignores_running_header_noise(tmp_path: Path) -> None:
    # footer에 상수 노이즈("Part 1")와 증가하는 page number를 함께 둔다.
    specs: list[list[tuple[float, float, str]]] = []
    for pdf_page in range(1, 21):
        printed = pdf_page + 8  # offset -8
        specs.append(
            [
                (100.0, FOOTER_Y, "Part 1"),
                (500.0, FOOTER_Y, str(printed)),
            ]
        )
    pdf_path = tmp_path / "noisy.pdf"
    _make_pdf(pdf_path, specs)

    result = estimate_page_offset(pdf_path)
    assert result.offset == -8


def test_estimate_fast_fail_when_no_page_numbers(tmp_path: Path) -> None:
    # band에 숫자가 전혀 없는 PDF는 fast-fail.
    specs = [[(300.0, 400.0, "본문 텍스트")] for _ in range(5)]
    pdf_path = tmp_path / "empty.pdf"
    _make_pdf(pdf_path, specs)

    with pytest.raises(OffsetEstimationError):
        estimate_page_offset(pdf_path)


def test_estimate_fast_fail_when_not_clean(tmp_path: Path) -> None:
    # offset 분포가 0,0,1,1,2로 흩어져 최빈 우세가 약하면 fast-fail.
    footers = ["1", "2", "2", "3", "3"]  # offsets: 0,0,1,1,2
    specs = [[(300.0, FOOTER_Y, value)] for value in footers]
    pdf_path = tmp_path / "ambiguous.pdf"
    _make_pdf(pdf_path, specs)

    with pytest.raises(OffsetEstimationError):
        estimate_page_offset(pdf_path)


def test_estimate_respects_config_thresholds(tmp_path: Path) -> None:
    # 깔끔한 offset이라도 min_modal_count를 높이면 fast-fail해야 한다.
    specs: list[list[tuple[float, float, str]]] = []
    for pdf_page in range(1, 7):
        specs.append([(300.0, FOOTER_Y, str(pdf_page))])  # offset 0, modal_count 6
    pdf_path = tmp_path / "few.pdf"
    _make_pdf(pdf_path, specs)

    strict = OffsetEstimationConfig(min_modal_count=100)
    with pytest.raises(OffsetEstimationError):
        estimate_page_offset(pdf_path, strict)
