"""디렉터리 단위 PDF batch 처리를 조립한다."""

from __future__ import annotations

from pathlib import Path

from pdfbooktree.config import ProcessingConfig
from pdfbooktree.models import BatchResult
from pdfbooktree.processor import Processor


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
        results = [
            Processor(path, self.output_dir / path.stem, self.config).run()
            for path in pdf_paths
        ]
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

    def _find_pdfs(self) -> list[Path]:
        pattern = "**/*.pdf" if self.recursive else "*.pdf"
        return sorted(self.input_dir.glob(pattern))
