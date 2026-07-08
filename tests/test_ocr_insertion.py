from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.ocr.insertion import write_overlay_pdf
from pdfbooktree.ocr.models import (
    InsertableOcrElement,
    InsertableOcrLine,
    InsertableOcrPage,
    OcrBox,
)


def make_pdf_with_invisible_text(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(20, 20, 80, 80), color=(1, 0, 0), fill=(1, 0, 0))
    page.insert_text((30, 120), "OLD OCR TEXT", fontsize=12, render_mode=3)
    second_page = doc.new_page(width=200, height=200)
    second_page.insert_text((30, 120), "UNCHANGED OCR TEXT", fontsize=12, render_mode=3)
    doc.save(path)
    doc.close()


def render_page_png(path: Path, pdf_page: int) -> bytes:
    doc = fitz.open(path)
    try:
        return doc[pdf_page - 1].get_pixmap(dpi=96, alpha=False).tobytes("png")
    finally:
        doc.close()


def extract_page_text(path: Path, pdf_page: int) -> str:
    doc = fitz.open(path)
    try:
        return doc[pdf_page - 1].get_text()
    finally:
        doc.close()


def test_write_overlay_pdf_strips_existing_text_and_preserves_page_render(
    tmp_path: Path,
) -> None:
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    make_pdf_with_invisible_text(input_pdf)
    before_png = render_page_png(input_pdf, 1)

    page = InsertableOcrPage(
        pdf_page=1,
        width_px=200,
        height_px=200,
        width_pt=200,
        height_pt=200,
        source_engine="test",
        elements=[
            InsertableOcrElement(
                element_id="1",
                category="paragraph",
                bbox=OcrBox(30, 95, 170, 125),
                content_text="NEW OCR TEXT",
                lines=[
                    InsertableOcrLine(
                        text="NEW OCR TEXT",
                        bbox=OcrBox(30, 95, 170, 125),
                    )
                ],
                overlay_mode="element",
            )
        ],
    )

    write_overlay_pdf([page], input_pdf, output_pdf, tmp_path / "overlay_pages")

    output_text = extract_page_text(output_pdf, 1)
    assert "NEW OCR TEXT" in output_text
    assert "OLD OCR TEXT" not in output_text
    assert render_page_png(output_pdf, 1) == before_png
    assert "UNCHANGED OCR TEXT" in extract_page_text(output_pdf, 2)

    output_doc = fitz.open(output_pdf)
    try:
        assert output_doc.page_count == 2
    finally:
        output_doc.close()
