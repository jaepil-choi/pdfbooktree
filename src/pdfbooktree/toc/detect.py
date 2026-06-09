"""TOC page detector의 v0.1 인터페이스를 제공한다."""

from __future__ import annotations

from pdfbooktree.models import PageFeature, TocDetectionResult


def detect_toc_pages(features: list[PageFeature]) -> TocDetectionResult:
    """feature 기반의 얇은 heuristic으로 TOC 후보 range를 고른다."""

    candidates: list[dict[str, object]] = []
    selected: list[int] = []
    for feature in features:
        monotone = feature.line_final_number_monotonicity or 0.0
        score = feature.line_final_number_count * monotone
        if feature.toc_keyword_presence:
            score += 3.0
        if feature.line_final_number_negative_gap_count:
            score -= feature.line_final_number_negative_gap_count * 2.0
        candidates.append({"pdf_page": feature.pdf_page, "score": score})
        if score >= 5.0:
            selected.append(feature.pdf_page)

    pages = _largest_contiguous_group(selected)
    confidence = min(1.0, len(pages) / 5) if pages else 0.0
    return TocDetectionResult(
        pages=pages,
        start_page=pages[0] if pages else None,
        end_page=pages[-1] if pages else None,
        confidence=confidence,
        method="feature_heuristic_scaffold",
        candidates=candidates,
    )


def _largest_contiguous_group(pages: list[int]) -> list[int]:
    if not pages:
        return []

    groups: list[list[int]] = []
    current = [pages[0]]
    for page in pages[1:]:
        if page == current[-1] + 1:
            current.append(page)
            continue
        groups.append(current)
        current = [page]
    groups.append(current)
    return max(groups, key=lambda group: (len(group), sum(group)))
