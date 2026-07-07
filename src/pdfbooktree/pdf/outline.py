"""PDF outline을 읽고 쓰는 low-level adapter다."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.models import BookmarkPlanItem, ExistingOutlineItem
from pdfbooktree.utils.text_normalize import normalize_text


def read_outline(pdf_path: Path) -> list[ExistingOutlineItem]:
    """PyMuPDF TOC를 1-based page 번호 outline 목록으로 반환한다."""

    items: list[ExistingOutlineItem] = []
    with fitz.open(pdf_path) as document:
        for order, item in enumerate(document.get_toc(simple=False), start=1):
            level, title, pdf_page = item[:3]
            items.append(
                ExistingOutlineItem(
                    order=order,
                    level=int(level),
                    title=normalize_text(str(title)),
                    pdf_page=int(pdf_page) if int(pdf_page) > 0 else None,
                )
            )
    return items


def write_outline_pdf(
    input_pdf: Path,
    output_pdf: Path,
    bookmark_plan: list[BookmarkPlanItem],
) -> Path:
    """bookmark plan을 PDF outline으로 삽입한 사본을 저장한다."""

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    toc = [
        [item.level, item.title, item.pdf_page]
        for item in bookmark_plan
        if item.pdf_page >= 1
    ]
    with fitz.open(input_pdf) as document:
        document.set_toc(toc)
        document.save(output_pdf)
    return output_pdf


def outline_to_plan(items: list[ExistingOutlineItem]) -> list[BookmarkPlanItem]:
    """기존 outline item을 공통 bookmark plan으로 변환한다."""

    return [
        BookmarkPlanItem(
            title=item.title,
            level=item.level,
            pdf_page=item.pdf_page,
            source="existing_outline",
            confidence=1.0,
        )
        for item in items
        if item.pdf_page is not None
    ]
