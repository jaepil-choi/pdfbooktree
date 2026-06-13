"""TOC page segment 후보를 다룬다.

역할:
- page 단위 feature나 점수에서 연속된 TOC 후보 구간을 만든다.
- 단일 page 점수와 구간 점수를 분리해 관리한다.
- 최종 detector가 여러 candidate segment 중 하나를 고를 수 있는 자료 구조를 제공한다.

책임 밖:
- PDF text에서 feature를 계산하는 일은 `toc.features`가 담당한다.
- 기존 bookmark를 기준 신호로 써서 TOC page를 찾는 일은
  `toc.detect_from_bookmarks`가 담당한다.
- detector 결과를 정답 후보와 비교하는 metric 계산은 `metrics.toc_pages`가 담당한다.

구현 메모:
- 실험 003의 contiguous window mass와 vote 기반 segment 선택을 제품 런타임에 맞게
  bookmark 없는 입력만으로 계산한다.
- 모든 page number는 package 규칙에 맞춰 1-based로 유지한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pdfbooktree.models import PageFeature


@dataclass(frozen=True)
class TocPageScore:
    """단일 page의 TOC 가능성 점수와 근거다."""

    pdf_page: int
    line_final_numbers: list[int]
    printed_page_sequence_score: float
    toc_entry_pattern_score: float
    window_mass_score: float
    vote_count: int
    voters: list[str]


@dataclass(frozen=True)
class TocPageSegment:
    """연속된 TOC page 후보 구간이다."""

    start_page: int
    end_page: int
    pages: list[int]
    score: float
    vote_sum: int
    length: int


def score_toc_page(feature: PageFeature) -> TocPageScore:
    """단일 page feature에서 독립적인 TOC 판단 점수를 계산한다."""

    monotone = feature.line_final_number_monotonicity or 0.0
    printed_score = max(
        0.0,
        feature.line_final_number_count * monotone
        - feature.line_final_number_negative_gap_count * 2,
    )
    entry_score = (
        feature.toc_entry_pattern_count * 1.5
        + feature.chapter_or_part_line_count * 0.5
        + (3.0 if feature.toc_keyword_presence else 0.0)
    )
    window_score = (
        min(feature.line_final_number_count, 40) * 0.15
        + min(feature.toc_entry_pattern_count, 20) * 0.25
        + monotone * 2
        + (1.0 if feature.toc_keyword_presence else 0.0)
    )

    voters: list[str] = []
    if printed_score >= 8.0:
        voters.append("printed_page_sequence")
    if entry_score >= 4.0:
        voters.append("toc_entry_pattern")
    if window_score >= 2.0:
        voters.append("window_mass")

    return TocPageScore(
        pdf_page=feature.pdf_page,
        line_final_numbers=feature.line_final_numbers,
        printed_page_sequence_score=printed_score,
        toc_entry_pattern_score=entry_score,
        window_mass_score=window_score,
        vote_count=len(voters),
        voters=voters,
    )


def score_toc_pages(features: list[PageFeature]) -> list[TocPageScore]:
    """여러 page feature를 page별 TOC 점수로 변환한다."""

    return [score_toc_page(feature) for feature in features]


def select_toc_segment(
    page_scores: list[TocPageScore],
    min_votes: int = 2,
    min_length: int = 1,
    max_length: int = 20,
) -> TocPageSegment | None:
    """vote와 window mass를 사용해 가장 그럴듯한 TOC segment를 고른다."""

    if not page_scores:
        return None

    vote_counts = {score.pdf_page: score.vote_count for score in page_scores}
    strong_pages = [
        score.pdf_page for score in page_scores if score.vote_count >= min_votes
    ]
    strong_segments = pages_to_segments(strong_pages)
    best = choose_best_voted_segment(strong_segments, vote_counts)
    if best is None:
        mass_scores = {score.pdf_page: score.window_mass_score for score in page_scores}
        best = find_best_window(
            mass_scores, min_length=min_length, max_length=max_length
        )
        if best is not None and best.score <= 0:
            return None
    if best is None:
        return None

    page_by_number = {score.pdf_page: score for score in page_scores}
    start_page, end_page = expand_soft_edges(best, page_by_number)
    pages = list(range(start_page, end_page + 1))
    vote_sum = sum(vote_counts.get(page, 0) for page in pages)
    score = best.score + vote_sum * 0.25
    return TocPageSegment(
        start_page=start_page,
        end_page=end_page,
        pages=pages,
        score=score,
        vote_sum=vote_sum,
        length=len(pages),
    )


def pages_to_segments(pages: list[int]) -> list[tuple[int, int]]:
    """page 목록을 연속 구간 목록으로 바꾼다."""

    ordered_pages = sorted(set(pages))
    if not ordered_pages:
        return []

    segments: list[tuple[int, int]] = []
    start = ordered_pages[0]
    previous = ordered_pages[0]
    for page in ordered_pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        segments.append((start, previous))
        start = page
        previous = page
    segments.append((start, previous))
    return segments


def choose_best_voted_segment(
    segments: list[tuple[int, int]],
    vote_counts: dict[int, int],
) -> TocPageSegment | None:
    """vote가 충분한 연속 구간 중 가장 강한 segment를 고른다."""

    best: TocPageSegment | None = None
    for start, end in segments:
        pages = list(range(start, end + 1))
        vote_sum = sum(vote_counts.get(page, 0) for page in pages)
        length = len(pages)
        score = vote_sum + length * 0.5
        candidate = TocPageSegment(
            start_page=start,
            end_page=end,
            pages=pages,
            score=score,
            vote_sum=vote_sum,
            length=length,
        )
        if best is None or candidate.score > best.score:
            best = candidate
    return best


def find_best_window(
    page_scores: dict[int, float],
    min_length: int = 1,
    max_length: int = 20,
) -> TocPageSegment | None:
    """page score mass와 boundary contrast가 큰 연속 구간을 고른다."""

    page_numbers = sorted(page_scores)
    best: TocPageSegment | None = None

    for start in page_numbers:
        for end in page_numbers:
            if end < start:
                continue
            length = end - start + 1
            if length < min_length or length > max_length:
                continue

            inside_pages = list(range(start, end + 1))
            inside_scores = [page_scores.get(page, 0.0) for page in inside_pages]
            inside_sum = sum(inside_scores)
            inside_mean = inside_sum / length
            left_score = page_scores.get(start - 1, 0.0)
            right_score = page_scores.get(end + 1, 0.0)
            boundary_contrast = max(0.0, inside_mean - (left_score + right_score) / 2)
            weak_page_penalty = sum(1 for score in inside_scores if score < 1.5) * 0.7
            length_penalty = math.log1p(length) * 0.8
            total_score = (
                inside_sum + boundary_contrast * 2 - weak_page_penalty - length_penalty
            )

            candidate = TocPageSegment(
                start_page=start,
                end_page=end,
                pages=inside_pages,
                score=total_score,
                vote_sum=0,
                length=length,
            )
            if best is None or candidate.score > best.score:
                best = candidate
    return best


def expand_soft_edges(
    segment: TocPageSegment,
    page_by_number: dict[int, TocPageScore],
) -> tuple[int, int]:
    """segment 전체 line-final number 흐름을 깨지 않는 인접 page를 포함한다."""

    start = segment.start_page
    end = segment.end_page
    while can_expand_segment(start, end, start - 1, "left", page_by_number):
        start -= 1
    while can_expand_segment(start, end, end + 1, "right", page_by_number):
        end += 1
    return start, end


def can_expand_segment(
    start: int,
    end: int,
    candidate_page: int,
    side: str,
    page_by_number: dict[int, TocPageScore],
) -> bool:
    """candidate page를 붙여도 segment 숫자 흐름이 유지되는지 판단한다."""

    candidate = page_by_number.get(candidate_page)
    if candidate is None or candidate.vote_count == 0:
        return False

    segment_numbers = collect_segment_numbers(start, end, page_by_number)
    candidate_numbers = candidate.line_final_numbers
    if side == "left":
        combined_numbers = candidate_numbers + segment_numbers
        if not has_monotone_boundary(candidate_numbers, segment_numbers):
            return False
    elif side == "right":
        combined_numbers = segment_numbers + candidate_numbers
        if not has_monotone_boundary(segment_numbers, candidate_numbers):
            return False
    else:
        raise ValueError(f"알 수 없는 확장 방향이다: {side}")

    current_monotonicity = sequence_monotonicity(segment_numbers)
    expanded_monotonicity = sequence_monotonicity(combined_numbers)
    if current_monotonicity is None or expanded_monotonicity is None:
        return True
    return expanded_monotonicity >= current_monotonicity - 0.05


def collect_segment_numbers(
    start: int,
    end: int,
    page_by_number: dict[int, TocPageScore],
) -> list[int]:
    """segment page 순서대로 line-final number를 이어 붙인다."""

    numbers: list[int] = []
    for page in range(start, end + 1):
        score = page_by_number.get(page)
        if score is not None:
            numbers.extend(score.line_final_numbers)
    return numbers


def has_monotone_boundary(left_numbers: list[int], right_numbers: list[int]) -> bool:
    """두 page group 사이의 마지막/첫 line-final number가 역행하지 않는지 본다."""

    if not left_numbers or not right_numbers:
        return True
    return left_numbers[-1] <= right_numbers[0]


def sequence_monotonicity(numbers: list[int]) -> float | None:
    """line 순서대로 읽은 숫자열이 거의 증가하는 정도를 계산한다."""

    if len(numbers) < 2:
        return None
    non_decreasing_count = sum(
        1 for left, right in zip(numbers, numbers[1:], strict=False) if right >= left
    )
    return non_decreasing_count / (len(numbers) - 1)
