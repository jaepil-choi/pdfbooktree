"""analyze_pdf/infer_bookmarks/apply_plan 개별 public 함수를 검증한다."""

from __future__ import annotations

from dataclasses import is_dataclass
from pathlib import Path

import fitz

from pdfbooktree.config import MarkdownSplitConfig, TypographyConfig
from pdfbooktree.models import BookmarkPlanItem, PdfAnalysis, TypographyLine
from pdfbooktree.outline.validate import validate_bookmark_plan
from pdfbooktree.pipeline import analyze_pdf, apply_plan, infer_bookmarks

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0


def _make_simple_pdf(path: Path, page_count: int = 3) -> None:
    document = fitz.open()
    try:
        for page_no in range(1, page_count + 1):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            page.insert_text((72, 90), f"Page {page_no} body text", fontsize=10)
        document.save(path)
    finally:
        document.close()


def _make_ocr_style_book_pdf(path: Path, chapter_pages: int = 7) -> None:
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


def test_analyze_pdf_returns_plain_dataclass_lines(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    _make_simple_pdf(pdf)

    analysis = analyze_pdf(pdf)

    assert analysis.input_pdf == pdf
    assert analysis.total_pages == 3
    assert analysis.lines
    assert all(
        is_dataclass(line) and isinstance(line, TypographyLine)
        for line in analysis.lines
    )
    assert analysis.extraction_config_hash


def test_analyze_pdf_extraction_config_hash_tracks_config(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    _make_simple_pdf(pdf)

    same_a = analyze_pdf(pdf, TypographyConfig(line_y_tolerance_ratio=0.5))
    same_b = analyze_pdf(pdf, TypographyConfig(line_y_tolerance_ratio=0.5))
    different = analyze_pdf(pdf, TypographyConfig(line_y_tolerance_ratio=0.7))

    assert same_a.extraction_config_hash == same_b.extraction_config_hash
    assert same_a.extraction_config_hash != different.extraction_config_hash


def test_infer_bookmarks_excludes_margin_lines_before_tiering() -> None:
    lines = []
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
    analysis = PdfAnalysis(input_pdf=Path("dummy.pdf"), total_pages=7, lines=lines)

    inference = infer_bookmarks(
        analysis, TypographyConfig(margin_min_consecutive_pages=3)
    )

    kept_texts = {line.text for line in inference.lines}
    assert "Course Notes" not in kept_texts
    assert all(not text.startswith("CHAPTER") for text in kept_texts)
    assert {f"Body page {page}" for page in range(3, 7)} <= kept_texts


def test_infer_bookmarks_respects_position_fallback_enabled(tmp_path: Path) -> None:
    pdf = tmp_path / "ocr_style_book.pdf"
    _make_ocr_style_book_pdf(pdf)
    analysis = analyze_pdf(pdf)

    enabled = infer_bookmarks(
        analysis,
        TypographyConfig(position_min_repeated_pages=5, position_fallback_enabled=True),
    )
    disabled = infer_bookmarks(
        analysis,
        TypographyConfig(
            position_min_repeated_pages=5, position_fallback_enabled=False
        ),
    )

    assert enabled.fallback_candidates
    assert disabled.fallback_candidates == []


def test_infer_bookmarks_validation_matches_standalone_validate_call(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_simple_pdf(pdf)
    analysis = analyze_pdf(pdf)

    inference = infer_bookmarks(analysis)

    assert inference.validation == validate_bookmark_plan(
        inference.plan, analysis.total_pages
    )


def test_apply_plan_writes_pdf_and_markdown_for_valid_plan(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_simple_pdf(pdf)
    plan = [
        BookmarkPlanItem(title="Chapter 1", level=1, pdf_page=1),
        BookmarkPlanItem(title="Chapter 2", level=1, pdf_page=2),
    ]

    result = apply_plan(pdf, output_dir, plan, total_pages=3)

    assert result.validation.valid
    assert result.output_pdf is not None and result.output_pdf.exists()
    assert (
        result.output_markdown_dir is not None
        and (result.output_markdown_dir / "toc.md").exists()
    )


def test_apply_plan_skips_writing_for_invalid_plan(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_simple_pdf(pdf)
    plan = [BookmarkPlanItem(title="Out of range", level=1, pdf_page=99)]

    result = apply_plan(pdf, output_dir, plan, total_pages=3)

    assert not result.validation.valid
    assert result.output_pdf is None
    assert result.output_markdown_dir is None
    assert not list(output_dir.glob("*_bookmarked.pdf"))


def test_apply_plan_does_not_reextract_typography(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_simple_pdf(pdf)
    plan = [BookmarkPlanItem(title="Chapter 1", level=1, pdf_page=1)]

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("apply_plan은 typography extraction을 다시 하면 안 된다.")

    monkeypatch.setattr("pdfbooktree.pipeline.extract_typography_lines", _fail)

    result = apply_plan(pdf, output_dir, plan, total_pages=3)

    assert result.validation.valid


def test_apply_plan_uses_markdown_split_when_configured(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_simple_pdf(pdf)
    plan = [BookmarkPlanItem(title="Chapter 1", level=1, pdf_page=1)]

    result = apply_plan(
        pdf,
        output_dir,
        plan,
        total_pages=3,
        markdown_split=MarkdownSplitConfig(max_words=1000, max_words_coverage=1.0),
    )

    assert result.markdown_export is not None
    assert result.output_markdown_dir == result.markdown_export.output_dir
