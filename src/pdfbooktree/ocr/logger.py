"""OCR runtime 로그와 진행 상태를 기록한다."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TextColumn, TimeElapsedColumn

from pdfbooktree.utils.jsonio import to_jsonable


OcrLogLevel = Literal["info", "warning", "error"]
OcrLogMode = Literal["rich", "plain", "json", "none"]


@dataclass(frozen=True)
class OcrLogEvent:
    """OCR overlay 실행 중 관찰 가능한 단일 이벤트다."""

    event: str
    level: OcrLogLevel
    input_pdf: Path
    pdf_page: int | None
    total_pages: int
    completed_pages: int
    cache_hit_count: int
    cache_miss_count: int
    elapsed_sec: float
    estimated_remaining_sec: float | None
    message: str


class OcrLogger(Protocol):
    """OCR runtime event를 받는 logger protocol이다."""

    def emit(self, event: OcrLogEvent) -> None:
        """event를 출력하거나 저장한다."""

    def close(self) -> None:
        """필요한 logger resource를 정리한다."""


class NullOcrLogger:
    """아무 출력도 하지 않는 logger다."""

    def emit(self, event: OcrLogEvent) -> None:
        return None

    def close(self) -> None:
        return None


class JsonFileOcrLogger:
    """전체 event log와 최신 progress snapshot을 파일로 저장한다."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.log_path = output_dir / "ocr_log.jsonl"
        self.progress_path = output_dir / "ocr_progress.json"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def emit(self, event: OcrLogEvent) -> None:
        payload = _event_to_jsonable(event)
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.progress_path.write_text(
            json.dumps(_progress_snapshot(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def close(self) -> None:
        return None


class PlainTextOcrLogger:
    """터미널에 한 줄씩 OCR 진행 로그를 출력한다."""

    def emit(self, event: OcrLogEvent) -> None:
        print(format_ocr_log_event(event), flush=True)

    def close(self) -> None:
        return None


class JsonStdoutOcrLogger:
    """stdout에 JSONL event를 출력한다."""

    def emit(self, event: OcrLogEvent) -> None:
        print(json.dumps(_event_to_jsonable(event), ensure_ascii=False), flush=True)

    def close(self) -> None:
        return None


class RichOcrLogger:
    """rich progress bar로 OCR 진행 상태를 표시한다."""

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

    def emit(self, event: OcrLogEvent) -> None:
        total = max(1, event.total_pages)
        description = f"OCR overlay: {event.input_pdf.name}"
        status = _rich_status(event)
        if self.task_id is None:
            self.task_id = self.progress.add_task(
                description,
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
        if event.event in {"failed", "done"}:
            self.console.print(format_ocr_log_event(event))

    def close(self) -> None:
        self.progress.stop()


class CompositeOcrLogger:
    """여러 logger에 같은 event를 전달한다."""

    def __init__(self, loggers: list[OcrLogger]) -> None:
        self.loggers = loggers

    def emit(self, event: OcrLogEvent) -> None:
        for logger in self.loggers:
            logger.emit(event)

    def close(self) -> None:
        for logger in self.loggers:
            logger.close()


def build_ocr_logger(
    mode: OcrLogMode,
    output_dir: Path,
    *,
    enable_file: bool = True,
) -> OcrLogger:
    """CLI 옵션에 맞는 OCR logger 조합을 만든다."""

    loggers: list[OcrLogger] = []
    if enable_file:
        loggers.append(JsonFileOcrLogger(output_dir))
    if mode == "rich":
        loggers.append(RichOcrLogger())
    elif mode == "plain":
        loggers.append(PlainTextOcrLogger())
    elif mode == "json":
        loggers.append(JsonStdoutOcrLogger())
    elif mode == "none":
        pass
    else:
        raise ValueError(f"지원하지 않는 OCR log mode다: {mode}")
    if not loggers:
        return NullOcrLogger()
    if len(loggers) == 1:
        return loggers[0]
    return CompositeOcrLogger(loggers)


def format_ocr_log_event(event: OcrLogEvent) -> str:
    """plain text logger가 출력할 한 줄 메시지를 만든다."""

    page = "-" if event.pdf_page is None else str(event.pdf_page)
    eta = "?" if event.estimated_remaining_sec is None else _format_duration(event.estimated_remaining_sec)
    return (
        f"[{event.completed_pages}/{event.total_pages}] page={page} "
        f"event={event.event} elapsed={_format_duration(event.elapsed_sec)} "
        f"eta={eta} cache_hit={event.cache_hit_count} cache_miss={event.cache_miss_count} "
        f"{event.message}"
    )


def _event_to_jsonable(event: OcrLogEvent) -> dict[str, object]:
    return to_jsonable(asdict(event))


def _progress_snapshot(payload: dict[str, object]) -> dict[str, object]:
    status = "failed" if payload["event"] == "failed" else "done" if payload["event"] == "done" else "running"
    return {
        "status": status,
        "event": payload["event"],
        "level": payload["level"],
        "input_pdf": payload["input_pdf"],
        "current_page": payload["pdf_page"],
        "total_pages": payload["total_pages"],
        "completed_pages": payload["completed_pages"],
        "cache_hit_count": payload["cache_hit_count"],
        "cache_miss_count": payload["cache_miss_count"],
        "elapsed_sec": payload["elapsed_sec"],
        "estimated_remaining_sec": payload["estimated_remaining_sec"],
        "message": payload["message"],
    }


def _rich_status(event: OcrLogEvent) -> str:
    page = "-" if event.pdf_page is None else str(event.pdf_page)
    eta = "?" if event.estimated_remaining_sec is None else _format_duration(event.estimated_remaining_sec)
    return (
        f"page {page} | {event.event} | eta {eta} | "
        f"hit {event.cache_hit_count} miss {event.cache_miss_count}"
    )


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def default_ocr_log_mode() -> OcrLogMode:
    """실행 환경에 맞는 기본 CLI log mode를 고른다."""

    return "rich" if sys.stderr.isatty() else "plain"
