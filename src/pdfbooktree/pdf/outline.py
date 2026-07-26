"""PDF outline을 읽고 쓰는 low-level adapter다."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

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


def replace_outline_pdf_atomic(
    input_pdf: Path,
    bookmark_plan: list[BookmarkPlanItem],
) -> Path:
    """완성·검증한 sibling temporary PDF로 입력 PDF를 atomic 교체한다."""

    source = input_pdf.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"입력 PDF가 없다: {source}")
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{source.stem}.bookmarks.",
        suffix=".pdf",
        dir=source.parent,
    )
    os.close(handle)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        write_outline_pdf(source, temporary, bookmark_plan)
        _validate_written_outline(source, temporary, bookmark_plan)
        os.replace(temporary, source)
    finally:
        temporary.unlink(missing_ok=True)
    return source


def _validate_written_outline(
    source_pdf: Path,
    candidate_pdf: Path,
    bookmark_plan: list[BookmarkPlanItem],
) -> None:
    """교체 전에 page 수와 실제 TOC가 계획과 같은지 확인한다."""

    expected = [
        [item.level, item.title, item.pdf_page]
        for item in bookmark_plan
        if item.pdf_page >= 1
    ]
    with fitz.open(source_pdf) as source, fitz.open(candidate_pdf) as candidate:
        if candidate.page_count != source.page_count:
            raise RuntimeError(
                "in-place bookmark PDF page 수가 바뀌었다: "
                f"source={source.page_count}, candidate={candidate.page_count}"
            )
        actual = [
            [int(level), normalize_text(str(title)), int(pdf_page)]
            for level, title, pdf_page, *_ in candidate.get_toc(simple=False)
        ]
    if actual != expected:
        raise RuntimeError(
            "in-place bookmark PDF outline 검증이 실패했다: "
            f"expected={len(expected)}, actual={len(actual)}"
        )


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
