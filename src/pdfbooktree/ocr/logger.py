"""OCR runtime 로그와 진행 상태를 기록한다."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol, TextIO

from tqdm import tqdm

from pdfbooktree.cli_contract import render_command_event_json
from pdfbooktree.utils.jsonio import to_jsonable


OcrLogLevel = Literal["info", "warning", "error"]
OcrLogMode = Literal["tqdm", "plain", "json", "none"]


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
    """stderr에 한 줄씩 OCR 진행 로그를 출력한다."""

    def emit(self, event: OcrLogEvent) -> None:
        print(format_ocr_log_event(event), file=sys.stderr, flush=True)

    def close(self) -> None:
        return None


class JsonStderrOcrLogger:
    """stderr에 versioned JSONL event를 출력한다."""

    def __init__(self, command: str = "ocr-overlay") -> None:
        self.command = command

    def emit(self, event: OcrLogEvent) -> None:
        payload = _event_to_jsonable(event)
        data = {
            key: value
            for key, value in payload.items()
            if key not in {"event", "level", "message"}
        }
        print(
            render_command_event_json(
                self.command,
                event.event,
                level=event.level,
                message=event.message,
                data=data,
            ),
            file=sys.stderr,
            flush=True,
        )

    def close(self) -> None:
        return None


class TqdmOcrLogger:
    """page 진행 상태만 tqdm progress bar 하나로 보여준다.

    이전 rich 기반 logger는 event(render_start/ocr_call_start/insertable_build_done
    등, page당 6~7개)마다 status 텍스트를 바꿔가며 갱신해서 너무 verbose했다. 이
    logger는 ``completed_pages``가 실제로 늘어난 순간(page_done)에만 bar를
    전진시키고, 나머지 event는 postfix로만 조용히 반영한다.
    """

    def __init__(
        self,
        *,
        total_pages: int | None = None,
        desc: str | None = None,
        position: int = 0,
        leave: bool = True,
        file: TextIO | None = None,
    ) -> None:
        self._file = file or sys.stderr
        self._bar = tqdm(
            total=total_pages,
            desc=desc,
            position=position,
            leave=leave,
            unit="page",
            file=self._file,
        )
        self._completed = 0

    def emit(self, event: OcrLogEvent) -> None:
        if event.total_pages and self._bar.total != event.total_pages:
            self._bar.total = event.total_pages
        advance = event.completed_pages - self._completed
        if advance > 0:
            self._bar.update(advance)
            self._completed = event.completed_pages
        self._bar.set_postfix(
            hit=event.cache_hit_count, miss=event.cache_miss_count, refresh=False
        )
        if event.event == "failed":
            tqdm.write(format_ocr_log_event(event), file=self._file)

    def close(self) -> None:
        self._bar.close()


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


class OcrBatchPreparationProgress:
    """OCR batch의 탐색·분류 단계를 stderr에 관찰 가능하게 표시한다."""

    def __init__(
        self,
        mode: OcrLogMode,
        *,
        command: str = "ocr-overlay-batch",
        file: TextIO | None = None,
    ) -> None:
        self._mode = mode
        self._command = command
        self._file = file or sys.stderr
        self._classification_bar: tqdm | None = None

    def search_started(self, input_dir: Path, recursive: bool) -> None:
        """PDF 탐색 조건을 탐색 전에 출력한다."""

        self._emit(
            "discovery_started",
            f"PDF 탐색 시작: input={input_dir}, recursive={recursive}",
            {"input_dir": input_dir, "recursive": recursive},
        )

    def search_completed(self, total_pdf_count: int) -> None:
        """발견한 PDF 수를 출력한다."""

        self._emit(
            "discovery_completed",
            f"PDF 탐색 완료: {total_pdf_count:,}개 발견",
            {"total_pdf_count": total_pdf_count},
        )

    def classification_started(self, total_pdf_count: int) -> None:
        """분류 progress를 시작한다."""

        self._emit(
            "classification_started",
            f"PDF 분류 시작: {total_pdf_count:,}개",
            {"total_pdf_count": total_pdf_count},
        )
        if self._mode == "tqdm":
            self._classification_bar = tqdm(
                total=total_pdf_count,
                desc="PDF 분류",
                unit="pdf",
                file=self._file,
            )

    def note_classified(
        self,
        *,
        completed_pdf_count: int,
        total_pdf_count: int,
        target_count: int,
        target_page_count: int,
        error_count: int,
    ) -> None:
        """PDF 하나의 분류 완료를 progress에 반영한다."""

        data = {
            "completed_pdf_count": completed_pdf_count,
            "total_pdf_count": total_pdf_count,
            "target_count": target_count,
            "target_page_count": target_page_count,
            "error_count": error_count,
        }
        if self._mode == "tqdm" and self._classification_bar is not None:
            self._classification_bar.set_postfix(
                target=target_count,
                pages=target_page_count,
                errors=error_count,
                refresh=False,
            )
            self._classification_bar.update(1)
        elif self._mode == "json":
            self._emit(
                "classification_progress",
                f"PDF 분류 진행: {completed_pdf_count}/{total_pdf_count}",
                data,
            )

    def classification_completed(self, summary: dict[str, object]) -> None:
        """분류 bar를 닫고 target 요약을 출력한다."""

        if self._classification_bar is not None:
            self._classification_bar.close()
            self._classification_bar = None
        message = (
            "PDF 분류 완료: "
            f"전체={summary['total_pdf_count']:,}권, "
            f"페이지 조건 통과={summary['page_count_eligible_count']:,}권, "
            f"scanned={summary['scanned_count']:,}권, "
            f"OCR 대상={summary['target_count']:,}권/"
            f"{summary['target_page_count']:,}page, "
            f"실행={summary['will_process_count']:,}권/"
            f"{summary['will_process_page_count']:,}page, "
            f"기존 출력={summary['existing_output_count']:,}권, "
            f"분류 실패={summary['classification_error_count']:,}권, "
            f"MuPDF 경고={summary['mupdf_warning_pdf_count']:,}권/"
            f"{summary['mupdf_warning_count']:,}건"
        )
        self._emit("classification_completed", message, summary)

    def mupdf_warnings_completed(
        self,
        *,
        warning_pdf_count: int,
        warning_count: int,
        detail_jsonl_path: Path,
    ) -> None:
        """raw MuPDF stderr 대신 압축된 경고 요약과 상세 경로를 출력한다."""

        if warning_count == 0:
            return
        self._emit(
            "mupdf_warnings_collected",
            (
                f"MuPDF 복구 경고: {warning_pdf_count:,}권에서 "
                f"{warning_count:,}건 감지됨; 상세={detail_jsonl_path}"
            ),
            {
                "warning_pdf_count": warning_pdf_count,
                "warning_count": warning_count,
                "detail_jsonl_path": detail_jsonl_path,
            },
            level="warning",
        )

    def close(self) -> None:
        """열린 분류 bar가 있으면 닫는다."""

        if self._classification_bar is not None:
            self._classification_bar.close()
            self._classification_bar = None

    def _emit(
        self,
        event: str,
        message: str,
        data: object,
        *,
        level: OcrLogLevel = "info",
    ) -> None:
        if self._mode == "none":
            return
        if self._mode == "json":
            print(
                render_command_event_json(
                    self._command,
                    event,
                    level=level,
                    message=message,
                    data=data,
                ),
                file=self._file,
                flush=True,
            )
            return
        if self._mode == "tqdm":
            tqdm.write(message, file=self._file)
            return
        print(message, file=self._file, flush=True)


def build_ocr_logger(
    mode: OcrLogMode,
    output_dir: Path,
    *,
    enable_file: bool = True,
    desc: str | None = None,
    command: str = "ocr-overlay",
) -> OcrLogger:
    """CLI 옵션에 맞는 OCR logger 조합을 만든다."""

    loggers: list[OcrLogger] = []
    if enable_file:
        loggers.append(JsonFileOcrLogger(output_dir))
    if mode == "tqdm":
        loggers.append(TqdmOcrLogger(desc=desc or f"OCR overlay: {output_dir.name}"))
    elif mode == "plain":
        loggers.append(PlainTextOcrLogger())
    elif mode == "json":
        loggers.append(JsonStderrOcrLogger(command=command))
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
    eta = (
        "?"
        if event.estimated_remaining_sec is None
        else _format_duration(event.estimated_remaining_sec)
    )
    return (
        f"[{event.completed_pages}/{event.total_pages}] page={page} "
        f"event={event.event} elapsed={_format_duration(event.elapsed_sec)} "
        f"eta={eta} cache_hit={event.cache_hit_count} cache_miss={event.cache_miss_count} "
        f"{event.message}"
    )


def _event_to_jsonable(event: OcrLogEvent) -> dict[str, object]:
    return to_jsonable(asdict(event))


def _progress_snapshot(payload: dict[str, object]) -> dict[str, object]:
    status = (
        "failed"
        if payload["event"] == "failed"
        else "done"
        if payload["event"] == "done"
        else "running"
    )
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


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def default_ocr_log_mode() -> OcrLogMode:
    """실행 환경에 맞는 기본 CLI log mode를 고른다.

    tqdm은 tty 여부를 스스로 감지해 non-tty에서는 갱신 빈도를 줄인 한 줄
    출력으로 자연스럽게 대체하므로, rich/plain을 tty 여부로 나누던 이전 방식과
    달리 항상 tqdm을 기본값으로 쓸 수 있다.
    """

    return "tqdm"


class BatchOcrProgress(Protocol):
    """OCR overlay batch 전체 진행 상태를 보여주는 progress 조립기 protocol이다."""

    def logger_for_book(self, name: str, page_count: int, book_index: int) -> OcrLogger:
        """지금 처리할 책의 page 단위 표시 logger를 만든다."""

    def note_skip(self) -> None:
        """target이 아니거나 처리하지 않을 책을 건너뛴다."""

    def note_book_done(self, page_count: int, processed_page_count: int) -> None:
        """책 하나의 처리(성공/실패 포함)가 끝났다."""

    def close(self) -> None:
        """progress 표시에 쓴 자원을 정리한다."""


class NullBatchOcrProgress:
    """아무 표시도 하지 않는 batch progress다."""

    def logger_for_book(self, name: str, page_count: int, book_index: int) -> OcrLogger:
        return NullOcrLogger()

    def note_skip(self) -> None:
        return None

    def note_book_done(self, page_count: int, processed_page_count: int) -> None:
        return None

    def close(self) -> None:
        return None


class FlatBatchOcrProgress:
    """책마다 독립된 flat logger(plain/json)를 그대로 쓰는 batch progress다."""

    def __init__(self, mode: OcrLogMode, *, command: str = "ocr-overlay-batch") -> None:
        self._mode = mode
        self._command = command

    def logger_for_book(self, name: str, page_count: int, book_index: int) -> OcrLogger:
        return build_ocr_logger(
            self._mode, Path(name), enable_file=False, command=self._command
        )

    def note_skip(self) -> None:
        return None

    def note_book_done(self, page_count: int, processed_page_count: int) -> None:
        return None

    def close(self) -> None:
        return None


class _BatchBookLoggerAdapter:
    """책 하나의 page 진행을 batch 전체 outer bar에도 함께 반영한다."""

    def __init__(self, inner: OcrLogger, outer_bar: tqdm) -> None:
        self._inner = inner
        self._outer_bar = outer_bar
        self._completed = 0

    def emit(self, event: OcrLogEvent) -> None:
        self._inner.emit(event)
        advance = event.completed_pages - self._completed
        if advance > 0:
            self._outer_bar.update(advance)
            self._completed = event.completed_pages

    def close(self) -> None:
        self._inner.close()


class TqdmBatchOcrProgress:
    """batch 전체 page 진행(outer bar)과 현재 책 진행(inner bar)을 함께 보여준다.

    outer bar의 total은 실제로 OCR을 돌릴 책들의 page 수 합이라, 남은 시간
    추정이 "책 몇 권 남았는가"가 아니라 "전체 page 중 몇 page 남았는가"를
    기준으로 계산된다(요청 사항).
    """

    def __init__(
        self, total_pages: int, total_books: int, *, file: TextIO | None = None
    ) -> None:
        self._total_books = total_books
        self._books_done = 0
        self._file = file
        self._outer = tqdm(
            total=total_pages,
            desc=self._outer_desc(),
            position=0,
            unit="page",
            file=file,
        )

    def logger_for_book(self, name: str, page_count: int, book_index: int) -> OcrLogger:
        inner = TqdmOcrLogger(
            total_pages=page_count,
            desc=f"[{book_index}/{self._total_books}] {name}",
            position=1,
            leave=False,
            file=self._file,
        )
        return _BatchBookLoggerAdapter(inner, self._outer)

    def note_skip(self) -> None:
        # 비대상·기존 출력 항목은 준비 단계 요약에 표시하고 OCR bar와 섞지 않는다.
        return None

    def note_book_done(self, page_count: int, processed_page_count: int) -> None:
        shortfall = max(0, page_count - processed_page_count)
        if shortfall:
            self._outer.update(shortfall)
        self._books_done += 1
        self._outer.set_description(self._outer_desc())

    def close(self) -> None:
        self._outer.close()

    def _outer_desc(self) -> str:
        return f"batch {self._books_done}/{self._total_books} books"


def build_batch_ocr_progress(
    mode: OcrLogMode,
    total_pages: int,
    total_books: int,
    *,
    command: str = "ocr-overlay-batch",
) -> BatchOcrProgress:
    """CLI log mode에 맞는 batch progress 조립기를 만든다."""

    if mode == "tqdm":
        return TqdmBatchOcrProgress(total_pages, total_books)
    if mode == "none":
        return NullBatchOcrProgress()
    if mode in ("plain", "json"):
        return FlatBatchOcrProgress(mode, command=command)
    raise ValueError(f"지원하지 않는 OCR log mode다: {mode}")
