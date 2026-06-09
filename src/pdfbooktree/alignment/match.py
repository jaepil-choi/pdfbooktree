"""TOC item과 heading 후보를 fuzzy matching한다."""

from __future__ import annotations

from rapidfuzz import fuzz

from pdfbooktree.models import AlignedTocItem, HeadingCandidate, OffsetEstimate, TocItem
from pdfbooktree.utils.text_normalize import normalize_for_match


def align_toc_items(
    items: list[TocItem],
    offset: OffsetEstimate,
    candidates_by_item: dict[int, list[HeadingCandidate]],
) -> list[AlignedTocItem]:
    """offset과 heading 후보를 사용해 TOC item의 최종 page를 고른다."""

    aligned: list[AlignedTocItem] = []
    for index, item in enumerate(items):
        estimated_pdf_page = (
            item.printed_page + offset.offset if offset.offset is not None else None
        )
        best = _best_heading_match(item, candidates_by_item.get(index, []))
        aligned.append(
            AlignedTocItem(
                title=item.title,
                level=item.level,
                printed_page=item.printed_page,
                estimated_pdf_page=estimated_pdf_page,
                matched_pdf_page=best.pdf_page if best else estimated_pdf_page,
                confidence=best.confidence if best else 0.0,
                method="offset_plus_heading_match_scaffold"
                if best
                else "offset_only_scaffold",
                source_pdf_page=item.source_pdf_page,
            )
        )
    return aligned


def _best_heading_match(
    item: TocItem, candidates: list[HeadingCandidate]
) -> HeadingCandidate | None:
    best: HeadingCandidate | None = None
    best_score = 0.0
    item_text = normalize_for_match(item.title)
    for candidate in candidates:
        score = fuzz.token_sort_ratio(item_text, normalize_for_match(candidate.text))
        if score > best_score:
            best_score = score
            best = HeadingCandidate(
                pdf_page=candidate.pdf_page,
                text=candidate.text,
                line_number=candidate.line_number,
                confidence=score / 100,
            )
    if best_score < 70:
        return None
    return best
