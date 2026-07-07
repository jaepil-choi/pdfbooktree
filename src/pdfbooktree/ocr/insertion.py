"""표준 OCR 삽입 모델을 invisible text layer PDF로 렌더링한다."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.ocr.models import InsertableOcrLine, InsertableOcrPage, OcrBox


def write_overlay_pdf(
    insertable_pages: list[InsertableOcrPage],
    page_images: dict[int, Path],
    output_pdf: Path,
    temp_dir: Path,
    dpi: int,
) -> None:
    """page image와 invisible text layer를 합쳐 searchable OCR PDF를 만든다."""

    if output_pdf.exists():
        output_pdf.unlink()
    temp_dir.mkdir(parents=True, exist_ok=True)
    page_pdf_paths: list[Path] = []
    for page in insertable_pages:
        page_pdf = temp_dir / f"overlay_page_{page.pdf_page:04d}.pdf"
        _render_overlay_page(page, page_images[page.pdf_page], page_pdf, dpi)
        page_pdf_paths.append(page_pdf)

    output = fitz.open()
    try:
        for page_pdf in page_pdf_paths:
            source = fitz.open(page_pdf)
            try:
                output.insert_pdf(source)
            finally:
                source.close()
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_pdf)
    finally:
        output.close()


def _render_overlay_page(
    page: InsertableOcrPage,
    image_path: Path,
    output_pdf: Path,
    dpi: int,
) -> None:
    try:
        from ocrmypdf.font import MultiFontManager
        from ocrmypdf.fpdf_renderer.renderer import Fpdf2PdfRenderer
        from ocrmypdf.models.ocr_element import BoundingBox, OcrClass, OcrElement
    except ImportError as exc:
        raise RuntimeError(
            "OCR overlay PDF 생성을 위해 ocrmypdf가 필요하다. "
            "`uv sync` 또는 `uv add ocrmypdf`로 의존성을 설치해야 한다."
        ) from exc

    ocr_page = OcrElement(
        ocr_class=OcrClass.PAGE,
        bbox=BoundingBox(0, 0, page.width_px, page.height_px),
    )
    for element in page.elements:
        for line in element.lines:
            ocr_page.children.append(
                _to_ocr_line(line, BoundingBox, OcrClass, OcrElement)
            )

    renderer = Fpdf2PdfRenderer(
        page=ocr_page,
        dpi=dpi,
        multi_font_manager=MultiFontManager(),
        invisible_text=True,
        image=image_path,
    )
    renderer.render(output_pdf)


def _to_ocr_line(
    line: InsertableOcrLine,
    bounding_box_type: type,
    ocr_class_type: type,
    ocr_element_type: type,
) -> object:
    if line.words:
        children = [
            ocr_element_type(
                ocr_class=ocr_class_type.WORD,
                bbox=_to_bounding_box(word.bbox, bounding_box_type),
                text=word.text,
            )
            for word in line.words
        ]
    else:
        children = [
            ocr_element_type(
                ocr_class=ocr_class_type.WORD,
                bbox=_to_bounding_box(line.bbox, bounding_box_type),
                text=line.text,
            )
        ]
    return ocr_element_type(
        ocr_class=ocr_class_type.LINE,
        bbox=_to_bounding_box(line.bbox, bounding_box_type),
        children=children,
    )


def _to_bounding_box(box: OcrBox, bounding_box_type: type) -> object:
    return bounding_box_type(box.x0, box.y0, box.x1, box.y1)
