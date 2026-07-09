"""typography 기반 outline 생성 파이프라인을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from pdfbooktree.config import ProcessingConfig, TypographyConfig
from pdfbooktree.processor import Processor
from pdfbooktree.typography.headings import extract_heading_candidates
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.tiers import assign_tier, compute_tier_set

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0


def _make_book_pdf(path: Path) -> None:
    document = fitz.open()
    try:
        for page_no in range(1, 7):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            if page_no == 1:
                page.insert_text((72, 90), "Chapter 1 Introduction", fontsize=28)
                page.insert_text((72, 155), "1.1 Motivation", fontsize=16)
            elif page_no == 4:
                page.insert_text((72, 90), "Chapter 2 Methods", fontsize=28)
                page.insert_text((72, 155), "2.1 Measurements", fontsize=16)
            else:
                page.insert_text((72, 90), f"Body page {page_no}", fontsize=10)
            page.insert_text(
                (72, 300), "This is ordinary body text for the chapter.", fontsize=10
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
