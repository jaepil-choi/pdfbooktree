"""PyMuPDF에서 1-based page text를 추출한다."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.models import PdfPageText
from pdfbooktree.utils.page_numbers import from_pymupdf_index
from pdfbooktree.utils.text_normalize import extract_lines


def extract_page_texts(
    pdf_path: Path, max_pages: int | None = None
) -> list[PdfPageText]:
    """PDF 앞부분 또는 전체 page의 text layer를 추출한다."""

    pages: list[PdfPageText] = []
    with fitz.open(pdf_path) as document:
        limit = (
            document.page_count
            if max_pages is None
            else min(max_pages, document.page_count)
        )
        for page_index in range(limit):
            text = document.load_page(page_index).get_text("text")
            pages.append(
                PdfPageText(
                    pdf_page=from_pymupdf_index(page_index),
                    text=text,
                    lines=extract_lines(text),
                    char_count=len(text),
                )
            )
    return pages
