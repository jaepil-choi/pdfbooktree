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

    def __post_init__(self) -> None:
        """Python API에서도 CLI와 같은 입력 계약을 조기에 검증한다."""

        if not isinstance(self.engine, str) or not self.engine.strip():
            raise ValueError("engine은 비어 있지 않은 문자열이어야 한다.")
        if not isinstance(self.engine_options, dict):
            raise ValueError("engine_options는 dict여야 한다.")
        if (
            isinstance(self.render_dpi, bool)
            or not isinstance(self.render_dpi, int)
            or self.render_dpi < 72
        ):
            raise ValueError("render_dpi는 72 이상의 정수여야 한다.")
        if self.pages is not None:
            if not isinstance(self.pages, list) or any(
                isinstance(page, bool) or not isinstance(page, int) or page < 1
                for page in self.pages
            ):
                raise ValueError("pages는 1 이상의 정수 목록이어야 한다.")
        if self.cache_policy not in {"reuse", "refresh", "only"}:
            raise ValueError("cache_policy는 reuse, refresh, only 중 하나여야 한다.")
        for name in (
            "force",
            "confirm_bookmark_ocr_overwrite",
            "stats_word_level",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name}은 bool이어야 한다.")
