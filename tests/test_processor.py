"""Processor의 기존 outline 처리 경로를 검증한다."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.config import MarkdownSplitConfig, ProcessingConfig
from pdfbooktree.processor import Processor


def test_processor_exports_markdown_for_existing_outline(tmp_path: Path) -> None:
    pdf = tmp_path / "bookmarked.pdf"
    document = fitz.open()
    try:
        for index in range(3):
            page = document.new_page()
            page.insert_text((72, 72), f"Page {index + 1}", fontsize=12)
        document.set_toc([[1, "Chapter 1", 1], [2, "1.1 Topic", 2]])
        document.save(pdf)
    finally:
        document.close()

    result = Processor(pdf, tmp_path / "out").run()

    assert result.status == "processed"
    assert result.output_pdf is None
    assert result.output_markdown_dir is not None
    assert (result.output_markdown_dir / "toc.md").exists()
    assert result.bookmark_count == 2


def test_processor_exports_coverage_split_for_existing_outline(tmp_path: Path) -> None:
    pdf = tmp_path / "bookmarked.pdf"
    document = fitz.open()
    try:
        for index in range(3):
            page = document.new_page()
            page.insert_text((72, 72), "one two three four five", fontsize=12)
        document.set_toc([[1, "Chapter 1", 1], [2, "Topic", 2]])
        document.save(pdf)
    finally:
        document.close()

    result = Processor(
        pdf,
        tmp_path / "out",
        ProcessingConfig(
            markdown_split=MarkdownSplitConfig(max_words=16, max_words_coverage=1.0)
        ),
    ).run()

    assert result.status == "processed"
    assert result.markdown_export is not None
    assert result.markdown_export.chosen_level == 2
    assert result.markdown_export.file_count == 2
    assert result.markdown_export.manifest_path is not None
