from __future__ import annotations

from pdfbooktree.models import PdfPageText
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
