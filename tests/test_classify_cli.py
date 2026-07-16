from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pdfbooktree.classify.logger import ClassifyLogEvent
from pdfbooktree.classify.models import ClassifyBatchResult
from pdfbooktree.cli import app


def test_classify_scan_cli_parses_options(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    input_dir = tmp_path / "300STUDY"
    input_dir.mkdir()

    class FakeLogger:
        def close(self) -> None:
            return None

    class FakeClassifier:
        def __init__(self, config, logger=None):
            captured["config"] = config
            captured["logger"] = logger

        def run(self):
            return ClassifyBatchResult(
                total_pdf_count=3,
                scanned_count=2,
                native_count=1,
                target_count=1,
                error_count=0,
                elapsed_sec=1.23,
                report_csv_path=Path(captured["config"].output_dir)
                / "classification_report.csv",
                detail_jsonl_path=Path(captured["config"].output_dir)
                / "classification_detail.jsonl",
                results=[],
            )

    def fake_build_logger(mode):
        captured["log_mode"] = mode
        return FakeLogger()

    monkeypatch.setattr("pdfbooktree.cli.ScanBookmarkClassifier", FakeClassifier)
    monkeypatch.setattr("pdfbooktree.cli.build_classify_logger", fake_build_logger)

    result = CliRunner().invoke(
        app,
        [
            "classify-scan",
            str(input_dir),
            "--output-dir",
            str(tmp_path / "out"),
            "--recursive",
            "--dry-run",
            "--no-write-report",
            "--max-sample-pages",
            "10",
            "--log-mode",
            "plain",
        ],
    )

    assert result.exit_code == 0
    config = captured["config"]
    assert config.input_dir == input_dir
    assert config.output_dir == tmp_path / "out"
    assert config.recursive is True
    assert config.dry_run is True
    assert config.write_report is False
    assert config.max_sample_pages == 10
    assert captured["log_mode"] == "plain"


def test_classify_scan_cli_defaults_to_non_dry_run(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    input_dir = tmp_path / "300STUDY"
    input_dir.mkdir()

    class FakeLogger:
        def close(self) -> None:
            return None

    class FakeClassifier:
        def __init__(self, config, logger=None):
            captured["config"] = config

        def run(self):
            return ClassifyBatchResult(
                total_pdf_count=0,
                scanned_count=0,
                native_count=0,
                target_count=0,
                error_count=0,
                elapsed_sec=0.0,
                report_csv_path=None,
                detail_jsonl_path=None,
                results=[],
            )

    monkeypatch.setattr("pdfbooktree.cli.ScanBookmarkClassifier", FakeClassifier)
    monkeypatch.setattr(
        "pdfbooktree.cli.build_classify_logger", lambda mode: FakeLogger()
    )

    result = CliRunner().invoke(
        app,
        [
            "classify-scan",
            str(input_dir),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    assert captured["config"].dry_run is False
    assert captured["config"].write_report is True
    assert captured["config"].max_sample_pages == 50
    assert captured["config"].recursive is False


def test_classify_scan_json_result_and_events_use_separate_streams(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()

    class FakeClassifier:
        def __init__(self, config, logger=None):
            self.config = config
            self.logger = logger

        def run(self):
            self.logger.emit(
                ClassifyLogEvent(
                    event="failed",
                    level="error",
                    input_pdf=self.config.input_dir / "broken.pdf",
                    completed_count=1,
                    total_count=1,
                    target_count=0,
                    error_count=1,
                    elapsed_sec=0.1,
                    message="PDF를 열지 못했다.",
                )
            )
            self.logger.close()
            return ClassifyBatchResult(
                total_pdf_count=1,
                scanned_count=0,
                native_count=1,
                target_count=0,
                error_count=1,
                elapsed_sec=0.1,
                report_csv_path=self.config.output_dir / "classification_report.csv",
                detail_jsonl_path=self.config.output_dir
                / "classification_detail.jsonl",
                results=[],
            )

    monkeypatch.setattr("pdfbooktree.cli.ScanBookmarkClassifier", FakeClassifier)

    result = CliRunner().invoke(
        app,
        [
            "classify-scan",
            str(input_dir),
            "--output-dir",
            str(tmp_path / "out"),
            "--log-mode",
            "json",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    final = json.loads(result.stdout)
    assert final["schema_version"] == 1
    assert final["command"] == "classify-scan"
    assert final["ok"] is True
    assert final["result"]["error_count"] == 1
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert len(events) == 1
    assert events[0]["schema_version"] == 1
    assert events[0]["command"] == "classify-scan"
    assert events[0]["event"] == "failed"


def test_classify_scan_missing_input_uses_json_input_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "classify-scan",
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
    assert error["command"] == "classify-scan"
    assert error["ok"] is False
    assert error["error"]["code"] == "invalid_input"


def test_classify_scan_invalid_log_mode_uses_json_input_error(tmp_path: Path) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()

    result = CliRunner().invoke(
        app,
        [
            "classify-scan",
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


def test_classify_scan_runtime_error_and_debug_contract(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()

    class FailingClassifier:
        def __init__(self, config, logger=None):
            pass

        def run(self):
            raise RuntimeError("분류 실행 실패")

    monkeypatch.setattr("pdfbooktree.cli.ScanBookmarkClassifier", FailingClassifier)
    args = [
        "classify-scan",
        str(input_dir),
        "--output-dir",
        str(tmp_path / "out"),
        "--log-mode",
        "none",
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
    assert str(debug_result.exception) == "분류 실행 실패"
