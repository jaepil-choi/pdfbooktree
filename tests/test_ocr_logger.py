from __future__ import annotations

import json
from pathlib import Path

from pdfbooktree.ocr.logger import (
    CompositeOcrLogger,
    JsonFileOcrLogger,
    OcrLogEvent,
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


def test_json_file_ocr_logger_writes_event_log_and_progress_snapshot(tmp_path: Path) -> None:
    logger = JsonFileOcrLogger(tmp_path)

    logger.emit(make_event("start", 0))
    logger.emit(make_event("page_done", 1))

    log_rows = [
        json.loads(line)
        for line in (tmp_path / "ocr_log.jsonl").read_text(encoding="utf-8").splitlines()
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
