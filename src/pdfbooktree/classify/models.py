"""scan/bookmark 배치 분류 결과 데이터 구조다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pdfbooktree.pdf.scan_signals import PageScanSignal


@dataclass(frozen=True)
class ClassifyFileResult:
    """PDF 1개의 scan/bookmark 분류 결과다."""

    pdf_path: Path
    relative_path: str
    page_count: int
    sampled_page_count: int
    scanned_page_fraction: float
    total_visible_chars_sampled: int
    total_invisible_chars_sampled: int
    is_scanned: bool
    reject_reasons: list[str]
    bookmark_count: int
    toc_level_count: int
    has_meaningful_bookmark: bool
    is_ocr_overwrite_target: bool
    target_reject_reason: str
    error: str | None = None
    elapsed_sec: float = 0.0
    page_features: tuple[PageScanSignal, ...] = ()


@dataclass(frozen=True)
class ClassifyBatchResult:
    """디렉터리 단위 분류 요약이다."""

    total_pdf_count: int
    scanned_count: int
    native_count: int
    target_count: int
    error_count: int
    elapsed_sec: float
    report_csv_path: Path | None
    detail_jsonl_path: Path | None
    results: list[ClassifyFileResult] = field(default_factory=list)
