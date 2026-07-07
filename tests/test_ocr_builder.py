from __future__ import annotations

from pathlib import Path

import pytest

from pdfbooktree.ocr.builder import (
    ExistingBookmarkConfirmationRequired,
    OcrOverlayBuilder,
)
from pdfbooktree.ocr.config import OcrOverlayConfig


def test_ocr_overlay_requires_confirmation_when_input_has_bookmarks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    input_pdf = tmp_path / "book.pdf"
    output_pdf = tmp_path / "book_ocr.pdf"
    input_pdf.write_bytes(b"not a real pdf")

    monkeypatch.setattr(
        "pdfbooktree.ocr.builder.extract_existing_bookmarks",
        lambda _path: [{"title": "Chapter 1", "level": 1, "pdf_page": 1}],
    )

    builder = OcrOverlayBuilder(
        OcrOverlayConfig(
            input_pdf=input_pdf,
            output_pdf=output_pdf,
            output_dir=tmp_path / "artifacts",
        )
    )

    with pytest.raises(ExistingBookmarkConfirmationRequired):
        builder.run()
