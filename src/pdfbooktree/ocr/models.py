"""OCR overlay 단계에서 쓰는 표준 데이터 모델이다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


OverlayMode = Literal["word", "row", "element"]
OcrOverlayStatus = Literal["processed", "failed"]


@dataclass(frozen=True)
class OcrBox:
    """렌더링 이미지의 픽셀 좌표계 bbox다."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)


@dataclass(frozen=True)
class InsertableOcrWord:
    """invisible text layer에 넣을 단어 단위 OCR 결과다."""

    text: str
    bbox: OcrBox


@dataclass(frozen=True)
class InsertableOcrLine:
    """invisible text layer에 넣을 시각적 줄 단위 OCR 결과다."""

    text: str
    bbox: OcrBox
    words: list[InsertableOcrWord] = field(default_factory=list)


@dataclass(frozen=True)
class InsertableOcrElement:
    """provider별 OCR 결과를 표준 삽입 단위로 변환한 element다."""

    element_id: str
    category: str | None
    bbox: OcrBox
    content_text: str
    lines: list[InsertableOcrLine]
    overlay_mode: OverlayMode


@dataclass(frozen=True)
class InsertableOcrPage:
    """provider와 무관하게 PDF text layer에 삽입할 수 있는 page 모델이다."""

    pdf_page: int
    width_px: int
    height_px: int
    width_pt: float
    height_pt: float
    elements: list[InsertableOcrElement]
    source_engine: str
    source_model: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RenderedPage:
    """OCR engine에 넘길 렌더링된 PDF page다."""

    pdf_page: int
    png_bytes: bytes
    png_sha1: str
    width_px: int
    height_px: int
    width_pt: float
    height_pt: float


@dataclass(frozen=True)
class OcrOverlayResult:
    """OCR overlay 실행 결과 요약이다."""

    status: OcrOverlayStatus
    input_pdf: Path
    output_pdf: Path | None
    output_dir: Path
    page_count: int
    processed_pages: list[int]
    engine: str
    cache_hit_count: int = 0
    cache_miss_count: int = 0
    page_stats_path: Path | None = None
    element_stats_path: Path | None = None
    line_stats_path: Path | None = None
    word_stats_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OcrStatsResult:
    """OCR stats artifact 경로 모음이다."""

    page_stats_path: Path
    element_stats_path: Path
    line_stats_path: Path
    word_stats_path: Path | None = None


JsonObject = dict[str, Any]
