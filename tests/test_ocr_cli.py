from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.ocr.models import OcrOverlayResult


def test_ocr_overlay_cli_parses_options(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class FakeLogger:
        pass

    class FakeBuilder:
        def __init__(self, config, logger=None):
            captured["config"] = config
            captured["logger"] = logger

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

    def fake_build_logger(mode, output_dir, *, enable_file, desc=None):
        captured["log_mode"] = mode
        captured["log_output_dir"] = output_dir
        captured["enable_file"] = enable_file
        captured["desc"] = desc
        return FakeLogger()

    monkeypatch.setattr("pdfbooktree.cli.OcrOverlayBuilder", FakeBuilder)
    monkeypatch.setattr("pdfbooktree.cli.build_ocr_logger", fake_build_logger)

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
            "--confirm-bookmark-ocr-overwrite",
            "--stats-word-level",
            "--engine-option",
            "model=document-parse",
            "--engine-option",
            "output_formats=text,html,markdown",
            "--log-mode",
            "plain",
            "--no-log-file",
        ],
    )

    assert result.exit_code == 0
    config = captured["config"]
    assert config.pages == [1, 2, 3, 42]
    assert config.force is True
    assert config.confirm_bookmark_ocr_overwrite is True
    assert config.stats_word_level is True
    assert config.engine_options["model"] == "document-parse"
    assert config.engine_options["output_formats"] == ["text", "html", "markdown"]
    assert isinstance(captured["logger"], FakeLogger)
    assert captured["log_mode"] == "plain"
    assert captured["log_output_dir"] == tmp_path / "artifacts"
    assert captured["enable_file"] is False
    assert captured["desc"] == "OCR overlay: book.pdf"
    assert "'processed_page_count': 4" in result.stdout
    assert "'processed_pages'" not in result.stdout
    assert "book_ocr.pdf" in result.stdout


def test_ocr_overlay_batch_cli_parses_options(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class FakeRunner:
        def __init__(self, config, *, log_mode=None, enable_log_file=True):
            captured["config"] = config
            captured["log_mode"] = log_mode
            captured["enable_log_file"] = enable_log_file

        def run(self):
            from pdfbooktree.ocr.batch import OcrOverlayBatchResult

            return OcrOverlayBatchResult(
                total_pdf_count=3,
                target_count=2,
                processed_count=1,
                dry_run_count=0,
                skipped_count=1,
                failed_count=0,
                elapsed_sec=1.0,
                report_csv_path=Path(captured["config"].output_dir)
                / "ocr_overlay_batch_report.csv",
                detail_jsonl_path=Path(captured["config"].output_dir)
                / "ocr_overlay_batch_detail.jsonl",
                summary_path=Path(captured["config"].output_dir)
                / "ocr_overlay_batch_summary.json",
                results=[],
            )

    monkeypatch.setattr("pdfbooktree.cli.OcrOverlayBatchRunner", FakeRunner)

    result = CliRunner().invoke(
        app,
        [
            "ocr-overlay-batch",
            str(tmp_path / "300STUDY"),
            "--output-dir",
            str(tmp_path / "out"),
            "--recursive",
            "--dry-run",
            "--force",
            "--confirm-bookmark-ocr-overwrite",
            "--engine",
            "upstage",
            "--render-dpi",
            "240",
            "--max-sample-pages",
            "50",
            "--stats-word-level",
            "--engine-option",
            "max_retries=3",
            "--log-mode",
            "none",
            "--no-log-file",
        ],
    )

    assert result.exit_code == 0
    config = captured["config"]
    assert config.input_dir == tmp_path / "300STUDY"
    assert config.output_dir == tmp_path / "out"
    assert config.recursive is True
    assert config.dry_run is True
    assert config.force is True
    assert config.confirm_bookmark_ocr_overwrite is True
    assert config.render_dpi == 240
    assert config.max_sample_pages == 50
    assert config.stats_word_level is True
    assert config.engine_options["max_retries"] == 3
    assert captured["log_mode"] == "none"
    assert captured["enable_log_file"] is False
