"""page 단위 scan 신호 추출을 검증한다."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.pdf.scan_signals import (
    DEFAULT_MAX_SAMPLE_PAGES,
    analyze_page,
    sample_page_indices,
)


def _new_page(
    document: fitz.Document, width: int = 200, height: int = 200
) -> fitz.Page:
    return document.new_page(width=width, height=height)


def _insert_full_page_image(page: fitz.Page) -> None:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100))
    pixmap.set_rect(pixmap.irect, (200, 200, 200))
    page.insert_image(page.rect, pixmap=pixmap)


def test_sample_page_indices_returns_full_range_when_within_limit() -> None:
    assert sample_page_indices(5, max_pages=20) == [0, 1, 2, 3, 4]


def test_default_max_sample_pages_is_50() -> None:
    assert DEFAULT_MAX_SAMPLE_PAGES == 50


def test_sample_page_indices_downsamples_evenly_across_document() -> None:
    indices = sample_page_indices(100, max_pages=10)

    assert len(indices) == 10
    assert indices[0] == 0
    assert indices[-1] < 100


def test_analyze_page_detects_scan_like_page_with_image_and_no_text(
    tmp_path: Path,
) -> None:
    document = fitz.open()
    try:
        page = _new_page(document)
        _insert_full_page_image(page)

        signal = analyze_page(page)
    finally:
        document.close()

    assert signal.is_scan_like_page is True
    assert signal.image_coverage_ratio == 1.0
    assert signal.visible_char_count == 0
    assert signal.reject_reasons == ()


def test_analyze_page_rejects_page_with_visible_text_on_image(tmp_path: Path) -> None:
    document = fitz.open()
    try:
        page = _new_page(document)
        _insert_full_page_image(page)
        page.insert_text((30, 100), "Real visible paragraph text", fontsize=12)

        signal = analyze_page(page)
    finally:
        document.close()

    assert signal.is_scan_like_page is False
    assert signal.visible_char_count > 0
    assert any("visible_char_count" in reason for reason in signal.reject_reasons)


def test_analyze_page_rejects_page_without_image_dominance(tmp_path: Path) -> None:
    document = fitz.open()
    try:
        page = _new_page(document)
        page.insert_text((30, 100), "Native typeset text", fontsize=12)

        signal = analyze_page(page)
    finally:
        document.close()

    assert signal.is_scan_like_page is False
    assert signal.image_coverage_ratio < 0.85
    assert any("image_coverage_ratio" in reason for reason in signal.reject_reasons)


def test_analyze_page_invisible_text_does_not_count_as_visible(tmp_path: Path) -> None:
    document = fitz.open()
    try:
        page = _new_page(document)
        _insert_full_page_image(page)
        page.insert_text((30, 100), "invisible ocr overlay", fontsize=12, render_mode=3)

        signal = analyze_page(page)
    finally:
        document.close()

    assert signal.visible_char_count == 0
    assert signal.invisible_char_count > 0
    assert signal.is_scan_like_page is True
