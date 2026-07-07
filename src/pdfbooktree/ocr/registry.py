"""OCR engine 이름을 실제 전략 객체로 연결한다."""

from __future__ import annotations

from typing import Any

from pdfbooktree.ocr.engines.base import OcrEngine
from pdfbooktree.ocr.engines.upstage import UpstageOcrEngine


def create_ocr_engine(engine: str, options: dict[str, Any] | None = None) -> OcrEngine:
    """engine 이름으로 OCR 전략을 생성한다."""

    normalized = engine.strip().lower()
    if normalized == "upstage":
        return UpstageOcrEngine(options)
    if normalized in {"paddle", "paddleocr", "easyocr"}:
        raise NotImplementedError(f"{engine} engine은 아직 placeholder다.")
    raise ValueError(f"지원하지 않는 OCR engine이다: {engine}")
