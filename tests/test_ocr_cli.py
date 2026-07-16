from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.ocr.models import OcrOverlayResult


def _processed_result(config) -> OcrOverlayResult:
    return OcrOverlayResult(
        status="processed",
        input_pdf=Path(config.input_pdf),
        output_pdf=Path(config.output_pdf),
        output_dir=Path(config.output_dir),
        page_count=10,
        processed_pages=[1, 2, 3, 42],
        engine="upstage",
    )


def test_ocr_overlay_cli_parses_options(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class FakeLogger:
        pass

    class FakeBuilder:
        def __init__(self, config, logger=None):
            captured["config"] = config
            captured["logger"] = logger

        def run(self):
            return _processed_result(captured["config"])

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


def test_ocr_overlay_json_result_and_events_use_separate_streams(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeBuilder:
        def __init__(self, config, logger=None):
            self.config = config
            self.logger = logger

        def run(self):
            from pdfbooktree.ocr.logger import OcrLogEvent

            for name, completed in (("start", 0), ("page_done", 1), ("done", 1)):
                self.logger.emit(
                    OcrLogEvent(
                        event=name,
                        level="info",
                        input_pdf=Path(self.config.input_pdf),
                        pdf_page=completed or None,
                        total_pages=1,
                        completed_pages=completed,
                        cache_hit_count=0,
                        cache_miss_count=1,
                        elapsed_sec=1.0,
                        estimated_remaining_sec=0.0 if completed else None,
                        message=f"{name} message",
                    )
                )
            self.logger.close()
            return _processed_result(self.config)

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
            "--log-mode",
            "json",
            "--no-log-file",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    final = json.loads(result.stdout)
    assert final["schema_version"] == 1
    assert final["command"] == "ocr-overlay"
    assert final["ok"] is True
    assert final["result"]["processed_page_count"] == 4
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert [event["event"] for event in events] == ["start", "page_done", "done"]
    assert all(event["schema_version"] == 1 for event in events)
    assert all(event["command"] == "ocr-overlay" for event in events)


def test_ocr_overlay_missing_input_uses_json_input_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "ocr-overlay",
            str(tmp_path / "missing.pdf"),
            "--output",
            str(tmp_path / "book_ocr.pdf"),
            "--output-dir",
            str(tmp_path / "artifacts"),
            "--log-mode",
            "none",
            "--no-log-file",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["schema_version"] == 1
    assert error["command"] == "ocr-overlay"
    assert error["ok"] is False
    assert error["error"]["code"] == "invalid_input"


def test_ocr_overlay_invalid_page_range_is_input_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "ocr-overlay",
            str(tmp_path / "book.pdf"),
            "--output",
            str(tmp_path / "book_ocr.pdf"),
            "--output-dir",
            str(tmp_path / "artifacts"),
            "--pages",
            "3-1",
            "--log-mode",
            "none",
            "--no-log-file",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    error = json.loads(result.stderr)
    assert error["error"]["code"] == "invalid_input"
    assert error["error"]["type"] == "BadParameter"


def test_ocr_overlay_runtime_error_and_debug_contract(
    monkeypatch, tmp_path: Path
) -> None:
    class FailingBuilder:
        def __init__(self, config, logger=None):
            pass

        def run(self):
            raise RuntimeError("OCR provider unavailable")

    monkeypatch.setattr("pdfbooktree.cli.OcrOverlayBuilder", FailingBuilder)
    args = [
        "ocr-overlay",
        str(tmp_path / "book.pdf"),
        "--output",
        str(tmp_path / "book_ocr.pdf"),
        "--output-dir",
        str(tmp_path / "artifacts"),
        "--log-mode",
        "none",
        "--no-log-file",
        "--format",
        "json",
    ]

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 1
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"]["code"] == "runtime_error"

    debug_result = CliRunner().invoke(app, [*args, "--debug"])
    assert debug_result.exit_code == 1
    assert isinstance(debug_result.exception, RuntimeError)
    assert str(debug_result.exception) == "OCR provider unavailable"


def test_ocr_overlay_failed_result_uses_processing_failed_exit(
    monkeypatch, tmp_path: Path
) -> None:
    class FailedResultBuilder:
        def __init__(self, config, logger=None):
            self.config = config

        def run(self):
            result = _processed_result(self.config)
            return OcrOverlayResult(
                status="failed",
                input_pdf=result.input_pdf,
                output_pdf=None,
                output_dir=result.output_dir,
                page_count=result.page_count,
                processed_pages=[],
                engine=result.engine,
            )

    monkeypatch.setattr("pdfbooktree.cli.OcrOverlayBuilder", FailedResultBuilder)

    result = CliRunner().invoke(
        app,
        [
            "ocr-overlay",
            str(tmp_path / "book.pdf"),
            "--output",
            str(tmp_path / "book_ocr.pdf"),
            "--output-dir",
            str(tmp_path / "artifacts"),
            "--log-mode",
            "none",
            "--no-log-file",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 3
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"]["code"] == "processing_failed"
    assert error["error"]["details"]["status"] == "failed"


def _batch_result(config, **overrides):
    from pdfbooktree.ocr.batch import OcrOverlayBatchResult

    defaults = dict(
        total_pdf_count=3,
        target_count=2,
        processed_count=1,
        dry_run_count=0,
        skipped_count=1,
        failed_count=0,
        elapsed_sec=1.0,
        report_csv_path=Path(config.output_dir) / "ocr_overlay_batch_report.csv",
        detail_jsonl_path=Path(config.output_dir) / "ocr_overlay_batch_detail.jsonl",
        summary_path=Path(config.output_dir) / "ocr_overlay_batch_summary.json",
        results=[],
    )
    defaults.update(overrides)
    return OcrOverlayBatchResult(**defaults)


def test_ocr_overlay_batch_cli_parses_options(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    input_dir = tmp_path / "300STUDY"
    input_dir.mkdir()

    class FakeRunner:
        def __init__(self, config, *, log_mode=None, enable_log_file=True):
            captured["config"] = config
            captured["log_mode"] = log_mode
            captured["enable_log_file"] = enable_log_file

        def run(self):
            return _batch_result(captured["config"])

    monkeypatch.setattr("pdfbooktree.cli.OcrOverlayBatchRunner", FakeRunner)

    result = CliRunner().invoke(
        app,
        [
            "ocr-overlay-batch",
            str(input_dir),
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
            "--min-page-count",
            "101",
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
    assert config.min_page_count == 101
    assert config.max_sample_pages == 50
    assert config.stats_word_level is True
    assert config.engine_options["max_retries"] == 3
    assert captured["log_mode"] == "none"
    assert captured["enable_log_file"] is False


def test_ocr_overlay_batch_json_result_and_events_use_separate_streams(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "300STUDY"
    input_dir.mkdir()

    class FakeRunner:
        def __init__(self, config, *, log_mode=None, enable_log_file=True):
            self.config = config

        def run(self):
            from pdfbooktree.ocr.logger import OcrLogEvent, build_batch_ocr_progress

            progress = build_batch_ocr_progress(
                "json", total_pages=1, total_books=1, command="ocr-overlay-batch"
            )
            logger = progress.logger_for_book(self.config.input_dir.name, 1, 1)

            logger.emit(
                OcrLogEvent(
                    event="failed",
                    level="error",
                    input_pdf=self.config.input_dir / "broken.pdf",
                    pdf_page=None,
                    total_pages=1,
                    completed_pages=0,
                    cache_hit_count=0,
                    cache_miss_count=0,
                    elapsed_sec=0.1,
                    estimated_remaining_sec=None,
                    message="OCR 호출이 실패했다.",
                )
            )
            logger.close()
            progress.close()
            return _batch_result(self.config, failed_count=1, processed_count=0)

    monkeypatch.setattr("pdfbooktree.cli.OcrOverlayBatchRunner", FakeRunner)

    result = CliRunner().invoke(
        app,
        [
            "ocr-overlay-batch",
            str(input_dir),
            "--output-dir",
            str(tmp_path / "out"),
            "--log-mode",
            "none",
            "--no-log-file",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    final = json.loads(result.stdout)
    assert final["schema_version"] == 1
    assert final["command"] == "ocr-overlay-batch"
    assert final["ok"] is True
    assert final["result"]["failed_count"] == 1
    assert final["result"]["target_page_count"] == 0
    assert final["result"]["will_process_page_count"] == 0
    assert final["result"]["mupdf_warning_count"] == 0
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert len(events) == 1
    assert events[0]["schema_version"] == 1
    assert events[0]["command"] == "ocr-overlay-batch"
    assert events[0]["event"] == "failed"


def test_ocr_overlay_batch_missing_input_uses_json_input_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "ocr-overlay-batch",
            str(tmp_path / "missing"),
            "--output-dir",
            str(tmp_path / "out"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["schema_version"] == 1
    assert error["command"] == "ocr-overlay-batch"
    assert error["ok"] is False
    assert error["error"]["code"] == "invalid_input"


def test_ocr_overlay_batch_invalid_log_mode_uses_json_input_error(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "300STUDY"
    input_dir.mkdir()

    result = CliRunner().invoke(
        app,
        [
            "ocr-overlay-batch",
            str(input_dir),
            "--output-dir",
            str(tmp_path / "out"),
            "--log-mode",
            "yaml",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    error = json.loads(result.stderr)
    assert error["error"]["code"] == "invalid_input"


def test_ocr_overlay_batch_runtime_error_and_debug_contract(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "300STUDY"
    input_dir.mkdir()

    class FailingRunner:
        def __init__(self, config, *, log_mode=None, enable_log_file=True):
            pass

        def run(self):
            raise RuntimeError("batch 실행 실패")

    monkeypatch.setattr("pdfbooktree.cli.OcrOverlayBatchRunner", FailingRunner)
    args = [
        "ocr-overlay-batch",
        str(input_dir),
        "--output-dir",
        str(tmp_path / "out"),
        "--log-mode",
        "none",
        "--no-log-file",
        "--format",
        "json",
    ]

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 1
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"]["code"] == "runtime_error"

    debug_result = CliRunner().invoke(app, [*args, "--debug"])
    assert debug_result.exit_code == 1
    assert isinstance(debug_result.exception, RuntimeError)
    assert str(debug_result.exception) == "batch 실행 실패"


def test_ocr_overlay_batch_partial_failure_keeps_exit_zero(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "300STUDY"
    input_dir.mkdir()

    class FakeRunner:
        def __init__(self, config, *, log_mode=None, enable_log_file=True):
            self.config = config

        def run(self):
            return _batch_result(self.config, failed_count=1, processed_count=1)

    monkeypatch.setattr("pdfbooktree.cli.OcrOverlayBatchRunner", FakeRunner)

    result = CliRunner().invoke(
        app,
        [
            "ocr-overlay-batch",
            str(input_dir),
            "--output-dir",
            str(tmp_path / "out"),
            "--log-mode",
            "none",
            "--no-log-file",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    final = json.loads(result.stdout)
    assert final["ok"] is True
    assert final["result"]["failed_count"] == 1
