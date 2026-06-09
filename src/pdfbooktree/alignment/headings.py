"""본문 heading 후보 추출 인터페이스다."""

from __future__ import annotations

from pdfbooktree.models import HeadingCandidate, PdfPageText


def extract_heading_candidates(
    pages: list[PdfPageText],
    target_pdf_page: int,
    window: int,
) -> list[HeadingCandidate]:
    """예상 page 주변의 상단 line을 heading 후보로 추출한다."""

    lower = max(1, target_pdf_page - window)
    upper = target_pdf_page + window
    candidates: list[HeadingCandidate] = []
    for page in pages:
        if page.pdf_page < lower or page.pdf_page > upper:
            continue
        for line_number, line in enumerate(page.lines[:8], start=1):
            if 4 <= len(line) <= 160:
                candidates.append(
                    HeadingCandidate(
                        pdf_page=page.pdf_page,
                        text=line,
                        line_number=line_number,
                        confidence=0.5,
                    )
                )
    return candidates
