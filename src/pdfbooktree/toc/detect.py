"""bookmark 없이 TOC page range를 찾는 기본 탐지기의 자리다.

역할:
- PDF 앞부분에서 추출한 page feature만 입력으로 받아 TOC page range를 고른다.
- 기존 PDF bookmark, 평가용 정답, 사람이 검수한 label은 참조하지 않는다.
- `Processor`가 호출하는 기본 TOC page detection 진입점으로 유지한다.

책임 밖:
- 기존 bookmark title을 기준으로 TOC page를 복원하는 흐름은
  `toc.detect_from_bookmarks`가 담당한다.
- 탐지 결과의 IoU, start/end error, precision/recall 같은 metric 계산은
  `metrics.toc_pages`가 담당한다.
- TOC line에서 chapter/section item을 파싱하는 일은 `toc.parse`가 담당한다.
"""

from __future__ import annotations

from pdfbooktree.models import PageFeature, TocDetectionResult
from pdfbooktree.toc.segments import score_toc_pages, select_toc_segment


def detect_toc_pages(features: list[PageFeature]) -> TocDetectionResult:
    """feature 기반 vote와 segment mass로 TOC page range를 고른다."""

    page_scores = score_toc_pages(features)
    segment = select_toc_segment(page_scores)
    candidates = [
        {
            "pdf_page": score.pdf_page,
            "printed_page_sequence_score": score.printed_page_sequence_score,
            "toc_entry_pattern_score": score.toc_entry_pattern_score,
            "window_mass_score": score.window_mass_score,
            "vote_count": score.vote_count,
            "voters": score.voters,
        }
        for score in page_scores
    ]
    if segment is None:
        return TocDetectionResult(
            pages=[],
            start_page=None,
            end_page=None,
            confidence=0.0,
            method="feature_vote_segment",
            candidates=candidates,
        )

    max_possible_vote_sum = max(1, segment.length * 3)
    confidence = min(1.0, segment.vote_sum / max_possible_vote_sum)
    return TocDetectionResult(
        pages=segment.pages,
        start_page=segment.start_page,
        end_page=segment.end_page,
        confidence=confidence,
        method="feature_vote_segment",
        candidates=candidates,
    )
