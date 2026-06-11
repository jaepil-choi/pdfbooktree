"""TOC page range 탐지 결과를 채점한다.

역할:
- 예측 TOC page range와 기준 TOC page range의 segment IoU를 계산한다.
- start/end page error, missing/extra page, page precision/recall 같은 값을 계산한다.
- 기본 detector와 bookmark 기반 detector의 결과를 비교할 때 쓰는 순수 함수를 제공한다.

책임 밖:
- TOC page range를 직접 탐지하지 않는다.
- 기존 bookmark에서 기준 range를 복원하지 않는다.
- 평가 report 파일 저장이나 batch orchestration은 별도 상위 모듈에서 담당한다.

구현 메모:
- 작은 list[int] 입력만 받는 순수 함수부터 제공한다.
- 모든 page number는 package 규칙에 맞춰 1-based로 해석한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TocPageComparison:
    """예측 TOC page 목록과 기준 TOC page 목록의 비교 결과다."""

    predicted_pages: list[int]
    expected_pages: list[int]
    true_positive_pages: list[int]
    missing_pages: list[int]
    extra_pages: list[int]
    precision: float | None
    recall: float | None
    segment_iou: float | None
    start_page_error: int | None
    end_page_error: int | None


def compare_toc_pages(
    predicted_pages: list[int],
    expected_pages: list[int],
) -> TocPageComparison:
    """예측 TOC page와 기준 TOC page를 page set과 segment 관점에서 비교한다."""

    predicted = set(predicted_pages)
    expected = set(expected_pages)
    true_positive = predicted & expected
    precision = len(true_positive) / len(predicted) if predicted else None
    recall = len(true_positive) / len(expected) if expected else None

    return TocPageComparison(
        predicted_pages=sorted(predicted),
        expected_pages=sorted(expected),
        true_positive_pages=sorted(true_positive),
        missing_pages=sorted(expected - predicted),
        extra_pages=sorted(predicted - expected),
        precision=precision,
        recall=recall,
        segment_iou=segment_iou(predicted_pages, expected_pages),
        start_page_error=boundary_error(predicted_pages, expected_pages, "start"),
        end_page_error=boundary_error(predicted_pages, expected_pages, "end"),
    )


def segment_iou(predicted_pages: list[int], expected_pages: list[int]) -> float | None:
    """두 TOC page 집합의 IoU를 계산한다."""

    predicted = set(predicted_pages)
    expected = set(expected_pages)
    union = predicted | expected
    if not union:
        return None
    return len(predicted & expected) / len(union)


def boundary_error(
    predicted_pages: list[int],
    expected_pages: list[int],
    boundary: str,
) -> int | None:
    """start 또는 end boundary의 page 오차를 계산한다."""

    if not predicted_pages or not expected_pages:
        return None
    if boundary == "start":
        return min(predicted_pages) - min(expected_pages)
    if boundary == "end":
        return max(predicted_pages) - max(expected_pages)
    raise ValueError(f"알 수 없는 boundary다: {boundary}")
