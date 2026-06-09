"""내부 1-based page 규칙과 PyMuPDF 0-based index 변환을 관리한다."""

from __future__ import annotations


def ensure_pdf_page(pdf_page: int) -> int:
    """1-based PDF page 번호인지 검증하고 그대로 반환한다."""

    if pdf_page < 1:
        raise ValueError(f"PDF page는 1 이상이어야 한다: {pdf_page}")
    return pdf_page


def to_pymupdf_index(pdf_page: int) -> int:
    """1-based PDF page를 PyMuPDF의 0-based page index로 바꾼다."""

    return ensure_pdf_page(pdf_page) - 1


def from_pymupdf_index(page_index: int) -> int:
    """PyMuPDF의 0-based page index를 1-based PDF page로 바꾼다."""

    if page_index < 0:
        raise ValueError(f"PyMuPDF page index는 0 이상이어야 한다: {page_index}")
    return page_index + 1
