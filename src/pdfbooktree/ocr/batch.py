"""디렉터리 단위 OCR overlay batch 실행을 조립한다."""

from __future__ import annotations

import csv
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

import fitz

from pdfbooktree.ocr.builder import OcrOverlayBuilder
from pdfbooktree.ocr.config import OcrOverlayConfig
from pdfbooktree.ocr.logger import (
    BatchOcrProgress,
    CompositeOcrLogger,
    JsonFileOcrLogger,
    NullBatchOcrProgress,
    OcrBatchPreparationProgress,
    OcrLogger,
    OcrLogMode,
    build_batch_ocr_progress,
)
from pdfbooktree.pdf.bookmarks import (
    extract_existing_bookmarks,
    has_meaningful_bookmark,
)
from pdfbooktree.pdf.scan_classification import classify_scan
from pdfbooktree.pdf.scan_signals import DEFAULT_MAX_SAMPLE_PAGES
from pdfbooktree.utils.jsonio import to_jsonable, write_json
from pdfbooktree.utils.pdf_discovery import discover_pdfs

OcrBatchStatus = Literal["processed", "dry_run", "skipped", "failed"]

CSV_FIELDS = [
    "relative_path",
    "status",
    "is_ocr_overwrite_target",
    "target_reject_reason",
    "input_pdf",
    "output_pdf",
    "artifact_dir",
    "page_count",
    "processed_page_count",
    "cache_hit_count",
    "cache_miss_count",
    "error",
    "mupdf_warning_count",
    "mupdf_warnings",
    "elapsed_sec",
]


@dataclass(frozen=True)
class OcrOverlayBatchConfig:
    """디렉터리 단위 OCR overlay 실행 설정이다."""

    input_dir: Path | str
    output_dir: Path | str
    recursive: bool = False
    dry_run: bool = False
    force: bool = False
    confirm_bookmark_ocr_overwrite: bool = False
    engine: str = "upstage"
    engine_options: dict[str, object] | None = None
    render_dpi: int = 300
    min_page_count: int = 1
    max_sample_pages: int = DEFAULT_MAX_SAMPLE_PAGES
    stats_word_level: bool = False
    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """최소 page 수가 public Python interface에서도 유효한지 확인한다."""

        if (
            isinstance(self.min_page_count, bool)
            or not isinstance(self.min_page_count, int)
            or self.min_page_count < 1
        ):
            raise ValueError("min_page_count는 1 이상의 정수여야 한다.")


@dataclass(frozen=True)
class OcrOverlayBatchFileResult:
    """PDF 1개의 OCR overlay batch 처리 결과다."""

    relative_path: str
    status: OcrBatchStatus
    is_ocr_overwrite_target: bool
    target_reject_reason: str
    input_pdf: Path
    output_pdf: Path | None
    artifact_dir: Path | None
    page_count: int = 0
    processed_page_count: int = 0
    cache_hit_count: int = 0
    cache_miss_count: int = 0
    error: str | None = None
    mupdf_warnings: tuple[str, ...] = ()
    elapsed_sec: float = 0.0


@dataclass(frozen=True)
class OcrOverlayBatchResult:
    """디렉터리 단위 OCR overlay batch 요약이다."""

    total_pdf_count: int
    target_count: int
    processed_count: int
    dry_run_count: int
    skipped_count: int
    failed_count: int
    elapsed_sec: float
    report_csv_path: Path
    detail_jsonl_path: Path
    summary_path: Path
    results: list[OcrOverlayBatchFileResult]
    target_page_count: int = 0
    will_process_count: int = 0
    will_process_page_count: int = 0
    mupdf_warning_pdf_count: int = 0
    mupdf_warning_count: int = 0
    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()
    excluded_output_subtree: Path | None = None


@dataclass(frozen=True)
class _Classification:
    """batch 실행 전 미리 판정해 둔 PDF 1개의 target/처리 여부다.

    OCR을 실제로 돌릴 page 수 합을 시작 전에 알아야 batch 전체 progress bar의
    남은 시간을 book 개수가 아니라 page 개수 기준으로 추정할 수 있다(요청 사항).
    그래서 classify_scan/bookmark 판정을 main loop보다 먼저 한 번에 끝낸다.
    """

    pdf_path: Path
    relative_path: str
    output_pdf: Path
    artifact_dir: Path
    page_count: int
    is_target: bool
    target_reject_reason: str
    will_process: bool
    is_scanned: bool = False
    has_meaningful_bookmark: bool = False
    meets_min_page_count: bool = False
    mupdf_warnings: tuple[str, ...] = ()
    error: str | None = None


class OcrOverlayBatchRunner:
    """디렉터리 아래 target PDF에 OCR overlay를 순차 적용한다."""

    def __init__(
        self,
        config: OcrOverlayBatchConfig,
        *,
        log_mode: OcrLogMode = "none",
        enable_log_file: bool = True,
        command: str = "ocr-overlay-batch",
    ) -> None:
        self.config = config
        self.input_dir = Path(config.input_dir)
        self.output_dir = Path(config.output_dir)
        self.output_pdf_root = self.output_dir / "pdfs"
        self.artifact_root = self.output_dir / "artifacts"
        self.log_mode = log_mode
        self.enable_log_file = enable_log_file
        self.command = command

    def run(self) -> OcrOverlayBatchResult:
        """PDF를 찾아 target만 OCR overlay하고 report를 저장한다."""

        started_at = time.monotonic()
        preparation = OcrBatchPreparationProgress(self.log_mode, command=self.command)
        try:
            preparation.search_started(self.input_dir, self.config.recursive)
            discovery = discover_pdfs(
                self.input_dir,
                self.output_dir,
                recursive=self.config.recursive,
                include_globs=self.config.include_globs,
                exclude_globs=self.config.exclude_globs,
            )
            pdf_paths = list(discovery.paths)
            preparation.search_completed(len(pdf_paths))
            preparation.classification_started(len(pdf_paths))
            classifications: list[_Classification] = []
            running_target_count = 0
            running_target_page_count = 0
            running_error_count = 0
            for index, pdf_path in enumerate(pdf_paths, start=1):
                classification = self._classify(pdf_path)
                classifications.append(classification)
                if classification.is_target:
                    running_target_count += 1
                    running_target_page_count += classification.page_count
                if classification.error is not None:
                    running_error_count += 1
                preparation.note_classified(
                    completed_pdf_count=index,
                    total_pdf_count=len(pdf_paths),
                    target_count=running_target_count,
                    target_page_count=running_target_page_count,
                    error_count=running_error_count,
                )

            total_pages = sum(c.page_count for c in classifications if c.will_process)
            total_books = sum(1 for c in classifications if c.will_process)
            existing_output_count = sum(
                1
                for c in classifications
                if c.is_target and c.output_pdf.exists() and not self.config.force
            )
            preparation.classification_completed(
                {
                    "total_pdf_count": len(classifications),
                    "page_count_eligible_count": sum(
                        1 for c in classifications if c.meets_min_page_count
                    ),
                    "scanned_count": sum(1 for c in classifications if c.is_scanned),
                    "target_count": running_target_count,
                    "target_page_count": running_target_page_count,
                    "will_process_count": total_books,
                    "will_process_page_count": total_pages,
                    "existing_output_count": existing_output_count,
                    "classification_error_count": running_error_count,
                    "mupdf_warning_pdf_count": sum(
                        1 for c in classifications if c.mupdf_warnings
                    ),
                    "mupdf_warning_count": sum(
                        len(c.mupdf_warnings) for c in classifications
                    ),
                    "dry_run": self.config.dry_run,
                    "min_page_count": self.config.min_page_count,
                }
            )
        except Exception:
            preparation.close()
            raise

        progress: BatchOcrProgress = (
            build_batch_ocr_progress(
                self.log_mode, total_pages, total_books, command=self.command
            )
            if total_books
            else NullBatchOcrProgress()
        )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        report_csv_path = self.output_dir / "ocr_overlay_batch_report.csv"
        detail_jsonl_path = self.output_dir / "ocr_overlay_batch_detail.jsonl"
        summary_path = self.output_dir / "ocr_overlay_batch_summary.json"

        results: list[OcrOverlayBatchFileResult] = []
        try:
            with report_csv_path.open(
                "w", encoding="utf-8-sig", newline=""
            ) as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
                writer.writeheader()
                with detail_jsonl_path.open("w", encoding="utf-8") as detail_file:
                    book_index = 0
                    for classification in classifications:
                        if classification.will_process:
                            book_index += 1
                        result = self._process_one(classification, progress, book_index)
                        results.append(result)
                        writer.writerow(_to_csv_row(result))
                        csv_file.flush()
                        detail_file.write(
                            json.dumps(to_jsonable(result), ensure_ascii=False) + "\n"
                        )
                        detail_file.flush()
        finally:
            progress.close()

        batch_result = OcrOverlayBatchResult(
            total_pdf_count=len(results),
            target_count=sum(1 for result in results if result.is_ocr_overwrite_target),
            processed_count=sum(
                1 for result in results if result.status == "processed"
            ),
            dry_run_count=sum(1 for result in results if result.status == "dry_run"),
            skipped_count=sum(1 for result in results if result.status == "skipped"),
            failed_count=sum(1 for result in results if result.status == "failed"),
            elapsed_sec=time.monotonic() - started_at,
            report_csv_path=report_csv_path,
            detail_jsonl_path=detail_jsonl_path,
            summary_path=summary_path,
            results=results,
            target_page_count=sum(
                result.page_count
                for result in results
                if result.is_ocr_overwrite_target
            ),
            will_process_count=total_books,
            will_process_page_count=total_pages,
            mupdf_warning_pdf_count=sum(
                1 for result in results if result.mupdf_warnings
            ),
            mupdf_warning_count=sum(len(result.mupdf_warnings) for result in results),
            include_globs=discovery.include_globs,
            exclude_globs=discovery.exclude_globs,
            excluded_output_subtree=discovery.excluded_output_subtree,
        )
        write_json(summary_path, _summary_dict(batch_result))
        preparation.mupdf_warnings_completed(
            warning_pdf_count=batch_result.mupdf_warning_pdf_count,
            warning_count=batch_result.mupdf_warning_count,
            detail_jsonl_path=detail_jsonl_path,
        )
        preparation.close()
        return batch_result

    def _classify(self, pdf_path: Path) -> _Classification:
        relative_path = pdf_path.relative_to(self.input_dir).as_posix()
        output_pdf = self.output_pdf_root / relative_path
        artifact_dir = self.artifact_root / Path(relative_path).with_suffix("")
        mupdf_warnings: list[str] = []
        try:
            with _capture_mupdf_warnings(mupdf_warnings):
                scan = classify_scan(pdf_path, self.config.max_sample_pages)
                bookmarks = extract_existing_bookmarks(pdf_path)
                meaningful = has_meaningful_bookmark(bookmarks)
                meets_min_page_count = scan.page_count >= self.config.min_page_count
                is_target = scan.is_scanned and not meaningful and meets_min_page_count
                target_reject_reason = _target_reject_reason(
                    scan.reject_reasons,
                    meaningful,
                    page_count=scan.page_count,
                    min_page_count=self.config.min_page_count,
                )
                will_process = (
                    is_target
                    and not self.config.dry_run
                    and not (output_pdf.exists() and not self.config.force)
                )
            return _Classification(
                pdf_path=pdf_path,
                relative_path=relative_path,
                output_pdf=output_pdf,
                artifact_dir=artifact_dir,
                page_count=scan.page_count,
                is_target=is_target,
                target_reject_reason=target_reject_reason,
                will_process=will_process,
                is_scanned=scan.is_scanned,
                has_meaningful_bookmark=meaningful,
                meets_min_page_count=meets_min_page_count,
                mupdf_warnings=tuple(mupdf_warnings),
            )
        except Exception as exc:  # noqa: BLE001 - 분류 실패도 개별 실패로 남기고 계속 진행한다.
            return _Classification(
                pdf_path=pdf_path,
                relative_path=relative_path,
                output_pdf=output_pdf,
                artifact_dir=artifact_dir,
                page_count=0,
                is_target=False,
                target_reject_reason="",
                will_process=False,
                mupdf_warnings=tuple(mupdf_warnings),
                error=str(exc),
            )

    def _process_one(
        self,
        classification: _Classification,
        progress: BatchOcrProgress,
        book_index: int,
    ) -> OcrOverlayBatchFileResult:
        started_at = time.monotonic()
        relative_path = classification.relative_path
        output_pdf = classification.output_pdf
        artifact_dir = classification.artifact_dir

        if classification.error is not None:
            progress.note_skip()
            return OcrOverlayBatchFileResult(
                relative_path=relative_path,
                status="failed",
                is_ocr_overwrite_target=False,
                target_reject_reason="",
                input_pdf=classification.pdf_path,
                output_pdf=output_pdf,
                artifact_dir=artifact_dir,
                error=classification.error,
                mupdf_warnings=classification.mupdf_warnings,
                elapsed_sec=time.monotonic() - started_at,
            )

        if not classification.is_target:
            progress.note_skip()
            return OcrOverlayBatchFileResult(
                relative_path=relative_path,
                status="skipped",
                is_ocr_overwrite_target=False,
                target_reject_reason=classification.target_reject_reason,
                input_pdf=classification.pdf_path,
                output_pdf=output_pdf,
                artifact_dir=artifact_dir,
                page_count=classification.page_count,
                mupdf_warnings=classification.mupdf_warnings,
                elapsed_sec=time.monotonic() - started_at,
            )

        if self.config.dry_run:
            progress.note_skip()
            return OcrOverlayBatchFileResult(
                relative_path=relative_path,
                status="dry_run",
                is_ocr_overwrite_target=True,
                target_reject_reason="",
                input_pdf=classification.pdf_path,
                output_pdf=output_pdf,
                artifact_dir=artifact_dir,
                page_count=classification.page_count,
                mupdf_warnings=classification.mupdf_warnings,
                elapsed_sec=time.monotonic() - started_at,
            )

        if not classification.will_process:
            progress.note_skip()
            return OcrOverlayBatchFileResult(
                relative_path=relative_path,
                status="skipped",
                is_ocr_overwrite_target=True,
                target_reject_reason="output_exists",
                input_pdf=classification.pdf_path,
                output_pdf=output_pdf,
                artifact_dir=artifact_dir,
                page_count=classification.page_count,
                mupdf_warnings=classification.mupdf_warnings,
                elapsed_sec=time.monotonic() - started_at,
            )

        processing_warnings: list[str] = []
        try:
            config = OcrOverlayConfig(
                input_pdf=classification.pdf_path,
                output_pdf=output_pdf,
                output_dir=artifact_dir,
                engine=self.config.engine,
                engine_options=self.config.engine_options or {},
                render_dpi=self.config.render_dpi,
                force=self.config.force,
                confirm_bookmark_ocr_overwrite=self.config.confirm_bookmark_ocr_overwrite,
                stats_word_level=self.config.stats_word_level,
            )
            display_logger = progress.logger_for_book(
                relative_path, classification.page_count, book_index
            )
            logger: OcrLogger = display_logger
            if self.enable_log_file:
                logger = CompositeOcrLogger(
                    [display_logger, JsonFileOcrLogger(artifact_dir)]
                )
            with _capture_mupdf_warnings(processing_warnings):
                overlay = OcrOverlayBuilder(config, logger=logger).run()
            progress.note_book_done(
                classification.page_count, len(overlay.processed_pages)
            )
            return OcrOverlayBatchFileResult(
                relative_path=relative_path,
                status="processed",
                is_ocr_overwrite_target=True,
                target_reject_reason="",
                input_pdf=classification.pdf_path,
                output_pdf=overlay.output_pdf,
                artifact_dir=overlay.output_dir,
                page_count=overlay.page_count,
                processed_page_count=len(overlay.processed_pages),
                cache_hit_count=overlay.cache_hit_count,
                cache_miss_count=overlay.cache_miss_count,
                mupdf_warnings=(
                    classification.mupdf_warnings + tuple(processing_warnings)
                ),
                elapsed_sec=time.monotonic() - started_at,
            )
        except Exception as exc:  # noqa: BLE001 - 파일별 실패를 report에 남기고 계속 진행한다.
            progress.note_book_done(classification.page_count, 0)
            return OcrOverlayBatchFileResult(
                relative_path=relative_path,
                status="failed",
                is_ocr_overwrite_target=True,
                target_reject_reason="",
                input_pdf=classification.pdf_path,
                output_pdf=output_pdf,
                artifact_dir=artifact_dir,
                error=str(exc),
                mupdf_warnings=(
                    classification.mupdf_warnings + tuple(processing_warnings)
                ),
                elapsed_sec=time.monotonic() - started_at,
            )


@contextmanager
def _capture_mupdf_warnings(collected: list[str]) -> Iterator[None]:
    """MuPDF raw stderr를 막고 현재 PDF 작업의 복구 경고를 수집한다."""

    previous_display = bool(fitz.TOOLS.mupdf_display_warnings())
    fitz.TOOLS.mupdf_display_warnings(False)
    fitz.TOOLS.reset_mupdf_warnings()
    try:
        yield
    finally:
        try:
            warning_text = fitz.TOOLS.mupdf_warnings()
            collected.extend(
                line.strip() for line in warning_text.splitlines() if line.strip()
            )
        finally:
            fitz.TOOLS.mupdf_display_warnings(previous_display)


def _target_reject_reason(
    reject_reasons: tuple[str, ...],
    meaningful: bool,
    *,
    page_count: int,
    min_page_count: int,
) -> str:
    if reject_reasons:
        return "not_scanned: " + " | ".join(reject_reasons)
    if page_count < min_page_count:
        return (
            "below_min_page_count: "
            f"page_count={page_count} < min_page_count={min_page_count}"
        )
    if meaningful:
        return "has_meaningful_bookmark"
    return ""


def _summary_dict(batch_result: OcrOverlayBatchResult) -> dict[str, object]:
    return {
        "total_pdf_count": batch_result.total_pdf_count,
        "target_count": batch_result.target_count,
        "target_page_count": batch_result.target_page_count,
        "will_process_count": batch_result.will_process_count,
        "will_process_page_count": batch_result.will_process_page_count,
        "processed_count": batch_result.processed_count,
        "dry_run_count": batch_result.dry_run_count,
        "skipped_count": batch_result.skipped_count,
        "failed_count": batch_result.failed_count,
        "mupdf_warning_pdf_count": batch_result.mupdf_warning_pdf_count,
        "mupdf_warning_count": batch_result.mupdf_warning_count,
        "include_globs": list(batch_result.include_globs),
        "exclude_globs": list(batch_result.exclude_globs),
        "excluded_output_subtree": batch_result.excluded_output_subtree,
        "elapsed_sec": batch_result.elapsed_sec,
        "report_csv_path": batch_result.report_csv_path,
        "detail_jsonl_path": batch_result.detail_jsonl_path,
    }


def _to_csv_row(result: OcrOverlayBatchFileResult) -> dict[str, object]:
    return {
        "relative_path": result.relative_path,
        "status": result.status,
        "is_ocr_overwrite_target": result.is_ocr_overwrite_target,
        "target_reject_reason": result.target_reject_reason,
        "input_pdf": result.input_pdf,
        "output_pdf": result.output_pdf or "",
        "artifact_dir": result.artifact_dir or "",
        "page_count": result.page_count,
        "processed_page_count": result.processed_page_count,
        "cache_hit_count": result.cache_hit_count,
        "cache_miss_count": result.cache_miss_count,
        "error": result.error or "",
        "mupdf_warning_count": len(result.mupdf_warnings),
        "mupdf_warnings": " | ".join(result.mupdf_warnings),
        "elapsed_sec": f"{result.elapsed_sec:.4f}",
    }
