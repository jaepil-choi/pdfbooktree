"""단계형 CLI command의 versioned result/error 계약을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
from typer.testing import CliRunner, Result

from pdfbooktree.cli import app

RUNNER = CliRunner()


def _make_pdf(path: Path, *, with_outline: bool = False) -> None:
    document = fitz.open()
    try:
        for page_no in range(1, 4):
            page = document.new_page()
            page.insert_text((72, 72), f"Page {page_no}", fontsize=12)
        if with_outline:
            document.set_toc([[1, "Chapter 1", 1], [2, "1.1 Topic", 2]])
        document.save(path)
    finally:
        document.close()


def _write_plan(path: Path, *, pdf_page: int = 1) -> None:
    path.write_text(
        json.dumps([{"title": "Chapter 1", "level": 1, "pdf_page": pdf_page}]),
        encoding="utf-8",
    )


def _success_payload(result: Result, command: str) -> dict[str, object]:
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert set(payload) == {"schema_version", "command", "ok", "result"}
    assert payload["schema_version"] == 1
    assert payload["command"] == command
    assert payload["ok"] is True
    return payload


def _error_payload(
    result: Result,
    command: str,
    *,
    exit_code: int,
    code: str,
) -> dict[str, object]:
    assert result.exit_code == exit_code, result.output
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert set(payload) == {"schema_version", "command", "ok", "error"}
    assert payload["schema_version"] == 1
    assert payload["command"] == command
    assert payload["ok"] is False
    assert payload["error"]["code"] == code
    return payload


def test_process_json_success_envelope은_run_identity를_보존한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "bookmarked.pdf"
    output_root = tmp_path / "runs"
    _make_pdf(pdf, with_outline=True)

    result = RUNNER.invoke(
        app,
        [
            "process",
            str(pdf),
            "--output-dir",
            str(output_root),
            "--format",
            "json",
        ],
    )

    payload = _success_payload(result, "process")
    command_result = payload["result"]
    assert set(command_result) == {
        "run_id",
        "run_dir",
        "manifest_path",
        "config_hash",
        "result",
    }
    assert command_result["result"]["status"] == "processed"
    assert Path(command_result["manifest_path"]).is_file()


def test_infer_json_success_envelope은_flat_result를_직렬화한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "bookmarked.pdf"
    output_dir = tmp_path / "out"
    _make_pdf(pdf, with_outline=True)

    result = RUNNER.invoke(
        app,
        [
            "infer",
            str(pdf),
            "--output-dir",
            str(output_dir),
            "--flat-output",
            "--format",
            "json",
        ],
    )

    payload = _success_payload(result, "infer")
    assert payload["result"]["status"] == "skipped"
    assert payload["result"]["output_pdf"] is None


def test_apply_json_success_envelope은_flat_result를_직렬화한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    plan = tmp_path / "plan.json"
    output_dir = tmp_path / "out"
    _make_pdf(pdf)
    _write_plan(plan)

    result = RUNNER.invoke(
        app,
        [
            "apply",
            str(pdf),
            "--plan",
            str(plan),
            "--output-dir",
            str(output_dir),
            "--flat-output",
            "--format",
            "json",
        ],
    )

    payload = _success_payload(result, "apply")
    assert payload["result"]["status"] == "processed"
    assert Path(payload["result"]["output_pdf"]).is_file()
    assert Path(payload["result"]["output_markdown_dir"]).is_dir()


def test_apply_invalid_plan은_json_stderr와_exit_2를_사용한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    plan = tmp_path / "plan.json"
    _make_pdf(pdf)
    plan.write_text(json.dumps([{"title": "Chapter 1"}]), encoding="utf-8")

    result = RUNNER.invoke(
        app,
        [
            "apply",
            str(pdf),
            "--plan",
            str(plan),
            "--flat-output",
            "--format",
            "json",
        ],
    )

    payload = _error_payload(
        result,
        "apply",
        exit_code=2,
        code="invalid_plan",
    )
    assert payload["error"]["type"] == "PlanError"
    assert "level" in payload["error"]["message"]


def test_infer_invalid_config는_json_stderr와_exit_2를_사용한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)

    result = RUNNER.invoke(
        app,
        [
            "infer",
            str(pdf),
            "--set",
            "typography.unknown_field=1",
            "--format",
            "json",
        ],
    )

    payload = _error_payload(
        result,
        "infer",
        exit_code=2,
        code="invalid_config",
    )
    assert payload["error"]["type"] == "ConfigError"


def test_process_missing_input은_json_stderr와_exit_2를_사용한다(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.pdf"

    result = RUNNER.invoke(
        app,
        ["process", str(missing), "--format", "json"],
    )

    payload = _error_payload(
        result,
        "process",
        exit_code=2,
        code="invalid_input",
    )
    assert payload["error"]["type"] == "RunError"


def test_process_flat_missing_input도_json_stderr와_exit_2를_사용한다(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.pdf"

    result = RUNNER.invoke(
        app,
        [
            "process",
            str(missing),
            "--flat-output",
            "--format",
            "json",
        ],
    )

    payload = _error_payload(
        result,
        "process",
        exit_code=2,
        code="invalid_input",
    )
    assert payload["error"]["type"] == "RunError"


def test_process_runtime_error는_manifest를_남기고_traceback을_숨긴다(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FailingProcessor:
        def __init__(self, pdf, output_dir, config):
            pass

        def run(self):
            raise RuntimeError("pipeline failed")

    monkeypatch.setattr("pdfbooktree.cli.Processor", FailingProcessor)
    pdf = tmp_path / "book.pdf"
    output_root = tmp_path / "runs"
    _make_pdf(pdf)

    result = RUNNER.invoke(
        app,
        [
            "process",
            str(pdf),
            "--output-dir",
            str(output_root),
            "--format",
            "json",
        ],
    )

    payload = _error_payload(
        result,
        "process",
        exit_code=1,
        code="runtime_error",
    )
    assert payload["error"]["type"] == "RuntimeError"
    assert "Traceback" not in result.stderr
    manifests = list(output_root.rglob("run_manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["error"] == {
        "type": "RuntimeError",
        "message": "pipeline failed",
    }


def test_process_debug는_manifest를_남기고_원래_예외를_노출한다(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FailingProcessor:
        def __init__(self, pdf, output_dir, config):
            pass

        def run(self):
            raise RuntimeError("debug pipeline failed")

    monkeypatch.setattr("pdfbooktree.cli.Processor", FailingProcessor)
    pdf = tmp_path / "book.pdf"
    output_root = tmp_path / "runs"
    _make_pdf(pdf)

    result = RUNNER.invoke(
        app,
        [
            "process",
            str(pdf),
            "--output-dir",
            str(output_root),
            "--format",
            "json",
            "--debug",
        ],
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    assert str(result.exception) == "debug pipeline failed"
    manifests = list(output_root.rglob("run_manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"


def test_apply_validation_failure는_result_detail과_exit_3을_사용한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    plan = tmp_path / "plan.json"
    output_dir = tmp_path / "out"
    _make_pdf(pdf)
    _write_plan(plan, pdf_page=99)

    result = RUNNER.invoke(
        app,
        [
            "apply",
            str(pdf),
            "--plan",
            str(plan),
            "--output-dir",
            str(output_dir),
            "--flat-output",
            "--format",
            "json",
        ],
    )

    payload = _error_payload(
        result,
        "apply",
        exit_code=3,
        code="processing_failed",
    )
    assert payload["error"]["type"] == "ProcessingFailedError"
    processing_result = payload["error"]["details"]
    assert processing_result["status"] == "failed"
    assert processing_result["bookmark_count"] == 1
    assert "범위를 벗어났다" in processing_result["warnings"][0]
