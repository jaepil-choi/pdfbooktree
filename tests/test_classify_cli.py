from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pdfbooktree.classify.models import ClassifyBatchResult
from pdfbooktree.cli import app


def test_classify_scan_cli_parses_options(monkeypatch, tmp_path: Path) -> None:
    captured = {}

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
            str(tmp_path / "300STUDY"),
            "--output-dir",
            str(tmp_path / "out"),
            "--recursive",
            "--dry-run",
            "--max-sample-pages",
            "10",
            "--log-mode",
            "plain",
        ],
    )

    assert result.exit_code == 0
    config = captured["config"]
    assert config.input_dir == tmp_path / "300STUDY"
    assert config.output_dir == tmp_path / "out"
    assert config.recursive is True
    assert config.dry_run is True
    assert config.max_sample_pages == 10
    assert captured["log_mode"] == "plain"


def test_classify_scan_cli_defaults_to_non_dry_run(monkeypatch, tmp_path: Path) -> None:
    captured = {}

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
            str(tmp_path / "300STUDY"),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    assert captured["config"].dry_run is False
    assert captured["config"].recursive is False
