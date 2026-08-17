"""typography 기반 outline 생성 파이프라인을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from pdfbooktree.config import ProcessingConfig, TypographyConfig
from pdfbooktree.models import TypographyLine
from pdfbooktree.processor import Processor
from pdfbooktree.typography.headings import extract_heading_candidates
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts
from pdfbooktree.typography.tiers import (
    _build_tiers,
    _cluster_by_density,
    assign_tier,
    compute_tier_set,
)

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0


def _계층_불변식을_검증한다(
    values: list[float], peaks: list[float], cuts: list[float]
) -> None:
    tiers = _build_tiers(values, peaks, cuts)

    assert len(tiers) == len(cuts) + 1
    assert [tier.tier for tier in tiers] == list(range(1, len(tiers) + 1))
    assert sum(tier.count for tier in tiers) == len(values)
    assert [tier.lower_bound for tier in tiers[:-1]] == sorted(cuts, reverse=True)
    assert [tier.upper_bound for tier in tiers[1:]] == sorted(cuts, reverse=True)
    assert tiers[0].upper_bound is None
    assert tiers[-1].lower_bound is None
    assert all(assign_tier(tier.peak, cuts) == tier.tier for tier in tiers)


def test_평평한_밀도_골짜기에서도_모든_절단점을_만든다() -> None:
    # 큰 본문 군집과 드문 큰 글씨 군집 사이의 언더플로 평탄 구간은 기존 엄격한
    # 골짜기 검출기가 최소점을 고르지 못하는 배열이다.
    values = [0.0] * 5000 + [float(value) for value in range(100, 109)]

    peaks, cuts = _cluster_by_density(values)

    assert len(peaks) > 1
    assert len(cuts) == len(peaks) - 1
    _계층_불변식을_검증한다(values, peaks, cuts)


def test_봉우리보다_절단점이_부족해도_실제_절단점_기준_계층을_구성한다() -> None:
    values = [5.0, 11.0, 19.0, 21.0, 30.0]
    peaks = [30.0, 22.0, 18.0, 12.0]
    cuts = [10.0, 20.0]

    _계층_불변식을_검증한다(values, peaks, cuts)


def _make_book_pdf(path: Path) -> None:
    document = fitz.open()
    try:
        for page_no in range(1, 7):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            chapter_title = {
                1: "Chapter 1 Introduction",
                4: "Chapter 2 Methods",
            }.get(page_no, f"Chapter {page_no} Introduction")
            page.insert_text((72, 90), chapter_title, fontsize=28)
            page.insert_text((72, 155), f"{page_no}.1 Motivation", fontsize=16)
            for row in range(20):
                page.insert_text(
                    (72, 300 + row * 15),
                    "This is ordinary body text for the chapter.",
                    fontsize=10,
                )
        document.save(path)
    finally:
        document.close()


def test_extract_typography_lines_merges_visual_line_spans(tmp_path: Path) -> None:
    pdf = tmp_path / "split_line.pdf"
    document = fitz.open()
    try:
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_text((72, 100), "Chapter", fontsize=28)
        page.insert_text((190, 100.5), "One", fontsize=28)
        document.save(pdf)
    finally:
        document.close()

    lines = extract_typography_lines(pdf)

    assert len(lines) == 1
    assert lines[0].text == "Chapter One"
    assert lines[0].font_size == 28


def test_exclude_margin_artifacts_removes_numbered_running_header_and_footer() -> None:
    lines = []
    opening_words = {3: "alpha", 4: "beta", 5: "gamma", 6: "delta"}
    for pdf_page in range(3, 7):
        lines.extend(
            [
                TypographyLine(
                    pdf_page=pdf_page,
                    text=f"CHAPTER {pdf_page - 2}. Example {pdf_page - 2}",
                    x0=72.0,
                    y0=12.0,
                    x1=450.0,
                    y1=22.0,
                    page_width=PAGE_WIDTH,
                    page_height=PAGE_HEIGHT,
                    font_size=10.0,
                    height=10.0,
                    is_bold=False,
                ),
                TypographyLine(
                    pdf_page=pdf_page,
                    text="Course Notes",
                    x0=72.0,
                    y0=32.0,
                    x1=150.0,
                    y1=42.0,
                    page_width=PAGE_WIDTH,
                    page_height=PAGE_HEIGHT,
                    font_size=8.0,
                    height=10.0,
                    is_bold=False,
                ),
                TypographyLine(
                    pdf_page=pdf_page,
                    text=f"Opening body {opening_words[pdf_page]}",
                    x0=72.0,
                    y0=82.0,
                    x1=200.0,
                    y1=94.0,
                    page_width=PAGE_WIDTH,
                    page_height=PAGE_HEIGHT,
                    font_size=10.0,
                    height=12.0,
                    is_bold=False,
                ),
                TypographyLine(
                    pdf_page=pdf_page,
                    text=f"Body page {pdf_page}",
                    x0=72.0,
                    y0=300.0,
                    x1=200.0,
                    y1=312.0,
                    page_width=PAGE_WIDTH,
                    page_height=PAGE_HEIGHT,
                    font_size=10.0,
                    height=12.0,
                    is_bold=False,
                ),
            ]
        )
    lines.append(
        TypographyLine(
            pdf_page=7,
            text="5",
            x0=290.0,
            y0=810.0,
            x1=305.0,
            y1=820.0,
            page_width=PAGE_WIDTH,
            page_height=PAGE_HEIGHT,
            font_size=10.0,
            height=10.0,
            is_bold=False,
        )
    )

    kept = exclude_margin_artifacts(
        lines, TypographyConfig(margin_min_consecutive_pages=3)
    )

    assert [line.text for line in kept] == [
        "Opening body alpha",
        "Body page 3",
        "Opening body beta",
        "Body page 4",
        "Opening body gamma",
        "Body page 5",
        "Opening body delta",
        "Body page 6",
    ]


def test_compute_tiers_and_heading_candidates(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    _make_book_pdf(pdf)
    config = TypographyConfig(min_tier_count=1, max_heading_tier=2)

    lines = extract_typography_lines(pdf, config)
    font_tiers = compute_tier_set(lines, "font_size", config)
    height_tiers = compute_tier_set(lines, "height", config)
    candidates = extract_heading_candidates(lines, font_tiers, height_tiers, config)

    assert font_tiers.final_tier_count >= 3
    assert assign_tier(28, font_tiers.cut_points) == 1
    assert {candidate.title for candidate in candidates} >= {
        "Chapter 1 Introduction",
        "Chapter 2 Methods",
    }


def test_extract_heading_candidates_merges_adjacent_same_tier_heading_lines(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "split_heading.pdf"
    document = fitz.open()
    try:
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_text((72, 90), "CHAPTER", fontsize=28)
        page.insert_text((72, 125), "1 Introduction", fontsize=28)
        page.insert_text((72, 200), "1.1 Motivation", fontsize=16)
        page.insert_text(
            (72, 340), "This is ordinary body text for the chapter.", fontsize=10
        )
        document.save(pdf)
    finally:
        document.close()

    config = TypographyConfig(min_tier_count=1, max_heading_tier=2)
    lines = extract_typography_lines(pdf, config)
    font_tiers = compute_tier_set(lines, "font_size", config)
    height_tiers = compute_tier_set(lines, "height", config)
    candidates = extract_heading_candidates(lines, font_tiers, height_tiers, config)

    titles = {candidate.title for candidate in candidates}
    assert "CHAPTER 1 Introduction" in titles
    assert "CHAPTER" not in titles
    assert "1 Introduction" not in titles


def test_extract_heading_candidates_does_not_merge_lines_with_large_gap(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "far_heading.pdf"
    document = fitz.open()
    try:
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_text((72, 90), "CHAPTER", fontsize=28)
        page.insert_text((72, 500), "1 Introduction", fontsize=28)
        page.insert_text((72, 200), "1.1 Motivation", fontsize=16)
        page.insert_text(
            (72, 700), "This is ordinary body text for the chapter.", fontsize=10
        )
        document.save(pdf)
    finally:
        document.close()

    config = TypographyConfig(min_tier_count=1, max_heading_tier=2)
    lines = extract_typography_lines(pdf, config)
    font_tiers = compute_tier_set(lines, "font_size", config)
    height_tiers = compute_tier_set(lines, "height", config)
    candidates = extract_heading_candidates(lines, font_tiers, height_tiers, config)

    titles = {candidate.title for candidate in candidates}
    assert "CHAPTER" in titles
    assert "1 Introduction" in titles
    assert "CHAPTER 1 Introduction" not in titles


def _make_ocr_style_book_pdf(path: Path, chapter_pages: int = 7) -> None:
    """chapter marker가 본문과 같은 font size로 매 page 같은 위치에 나오는 책이다.

    scanned/OCR 책에서 chapter font가 본문 tier에 흡수되는 실패 패턴(실험 098)을
    재현한다. font 골격만으로는 "Chapter N"을 heading으로 볼 수 없고, 반복
    위치만이 유일한 단서다.
    """

    document = fitz.open()
    try:
        for page_no in range(1, chapter_pages + 1):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            if page_no == 1:
                page.insert_text((72, 90), "Book Title", fontsize=24)
            page.insert_text((72, 150), f"Chapter {page_no}", fontsize=10)
            for row in range(10):
                page.insert_text(
                    (72, 200 + row * 14),
                    "This is ordinary OCR body text repeated across the page.",
                    fontsize=10,
                )
        document.save(path)
    finally:
        document.close()


def test_processor_rescues_body_tier_chapter_marker_via_position_fallback(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "ocr_style_book.pdf"
    output_dir = tmp_path / "out"
    _make_ocr_style_book_pdf(pdf)

    result = Processor(
        pdf,
        output_dir,
        ProcessingConfig(typography=TypographyConfig(position_min_repeated_pages=5)),
    ).run()

    assert result.status == "processed"
    plan = json.loads((output_dir / "bookmark_plan_full.json").read_text("utf-8"))
    titles = {item["title"] for item in plan}
    chapter_titles = {f"Chapter {page}" for page in range(1, 8)}
    assert chapter_titles <= titles
    fallback_items = [item for item in plan if item["title"] in chapter_titles]
    assert all(
        item["source"] == "geometry_position_fallback" for item in fallback_items
    )
    assert all(item["level"] >= 2 for item in fallback_items)


def test_processor_position_fallback_disabled_drops_body_tier_chapter_marker(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "ocr_style_book.pdf"
    output_dir = tmp_path / "out"
    _make_ocr_style_book_pdf(pdf)

    Processor(
        pdf,
        output_dir,
        ProcessingConfig(
            typography=TypographyConfig(
                position_min_repeated_pages=5, position_fallback_enabled=False
            )
        ),
    ).run()

    plan = json.loads((output_dir / "bookmark_plan.json").read_text("utf-8"))
    titles = {item["title"] for item in plan}
    chapter_titles = {f"Chapter {page}" for page in range(1, 8)}
    assert not (chapter_titles & titles)


def test_processor_creates_bookmark_pdf_markdown_and_artifacts(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_book_pdf(pdf)

    result = Processor(
        pdf,
        output_dir,
        ProcessingConfig(
            typography=TypographyConfig(min_tier_count=1, max_heading_tier=2)
        ),
    ).run()

    assert result.status == "processed"
    assert result.output_pdf is not None and result.output_pdf.exists()
    assert (
        result.output_markdown_dir is not None and result.output_markdown_dir.exists()
    )
    assert result.bookmark_count >= 2
    assert (output_dir / "whole_book_lines.jsonl").exists()
    assert (output_dir / "font_size_tiers.json").exists()
    assert (output_dir / "height_tiers.json").exists()
    assert (output_dir / "heading_candidates.json").exists()
    assert (output_dir / "bookmark_plan.json").exists()
    assert (result.output_markdown_dir / "toc.md").exists()

    plan = json.loads((output_dir / "bookmark_plan.json").read_text("utf-8"))
    assert plan[0]["title"] == "Chapter 1 Introduction"
    with fitz.open(result.output_pdf) as document:
        toc = document.get_toc()
    assert toc[0][1] == "Chapter 1 Introduction"
