"""기존 bookmark 판정 helper를 검증한다."""

from __future__ import annotations

from pdfbooktree.pdf.bookmarks import build_skip_reason, is_clean_bookmark_set


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
