"""Processor의 기존 outline 처리 경로를 검증한다."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.config import (
    MarkdownSplitConfig,
    OutlineQualityConfig,
    ProcessingConfig,
    TypographyConfig,
)
from pdfbooktree.processor import Processor

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0


def test_processor_exports_markdown_for_existing_outline(tmp_path: Path) -> None:
    pdf = tmp_path / "bookmarked.pdf"
    document = fitz.open()
    try:
        for index in range(3):
            page = document.new_page()
            page.insert_text((72, 72), f"Page {index + 1}", fontsize=12)
        document.set_toc([[1, "Chapter 1", 1], [2, "1.1 Topic", 2]])
        document.save(pdf)
    finally:
        document.close()

    result = Processor(pdf, tmp_path / "out").run()

    assert result.status == "processed"
    assert result.output_pdf is None
    assert result.output_markdown_dir is not None
    assert (result.output_markdown_dir / "toc.md").exists()
    assert result.markdown_export is not None
    assert result.markdown_export.export_mode == "tree_graph"
    assert result.markdown_export.manifest_path is not None
    assert result.artifact_paths["markdown_manifest"] == (
        result.markdown_export.manifest_path
    )
    assert result.bookmark_count == 2
    assert result.existing_outline_quality is not None
    assert result.existing_outline_quality.is_low_quality is True
    assert "too_few_items" in result.existing_outline_quality.reasons
    assert any("low quality" in warning for warning in result.warnings)


def test_processor_exports_coverage_split_for_existing_outline(tmp_path: Path) -> None:
    pdf = tmp_path / "bookmarked.pdf"
    document = fitz.open()
    try:
        for index in range(3):
            page = document.new_page()
            page.insert_text((72, 72), "one two three four five", fontsize=12)
        document.set_toc([[1, "Chapter 1", 1], [2, "Topic", 2]])
        document.save(pdf)
    finally:
        document.close()

    result = Processor(
        pdf,
        tmp_path / "out",
        ProcessingConfig(
            markdown_split=MarkdownSplitConfig(max_words=16, max_words_coverage=1.0)
        ),
    ).run()

    assert result.status == "processed"
    assert result.markdown_export is not None
    assert result.markdown_export.chosen_level == 2
    assert result.markdown_export.file_count == 2
    assert result.markdown_export.manifest_path is not None


def test_existing_outline_split은_same_page의_하위_heading을_보존한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "same-page-bookmarked.pdf"
    document = fitz.open()
    try:
        for index in range(3):
            page = document.new_page()
            page.insert_text(
                (72, 72),
                f"Page {index + 1} body text",
                fontsize=12,
            )
        document.set_toc(
            [
                [1, "Chapter 1", 1],
                [2, "Section Before Next Chapter", 2],
                [1, "Chapter 2", 2],
                [2, "Section 2", 3],
            ]
        )
        document.save(pdf)
    finally:
        document.close()

    result = Processor(
        pdf,
        tmp_path / "out",
        ProcessingConfig(
            markdown_split=MarkdownSplitConfig(
                max_words=1_000,
                max_words_coverage=1.0,
            )
        ),
    ).run()

    assert result.markdown_export is not None
    assert result.markdown_export.chosen_level == 1
    node_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((result.output_markdown_dir / "nodes").glob("*.md"))
    )
    assert node_text.count("## Section Before Next Chapter") == 1
    assert node_text.count("<!-- pdf_page 2 -->") == 1


def _make_typography_book_with_tiny_toc(path: Path) -> None:
    """low quality(2-item) embedded TOC와 실제 typography 골격을 함께 담은 책이다."""

    document = fitz.open()
    try:
        for page_no in range(1, 7):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            chapter_title = {1: "Chapter 1 Introduction", 4: "Chapter 2 Methods"}.get(
                page_no, f"Chapter {page_no} Introduction"
            )
            page.insert_text((72, 90), chapter_title, fontsize=28)
            page.insert_text((72, 155), f"{page_no}.1 Motivation", fontsize=16)
            for row in range(20):
                page.insert_text(
                    (72, 300 + row * 15),
                    "This is ordinary body text for the chapter.",
                    fontsize=10,
                )
        document.set_toc([[1, "Chapter 1", 1], [1, "Chapter 2", 4]])
        document.save(path)
    finally:
        document.close()


def test_processor_skips_low_quality_existing_outline_by_default(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_typography_book_with_tiny_toc(pdf)

    result = Processor(
        pdf,
        tmp_path / "out",
        ProcessingConfig(
            typography=TypographyConfig(min_tier_count=1, max_heading_tier=2)
        ),
    ).run()

    assert result.output_pdf is None
    assert result.bookmark_count == 2
    assert result.existing_outline_quality is not None
    assert result.existing_outline_quality.is_low_quality is True


def test_processor_replaces_low_quality_existing_outline_when_configured(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_typography_book_with_tiny_toc(pdf)

    result = Processor(
        pdf,
        tmp_path / "out",
        ProcessingConfig(
            typography=TypographyConfig(min_tier_count=1, max_heading_tier=2),
            outline_quality=OutlineQualityConfig(replace_when_low_quality=True),
        ),
    ).run()

    assert result.status == "processed"
    assert result.output_pdf is not None and result.output_pdf.exists()
    assert result.bookmark_count > 2
    assert result.existing_outline_quality is not None
    assert result.existing_outline_quality.is_low_quality is True
    assert result.artifact_paths["bookmark_review_summary"].is_file()
    assert result.artifact_paths["bookmark_review_items"].is_file()
    assert result.artifact_paths["existing_outline_plan"].is_file()
