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


def detect_toc_pages(features: list[PageFeature]) -> TocDetectionResult:
    """기본 TOC 탐지기의 공개 계약만 고정한다.

    실제 scoring과 segment 선택 로직은 다음 구현 단계에서 채운다.
    현재는 scaffold 상태를 명확히 드러내기 위해 빈 결과를 반환한다.
    """

    candidates = [{"pdf_page": feature.pdf_page} for feature in features]
    return TocDetectionResult(
        pages=[],
        start_page=None,
        end_page=None,
        confidence=0.0,
        method="toc_detector_scaffold",
        candidates=candidates,
    )
