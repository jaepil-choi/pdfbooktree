from __future__ import annotations

from pathlib import Path

from pdfbooktree.utils.paths import (
    build_bookmarked_pdf_path,
    build_markdown_dir_path,
    safe_filename,
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
