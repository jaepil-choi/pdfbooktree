from __future__ import annotations

from pdfbooktree.models import PageFeature, PdfPageText
from pdfbooktree.toc.detect_from_bookmarks import (
    OFFSET_CONSISTENCY_VOTE_THRESHOLD,
    detect_toc_pages_from_bookmarks,
    score_offset_consistency,
)


def test_detect_toc_pages_from_bookmarks_uses_title_anchors() -> None:
    pages = [
        PdfPageText(1, "Preface", ["Preface"], 7),
        PdfPageText(
            2,
            "Contents\nChapter 1 Introduction 3\n1.1 Motivation 7",
            ["Contents", "Chapter 1 Introduction 3", "1.1 Motivation 7"],
            51,
        ),
        PdfPageText(
            3,
            "1.2 Background 12\nChapter 2 Probability 25",
            ["1.2 Background 12", "Chapter 2 Probability 25"],
            43,
        ),
        PdfPageText(4, "Body text", ["Body text"], 9),
    ]
    bookmarks = [
        {"order": 1, "level": 1, "title": "Chapter 1 Introduction", "pdf_page": 5},
        {"order": 2, "level": 2, "title": "1.1 Motivation", "pdf_page": 9},
        {"order": 3, "level": 2, "title": "1.2 Background", "pdf_page": 14},
        {"order": 4, "level": 1, "title": "Chapter 2 Probability", "pdf_page": 27},
    ]

    result = detect_toc_pages_from_bookmarks(pages, bookmarks)

    assert result.pages == [2, 3]
    assert result.method == "bookmark_guided_feature_vote"
    assert result.confidence > 0
    assert result.candidates[1]["matched_bookmark_count"] >= 2
    assert (
        result.candidates[1]["offset_consistency_score"]
        >= OFFSET_CONSISTENCY_VOTE_THRESHOLD
    )


def test_detect_toc_pages_from_bookmarks_expands_to_cover_missing_bookmarks() -> None:
    pages = [
        PdfPageText(3, "Chapter 0 Warmup 1", ["Chapter 0 Warmup 1"], 18),
        PdfPageText(4, "Chapter 1 Introduction 3", ["Chapter 1 Introduction 3"], 24),
        PdfPageText(5, "Chapter 2 Probability 25", ["Chapter 2 Probability 25"], 24),
        PdfPageText(6, "Chapter 3 Integration 48", ["Chapter 3 Integration 48"], 24),
        PdfPageText(7, "Chapter 4 Martingales 67", ["Chapter 4 Martingales 67"], 25),
        PdfPageText(8, "Chapter 0 Warmup", ["Chapter 0 Warmup"], 16),
    ]
    bookmarks = [
        {"order": 1, "level": 1, "title": "Chapter 0 Warmup", "pdf_page": 1},
        {"order": 2, "level": 1, "title": "Chapter 1 Introduction", "pdf_page": 3},
        {"order": 3, "level": 1, "title": "Chapter 2 Probability", "pdf_page": 25},
        {"order": 4, "level": 1, "title": "Chapter 3 Integration", "pdf_page": 48},
        {"order": 5, "level": 1, "title": "Chapter 4 Martingales", "pdf_page": 67},
    ]
    features = [
        build_page_feature(pdf_page=3, line_final_numbers=[1]),
        build_page_feature(pdf_page=4, line_final_numbers=[3, 12, 20]),
        build_page_feature(pdf_page=5, line_final_numbers=[25, 33, 41]),
        build_page_feature(pdf_page=6, line_final_numbers=[48, 55, 61]),
        build_page_feature(pdf_page=7, line_final_numbers=[67]),
        build_page_feature(pdf_page=8, line_final_numbers=[]),
    ]

    result = detect_toc_pages_from_bookmarks(pages, bookmarks, features=features)

    assert result.pages == [3, 4, 5, 6, 7]


def build_page_feature(
    pdf_page: int,
    line_final_numbers: list[int],
) -> PageFeature:
    strong_toc_page = 4 <= pdf_page <= 6
    return PageFeature(
        pdf_page=pdf_page,
        line_count=3 if strong_toc_page else 1,
        word_count=9 if strong_toc_page else 4,
        mean_line_length=20.0,
        line_length_std=0.0,
        line_final_number_count=len(line_final_numbers),
        line_final_numbers=line_final_numbers,
        line_final_number_monotonicity=1.0 if len(line_final_numbers) >= 2 else None,
        line_final_number_gap_mean=None,
        line_final_number_gap_median=None,
        line_final_number_gap_max=None,
        line_final_number_negative_gap_count=0,
        toc_entry_pattern_count=4 if strong_toc_page else 0,
        toc_entry_pattern_ratio=1.0 if strong_toc_page else 0.0,
        chapter_or_part_line_count=1 if strong_toc_page else 0,
        page_position=pdf_page / 100,
        toc_keyword_presence=False,
    )


def test_score_offset_consistency_uses_non_final_number_candidates() -> None:
    matches = [
        {
            "pdf_page": 2,
            "bookmark_order": 1,
            "bookmark_target_pdf_page": 20,
            "number_candidates": [1, 3],
        },
        {
            "pdf_page": 2,
            "bookmark_order": 2,
            "bookmark_target_pdf_page": 42,
            "number_candidates": [2, 25],
        },
    ]

    scores = score_offset_consistency(matches)

    assert scores[2] >= OFFSET_CONSISTENCY_VOTE_THRESHOLD
