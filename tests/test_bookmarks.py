"""기존 bookmark 판정 helper를 검증한다."""

from __future__ import annotations

from pdfbooktree.pdf.bookmarks import (
    build_skip_reason,
    has_meaningful_bookmark,
    is_clean_bookmark_set,
)


def test_build_skip_reason_returns_none_without_bookmark() -> None:
    """bookmark가 없으면 runtime 처리 대상으로 남긴다."""

    assert build_skip_reason([]) is None


def test_build_skip_reason_skips_any_existing_bookmark() -> None:
    """runtime에서는 품질과 무관하게 bookmark가 있는 문서를 제외한다."""

    bookmarks = [
        {
            "order": 1,
            "level": 1,
            "title": "1",
            "pdf_page": 1,
        }
    ]

    assert not is_clean_bookmark_set(bookmarks)
    assert build_skip_reason(bookmarks) == (
        "기존 bookmark 1개가 있어서 runtime 자동 처리를 건너뛰었다."
    )


def test_has_meaningful_bookmark_false_when_empty() -> None:
    """bookmark가 아예 없으면 진짜 목차로 볼 수 없다."""

    assert has_meaningful_bookmark([]) is False


def test_has_meaningful_bookmark_false_for_flat_level_only() -> None:
    """병합 도구가 파일명을 그대로 옮긴 flat bookmark는 진짜 목차가 아니다."""

    bookmarks = [
        {"order": 1, "level": 1, "title": "부분1", "pdf_page": 1},
        {"order": 2, "level": 1, "title": "부분2", "pdf_page": 60},
        {"order": 3, "level": 1, "title": "부분3", "pdf_page": 118},
    ]

    assert has_meaningful_bookmark(bookmarks) is False


def test_has_meaningful_bookmark_true_for_multi_level_toc() -> None:
    """level 구조가 있으면 짧아도 진짜 목차로 본다."""

    bookmarks = [
        {"order": 1, "level": 1, "title": "Chapter 1", "pdf_page": 1},
        {"order": 2, "level": 2, "title": "1.1 Topic", "pdf_page": 3},
    ]

    assert has_meaningful_bookmark(bookmarks) is True
