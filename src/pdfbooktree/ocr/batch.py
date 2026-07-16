"""디렉터리 단위 OCR overlay batch 실행을 조립한다."""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pdfbooktree.ocr.builder import OcrOverlayBuilder
from pdfbooktree.ocr.config import OcrOverlayConfig
from pdfbooktree.ocr.logger import (
    BatchOcrProgress,
    CompositeOcrLogger,
    JsonFileOcrLogger,
    NullBatchOcrProgress,
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
    max_sample_pages: int = DEFAULT_MAX_SAMPLE_PAGES
    stats_word_level: bool = False


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
        pdf_paths = self._find_pdfs()
        classifications = [self._classify(pdf_path) for pdf_path in pdf_paths]

        total_pages = sum(c.page_count for c in classifications if c.will_process)
        total_books = sum(1 for c in classifications if c.will_process)
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
        )
        write_json(summary_path, _summary_dict(batch_result))
        return batch_result

    def _classify(self, pdf_path: Path) -> _Classification:
        relative_path = str(pdf_path.relative_to(self.input_dir))
        output_pdf = self.output_pdf_root / relative_path
        artifact_dir = self.artifact_root / Path(relative_path).with_suffix("")
        try:
            scan = classify_scan(pdf_path, self.config.max_sample_pages)
            bookmarks = extract_existing_bookmarks(pdf_path)
            meaningful = has_meaningful_bookmark(bookmarks)
            is_target = scan.is_scanned and not meaningful
            target_reject_reason = _target_reject_reason(
                scan.reject_reasons, meaningful
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
                elapsed_sec=time.monotonic() - started_at,
            )

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
                elapsed_sec=time.monotonic() - started_at,
            )

    def _find_pdfs(self) -> list[Path]:
        pattern = "**/*.pdf" if self.config.recursive else "*.pdf"
        return sorted(self.input_dir.glob(pattern))


def _target_reject_reason(reject_reasons: tuple[str, ...], meaningful: bool) -> str:
    if reject_reasons:
        return "not_scanned: " + " | ".join(reject_reasons)
    if meaningful:
        return "has_meaningful_bookmark"
    return ""


def _summary_dict(batch_result: OcrOverlayBatchResult) -> dict[str, object]:
    return {
        "total_pdf_count": batch_result.total_pdf_count,
        "target_count": batch_result.target_count,
        "processed_count": batch_result.processed_count,
        "dry_run_count": batch_result.dry_run_count,
        "skipped_count": batch_result.skipped_count,
        "failed_count": batch_result.failed_count,
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
        "elapsed_sec": f"{result.elapsed_sec:.4f}",
    }
