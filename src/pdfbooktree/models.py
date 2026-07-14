"""파이프라인 단계 사이에서 주고받는 핵심 데이터 구조다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


ProcessingStatus = Literal["processed", "skipped", "failed"]


@dataclass(frozen=True)
class ExistingOutlineItem:
    """PDF에 이미 들어 있는 outline 항목이다."""

    order: int
    title: str
    level: int
    pdf_page: int | None


@dataclass(frozen=True)
class PdfPageText:
    """1-based PDF page text와 line 정보를 담는다."""

    pdf_page: int
    text: str
    lines: list[str]
    char_count: int


@dataclass(frozen=True)
class TypographyLine:
    """책 전체 typography 추론에 쓰는 시각적 line이다."""

    pdf_page: int
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_width: float
    page_height: float
    font_size: float
    height: float
    is_bold: bool
    font_names: tuple[str, ...] = ()

    @property
    def y_center_ratio(self) -> float:
        """page 높이 대비 line 중심 y 위치다."""

        if self.page_height <= 0:
            return 0.0
        return ((self.y0 + self.y1) / 2.0) / self.page_height


@dataclass(frozen=True)
class Tier:
    """단일 typography tier 요약이다."""

    tier: int
    lower_bound: float | None
    upper_bound: float | None
    peak: float
    count: int


@dataclass(frozen=True)
class TierSet:
    """font size 또는 bbox height 기준 tier 계산 결과다."""

    signal: Literal["font_size", "height"]
    cut_points: list[float]
    tiers: list[Tier]
    raw_tier_count: int
    gap_merged_tier_count: int
    final_tier_count: int


@dataclass(frozen=True)
class HeadingCandidate:
    """typography 기반 heading 후보이다."""

    title: str
    pdf_page: int
    font_tier: int | None
    height_tier: int | None
    y0: float
    y1: float
    numbering_depth: int | None
    confidence: float
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BookmarkPlanItem:
    """PDF bookmark로 쓸 단일 outline 항목이다."""

    title: str
    level: int
    pdf_page: int
    source: str = "typography"
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BookmarkTreeNode:
    """bookmark plan을 level 기반으로 중첩한 노드다."""

    title: str
    level: int
    start_pdf_page: int
    end_pdf_page: int | None
    order: int
    children: tuple["BookmarkTreeNode", ...] = ()


@dataclass(frozen=True)
class BookmarkPlanValidation:
    """bookmark plan 검증 결과다."""

    valid: bool
    item_count: int
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarkdownFileStat:
    """하나의 split Markdown 파일 길이와 범위다."""

    path: Path
    title: str
    level: int
    start_pdf_page: int
    end_pdf_page: int
    word_count: int


@dataclass(frozen=True)
class MarkdownExportResult:
    """길이 coverage 정책으로 export한 Markdown 묶음의 결과다."""

    output_dir: Path
    chosen_level: int | None
    constraint_satisfied: bool
    file_count: int
    total_word_count: int
    fallback_used: bool = False
    fallback_reason: str | None = None
    word_count_stats: dict[str, int | float | None] = field(default_factory=dict)
    overflow_files: list[MarkdownFileStat] = field(default_factory=list)
    manifest_path: Path | None = None


@dataclass(frozen=True)
class ConfidenceSummary:
    """주요 단계의 신뢰도를 요약한다."""

    line_extraction: float | None = None
    tiering: float | None = None
    heading_candidates: float | None = None
    outline: float | None = None


@dataclass(frozen=True)
class ProcessingResult:
    """단일 PDF 처리 결과다."""

    status: ProcessingStatus
    input_pdf: Path
    output_pdf: Path | None = None
    output_markdown_dir: Path | None = None
    markdown_export: MarkdownExportResult | None = None
    ocr_pdf: Path | None = None
    bookmark_count: int = 0
    confidence_summary: ConfidenceSummary = field(default_factory=ConfidenceSummary)
    warnings: list[str] = field(default_factory=list)
    artifact_paths: dict[str, Path] = field(default_factory=dict)
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


JsonDict = dict[str, Any]
