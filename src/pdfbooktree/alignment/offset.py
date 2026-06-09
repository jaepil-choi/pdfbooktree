"""printed page number와 PDF page 사이의 offset 추정 인터페이스다."""

from __future__ import annotations

from pdfbooktree.models import OffsetEstimate, PdfPageText, TocItem


def estimate_page_offset(
    items: list[TocItem], pages: list[PdfPageText]
) -> OffsetEstimate:
    """offset 추정은 v0.1 다음 단계에서 구현한다."""

    _ = (items, pages)
    return OffsetEstimate(
        offset=None,
        confidence=0.0,
        evidence=[],
    )
