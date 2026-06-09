"""TOC page line에서 chapter/section 항목을 파싱한다."""

from __future__ import annotations

import re

from pdfbooktree.models import PdfPageText, TocItem
from pdfbooktree.toc.features import extract_line_final_number
from pdfbooktree.utils.text_normalize import normalize_text


TOC_ITEM_PATTERNS = [
    re.compile(r"^(?P<title>chapter\s+\d+\s+.+?)\s+\.{0,}\s*(?P<page>\d{1,4})$", re.I),
    re.compile(r"^(?P<title>\d+(?:\.\d+)*\.?\s+.+?)\s+\.{0,}\s*(?P<page>\d{1,4})$"),
    re.compile(
        r"^(?P<title>appendix\s+[a-z0-9]+(?:\s+.+?)?)\s+\.{0,}\s*(?P<page>\d{1,4})$",
        re.I,
    ),
    re.compile(
        r"^(?P<title>[a-z]\.\d+(?:\.\d+)*\s+.+?)\s+\.{0,}\s*(?P<page>\d{1,4})$", re.I
    ),
]


def parse_toc_items(pages: list[PdfPageText], toc_pages: list[int]) -> list[TocItem]:
    """탐지된 TOC page들에서 파싱 가능한 항목을 반환한다."""

    toc_page_set = set(toc_pages)
    items: list[TocItem] = []
    for page in pages:
        if page.pdf_page not in toc_page_set:
            continue
        for line in page.lines:
            item = parse_toc_line(line, page.pdf_page)
            if item is not None:
                items.append(item)
    return items


def parse_toc_line(line: str, source_pdf_page: int) -> TocItem | None:
    """단일 TOC line을 파싱한다."""

    normalized = normalize_text(line)
    if extract_line_final_number(normalized) is None:
        return None

    for pattern in TOC_ITEM_PATTERNS:
        match = pattern.match(normalized)
        if match:
            title = normalize_text(match.group("title").rstrip(". "))
            return TocItem(
                title=title,
                level=infer_level(title),
                printed_page=int(match.group("page")),
                raw_text=normalized,
                source_pdf_page=source_pdf_page,
                confidence=0.8,
            )
    return None


def infer_level(title: str) -> int:
    """TOC title의 numbering 형태에서 hierarchy level을 추론한다."""

    lowered = title.lower()
    if lowered.startswith(("chapter ", "part ", "appendix ")):
        return 1

    numeric_match = re.match(r"^(\d+(?:\.\d+)*)\.?\s+", title)
    if numeric_match:
        return numeric_match.group(1).count(".") + 1

    appendix_match = re.match(r"^[a-z]\.(\d+(?:\.\d+)*)\s+", lowered)
    if appendix_match:
        return appendix_match.group(1).count(".") + 2

    return 1
