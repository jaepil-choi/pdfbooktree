"""classify 배치 실행 중 file 단위 progress/에러를 기록한다.

`ocr/logger.py`의 event/Protocol 패턴을 그대로 따르되, page 단위가 아니라
file 단위 event를 다룬다.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TextColumn, TimeElapsedColumn

from pdfbooktree.utils.jsonio import to_jsonable


ClassifyLogLevel = Literal["info", "warning", "error"]
ClassifyLogMode = Literal["rich", "plain", "json", "none"]


@dataclass(frozen=True)
class ClassifyLogEvent:
    """classify 배치 실행 중 관찰 가능한 단일 file event다."""

    event: str
    level: ClassifyLogLevel
    input_pdf: Path
    completed_count: int
    total_count: int
    target_count: int
    error_count: int
    elapsed_sec: float
    message: str


class ClassifyLogger(Protocol):
    """classify 배치 event를 받는 logger protocol이다."""

    def emit(self, event: ClassifyLogEvent) -> None:
        """event를 출력하거나 저장한다."""

    def close(self) -> None:
        """필요한 logger resource를 정리한다."""


class NullClassifyLogger:
    """아무 출력도 하지 않는 logger다."""

    def emit(self, event: ClassifyLogEvent) -> None:
        return None

    def close(self) -> None:
        return None


class PlainTextClassifyLogger:
    """터미널에 한 줄씩 classify 진행 로그를 출력한다."""

    def emit(self, event: ClassifyLogEvent) -> None:
        print(format_classify_log_event(event), flush=True)

    def close(self) -> None:
        return None


class JsonStdoutClassifyLogger:
    """stdout에 JSONL event를 출력한다."""

    def emit(self, event: ClassifyLogEvent) -> None:
        print(json.dumps(_event_to_jsonable(event), ensure_ascii=False), flush=True)

    def close(self) -> None:
        return None


class RichClassifyLogger:
    """rich progress bar로 classify 진행 상태를 표시한다."""

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

    def emit(self, event: ClassifyLogEvent) -> None:
        total = max(1, event.total_count)
        status = _rich_status(event)
        if self.task_id is None:
            self.task_id = self.progress.add_task(
                "classify-scan",
                total=total,
                completed=event.completed_count,
                status=status,
            )
        else:
            self.progress.update(
                self.task_id,
                total=total,
                completed=event.completed_count,
                status=status,
            )
        if event.level == "error":
            self.console.print(format_classify_log_event(event))

    def close(self) -> None:
        self.progress.stop()


class CompositeClassifyLogger:
    """여러 logger에 같은 event를 전달한다."""

    def __init__(self, loggers: list[ClassifyLogger]) -> None:
        self.loggers = loggers

    def emit(self, event: ClassifyLogEvent) -> None:
        for logger in self.loggers:
            logger.emit(event)

    def close(self) -> None:
        for logger in self.loggers:
            logger.close()


def build_classify_logger(mode: ClassifyLogMode) -> ClassifyLogger:
    """CLI 옵션에 맞는 classify logger를 만든다."""

    if mode == "rich":
        return RichClassifyLogger()
    if mode == "plain":
        return PlainTextClassifyLogger()
    if mode == "json":
        return JsonStdoutClassifyLogger()
    if mode == "none":
        return NullClassifyLogger()
    raise ValueError(f"지원하지 않는 classify log mode다: {mode}")


def format_classify_log_event(event: ClassifyLogEvent) -> str:
    """plain text logger가 출력할 한 줄 메시지를 만든다."""

    return (
        f"[{event.completed_count}/{event.total_count}] "
        f"target={event.target_count} error={event.error_count} "
        f"elapsed={_format_duration(event.elapsed_sec)} "
        f"{event.input_pdf} {event.message}"
    )


def _event_to_jsonable(event: ClassifyLogEvent) -> dict[str, object]:
    return to_jsonable(asdict(event))


def _rich_status(event: ClassifyLogEvent) -> str:
    return f"target {event.target_count} | error {event.error_count}"


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def default_classify_log_mode() -> ClassifyLogMode:
    """실행 환경에 맞는 기본 CLI log mode를 고른다."""

    return "rich" if sys.stderr.isatty() else "plain"
