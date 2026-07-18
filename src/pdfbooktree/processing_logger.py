"""단일 PDF process/infer 진행 상태를 관찰 가능한 event로 제공한다."""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TextColumn, TimeElapsedColumn

from pdfbooktree.cli_contract import render_command_event_json
from pdfbooktree.utils.jsonio import to_jsonable

ProcessingLogLevel = Literal["info", "warning", "error"]
ProcessingLogMode = Literal["rich", "plain", "json", "none"]


@dataclass(frozen=True)
class ProcessingLogEvent:
    """단일 PDF 처리 단계 또는 page 진행 event다."""

    event: str
    level: ProcessingLogLevel
    input_pdf: Path
    completed_pages: int
    total_pages: int
    bookmark_count: int
    elapsed_sec: float
    message: str


class ProcessingLogger(Protocol):
    """processing event를 받는 logger protocol이다."""

    def emit(self, event: ProcessingLogEvent) -> None:
        """event를 출력하거나 저장한다."""

    def close(self) -> None:
        """logger resource를 정리한다."""


class NullProcessingLogger:
    """아무 출력도 하지 않는 logger다."""

    def emit(self, event: ProcessingLogEvent) -> None:
        return None

    def close(self) -> None:
        return None


class PlainTextProcessingLogger:
    """stderr에 한 줄씩 처리 진행 상태를 출력한다."""

    def emit(self, event: ProcessingLogEvent) -> None:
        _safe_print_line(
            f"[{event.completed_pages}/{event.total_pages}] {event.event} "
            f"bookmarks={event.bookmark_count} elapsed={event.elapsed_sec:.1f}s "
            f"{event.message}"
        )

    def close(self) -> None:
        return None


class JsonStderrProcessingLogger:
    """stderr에 versioned JSONL event를 출력한다."""

    def __init__(self, command: str) -> None:
        self.command = command

    def emit(self, event: ProcessingLogEvent) -> None:
        payload = to_jsonable(asdict(event))
        data = {
            key: value
            for key, value in payload.items()
            if key not in {"event", "level", "message"}
        }
        _safe_print_line(
            render_command_event_json(
                self.command,
                event.event,
                level=event.level,
                message=event.message,
                data=data,
            )
        )

    def close(self) -> None:
        return None


class RichProcessingLogger:
    """페이지 추출을 progress bar로 보여주는 logger다."""

    def __init__(self) -> None:
        self.console = Console(stderr=True)
        self.progress = Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TextColumn("{task.fields[status]}"),
            TimeElapsedColumn(),
            console=self.console,
        )
        self.task_id: TaskID | None = None
        self.progress.start()

    def emit(self, event: ProcessingLogEvent) -> None:
        total = max(1, event.total_pages)
        status = event.message
        if self.task_id is None:
            self.task_id = self.progress.add_task(
                "pdf",
                total=total,
                completed=event.completed_pages,
                status=status,
            )
        else:
            self.progress.update(
                self.task_id,
                total=total,
                completed=event.completed_pages,
                status=status,
            )
        if event.level == "error":
            self.console.print(event.message)

    def close(self) -> None:
        self.progress.stop()


def build_processing_logger(
    mode: ProcessingLogMode, *, command: str
) -> ProcessingLogger:
    """CLI option에 맞는 processing logger를 만든다."""

    if mode == "rich":
        return RichProcessingLogger()
    if mode == "plain":
        return PlainTextProcessingLogger()
    if mode == "json":
        return JsonStderrProcessingLogger(command)
    if mode == "none":
        return NullProcessingLogger()
    raise ValueError(f"지원하지 않는 processing log mode다: {mode}")


def default_processing_log_mode() -> ProcessingLogMode:
    """TTY에서만 rich를 사용하고 자동화에서는 기존 무출력을 유지한다."""

    return "rich" if sys.stderr.isatty() else "none"


def _safe_print_line(text: str) -> None:
    encoding = sys.stderr.encoding or "utf-8"
    safe_text = text.encode(encoding, errors="replace").decode(encoding)
    print(safe_text, file=sys.stderr, flush=True)
