"""Upstage Document Parse OCR engine과 표준 삽입 모델 adapter다."""

from __future__ import annotations

import io
import json
import os
import re
import ssl
import time
from typing import Any

import httpx

from pdfbooktree.ocr.models import (
    InsertableOcrElement,
    InsertableOcrLine,
    InsertableOcrPage,
    InsertableOcrWord,
    OcrBox,
    RenderedPage,
)


LINE_GROUP_Y_TOL_FRAC = 0.006
TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+\|?$")


class UpstageOcrEngine:
    """Upstage Document Parse raw response를 OCR overlay 표준 모델로 변환한다."""

    engine_id = "upstage"
    adapter_version = "upstage-document-parse-adapter-v1"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        options = options or {}
        self.model = str(options.get("model", "document-parse"))
        self.output_formats = list(
            options.get("output_formats", ["text", "html", "markdown"])
        )
        self.coordinates = bool(options.get("coordinates", True))
        self.words = bool(options.get("words", True))
        self.base_url = str(options.get("base_url", "https://api.upstage.ai/v1"))
        self.api_key_env = str(options.get("api_key_env", "UPSTAGE_API_KEY"))
        self.timeout = float(options.get("timeout", 180.0))
        self.max_retries = int(options.get("max_retries", 3))
        self.retry_initial_wait_sec = float(options.get("retry_initial_wait_sec", 2.0))

    def request_params(self) -> dict[str, Any]:
        """Upstage 호출 결과를 바꾸는 요청 파라미터를 반환한다."""

        return {
            "model": self.model,
            "output_formats": self.output_formats,
            "coordinates": self.coordinates,
            "words": self.words,
        }

    def recognize_page(self, rendered_page: RenderedPage) -> dict[str, Any]:
        """Upstage Document Parse API를 호출한다."""

        _load_dotenv_if_available()
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"{self.api_key_env}가 설정되지 않았다.")

        url = f"{self.base_url.rstrip('/')}/document-digitization"
        data = {
            "model": self.model,
            "output_formats": json.dumps(self.output_formats),
            "coordinates": str(self.coordinates).lower(),
            "words": str(self.words).lower(),
        }
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(
                    timeout=self.timeout, verify=_ssl_context()
                ) as client:
                    response = client.post(
                        url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        files={
                            "document": (
                                f"page_{rendered_page.pdf_page}.png",
                                io.BytesIO(rendered_page.png_bytes),
                                "image/png",
                            )
                        },
                        data=data,
                    )
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt == self.max_retries:
                    break
                time.sleep(self._retry_wait_sec(attempt))
                continue
            return response.json()
        raise last_exc or RuntimeError("Upstage Document Parse 호출에 실패했다.")

    def _retry_wait_sec(self, attempt: int) -> float:
        """실패 뒤 재시도 전 대기 시간을 2, 4, 8초처럼 계산한다."""

        return self.retry_initial_wait_sec * (2**attempt)

    def to_insertable_page(
        self,
        raw_response: dict[str, Any],
        rendered_page: RenderedPage,
    ) -> InsertableOcrPage:
        """Upstage element/word 구조를 InsertableOcrPage로 변환한다."""

        elements: list[InsertableOcrElement] = []
        warnings: list[str] = []
        for index, raw_element in enumerate(raw_response.get("elements", [])):
            element = self._to_insertable_element(raw_element, rendered_page, index)
            if element is None:
                warnings.append(f"빈 element를 건너뛰었다: index={index}")
                continue
            elements.append(element)

        return InsertableOcrPage(
            pdf_page=rendered_page.pdf_page,
            width_px=rendered_page.width_px,
            height_px=rendered_page.height_px,
            width_pt=rendered_page.width_pt,
            height_pt=rendered_page.height_pt,
            elements=elements,
            source_engine=self.engine_id,
            source_model=self.model,
            warnings=warnings,
        )

    def _to_insertable_element(
        self,
        raw_element: dict[str, Any],
        rendered_page: RenderedPage,
        index: int,
    ) -> InsertableOcrElement | None:
        words = _words_for_element(raw_element, rendered_page)
        content_text = _content_text(raw_element)
        if not words and not content_text.strip():
            return None

        bbox = _element_bbox(raw_element, rendered_page, words)
        row_groups = _group_words_into_lines(words, rendered_page.height_px)
        naive_join = _normalize_ws(
            " ".join(word.text for row in row_groups for word in row)
        )
        clean_join = _normalize_ws(content_text)
        element_id = str(raw_element.get("id", index))
        category = raw_element.get("category")

        if words and naive_join == clean_join:
            lines = [
                InsertableOcrLine(
                    text=" ".join(word.text for word in row),
                    bbox=_union_word_bbox(row),
                    words=row,
                )
                for row in row_groups
            ]
            return InsertableOcrElement(
                element_id=element_id,
                category=category,
                bbox=bbox,
                content_text=content_text,
                lines=lines,
                overlay_mode="word",
            )

        text_rows = _content_text_rows(content_text)
        if words and text_rows and len(text_rows) == len(row_groups):
            lines = [
                InsertableOcrLine(text=row_text, bbox=_union_word_bbox(row), words=[])
                for row, row_text in zip(row_groups, text_rows)
            ]
            return InsertableOcrElement(
                element_id=element_id,
                category=category,
                bbox=bbox,
                content_text=content_text,
                lines=lines,
                overlay_mode="row",
            )

        line_text = _normalize_ws(content_text)
        if not line_text and words:
            line_text = " ".join(word.text for row in row_groups for word in row)
        return InsertableOcrElement(
            element_id=element_id,
            category=category,
            bbox=bbox,
            content_text=content_text,
            lines=[InsertableOcrLine(text=line_text, bbox=bbox, words=[])],
            overlay_mode="element",
        )


def _content_text(raw_element: dict[str, Any]) -> str:
    content = raw_element.get("content") or {}
    return str(content.get("text") or content.get("markdown") or "")


def _words_for_element(
    raw_element: dict[str, Any],
    rendered_page: RenderedPage,
) -> list[InsertableOcrWord]:
    words: list[InsertableOcrWord] = []
    for raw_word in raw_element.get("words") or []:
        text = str(raw_word.get("text", ""))
        coords = raw_word.get("coordinates")
        if not text or not coords:
            continue
        words.append(
            InsertableOcrWord(
                text=text,
                bbox=_coords_to_box(coords, rendered_page),
            )
        )
    return words


def _element_bbox(
    raw_element: dict[str, Any],
    rendered_page: RenderedPage,
    words: list[InsertableOcrWord],
) -> OcrBox:
    coords = raw_element.get("coordinates")
    if coords:
        return _coords_to_box(coords, rendered_page)
    if words:
        return _union_word_bbox(words)
    return OcrBox(
        0.0, 0.0, float(rendered_page.width_px), float(rendered_page.height_px)
    )


def _coords_to_box(coords: list[dict[str, Any]], rendered_page: RenderedPage) -> OcrBox:
    xs = [float(coord["x"]) for coord in coords]
    ys = [float(coord["y"]) for coord in coords]
    if max(xs, default=0.0) <= 1.5 and max(ys, default=0.0) <= 1.5:
        xs = [x * rendered_page.width_px for x in xs]
        ys = [y * rendered_page.height_px for y in ys]
    return OcrBox(min(xs), min(ys), max(xs), max(ys))


def _group_words_into_lines(
    words: list[InsertableOcrWord],
    page_height_px: int,
) -> list[list[InsertableOcrWord]]:
    y_tol = page_height_px * LINE_GROUP_Y_TOL_FRAC
    ordered = sorted(words, key=lambda word: (_y_center(word.bbox), word.bbox.x0))
    lines: list[list[InsertableOcrWord]] = []
    for word in ordered:
        if lines and abs(_y_center(word.bbox) - _y_center(lines[-1][-1].bbox)) <= y_tol:
            lines[-1].append(word)
        else:
            lines.append([word])
    for line in lines:
        line.sort(key=lambda word: word.bbox.x0)
    return lines


def _union_word_bbox(words: list[InsertableOcrWord]) -> OcrBox:
    return OcrBox(
        x0=min(word.bbox.x0 for word in words),
        y0=min(word.bbox.y0 for word in words),
        x1=max(word.bbox.x1 for word in words),
        y1=max(word.bbox.y1 for word in words),
    )


def _y_center(box: OcrBox) -> float:
    return (box.y0 + box.y1) / 2


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _content_text_rows(content_text: str) -> list[str]:
    return [
        line
        for line in content_text.splitlines()
        if line.strip() and not TABLE_SEPARATOR_RE.match(line.strip())
    ]


def _install_truststore_if_available() -> None:
    """Windows 사내 TLS 체인에서도 OS 신뢰 저장소를 사용하게 한다."""

    try:
        import truststore
    except ImportError:
        return
    truststore.inject_into_ssl()


def _ssl_context() -> ssl.SSLContext | bool:
    """가능하면 OS 신뢰 저장소를 쓰는 SSL context를 반환한다."""

    try:
        import truststore
    except ImportError:
        return True
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _load_dotenv_if_available() -> None:
    """현재 작업 디렉터리부터 올라가며 .env를 찾아 환경변수에 반영한다."""

    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)
