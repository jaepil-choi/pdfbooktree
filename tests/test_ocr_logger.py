from __future__ import annotations

import io
import json
from pathlib import Path

from pdfbooktree.ocr.logger import (
    CompositeOcrLogger,
    FlatBatchOcrProgress,
    JsonFileOcrLogger,
    JsonStderrOcrLogger,
    NullBatchOcrProgress,
    OcrBatchPreparationProgress,
    OcrLogEvent,
    PlainTextOcrLogger,
    TqdmBatchOcrProgress,
    TqdmOcrLogger,
    build_batch_ocr_progress,
    build_ocr_logger,
)


def make_event(event: str, completed_pages: int = 0) -> OcrLogEvent:
    return OcrLogEvent(
        event=event,
        level="info",
        input_pdf=Path("book.pdf"),
        pdf_page=completed_pages or None,
        total_pages=10,
        completed_pages=completed_pages,
        cache_hit_count=2,
        cache_miss_count=3,
        elapsed_sec=12.5,
        estimated_remaining_sec=25.0,
        message=f"{event} message",
    )


def test_json_file_ocr_logger_writes_event_log_and_progress_snapshot(
    tmp_path: Path,
) -> None:
    logger = JsonFileOcrLogger(tmp_path)

    logger.emit(make_event("start", 0))
    logger.emit(make_event("page_done", 1))

    log_rows = [
        json.loads(line)
        for line in (tmp_path / "ocr_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    progress = json.loads((tmp_path / "ocr_progress.json").read_text(encoding="utf-8"))

    assert [row["event"] for row in log_rows] == ["start", "page_done"]
    assert progress["status"] == "running"
    assert progress["event"] == "page_done"
    assert progress["completed_pages"] == 1
    assert progress["cache_hit_count"] == 2
    assert progress["estimated_remaining_sec"] == 25.0


def test_composite_ocr_logger_forwards_events() -> None:
    seen_left: list[str] = []
    seen_right: list[str] = []

    class ListLogger:
        def __init__(self, seen: list[str]) -> None:
            self.seen = seen

        def emit(self, event: OcrLogEvent) -> None:
            self.seen.append(event.event)

        def close(self) -> None:
            self.seen.append("closed")

    logger = CompositeOcrLogger([ListLogger(seen_left), ListLogger(seen_right)])

    logger.emit(make_event("page_done", 1))
    logger.close()

    assert seen_left == ["page_done", "closed"]
    assert seen_right == ["page_done", "closed"]


def test_json_stderr_ocr_logger_writes_versioned_event_envelope(capsys) -> None:
    logger = JsonStderrOcrLogger()

    logger.emit(make_event("page_done", 1))

    captured = capsys.readouterr()
    assert captured.out == ""
    envelope = json.loads(captured.err)
    assert envelope["schema_version"] == 1
    assert envelope["command"] == "ocr-overlay"
    assert envelope["event"] == "page_done"
    assert envelope["level"] == "info"
    assert envelope["message"] == "page_done message"
    assert envelope["data"]["completed_pages"] == 1
    assert envelope["data"]["input_pdf"] == "book.pdf"


def test_plain_text_ocr_logger_writes_only_to_stderr(capsys) -> None:
    logger = PlainTextOcrLogger()

    logger.emit(make_event("page_done", 1))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "event=page_done" in captured.err


def test_tqdm_ocr_logger_failure_does_not_write_stdout(capsys) -> None:
    logger = TqdmOcrLogger(total_pages=1)

    logger.emit(make_event("failed", 0))
    logger.close()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "event=failed" in captured.err


def test_tqdm_ocr_logger_advances_only_when_completed_pages_grows() -> None:
    """render_start/ocr_call_start처럼 completed_pages가 그대로인 event는

    bar를 전진시키지 않아야 한다. 이전 rich/plain logger는 이런 event마다
    한 줄씩 출력해서 page당 6~7줄이 나왔다.
    """

    sink = io.StringIO()
    logger = TqdmOcrLogger(total_pages=3, file=sink)

    logger.emit(make_event("page_start", 0))
    logger.emit(make_event("page_render_start", 0))
    logger.emit(make_event("page_render_done", 0))
    assert logger._bar.n == 0

    logger.emit(make_event("page_done", 1))
    assert logger._bar.n == 1

    logger.emit(make_event("page_done", 2))
    assert logger._bar.n == 2
    logger.close()


def test_tqdm_batch_progress_advances_outer_bar_across_books() -> None:
    """batch 전체 outer bar가 여러 책의 page_done을 누적해서 전진해야 한다."""

    sink = io.StringIO()
    progress = TqdmBatchOcrProgress(total_pages=5, total_books=2, file=sink)

    book1 = progress.logger_for_book("book1.pdf", 3, 1)
    book1.emit(make_event("page_done", 1))
    book1.emit(make_event("page_done", 2))
    book1.emit(make_event("page_done", 3))
    progress.note_book_done(3, 3)
    assert progress._outer.n == 3

    book2 = progress.logger_for_book("book2.pdf", 2, 2)
    book2.emit(make_event("page_done", 1))
    book2.emit(make_event("page_done", 2))
    progress.note_book_done(2, 2)
    assert progress._outer.n == 5
    progress.close()


def test_tqdm_batch_progress_reconciles_shortfall_on_failure() -> None:
    """책 처리가 중간에 실패해도 outer bar가 그 책의 남은 page만큼 전진해서

    batch 전체 progress가 멈추지 않아야 한다.
    """

    sink = io.StringIO()
    progress = TqdmBatchOcrProgress(total_pages=4, total_books=1, file=sink)

    book = progress.logger_for_book("book.pdf", 4, 1)
    book.emit(make_event("page_done", 1))
    assert progress._outer.n == 1

    progress.note_book_done(4, 1)
    assert progress._outer.n == 4
    progress.close()


def test_tqdm_batch_progress_does_not_mix_skips_into_ocr_bar() -> None:
    """비대상 PDF 수는 OCR page bar postfix에 섞이지 않아야 한다."""

    sink = io.StringIO()
    progress = TqdmBatchOcrProgress(total_pages=2, total_books=1, file=sink)

    progress.note_skip()
    progress.note_skip()
    progress.close()

    assert "skipped=" not in sink.getvalue()


def test_batch_preparation_tqdm_shows_discovery_classification_and_summary() -> None:
    sink = io.StringIO()
    progress = OcrBatchPreparationProgress("tqdm", file=sink)

    progress.search_started(Path("300STUDY"), recursive=True)
    progress.search_completed(2)
    progress.classification_started(2)
    progress.note_classified(
        completed_pdf_count=1,
        total_pdf_count=2,
        target_count=1,
        target_page_count=120,
        error_count=0,
    )
    progress.note_classified(
        completed_pdf_count=2,
        total_pdf_count=2,
        target_count=1,
        target_page_count=120,
        error_count=1,
    )
    progress.classification_completed(
        {
            "total_pdf_count": 2,
            "page_count_eligible_count": 1,
            "scanned_count": 1,
            "target_count": 1,
            "target_page_count": 120,
            "will_process_count": 1,
            "will_process_page_count": 120,
            "existing_output_count": 0,
            "classification_error_count": 1,
            "mupdf_warning_pdf_count": 1,
            "mupdf_warning_count": 2,
        }
    )

    output = sink.getvalue()
    assert "PDF 탐색 시작" in output
    assert "recursive=True" in output
    assert "PDF 탐색 완료: 2개 발견" in output
    assert "PDF 분류" in output
    assert "OCR 대상=1권/120page" in output
    assert "분류 실패=1권" in output
    assert "MuPDF 경고=1권/2건" in output


def test_batch_preparation_json_emits_versioned_lifecycle_events(capsys) -> None:
    progress = OcrBatchPreparationProgress("json")

    progress.search_started(Path("300STUDY"), recursive=True)
    progress.search_completed(1)
    progress.classification_started(1)
    progress.note_classified(
        completed_pdf_count=1,
        total_pdf_count=1,
        target_count=1,
        target_page_count=100,
        error_count=0,
    )

    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [event["event"] for event in events] == [
        "discovery_started",
        "discovery_completed",
        "classification_started",
        "classification_progress",
    ]
    assert all(event["schema_version"] == 1 for event in events)
    assert all(event["command"] == "ocr-overlay-batch" for event in events)
    assert events[-1]["data"]["target_page_count"] == 100


def test_build_batch_ocr_progress_dispatches_by_mode() -> None:
    assert isinstance(build_batch_ocr_progress("none", 10, 2), NullBatchOcrProgress)


def test_build_ocr_logger_json_mode_defaults_to_ocr_overlay_command(
    tmp_path: Path, capsys
) -> None:
    logger = build_ocr_logger("json", tmp_path, enable_file=False)

    logger.emit(make_event("page_done", 1))

    envelope = json.loads(capsys.readouterr().err)
    assert envelope["command"] == "ocr-overlay"


def test_build_ocr_logger_json_mode_accepts_explicit_command(
    tmp_path: Path, capsys
) -> None:
    logger = build_ocr_logger(
        "json", tmp_path, enable_file=False, command="ocr-overlay-batch"
    )

    logger.emit(make_event("page_done", 1))

    envelope = json.loads(capsys.readouterr().err)
    assert envelope["command"] == "ocr-overlay-batch"


def test_flat_batch_progress_tags_book_loggers_with_batch_command(capsys) -> None:
    progress = build_batch_ocr_progress(
        "json", total_pages=1, total_books=1, command="ocr-overlay-batch"
    )
    assert isinstance(progress, FlatBatchOcrProgress)

    logger = progress.logger_for_book("book.pdf", 1, 1)
    logger.emit(make_event("page_done", 1))

    envelope = json.loads(capsys.readouterr().err)
    assert envelope["command"] == "ocr-overlay-batch"
