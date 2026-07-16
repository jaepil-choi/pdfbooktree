from __future__ import annotations

import json
from pathlib import Path

import fitz
from typer.testing import CliRunner

from pdfbooktree.batch_logger import BatchLogEvent
from pdfbooktree.cli import app
from pdfbooktree.config_io import ResolvedConfig
from pdfbooktree.models import BatchItemResult, BatchResult


def _write_outline_pdf(path: Path) -> None:
    """batch CLI run manifest 검사용 기존 outline PDF를 만든다."""

    document = fitz.open()
    try:
        toc = []
        for page_no in range(1, 6):
            page = document.new_page()
            page.insert_text((72, 72), f"Chapter {page_no}")
            toc.append([1, f"Chapter {page_no}", page_no])
        document.set_toc(toc)
        document.save(path)
    finally:
        document.close()


def test_batch_cli_parses_options(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()

    class FakeLogger:
        def close(self) -> None:
            return None

    class FakeBatchProcessor:
        def __init__(self, input_dir, output_dir, config, recursive=False, log=None):
            captured["input_dir"] = input_dir
            captured["output_dir"] = output_dir
            captured["config"] = config
            captured["recursive"] = recursive
            captured["log"] = log

        def run(self):
            return BatchResult(
                total_pdf_count=0,
                processed_count=0,
                skipped_existing_bookmark_count=0,
                failed_count=0,
                bookmark_reference_candidate_count=0,
                results=[],
            )

    def fake_build_logger(mode):
        captured["log_mode"] = mode
        return FakeLogger()

    monkeypatch.setattr("pdfbooktree.cli.BatchProcessor", FakeBatchProcessor)
    monkeypatch.setattr("pdfbooktree.cli.build_batch_logger", fake_build_logger)

    result = CliRunner().invoke(
        app,
        [
            "batch",
            str(input_dir),
            "--output-dir",
            str(tmp_path / "out"),
            "--recursive",
            "--log-mode",
            "plain",
        ],
    )

    assert result.exit_code == 0
    assert captured["input_dir"] == input_dir
    assert captured["output_dir"] == tmp_path / "out"
    assert captured["recursive"] is True
    assert captured["log_mode"] == "plain"
    assert isinstance(captured["config"], ResolvedConfig)
    assert captured["config"].config_hash


def test_batch_json_result_and_events_use_separate_streams(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()

    class FakeBatchProcessor:
        def __init__(self, input_dir, output_dir, config, recursive=False, log=None):
            self.input_dir = input_dir
            self.log = log

        def run(self):
            self.log.emit(
                BatchLogEvent(
                    event="failed",
                    level="error",
                    input_pdf=self.input_dir / "broken.pdf",
                    completed_count=1,
                    total_count=1,
                    processed_count=0,
                    failed_count=1,
                    elapsed_sec=0.1,
                    message="PDF를 열지 못했다.",
                )
            )
            self.log.close()
            return BatchResult(
                total_pdf_count=1,
                processed_count=0,
                skipped_existing_bookmark_count=0,
                failed_count=1,
                bookmark_reference_candidate_count=0,
                results=[
                    BatchItemResult(
                        status="failed",
                        input_pdf=self.input_dir / "broken.pdf",
                        warnings=["PDF를 열지 못했다."],
                    )
                ],
            )

    monkeypatch.setattr("pdfbooktree.cli.BatchProcessor", FakeBatchProcessor)

    result = CliRunner().invoke(
        app,
        [
            "batch",
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
    assert final["command"] == "batch"
    assert final["ok"] is True
    assert final["result"]["failed_count"] == 1
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert len(events) == 1
    assert events[0]["schema_version"] == 1
    assert events[0]["command"] == "batch"
    assert events[0]["event"] == "failed"


def test_batch_cli_json_result_links_item_run_manifest(tmp_path: Path) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()
    _write_outline_pdf(input_dir / "book.pdf")
    output_dir = tmp_path / "runs"

    result = CliRunner().invoke(
        app,
        [
            "batch",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--set",
            "processing.write_artifacts=false",
            "--log-mode",
            "none",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    item = envelope["result"]["results"][0]
    manifest_path = Path(item["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert item["status"] == "processed"
    assert Path(item["run_dir"]) == manifest_path.parent
    assert item["run_id"] == manifest["run_id"]
    assert item["config_hash"] == manifest["config_hash"]
    assert manifest["status"] == "succeeded"
    assert manifest["config_sources"][-1]["kind"] == "set_overrides"


def test_batch_missing_input_uses_json_input_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "batch",
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
    assert error["command"] == "batch"
    assert error["ok"] is False
    assert error["error"]["code"] == "invalid_input"


def test_batch_invalid_log_mode_uses_json_input_error(tmp_path: Path) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()

    result = CliRunner().invoke(
        app,
        [
            "batch",
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


def test_batch_invalid_config_uses_json_input_error(tmp_path: Path) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()

    result = CliRunner().invoke(
        app,
        [
            "batch",
            str(input_dir),
            "--output-dir",
            str(tmp_path / "out"),
            "--set",
            "typography.unknown_field=1",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    error = json.loads(result.stderr)
    assert error["command"] == "batch"
    assert error["error"]["code"] == "invalid_config"
    assert error["error"]["type"] == "ConfigError"


def test_batch_runtime_error_and_debug_contract(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()

    class FailingBatchProcessor:
        def __init__(self, input_dir, output_dir, config, recursive=False, log=None):
            pass

        def run(self):
            raise RuntimeError("batch 실행 실패")

    monkeypatch.setattr("pdfbooktree.cli.BatchProcessor", FailingBatchProcessor)
    args = [
        "batch",
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
    assert str(debug_result.exception) == "batch 실행 실패"
