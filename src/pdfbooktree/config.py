"""처리 파이프라인의 기본 설정값을 정의한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TypographyConfig:
    """책 전체 typography 기반 outline 추론 설정이다."""

    line_y_tolerance_ratio: float = 0.55
    min_tier_gap: float = 2.0
    min_tier_count: int = 5
    max_heading_tier: int = 3
    max_heading_length: int = 160
    min_heading_confidence: float = 0.45
    heading_merge_gap_ratio: float = 1.5


@dataclass(frozen=True)
class ProcessingConfig:
    """단일 PDF 처리 설정이다."""

    skip_existing_bookmarks: bool = True
    write_artifacts: bool = True
    ocr_policy: Literal["never", "auto", "always"] = "never"
    typography: TypographyConfig = TypographyConfig()
