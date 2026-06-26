"""단일 PDF 처리 파이프라인을 조립한다."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.alignment.headings import extract_heading_candidates
from pdfbooktree.alignment.match import align_toc_items
from pdfbooktree.alignment.offset import estimate_page_offset
from pdfbooktree.alignment.ranges import calculate_content_ranges
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.models import (
    ConfidenceSummary,
    HeadingCandidate,
    ProcessingResult,
    TocDetectionResult,
    TocItem,
    TocRangeReview,
)
from pdfbooktree.output.intermediates import write_intermediate
from pdfbooktree.output.markdown import plan_markdown_dir_path
from pdfbooktree.output.pdf_writer import plan_output_pdf_path
from pdfbooktree.output.report import write_processing_report
from pdfbooktree.pdf.bookmarks import build_skip_reason, extract_existing_bookmarks
from pdfbooktree.pdf.text import extract_page_texts, extract_selected_page_texts
from pdfbooktree.toc.detect import detect_toc_pages
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.toc.llm_extract import LlmTocExtractor
from pdfbooktree.toc.llm_range_review import LlmTocRangeReviewer
from pdfbooktree.toc.parse import parse_toc_items


class Processor:
    """단일 PDF를 bookmark/Markdown 생성 대상으로 처리한다."""

    def __init__(
        self,
        input_pdf: Path | str,
        output_dir: Path | str,
        config: ProcessingConfig | None = None,
        *,
        range_reviewer: LlmTocRangeReviewer | None = None,
        item_extractor: LlmTocExtractor | None = None,
    ) -> None:
        self.input_pdf = Path(input_pdf)
        self.output_dir = Path(output_dir)
        self.config = config or ProcessingConfig()
        # LLM 단계는 테스트/재현을 위해 주입할 수 있고, 없으면 use_llm일 때 lazy 생성한다.
        self._range_reviewer = range_reviewer
        self._item_extractor = item_extractor

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

        # LLM 3단계 fallback으로 TOC range를 보정한다(use_llm일 때만).
        range_review = self._review_toc_range(toc_detection, total_pages)
        toc_pages = (
            range_review.pages
            if range_review is not None and range_review.pages
            else toc_detection.pages
        )
        # range review는 offset 추정 전에 끝나므로, offset fast-fail이 나도 근거가
        # 남도록 여기서 먼저 저장한다.
        if self.config.write_intermediates:
            write_intermediate(self.output_dir, "toc_page_candidates", toc_detection)
            if range_review is not None:
                write_intermediate(self.output_dir, "toc_range_review", range_review)

        toc_items = parse_toc_items(pages, toc_pages)
        item_method = "deterministic_regex"
        # 결정적 파서가 0개면(한국어/OCR 목차) LLM item 추출로 fallback한다.
        if not toc_items and self.config.use_llm and toc_pages:
            toc_items = self._extract_items_with_llm(toc_pages)
            item_method = "llm_item_extraction" if toc_items else "none"

        # offset 추정. clean하지 않으면 OffsetEstimationError를 그대로 전파해
        # 중단한다(fallback 없음). 이후 ignore-offset-error 옵션 추가 여지를 둔다.
        offset_estimate = estimate_page_offset(self.input_pdf, self.config.offset)

        # offset으로 각 item의 예상 PDF page를 구하고, 그 주변 window page text만
        # 한 번에 추출해 heading 후보를 만든다(item마다 PDF 재오픈 방지).
        candidates_by_item = self._build_heading_candidates(
            toc_items, offset_estimate.offset, total_pages
        )
        aligned = align_toc_items(toc_items, offset_estimate, candidates_by_item)
        ranges = calculate_content_ranges(aligned, total_pages)

        if self.config.write_intermediates:
            write_intermediate(self.output_dir, "toc_raw", toc_items)
            write_intermediate(self.output_dir, "page_offset", offset_estimate)
            write_intermediate(self.output_dir, "toc_aligned", aligned)
            write_intermediate(self.output_dir, "ranges", ranges)

        alignment_confidence = (
            sum(item.confidence for item in aligned) / len(aligned) if aligned else 0.0
        )

        warnings = [
            "현재 scaffold는 PDF bookmark 삽입과 Markdown export를 아직 지원하지 않는다."
        ]
        if not toc_pages:
            warnings.append("TOC page 후보를 찾지 못했다.")
        if not toc_items:
            warnings.append(f"TOC item을 파싱하지 못했다(method={item_method}).")
        if not ranges:
            warnings.append("content range를 만들지 못했다.")

        return self._finalize(
            ProcessingResult(
                status="failed",
                input_pdf=self.input_pdf,
                output_pdf=output_pdf,
                output_markdown_dir=output_markdown_dir,
                toc_pages=toc_pages,
                bookmark_count=0,
                confidence_summary=ConfidenceSummary(
                    toc_detection=toc_detection.confidence,
                    offset=offset_estimate.confidence,
                    alignment=alignment_confidence,
                ),
                warnings=warnings,
            )
        )

    def _review_toc_range(
        self, toc_detection: TocDetectionResult, total_pages: int
    ) -> TocRangeReview | None:
        """use_llm일 때 3단계 LLM fallback으로 TOC range를 보정한다."""

        if not self.config.use_llm:
            return None
        if self._range_reviewer is None:
            self._range_reviewer = LlmTocRangeReviewer(self.config.llm_range_review)
        return self._range_reviewer.review(self.input_pdf, toc_detection, total_pages)

    def _extract_items_with_llm(self, toc_pages: list[int]) -> list[TocItem]:
        """결정적 파서가 0개를 뽑은 TOC range에서 LLM으로 item을 추출한다."""

        if self._item_extractor is None:
            self._item_extractor = LlmTocExtractor(self.config.llm_extraction)
        return self._item_extractor.extract(self.input_pdf, toc_pages)

    def _build_heading_candidates(
        self,
        toc_items: list[TocItem],
        offset: int | None,
        total_pages: int,
    ) -> dict[int, list[HeadingCandidate]]:
        """item별 예상 PDF page 주변에서 heading 후보를 모은다."""

        if offset is None:
            return {}

        window = self.config.heading_search_window
        estimated_by_index: dict[int, int] = {}
        needed_pages: set[int] = set()
        for index, item in enumerate(toc_items):
            if item.printed_page is None:
                continue
            estimated = item.printed_page + offset
            estimated_by_index[index] = estimated
            for page in range(estimated - window, estimated + window + 1):
                if 1 <= page <= total_pages:
                    needed_pages.add(page)

        if not needed_pages:
            return {}

        heading_pages = extract_selected_page_texts(
            self.input_pdf, sorted(needed_pages)
        )
        return {
            index: extract_heading_candidates(heading_pages, estimated, window)
            for index, estimated in estimated_by_index.items()
        }

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
