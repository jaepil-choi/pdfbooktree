"""디렉터리 단위 PDF batch 처리를 조립한다."""

from __future__ import annotations

import logging
import time
from dataclasses import fields
from pathlib import Path

from pdfbooktree.batch_logger import BatchLogEvent, BatchLogger, NullBatchLogger
from pdfbooktree.batch_run import BatchRunContext, create_batch_run_context
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.config_io import (
    ResolvedConfig,
    processing_config_to_data,
)
from pdfbooktree.models import BatchItemResult, BatchResult, ProcessingResult
from pdfbooktree.processor import Processor
from pdfbooktree.run import RunContext, create_run_context
from pdfbooktree.utils.hashing import stable_json_hash
from pdfbooktree.utils.pdf_discovery import discover_pdfs

logger = logging.getLogger(__name__)


class BatchProcessor:
    """입력 디렉터리의 PDF들을 순회하며 단일 Processor를 실행한다."""

    def __init__(
        self,
        input_dir: Path | str,
        output_dir: Path | str,
        config: ProcessingConfig | ResolvedConfig | None = None,
        recursive: bool = False,
        log: BatchLogger | None = None,
        *,
        include_globs: tuple[str, ...] = (),
        exclude_globs: tuple[str, ...] = (),
    ) -> None:
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.resolved = _resolve_batch_config(config)
        self.config = self.resolved.config
        self.recursive = recursive
        self.include_globs = include_globs
        self.exclude_globs = exclude_globs
        self.log = log or NullBatchLogger()

    def run(self) -> BatchResult:
        """PDF batch 처리를 실행한다."""

        pdf_paths: list[Path] = []
        batch_run: BatchRunContext | None = None
        results: list[BatchItemResult] = []
        logger_closed = False
        started_at = time.perf_counter()
        processed_count = 0
        failed_count = 0
        try:
            discovery = discover_pdfs(
                self.input_dir,
                self.output_dir,
                recursive=self.recursive,
                include_globs=self.include_globs,
                exclude_globs=self.exclude_globs,
            )
            pdf_paths = list(discovery.paths)
            batch_run = create_batch_run_context(
                self.input_dir,
                self.output_dir,
                self.resolved,
                recursive=self.recursive,
                pdf_paths=pdf_paths,
                include_globs=discovery.include_globs,
                exclude_globs=discovery.exclude_globs,
                excluded_output_subtree=discovery.excluded_output_subtree,
            )
            batch_run.start()
            for path in pdf_paths:
                result = self._run_one(path)
                results.append(result)
                if result.status == "failed":
                    failed_count += 1
                else:
                    processed_count += 1
                self.log.emit(
                    BatchLogEvent(
                        event="failed" if result.status == "failed" else "processed",
                        level="error" if result.status == "failed" else "info",
                        input_pdf=path,
                        completed_count=len(results),
                        total_count=len(pdf_paths),
                        processed_count=processed_count,
                        failed_count=failed_count,
                        elapsed_sec=time.perf_counter() - started_at,
                        message=(
                            result.warnings[0] if result.warnings else result.status
                        ),
                    )
                )
            self.log.close()
            logger_closed = True
            batch_result = self._build_result(pdf_paths, results, batch_run)
            batch_run.complete(batch_result)
            return batch_result
        except Exception as error:
            if batch_run is not None:
                partial_result = self._build_result(pdf_paths, results, batch_run)
                try:
                    batch_run.fail(error, partial_result)
                except Exception:  # noqa: BLE001 - 원래 command 오류를 보존해야 한다.
                    logger.exception("batch manifest 실패 기록 실패")
            raise
        finally:
            if not logger_closed:
                try:
                    self.log.close()
                except Exception:  # noqa: BLE001 - 원래 command 오류를 보존해야 한다.
                    logger.exception("batch logger 종료 실패")

    def _build_result(
        self,
        pdf_paths: list[Path],
        results: list[BatchItemResult],
        batch_run: BatchRunContext,
    ) -> BatchResult:
        """완료된 item 목록과 batch run identity를 하나의 결과로 묶는다."""

        return BatchResult(
            total_pdf_count=len(pdf_paths),
            processed_count=sum(
                1 for result in results if result.status == "processed"
            ),
            skipped_existing_bookmark_count=sum(
                1
                for result in results
                if result.output_pdf is None and result.status == "processed"
            ),
            failed_count=sum(1 for result in results if result.status == "failed"),
            bookmark_reference_candidate_count=sum(
                1
                for result in results
                if result.output_pdf is None and result.status == "processed"
            ),
            created_bookmarked_pdf_paths=[
                result.output_pdf
                for result in results
                if result.status == "processed" and result.output_pdf is not None
            ],
            created_markdown_dirs=[
                result.output_markdown_dir
                for result in results
                if result.status == "processed"
                and result.output_markdown_dir is not None
            ],
            results=results,
            batch_run_id=batch_run.manifest.batch_run_id,
            batch_run_dir=batch_run.batch_run_dir,
            batch_manifest_path=batch_run.manifest_path,
            config_hash=batch_run.manifest.config_hash,
        )

    def _run_one(self, path: Path) -> BatchItemResult:
        run: RunContext | None = None
        try:
            run = create_run_context(
                path,
                self.output_dir,
                self.resolved,
                allow_unreadable_input=True,
            )
            run.start()
            result = Processor(path, run.run_dir, self.config).run()
            run.complete(result)
            return _batch_item_result(result, run)
        except Exception as error:  # noqa: BLE001 - batch는 파일별 실패를 report에 남겨야 한다.
            logger.exception("PDF 처리 실패: %s", path)
            if run is not None:
                try:
                    run.fail(error)
                except Exception:  # noqa: BLE001 - 원래 item 오류를 보존해야 한다.
                    logger.exception("batch run manifest 실패 기록 실패: %s", path)
            result = ProcessingResult(
                status="failed",
                input_pdf=path,
                warnings=[str(error)],
            )
            return _batch_item_result(result, run)


def _resolve_batch_config(
    config: ProcessingConfig | ResolvedConfig | None,
) -> ResolvedConfig:
    """CLI resolved config 또는 Python API config를 run identity로 정규화한다."""

    if isinstance(config, ResolvedConfig):
        return config
    processing_config = config or ProcessingConfig()
    data = processing_config_to_data(processing_config)
    return ResolvedConfig(
        config=processing_config,
        data=data,
        config_hash=stable_json_hash(data),
        sources=({"kind": "python_api"},),
    )


def _batch_item_result(
    result: ProcessingResult,
    run: RunContext | None,
) -> BatchItemResult:
    """기존 ProcessingResult shape에 batch run identity를 덧붙인다."""

    processing_values = {
        field.name: getattr(result, field.name) for field in fields(ProcessingResult)
    }
    if run is None:
        return BatchItemResult(**processing_values)
    return BatchItemResult(
        **processing_values,
        run_id=run.manifest.run_id,
        run_dir=run.run_dir,
        manifest_path=run.manifest_path,
        config_hash=run.manifest.config_hash,
    )
