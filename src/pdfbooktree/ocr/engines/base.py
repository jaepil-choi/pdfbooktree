"""OCR engine 전략이 따라야 하는 protocol이다."""

from __future__ import annotations

from typing import Any, Protocol

from pdfbooktree.ocr.models import InsertableOcrPage, RenderedPage


class OcrEngine(Protocol):
    """provider별 OCR 호출과 표준 삽입 모델 변환을 담당한다."""

    engine_id: str
    adapter_version: str

    def request_params(self) -> dict[str, Any]:
        """raw OCR cache key에 포함할 요청 파라미터를 반환한다."""

    def recognize_page(self, rendered_page: RenderedPage) -> dict[str, Any]:
        """렌더링된 page image를 OCR provider에 보내 raw response를 얻는다."""

    def to_insertable_page(
        self,
        raw_response: dict[str, Any],
        rendered_page: RenderedPage,
    ) -> InsertableOcrPage:
        """provider raw response를 표준 삽입 모델로 변환한다."""
