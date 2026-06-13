"""기존 PDF bookmark를 기준 신호로 사용해 TOC page range를 찾는다.

역할:
- bookmark title 목록과 앞부분 page text를 함께 사용해 TOC page range를 복원한다.
- bookmark가 있는 PDF에서 detector 검증용 기준 결과를 만들 때 사용한다.
- bookmark title matching, anchor page 관찰, page text와 bookmark title의 overlap 같은
  bookmark-guided 신호를 이 파일에 모은다.

책임 밖:
- bookmark 없이 feature만으로 TOC page를 찾는 기본 처리 경로는 `toc.detect`가 담당한다.
- 기존 bookmark 자체를 추출하고 clean 여부를 판단하는 일은 `pdf.bookmarks`가 담당한다.
- 결과 간 IoU나 page precision/recall 계산은 `metrics.toc_pages`가 담당한다.

명명 결정:
- `from_bookmarks`는 입력 계약을 직접 드러낸다.
- 이 모듈은 bookmark가 있을 때만 의미가 있다.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from typing import Any

from rapidfuzz import fuzz

from pdfbooktree.models import PageFeature, PdfPageText, TocDetectionResult
from pdfbooktree.toc.features import (
    calculate_page_features,
    extract_line_final_number,
    extract_page_number_candidates,
)
from pdfbooktree.toc.segments import (
    TocPageScore,
    choose_best_voted_segment,
    expand_soft_edges,
    pages_to_segments,
    score_toc_pages,
)
from pdfbooktree.utils.text_normalize import normalize_text


WINDOW_MAX_LINES = 3
MATCH_SCORE_THRESHOLD = 80.0
OFFSET_CONSISTENCY_VOTE_THRESHOLD = 1.5

GENERIC_BOOKMARK_TITLES = {
    "summary",
    "further reading",
    "practice questions",
    "problems",
    "exercises",
    "references",
    "bibliography",
    "appendix",
    "index",
}


def detect_toc_pages_from_bookmarks(
    pages: list[PdfPageText],
    bookmarks: list[dict[str, Any]],
    features: list[PageFeature] | None = None,
) -> TocDetectionResult:
    """bookmark title matching을 함께 사용해 TOC page range를 복원한다."""

    page_features = features or calculate_page_features(
        pages,
        total_pages=max((page.pdf_page for page in pages), default=1),
    )
    base_scores = score_toc_pages(page_features)
    usable_bookmarks = normalize_bookmarks_for_matching(bookmarks)
    windows_by_page = {
        page.pdf_page: build_page_windows(page.pdf_page, page.lines) for page in pages
    }
    anchor_evidence_by_page, all_matches = match_bookmarks_to_pages(
        usable_bookmarks,
        windows_by_page,
    )
    anchor_scores = score_bookmark_anchor_density(anchor_evidence_by_page)
    offset_scores = score_offset_consistency(all_matches)
    enriched_scores = merge_bookmark_votes(base_scores, anchor_scores, offset_scores)
    vote_counts = {score.pdf_page: score.vote_count for score in enriched_scores}
    strong_pages = [
        score.pdf_page for score in enriched_scores if score.vote_count >= 2
    ]
    segment = choose_best_voted_segment(pages_to_segments(strong_pages), vote_counts)
    if segment is not None:
        segment_pages = dict.fromkeys(range(segment.start_page, segment.end_page + 1))
        start_page, end_page = expand_soft_edges(
            segment,
            {score.pdf_page: score for score in enriched_scores},
        )
        selected_pages = list(range(start_page, end_page + 1))
        segment_pages.update(dict.fromkeys(selected_pages))
        pages_result = sorted(segment_pages)
    else:
        pages_result = []
    pages_result = expand_pages_to_cover_bookmark_matches(
        pages_result,
        usable_bookmarks,
        all_matches,
    )

    candidates = build_bookmark_candidate_rows(
        enriched_scores,
        anchor_scores,
        offset_scores,
        anchor_evidence_by_page,
    )
    confidence = calculate_bookmark_detection_confidence(pages_result, enriched_scores)
    return TocDetectionResult(
        pages=pages_result,
        start_page=pages_result[0] if pages_result else None,
        end_page=pages_result[-1] if pages_result else None,
        confidence=confidence,
        method="bookmark_guided_feature_vote",
        candidates=candidates,
    )


def normalize_for_match(text: str) -> str:
    """bookmark title과 page text를 matching하기 위한 문자열로 정규화한다."""

    replacements = {
        "ﬁ": "fi",
        "ﬂ": "fl",
        "–": "-",
        "—": "-",
        "’": "'",
        "“": '"',
        "”": '"',
    }
    for source, target in replacements.items():
        text = text.replace(source, target)

    text = normalize_text(text).lower()
    text = re.sub(r"\.{2,}", " ", text)
    text = re.sub(r"[\s.·•_=-]{4,}", " ", text)
    text = re.sub(r"\b\d{1,4}\s*$", " ", text)
    text = re.sub(r"[^0-9a-z가-힣]+", " ", text)
    return normalize_text(text)


def normalize_bookmarks_for_matching(
    bookmarks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """기존 bookmark 목록에서 TOC page matching에 쓸 title만 남긴다."""

    normalized_bookmarks: list[dict[str, Any]] = []
    for order, bookmark in enumerate(bookmarks, start=1):
        title = normalize_text(str(bookmark.get("title", "")))
        normalized_title = normalize_for_match(title)
        if not is_usable_bookmark_title(normalized_title):
            continue
        normalized_bookmarks.append(
            {
                "order": int(bookmark.get("order", order)),
                "level": int(bookmark.get("level", 1)),
                "title": title,
                "normalized_title": normalized_title,
                "target_pdf_page": bookmark.get("pdf_page"),
            }
        )
    return normalized_bookmarks


def is_usable_bookmark_title(normalized_title: str) -> bool:
    """TOC page anchor로 쓰기 어려운 bookmark title을 제외한다."""

    if len(normalized_title) < 6:
        return False
    if normalized_title in GENERIC_BOOKMARK_TITLES:
        return False
    return not (
        len(normalized_title.split()) == 1 and not re.search(r"\d", normalized_title)
    )


def build_page_windows(page_number: int, lines: list[str]) -> list[dict[str, Any]]:
    """page line에서 bookmark title과 비교할 짧은 text window를 만든다."""

    windows: list[dict[str, Any]] = []
    for start_index in range(len(lines)):
        for size in range(1, WINDOW_MAX_LINES + 1):
            end_index = start_index + size
            if end_index > len(lines):
                continue
            raw_text = " ".join(lines[start_index:end_index])
            normalized_text = normalize_for_match(raw_text)
            if len(normalized_text) < 6:
                continue
            windows.append(
                {
                    "pdf_page": page_number,
                    "start_line": start_index + 1,
                    "end_line": end_index,
                    "raw_text": raw_text,
                    "normalized_text": normalized_text,
                    "trailing_number": extract_line_final_number(raw_text),
                    "number_candidates": extract_page_number_candidates(raw_text),
                }
            )
    return windows


def match_bookmarks_to_pages(
    bookmarks: list[dict[str, Any]],
    windows_by_page: dict[int, list[dict[str, Any]]],
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    """bookmark title과 page text window를 fuzzy matching한다."""

    evidence_by_page: dict[int, dict[str, Any]] = {}
    all_matches: list[dict[str, Any]] = []

    for page_number, windows in windows_by_page.items():
        best_match_by_bookmark: dict[int, dict[str, Any]] = {}
        for window in windows:
            window_text = str(window["normalized_text"])
            for bookmark in bookmarks:
                score = score_window_against_title(
                    window_text,
                    str(bookmark["normalized_title"]),
                )
                if score < MATCH_SCORE_THRESHOLD:
                    continue

                match = {
                    "pdf_page": page_number,
                    "bookmark_order": bookmark["order"],
                    "bookmark_level": bookmark["level"],
                    "bookmark_title": bookmark["title"],
                    "bookmark_target_pdf_page": bookmark["target_pdf_page"],
                    "score": score,
                    "trailing_number": window["trailing_number"],
                    "number_candidates": window["number_candidates"],
                    "window": {
                        "start_line": window["start_line"],
                        "end_line": window["end_line"],
                        "raw_text": window["raw_text"],
                    },
                }
                previous = best_match_by_bookmark.get(int(bookmark["order"]))
                if previous is not None and previous["score"] >= score:
                    continue
                best_match_by_bookmark[int(bookmark["order"])] = match

        matches = sorted(
            best_match_by_bookmark.values(),
            key=lambda match: (-float(match["score"]), int(match["bookmark_order"])),
        )
        all_matches.extend(matches)
        orders = sorted(int(match["bookmark_order"]) for match in matches)
        scores = [float(match["score"]) for match in matches]
        evidence_by_page[page_number] = {
            "pdf_page": page_number,
            "unique_matched_bookmark_count": len(matches),
            "matched_bookmark_order_density": calculate_bookmark_order_density(orders),
            "median_match_score": statistics.median(scores) if scores else None,
            "max_match_score": max(scores) if scores else None,
            "matched_examples": matches[:10],
        }

    return evidence_by_page, all_matches


def expand_pages_to_cover_bookmark_matches(
    selected_pages: list[int],
    bookmarks: list[dict[str, Any]],
    matches: list[dict[str, Any]],
) -> list[int]:
    """선택된 TOC page range가 관측된 bookmark match를 모두 포함하게 확장한다."""

    if not selected_pages or not bookmarks:
        return selected_pages

    selected_page_set = set(selected_pages)
    expected_orders = {int(bookmark["order"]) for bookmark in bookmarks}
    covered_orders = {
        int(match["bookmark_order"])
        for match in matches
        if int(match["pdf_page"]) in selected_page_set
    }
    missing_orders = expected_orders - covered_orders
    if not missing_orders:
        return sorted(selected_page_set)

    matches_by_order: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for match in matches:
        matches_by_order[int(match["bookmark_order"])].append(match)

    required_pages = set(selected_page_set)
    for order in missing_orders:
        candidates = matches_by_order.get(order, [])
        if not candidates:
            continue
        best_match = min(
            candidates,
            key=lambda match: (
                calculate_page_distance_to_selection(
                    int(match["pdf_page"]),
                    selected_page_set,
                ),
                -float(match["score"]),
            ),
        )
        required_pages.add(int(best_match["pdf_page"]))

    return list(range(min(required_pages), max(required_pages) + 1))


def calculate_page_distance_to_selection(page: int, selected_pages: set[int]) -> int:
    """선택된 range에서 candidate page까지의 최소 거리를 계산한다."""

    if page in selected_pages:
        return 0
    return min(abs(page - selected_page) for selected_page in selected_pages)


def score_window_against_title(window_text: str, title: str) -> float:
    """text window와 bookmark title의 fuzzy score를 계산한다."""

    if not has_enough_title_token_coverage(window_text, title):
        return 0.0
    return max(
        fuzz.ratio(window_text, title),
        fuzz.token_sort_ratio(window_text, title),
        fuzz.partial_ratio(window_text, title),
    )


def has_enough_title_token_coverage(window_text: str, title: str) -> bool:
    """짧은 우연 매칭을 줄이기 위해 token overlap 하한을 적용한다."""

    window_tokens = set(window_text.split())
    title_tokens = set(title.split())
    if not title_tokens or not window_tokens:
        return False

    overlap_ratio = len(window_tokens & title_tokens) / len(title_tokens)
    if len(title_tokens) <= 3:
        return overlap_ratio >= 0.85
    if len(title_tokens) <= 6:
        return overlap_ratio >= 0.70
    return overlap_ratio >= 0.60


def calculate_bookmark_order_density(orders: list[int]) -> float:
    """한 page에서 matching된 bookmark order가 얼마나 조밀한지 계산한다."""

    if not orders:
        return 0.0
    return len(orders) / (max(orders) - min(orders) + 1)


def score_bookmark_anchor_density(
    evidence_by_page: dict[int, dict[str, Any]],
) -> dict[int, float]:
    """bookmark anchor matching evidence를 page score로 바꾼다."""

    scores: dict[int, float] = {}
    for page, evidence in evidence_by_page.items():
        count = int(evidence["unique_matched_bookmark_count"])
        density = float(evidence["matched_bookmark_order_density"])
        median_score = float(evidence["median_match_score"] or 0.0)
        scores[page] = min(count, 20) * density * (median_score / 100)
    return scores


def score_offset_consistency(matches: list[dict[str, Any]]) -> dict[int, float]:
    """page text 숫자와 bookmark target page의 offset 일관성을 점수화한다."""

    evidence_by_page: dict[int, list[dict[str, int]]] = defaultdict(list)
    for match in matches:
        target_pdf_page = match.get("bookmark_target_pdf_page")
        if target_pdf_page is None:
            continue

        numbers = list(match.get("number_candidates", []))
        trailing_number = match.get("trailing_number")
        if trailing_number is not None and int(trailing_number) not in numbers:
            numbers.append(int(trailing_number))

        for number in numbers:
            if int(number) <= 0 or int(number) > 2000:
                continue
            evidence_by_page[int(match["pdf_page"])].append(
                {
                    "bookmark_order": int(match["bookmark_order"]),
                    "offset": int(target_pdf_page) - int(number),
                }
            )

    scores: dict[int, float] = {}
    for page, evidence in evidence_by_page.items():
        if len(evidence) < 2:
            scores[page] = 0.0
            continue
        offset_counts = Counter(item["offset"] for item in evidence)
        modal_offset, modal_candidate_count = offset_counts.most_common(1)[0]
        modal_bookmark_count = len(
            {
                item["bookmark_order"]
                for item in evidence
                if item["offset"] == modal_offset
            }
        )
        if modal_bookmark_count < 2:
            scores[page] = 0.0
            continue
        modal_share = modal_candidate_count / len(evidence)
        scores[page] = modal_bookmark_count * (0.75 + 0.25 * modal_share)
    return scores


def merge_bookmark_votes(
    base_scores: list[TocPageScore],
    anchor_scores: dict[int, float],
    offset_scores: dict[int, float],
) -> list[TocPageScore]:
    """기본 TOC feature vote에 bookmark 기반 vote를 더한다."""

    enriched: list[TocPageScore] = []
    for score in base_scores:
        voters = list(score.voters)
        anchor_score = anchor_scores.get(score.pdf_page, 0.0)
        offset_score = offset_scores.get(score.pdf_page, 0.0)
        if anchor_score >= 1.5:
            voters.append("bookmark_anchor_density")
        if offset_score >= OFFSET_CONSISTENCY_VOTE_THRESHOLD:
            voters.append("offset_consistency")
        enriched.append(
            TocPageScore(
                pdf_page=score.pdf_page,
                line_final_numbers=score.line_final_numbers,
                printed_page_sequence_score=score.printed_page_sequence_score,
                toc_entry_pattern_score=score.toc_entry_pattern_score,
                window_mass_score=score.window_mass_score,
                vote_count=len(voters),
                voters=voters,
            )
        )
    return enriched


def build_bookmark_candidate_rows(
    scores: list[TocPageScore],
    anchor_scores: dict[int, float],
    offset_scores: dict[int, float],
    evidence_by_page: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """중간 산출물에 남길 bookmark-guided page candidate를 만든다."""

    rows: list[dict[str, Any]] = []
    for score in scores:
        evidence = evidence_by_page.get(score.pdf_page, {})
        rows.append(
            {
                "pdf_page": score.pdf_page,
                "printed_page_sequence_score": score.printed_page_sequence_score,
                "toc_entry_pattern_score": score.toc_entry_pattern_score,
                "window_mass_score": score.window_mass_score,
                "bookmark_anchor_score": anchor_scores.get(score.pdf_page, 0.0),
                "offset_consistency_score": offset_scores.get(score.pdf_page, 0.0),
                "vote_count": score.vote_count,
                "voters": score.voters,
                "matched_bookmark_count": evidence.get(
                    "unique_matched_bookmark_count",
                    0,
                ),
            }
        )
    return rows


def calculate_bookmark_detection_confidence(
    pages: list[int],
    scores: list[TocPageScore],
) -> float:
    """bookmark-guided TOC detection 결과의 간단한 신뢰도를 계산한다."""

    if not pages:
        return 0.0
    score_by_page = {score.pdf_page: score for score in scores}
    vote_sum = sum(score_by_page[page].vote_count for page in pages)
    return min(1.0, vote_sum / (len(pages) * 5))
