"""파이프라인 단계 사이에서 주고받는 데이터 구조를 정의한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


ProcessingStatus = Literal["processed", "skipped", "failed"]
BookmarkTocDetectionStatus = Literal["detected", "not_detected", "failed"]


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
class TocRangeReview:
    """LLM per-page 판정이 보정한 TOC page range와 근거다.

    experiment 038 흐름(seed부터 forward 스캔으로 anchor를 잡고 양방향 확장)을
    거친 결과다. `pages`는 보정된 1-based TOC page 목록이고, `stage`는 결과 상태
    ("forward_scan" 성공 / "no_toc_range" 실패)이며, `decisions`는 page별 LLM
    판정 trace다.
    """

    pages: list[int]
    start_page: int | None
    end_page: int | None
    anchor_page: int | None
    stage: str
    method: str
    llm_calls: int = 0
    decisions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class BookmarkedPdfTocDetection:
    """bookmark가 있는 단일 PDF의 TOC page detection 결과다."""

    status: BookmarkTocDetectionStatus
    input_pdf: Path
    root_relative_pdf: Path | None = None
    total_pages: int = 0
    observed_text_pages: int = 0
    bookmark_count: int = 0
    toc_pages: list[int] = field(default_factory=list)
    confidence: float | None = None
    method: str | None = None
    detection: TocDetectionResult | None = None
    dataset_rows: list[TocPageDatasetRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class TocPageDatasetRow:
    """TOC page classifier 학습/분석용 단일 page row다."""

    input_pdf: Path
    root_relative_pdf: Path | None
    pdf_page: int
    label: int
    sample_role: Literal["positive", "negative"]
    label_source: str
    total_pages: int
    bookmark_count: int
    detection_confidence: float
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
    prev_page_available: bool
    prev_line_count: int | None
    prev_word_count: int | None
    prev_mean_line_length: float | None
    prev_line_length_std: float | None
    prev_line_final_number_count: int | None
    prev_line_final_number_monotonicity: float | None
    prev_line_final_number_gap_mean: float | None
    prev_line_final_number_gap_median: float | None
    prev_line_final_number_gap_max: int | None
    prev_line_final_number_negative_gap_count: int | None
    prev_toc_entry_pattern_count: int | None
    prev_toc_entry_pattern_ratio: float | None
    prev_chapter_or_part_line_count: int | None
    prev_toc_keyword_presence: bool | None


@dataclass(frozen=True)
class BookmarkedPdfTocBatchResult:
    """임의 디렉터리 아래 bookmark 보유 PDF들의 TOC detection 요약이다."""

    root_dir: Path
    recursive: bool
    max_text_pages: int
    workers: int
    total_pdf_count: int
    bookmarked_pdf_count: int
    skipped_no_bookmark_count: int
    detected_count: int
    not_detected_count: int
    failed_count: int
    min_total_pages: int = 50
    skipped_short_pdf_count: int = 0
    skipped_no_letter_bookmark_count: int = 0
    dataset_row_count: int = 0
    results: list[BookmarkedPdfTocDetection] = field(default_factory=list)
    dataset_rows: list[TocPageDatasetRow] = field(default_factory=list)


@dataclass(frozen=True)
class TocItem:
    """TOC line에서 파싱한 항목이다."""

    title: str
    level: int
    printed_page: int | None
    raw_text: str
    source_pdf_page: int
    confidence: float


@dataclass(frozen=True)
class TocVisualLine:
    """TOC page의 한 줄, 대표 글씨 높이, 줄 시작 x 좌표를 담는다."""

    pdf_page: int
    height: float
    text: str
    x1: float = 0.0


@dataclass(frozen=True)
class BandPageNumber:
    """page 상/하위 band에서 추출한 인쇄 page number 후보다."""

    pdf_page: int
    number: int
    text: str
    band: Literal["top", "bottom"]
    x_ratio: float
    y_ratio: float


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
    printed_page: int | None
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
class BookmarkTreeNode:
    """bookmark 트리의 단일 노드다.

    flat bookmark 목록을 level 기반으로 중첩한 결과이며, ``own_span``은 이 노드가
    자기 본문으로 갖는 1-based PDF page 구간(start, end, inclusive)이다. 다음
    bookmark가 같은 page에서 시작하는 등 본문이 없으면 ``None``이다.
    """

    title: str
    level: int
    start_pdf_page: int | None
    own_span: tuple[int, int] | None
    order: int
    children: tuple["BookmarkTreeNode", ...] = ()


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
