"""문서 단위 native/scanned 판정을 검증한다."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.pdf.scan_classification import classify_scan


def _insert_full_page_image(page: fitz.Page) -> None:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100))
    pixmap.set_rect(pixmap.irect, (200, 200, 200))
    page.insert_image(page.rect, pixmap=pixmap)


def test_classify_scan_true_when_all_pages_are_scan_like(tmp_path: Path) -> None:
    pdf = tmp_path / "scanned.pdf"
    document = fitz.open()
    try:
        for _ in range(2):
            page = document.new_page(width=200, height=200)
            _insert_full_page_image(page)
        document.save(pdf)
    finally:
        document.close()

    result = classify_scan(pdf)

    assert result.is_scanned is True
    assert result.scanned_page_fraction == 1.0
    assert result.total_visible_chars_sampled == 0
    assert result.reject_reasons == ()


def test_classify_scan_false_for_native_pdf_with_reasons(tmp_path: Path) -> None:
    pdf = tmp_path / "native.pdf"
    document = fitz.open()
    try:
        for index in range(2):
            page = document.new_page(width=200, height=200)
            page.insert_text(
                (30, 100), f"Native page {index + 1} body text", fontsize=12
            )
        document.save(pdf)
    finally:
        document.close()

    result = classify_scan(pdf)

    assert result.is_scanned is False
    assert result.total_visible_chars_sampled > 0
    reasons_text = " ".join(result.reject_reasons)
    assert "scanned_page_fraction" in reasons_text
    assert "total_visible_chars_sampled" in reasons_text
    assert str(result.total_visible_chars_sampled) in reasons_text


def test_classify_scan_false_for_mixed_pdf_reports_only_failing_condition(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "mixed.pdf"
    document = fitz.open()
    try:
        scanned_page = document.new_page(width=200, height=200)
        _insert_full_page_image(scanned_page)
        native_page = document.new_page(width=200, height=200)
        native_page.insert_text((30, 100), "Native chapter text", fontsize=12)
        document.save(pdf)
    finally:
        document.close()

    result = classify_scan(pdf)

    assert result.is_scanned is False
    assert 0.0 < result.scanned_page_fraction < 1.0
    assert result.total_visible_chars_sampled > 0
    assert len(result.reject_reasons) == 2
