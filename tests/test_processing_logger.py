"""단일 PDF processing logger와 CLI stream 계약을 검증한다."""

from __future__ import annotations

import io
import json
from pathlib import Path

import fitz
from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.pipeline import analyze_pdf
from pdfbooktree.processing_logger import (
    PlainTextProcessingLogger,
    ProcessingLogEvent,
)


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[ProcessingLogEvent] = []

    def emit(self, event: ProcessingLogEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        return None


def _make_book(path: Path) -> None:
    document = fitz.open()
    for page_no in range(1, 7):
        page = document.new_page()
        page.insert_text((72, 72), f"Chapter {page_no}", fontsize=28)
        page.insert_text((72, 120), f"{page_no}.1 Topic", fontsize=16)
        for row in range(12):
            page.insert_text(
                (72, 180 + row * 15),
                "ordinary body text for typography coverage",
                fontsize=10,
            )
    document.save(path)
    document.close()


def test_analyze_pdf_emits_page_progress(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    _make_book(pdf)
    logger = RecordingLogger()

    analyze_pdf(pdf, log=logger)

    assert [event.event for event in logger.events] == [
        "analysis_started",
        "page_extracted",
        "page_extracted",
        "page_extracted",
        "page_extracted",
        "page_extracted",
        "page_extracted",
        "analysis_completed",
    ]
    assert [event.completed_pages for event in logger.events[1:7]] == [
        1,
        2,
        3,
        4,
        5,
        6,
    ]
    assert all(event.total_pages == 6 for event in logger.events)


def test_infer_json_progress_is_stderr_jsonl_and_result_is_stdout(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_book(pdf)

    result = CliRunner().invoke(
        app,
        [
            "infer",
            str(pdf),
            "--output-dir",
            str(tmp_path / "out"),
            "--flat-output",
            "--set",
            "typography.min_tier_count=1",
            "--log-mode",
            "json",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    final = json.loads(result.stdout)
    assert final["command"] == "infer"
    events = [json.loads(line) for line in result.stderr.splitlines()]
    names = [event["event"] for event in events]
    assert "analysis_started" in names
    assert names.count("page_extracted") == 6
    assert "inference_completed" in names
    assert names[-1] == "done"
    assert all(event["command"] == "infer" for event in events)


def test_auto_mode_is_quiet_for_non_tty_cli(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    _make_book(pdf)

    result = CliRunner().invoke(
        app,
        [
            "infer",
            str(pdf),
            "--output-dir",
            str(tmp_path / "out"),
            "--flat-output",
            "--set",
            "typography.min_tier_count=1",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.stderr == ""


def test_process_json_progress_includes_apply_events(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    _make_book(pdf)

    result = CliRunner().invoke(
        app,
        [
            "process",
            str(pdf),
            "--output-dir",
            str(tmp_path / "out"),
            "--flat-output",
            "--set",
            "typography.min_tier_count=1",
            "--log-mode",
            "json",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["command"] == "process"
    events = [json.loads(line) for line in result.stderr.splitlines()]
    names = [event["event"] for event in events]
    assert names.count("page_extracted") == 6
    assert "apply_started" in names
    assert "apply_completed" in names
    assert names[-1] == "done"
    assert all(event["command"] == "process" for event in events)


def test_plain_logger_replaces_unencodable_text_on_cp949(monkeypatch) -> None:
    buffer = io.BytesIO()
    stderr = io.TextIOWrapper(buffer, encoding="cp949")
    monkeypatch.setattr("pdfbooktree.processing_logger.sys.stderr", stderr)
    logger = PlainTextProcessingLogger()

    logger.emit(
        ProcessingLogEvent(
            event="page_extracted",
            level="info",
            input_pdf=Path("book.pdf"),
            completed_pages=1,
            total_pages=1,
            bookmark_count=0,
            elapsed_sec=0.1,
            message="분석 완료 🧪",
        )
    )
    stderr.flush()

    assert "분석 완료 ?" in buffer.getvalue().decode("cp949")
