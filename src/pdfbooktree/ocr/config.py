"""OCR overlay 설정값을 정의한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


CachePolicy = Literal["reuse", "refresh", "only"]


@dataclass(frozen=True)
class OcrOverlayConfig:
    """독립 OCR overlay 전처리 실행 설정이다."""

    input_pdf: Path | str
    output_pdf: Path | str
    output_dir: Path | str
    engine: str = "upstage"
    engine_options: dict[str, Any] = field(default_factory=dict)
    render_dpi: int = 300
    pages: list[int] | None = None
    force: bool = False
    confirm_bookmark_ocr_overwrite: bool = False
    cache_policy: CachePolicy = "reuse"
    stats_word_level: bool = False
