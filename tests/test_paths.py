from __future__ import annotations

from pathlib import Path

from pdfbooktree.utils.paths import (
    build_bookmarked_pdf_path,
    build_markdown_dir_path,
    safe_filename,
    sanitize_title_for_path,
)


def test_output_paths_use_expected_suffixes() -> None:
    input_pdf = Path("book.pdf")
    output_dir = Path("out")

    assert build_bookmarked_pdf_path(input_pdf, output_dir) == Path(
        "out/book_bookmarked.pdf"
    )
    assert build_markdown_dir_path(input_pdf, output_dir) == Path("out/book_markdown")


def test_safe_filename_replaces_unsafe_characters() -> None:
    assert safe_filename("1.1 Motivation / Background") == "1.1_Motivation_Background"


def test_sanitize_title_for_path_preserves_spaces_and_unicode() -> None:
    # safe_filename과 달리 공백·한글을 그대로 둔다.
    assert (
        sanitize_title_for_path("1.1 Exchange-Traded Markets")
        == "1.1 Exchange-Traded Markets"
    )
    assert sanitize_title_for_path("제1장 서론") == "제1장 서론"


def test_sanitize_title_for_path_removes_illegal_chars() -> None:
    # Windows 금지 문자(/ \ : * ? " < > |)는 제거한다(치환이 아니라 삭제).
    assert sanitize_title_for_path('Ch 1: A/B "test"?') == "Ch 1 AB test"


def test_sanitize_title_for_path_collapses_whitespace_and_strips_trailing() -> None:
    assert sanitize_title_for_path("  Many   spaces  .") == "Many spaces"


def test_sanitize_title_for_path_empty_becomes_untitled() -> None:
    assert sanitize_title_for_path("///") == "untitled"
    assert sanitize_title_for_path("   ") == "untitled"


def test_sanitize_title_for_path_caps_length() -> None:
    long_title = "A" * 200
    assert sanitize_title_for_path(long_title, max_length=80) == "A" * 80
