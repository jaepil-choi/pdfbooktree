"""resolve_existing_outline_action()의 existing-outline policy를 검증한다."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.config import OutlineQualityConfig, ProcessingConfig
from pdfbooktree.pipeline import resolve_existing_outline_action

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0


def _make_pdf_with_toc(path: Path, toc: list[list[object]], page_count: int) -> None:
    document = fitz.open()
    try:
        for page_no in range(page_count):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            page.insert_text((72, 90), f"Page {page_no + 1}", fontsize=10)
        if toc:
            document.set_toc(toc)
        document.save(path)
    finally:
        document.close()


def test_resolve_existing_outline_action_no_outline_runs_inference(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_pdf_with_toc(pdf, toc=[], page_count=5)

    decision = resolve_existing_outline_action(pdf, 5, ProcessingConfig())

    assert decision.existing_outline == []
    assert decision.quality is None
    assert decision.reuse_existing is False


def test_resolve_existing_outline_action_good_quality_reuses_existing(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    toc = [[1, f"Chapter {index}", index] for index in range(1, 6)]
    _make_pdf_with_toc(pdf, toc=toc, page_count=200)

    decision = resolve_existing_outline_action(pdf, 200, ProcessingConfig())

    assert decision.reuse_existing is True
    assert decision.quality is not None
    assert decision.quality.is_low_quality is False


def test_resolve_existing_outline_action_low_quality_still_reused_by_default(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    toc = [[1, "Chapter 1", 1], [1, "Chapter 2", 2]]
    _make_pdf_with_toc(pdf, toc=toc, page_count=200)

    decision = resolve_existing_outline_action(pdf, 200, ProcessingConfig())

    assert decision.reuse_existing is True
    assert decision.quality is not None
    assert decision.quality.is_low_quality is True
    assert "too_few_items" in decision.quality.reasons


def test_resolve_existing_outline_action_replace_when_low_quality_enabled(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    toc = [[1, "Chapter 1", 1], [1, "Chapter 2", 2]]
    _make_pdf_with_toc(pdf, toc=toc, page_count=200)
    config = ProcessingConfig(
        outline_quality=OutlineQualityConfig(replace_when_low_quality=True)
    )

    decision = resolve_existing_outline_action(pdf, 200, config)

    assert decision.reuse_existing is False
    assert decision.quality is not None
    assert decision.quality.is_low_quality is True


def test_resolve_existing_outline_action_skip_existing_bookmarks_false_ignores_quality(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    toc = [[1, f"Chapter {index}", index] for index in range(1, 6)]
    _make_pdf_with_toc(pdf, toc=toc, page_count=200)
    config = ProcessingConfig(skip_existing_bookmarks=False)

    decision = resolve_existing_outline_action(pdf, 200, config)

    assert decision.reuse_existing is False
    assert decision.quality is not None
    assert decision.quality.is_low_quality is False
