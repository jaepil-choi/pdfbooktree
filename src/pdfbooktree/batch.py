"""디렉터리 단위 PDF batch 처리를 조립한다."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from pdfbooktree.alignment.offset import OffsetEstimationError
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.models import BatchResult, ProcessingResult
from pdfbooktree.output.report import write_processing_report
from pdfbooktree.processor import Processor

logger = logging.getLogger(__name__)


class BatchProcessor:
    """입력 디렉터리의 PDF들을 순회하며 단일 Processor를 실행한다."""

    def __init__(
        self,
        input_dir: Path | str,
        output_dir: Path | str,
        config: ProcessingConfig | None = None,
        recursive: bool = False,
    ) -> None:
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.config = config or ProcessingConfig()
        self.recursive = recursive

    def run(self) -> BatchResult:
        pdf_paths = self._find_pdfs()
        # 한 PDF가 실패해도 batch 전체를 중단하지 않는다. offset이 clean하지 않은
        # PDF는 그 PDF만 failed로 기록하고 로그를 남긴 뒤 다음 PDF로 넘어간다.
        results = [self._run_one(path) for path in pdf_paths]
        return BatchResult(
            total_pdf_count=len(pdf_paths),
            processed_count=sum(
                1 for result in results if result.status == "processed"
            ),
            skipped_existing_bookmark_count=sum(
                1 for result in results if result.status == "skipped"
            ),
            failed_count=sum(1 for result in results if result.status == "failed"),
            bookmark_reference_candidate_count=sum(
                1 for result in results if result.status == "skipped"
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

    def _run_one(self, path: Path) -> ProcessingResult:
        """단일 PDF를 처리하되 offset 실패는 batch를 멈추지 않고 failed로 기록한다."""

        output_dir = self.output_dir / path.stem
        try:
            return Processor(path, output_dir, self.config).run()
        except OffsetEstimationError as error:
            logger.warning(
                "offset 추정 실패로 PDF를 failed 처리하고 다음으로 넘어간다: %s (%s)",
                path,
                error,
            )
            return self._record_offset_failure(path, output_dir, error)

    def _record_offset_failure(
        self, path: Path, output_dir: Path, error: OffsetEstimationError
    ) -> ProcessingResult:
        """offset 실패한 PDF의 failed 결과를 만들고 report로 남긴다."""

        output_dir.mkdir(parents=True, exist_ok=True)
        result = ProcessingResult(
            status="failed",
            input_pdf=path,
            warnings=[f"offset 추정 실패로 처리를 중단했다: {error}"],
        )
        report_path = write_processing_report(result, output_dir)
        return replace(result, report_path=report_path)

    def _find_pdfs(self) -> list[Path]:
        pattern = "**/*.pdf" if self.recursive else "*.pdf"
        return sorted(self.input_dir.glob(pattern))
