from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz
import pytest

from pdfbooktree.ocr.builder import (
    ExistingBookmarkConfirmationRequired,
    OcrOverlayBuilder,
)
from pdfbooktree.ocr.config import OcrOverlayConfig
from pdfbooktree.ocr.models import (
    InsertableOcrElement,
    InsertableOcrLine,
    InsertableOcrPage,
    OcrBox,
    OcrStatsResult,
    RenderedPage,
)


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.closed = False

    def emit(self, event) -> None:
        self.events.append(event.event)

    def close(self) -> None:
        self.closed = True


def make_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=100, height=100)
    doc.save(path)
    doc.close()


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


def test_ocr_overlay_builder_emits_runtime_log_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    input_pdf = tmp_path / "book.pdf"
    output_pdf = tmp_path / "book_ocr.pdf"
    output_dir = tmp_path / "artifacts"
    make_pdf(input_pdf)

    class FakeEngine:
        engine_id = "fake"
        adapter_version = "v1"

        def request_params(self) -> dict[str, Any]:
            return {"model": "fake"}

        def recognize_page(self, rendered_page: RenderedPage) -> dict[str, Any]:
            return {"elements": []}

        def to_insertable_page(
            self,
            raw_response: dict[str, Any],
            rendered_page: RenderedPage,
        ) -> InsertableOcrPage:
            return InsertableOcrPage(
                pdf_page=1,
                width_px=100,
                height_px=100,
                width_pt=100,
                height_pt=100,
                source_engine="fake",
                elements=[
                    InsertableOcrElement(
                        element_id="1",
                        category="paragraph",
                        bbox=OcrBox(0, 0, 10, 10),
                        content_text="Hello",
                        lines=[InsertableOcrLine("Hello", OcrBox(0, 0, 10, 10))],
                        overlay_mode="element",
                    )
                ],
            )

    monkeypatch.setattr(
        "pdfbooktree.ocr.builder.extract_existing_bookmarks", lambda _path: []
    )
    monkeypatch.setattr(
        "pdfbooktree.ocr.builder.create_ocr_engine", lambda *_args: FakeEngine()
    )
    monkeypatch.setattr(
        "pdfbooktree.ocr.builder.render_pdf_page",
        lambda *_args: RenderedPage(1, b"png", "sha", 100, 100, 100, 100),
    )
    monkeypatch.setattr(
        "pdfbooktree.ocr.builder.write_rendered_page_image",
        lambda _rendered, out_dir: out_dir / "page_0001.png",
    )
    monkeypatch.setattr(
        "pdfbooktree.ocr.builder.write_overlay_pdf", lambda *_args: None
    )
    monkeypatch.setattr(
        "pdfbooktree.ocr.builder.write_ocr_stats",
        lambda *_args, **_kwargs: OcrStatsResult(
            page_stats_path=output_dir / "ocr_page_stats.jsonl",
            element_stats_path=output_dir / "ocr_element_stats.jsonl",
            line_stats_path=output_dir / "ocr_line_stats.jsonl",
        ),
    )
    logger = RecordingLogger()

    OcrOverlayBuilder(
        OcrOverlayConfig(
            input_pdf=input_pdf,
            output_pdf=output_pdf,
            output_dir=output_dir,
            pages=[1],
        ),
        logger=logger,
    ).run()

    assert "start" in logger.events
    assert "page_start" in logger.events
    assert "ocr_call_start" in logger.events
    assert "ocr_call_done" in logger.events
    assert "page_done" in logger.events
    assert "done" in logger.events
    assert logger.closed is True
