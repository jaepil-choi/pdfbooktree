"""디렉터리 단위 PDF batch 처리를 조립한다."""

from __future__ import annotations

import logging
import time
from dataclasses import fields
from pathlib import Path

from pdfbooktree.batch_logger import BatchLogEvent, BatchLogger, NullBatchLogger
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.config_io import (
    ResolvedConfig,
    processing_config_to_data,
)
from pdfbooktree.models import BatchItemResult, BatchResult, ProcessingResult
from pdfbooktree.processor import Processor
from pdfbooktree.run import RunContext, create_run_context
from pdfbooktree.utils.hashing import stable_json_hash

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
    ) -> None:
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.resolved = _resolve_batch_config(config)
        self.config = self.resolved.config
        self.recursive = recursive
        self.log = log or NullBatchLogger()

    def run(self) -> BatchResult:
        """PDF batch 처리를 실행한다."""

        pdf_paths = self._find_pdfs()
        started_at = time.perf_counter()
        results: list[BatchItemResult] = []
        processed_count = 0
        failed_count = 0
        try:
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
        finally:
            self.log.close()
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

    def _find_pdfs(self) -> list[Path]:
        pattern = "**/*.pdf" if self.recursive else "*.pdf"
        return sorted(self.input_dir.glob(pattern))


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
