from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.ocr.models import OcrOverlayResult


def test_ocr_overlay_cli_parses_options(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class FakeBuilder:
        def __init__(self, config):
            captured["config"] = config

        def run(self):
            return OcrOverlayResult(
                status="processed",
                input_pdf=Path(captured["config"].input_pdf),
                output_pdf=Path(captured["config"].output_pdf),
                output_dir=Path(captured["config"].output_dir),
                page_count=10,
                processed_pages=[1, 2, 3, 42],
                engine="upstage",
            )

    monkeypatch.setattr("pdfbooktree.cli.OcrOverlayBuilder", FakeBuilder)

    result = CliRunner().invoke(
        app,
        [
            "ocr-overlay",
            str(tmp_path / "book.pdf"),
            "--output",
            str(tmp_path / "book_ocr.pdf"),
            "--output-dir",
            str(tmp_path / "artifacts"),
            "--engine",
            "upstage",
            "--render-dpi",
            "300",
            "--pages",
            "1-3,42",
            "--force",
            "--stats-word-level",
            "--engine-option",
            "model=document-parse",
            "--engine-option",
            "output_formats=text,html,markdown",
        ],
    )

    assert result.exit_code == 0
    config = captured["config"]
    assert config.pages == [1, 2, 3, 42]
    assert config.force is True
    assert config.stats_word_level is True
    assert config.engine_options["model"] == "document-parse"
    assert config.engine_options["output_formats"] == ["text", "html", "markdown"]

