"""단일 PDF 처리 파이프라인을 조립한다."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.config import ProcessingConfig
from pdfbooktree.models import ConfidenceSummary, ProcessingResult
from pdfbooktree.output.intermediates import write_intermediate
from pdfbooktree.output.markdown import plan_markdown_dir_path
from pdfbooktree.output.pdf_writer import plan_output_pdf_path
from pdfbooktree.output.report import write_processing_report
from pdfbooktree.pdf.bookmarks import build_skip_reason, extract_existing_bookmarks
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.toc.detect import detect_toc_pages
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.toc.parse import parse_toc_items


class Processor:
    """단일 PDF를 bookmark/Markdown 생성 대상으로 처리한다."""

    def __init__(
        self,
        input_pdf: Path | str,
        output_dir: Path | str,
        config: ProcessingConfig | None = None,
    ) -> None:
        self.input_pdf = Path(input_pdf)
        self.output_dir = Path(output_dir)
        self.config = config or ProcessingConfig()

    def run(self) -> ProcessingResult:
        """현재 scaffold가 지원하는 단계까지 실행하고 결과를 반환한다."""

        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_pdf = plan_output_pdf_path(self.input_pdf, self.output_dir)
        output_markdown_dir = plan_markdown_dir_path(self.input_pdf, self.output_dir)

        bookmarks = extract_existing_bookmarks(self.input_pdf)
        skip_reason = (
            build_skip_reason(bookmarks)
            if self.config.skip_existing_bookmarks
            else None
        )
        if skip_reason:
            return self._finalize(
                ProcessingResult(
                    status="skipped",
                    input_pdf=self.input_pdf,
                    output_pdf=None,
                    output_markdown_dir=None,
                    warnings=[skip_reason],
                )
            )

        with fitz.open(self.input_pdf) as document:
            total_pages = document.page_count

        pages = extract_page_texts(
            self.input_pdf,
            max_pages=self.config.max_toc_search_pages,
        )
        features = calculate_page_features(pages, total_pages)
        toc_detection = detect_toc_pages(features)
        toc_items = parse_toc_items(pages, toc_detection.pages)

        if self.config.write_intermediates:
            write_intermediate(self.output_dir, "toc_page_candidates", toc_detection)
            write_intermediate(self.output_dir, "toc_raw", toc_items)

        warnings = [
            "현재 scaffold는 offset 추정, heading alignment, PDF bookmark 삽입, Markdown export를 아직 지원하지 않는다."
        ]
        if not toc_detection.pages:
            warnings.append("TOC page 후보를 찾지 못했다.")
        if not toc_items:
            warnings.append("TOC item을 파싱하지 못했다.")

        return self._finalize(
            ProcessingResult(
                status="failed",
                input_pdf=self.input_pdf,
                output_pdf=output_pdf,
                output_markdown_dir=output_markdown_dir,
                toc_pages=toc_detection.pages,
                bookmark_count=0,
                confidence_summary=ConfidenceSummary(
                    toc_detection=toc_detection.confidence,
                    offset=None,
                    alignment=None,
                ),
                warnings=warnings,
            )
        )

    def _finalize(self, result: ProcessingResult) -> ProcessingResult:
        report_path = write_processing_report(result, self.output_dir)
        return ProcessingResult(
            status=result.status,
            input_pdf=result.input_pdf,
            output_pdf=result.output_pdf,
            output_markdown_dir=result.output_markdown_dir,
            toc_pages=result.toc_pages,
            bookmark_count=result.bookmark_count,
            confidence_summary=result.confidence_summary,
            warnings=result.warnings,
            report_path=report_path,
        )
