"""BatchProcessor를 검증한다."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.batch import BatchProcessor
from pdfbooktree.config import ProcessingConfig, TypographyConfig


def _write_pdf(path: Path, title: str) -> None:
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 90), title, fontsize=28)
        page.insert_text((72, 160), "Body text", fontsize=10)
        document.save(path)
    finally:
        document.close()


def test_batch_processes_pdfs(tmp_path: Path) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()
    _write_pdf(input_dir / "a.pdf", "Chapter 1 Alpha")
    _write_pdf(input_dir / "b.pdf", "Chapter 1 Beta")

    result = BatchProcessor(
        input_dir,
        tmp_path / "out",
        ProcessingConfig(
            typography=TypographyConfig(min_tier_count=1, max_heading_tier=2)
        ),
    ).run()

    assert result.total_pdf_count == 2
    assert result.processed_count == 2
    assert result.failed_count == 0
