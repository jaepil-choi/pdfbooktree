"""PDF page를 OCR engine 입력 이미지로 렌더링한다."""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

from pdfbooktree.ocr.models import RenderedPage
from pdfbooktree.utils.page_numbers import to_pymupdf_index


def render_pdf_page(pdf_path: Path, pdf_page: int, dpi: int) -> RenderedPage:
    """1-based PDF page를 PNG bytes로 렌더링한다."""

    with fitz.open(pdf_path) as document:
        page = document.load_page(to_pymupdf_index(pdf_page))
        pixmap = page.get_pixmap(dpi=dpi)
        png_bytes = pixmap.tobytes("png")
        return RenderedPage(
            pdf_page=pdf_page,
            png_bytes=png_bytes,
            png_sha1=hashlib.sha1(png_bytes).hexdigest(),
            width_px=pixmap.width,
            height_px=pixmap.height,
            width_pt=page.rect.width,
            height_pt=page.rect.height,
        )


def write_rendered_page_image(rendered_page: RenderedPage, output_dir: Path) -> Path:
    """렌더링된 PNG를 artifact 디렉터리에 저장하고 경로를 반환한다."""

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"page_{rendered_page.pdf_page:04d}.png"
    path.write_bytes(rendered_page.png_bytes)
    return path
