"""파이프라인 단계 사이에서 주고받는 데이터 구조를 정의한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


ProcessingStatus = Literal["processed", "skipped", "failed"]


@dataclass(frozen=True)
class PdfPageText:
    """1-based PDF page text와 line 정보를 담는다."""

    pdf_page: int
    text: str
    lines: list[str]
    char_count: int


@dataclass(frozen=True)
class PageFeature:
    """TOC 탐지에 쓰는 objective page feature다."""

    pdf_page: int
    line_count: int
    word_count: int
    mean_line_length: float
    line_length_std: float
    line_final_number_count: int
    line_final_numbers: list[int]
    line_final_number_monotonicity: float | None
    line_final_number_gap_mean: float | None
    line_final_number_gap_median: float | None
    line_final_number_gap_max: int | None
    line_final_number_negative_gap_count: int
    toc_entry_pattern_count: int
    toc_entry_pattern_ratio: float
    chapter_or_part_line_count: int
    page_position: float
    toc_keyword_presence: bool


@dataclass(frozen=True)
class TocDetectionResult:
    """탐지된 TOC page range와 근거를 담는다."""

    pages: list[int]
    start_page: int | None
    end_page: int | None
    confidence: float
    method: str
    candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class TocItem:
    """TOC line에서 파싱한 항목이다."""

    title: str
    level: int
    printed_page: int
    raw_text: str
    source_pdf_page: int
    confidence: float


@dataclass(frozen=True)
class OffsetEstimate:
    """printed page와 PDF page 사이의 offset 추정 결과다."""

    offset: int | None
    confidence: float
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class HeadingCandidate:
    """본문 page에서 추출한 heading 후보이다."""

    pdf_page: int
    text: str
    line_number: int
    confidence: float


@dataclass(frozen=True)
class AlignedTocItem:
    """TOC 항목을 실제 PDF page에 align한 결과다."""

    title: str
    level: int
    printed_page: int
    estimated_pdf_page: int | None
    matched_pdf_page: int | None
    confidence: float
    method: str
    source_pdf_page: int


@dataclass(frozen=True)
class ContentRange:
    """Markdown export와 bookmark 계획에 쓰는 page range다."""

    title: str
    level: int
    start_pdf_page: int
    end_pdf_page: int
    source_index: int


@dataclass(frozen=True)
class BookmarkPlanItem:
    """PDF bookmark로 쓸 단일 outline 항목이다."""

    title: str
    level: int
    pdf_page: int


@dataclass(frozen=True)
class ConfidenceSummary:
    """주요 단계의 신뢰도를 요약한다."""

    toc_detection: float | None = None
    offset: float | None = None
    alignment: float | None = None


@dataclass(frozen=True)
class ProcessingResult:
    """단일 PDF 처리 결과다."""

    status: ProcessingStatus
    input_pdf: Path
    output_pdf: Path | None = None
    output_markdown_dir: Path | None = None
    toc_pages: list[int] = field(default_factory=list)
    bookmark_count: int = 0
    confidence_summary: ConfidenceSummary = field(default_factory=ConfidenceSummary)
    warnings: list[str] = field(default_factory=list)
    report_path: Path | None = None


@dataclass(frozen=True)
class BatchResult:
    """디렉터리 단위 처리 요약이다."""

    total_pdf_count: int
    processed_count: int
    skipped_existing_bookmark_count: int
    failed_count: int
    bookmark_reference_candidate_count: int
    created_bookmarked_pdf_paths: list[Path] = field(default_factory=list)
    created_markdown_dirs: list[Path] = field(default_factory=list)
    results: list[ProcessingResult] = field(default_factory=list)
