"""탐지된 TOC page에서 Upstage LLM으로 목차 항목을 추출한다.

experiment 014에서 검증한 흐름을 패키지 코드로 옮긴 것이다.
- 기본 경로(text)는 OCR text layer를 solar-pro2 chat에 보내 structured JSON을 받는다.
- 대안 경로(image)는 페이지 이미지를 information-extract 엔드포인트로 page별 추출한다.
- 모델/하이퍼파라미터/엔드포인트/임계값은 모두 `LlmTocExtractionConfig`로 교체한다.

PRD 3.5 원칙상 LLM은 본래 backup이지만, OCR 한국어 책의 TOC item parsing은
regex로는 약해 이 단계만 LLM-primary로 둔다.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import fitz

from pdfbooktree.config import LlmTocExtractionConfig
from pdfbooktree.models import PdfPageText, TocItem
from pdfbooktree.pdf.text import extract_selected_page_texts
from pdfbooktree.utils.text_normalize import normalize_text

if TYPE_CHECKING:
    from openai import OpenAI


def build_toc_schema(
    *, nullable_page: bool, include_source_page: bool
) -> dict[str, Any]:
    """목차 추출용 json_schema response_format을 만든다.

    solar-pro2(text)는 ["integer","null"] union을 받지만, information-extract(image)는
    단일 타입만 허용하므로 page nullable 여부를 경로별로 다르게 둔다.
    """

    page_type: Any = ["integer", "null"] if nullable_page else "integer"
    page_desc = (
        "목차에 인쇄된 페이지 번호. 없으면 null."
        if nullable_page
        else "목차에 인쇄된 페이지 번호. 없으면 0."
    )
    properties: dict[str, Any] = {
        "title": {
            "type": "string",
            "description": "목차 항목 제목. 번호가 있으면 번호 포함.",
        },
        "level": {
            "type": "integer",
            "description": "계층 레벨. 최상위 chapter/장/부=1, 하위 절=2, 그 하위=3.",
        },
        "printed_page": {"type": page_type, "description": page_desc},
    }
    required = ["title", "level", "printed_page"]
    if include_source_page:
        properties["source_pdf_page"] = {
            "type": "integer",
            "description": "이 항목이 나타난 목차 PDF page (입력 마커 기준).",
        }
        required.append("source_pdf_page")
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_extraction",
            "schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    }
                },
                "required": ["items"],
            },
        },
    }


class LlmTocExtractor:
    """Upstage LLM으로 TOC page에서 `TocItem` 목록을 추출한다.

    테스트나 재현을 위해 `chat_client`/`image_client`를 주입할 수 있다.
    주입하지 않으면 config로 lazy 생성한다.
    """

    def __init__(
        self,
        config: LlmTocExtractionConfig | None = None,
        *,
        chat_client: "OpenAI | None" = None,
        image_client: "OpenAI | None" = None,
    ) -> None:
        self.config = config or LlmTocExtractionConfig()
        self._chat_client = chat_client
        self._image_client = image_client

    # ------------------------------------------------------------------ #
    # client
    # ------------------------------------------------------------------ #
    def _make_client(self, base_url: str) -> "OpenAI":
        from openai import OpenAI

        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"환경변수 {self.config.api_key_env}가 설정되지 않았다.")
        kwargs: dict[str, Any] = {"api_key": api_key, "base_url": base_url}
        if self.config.request_timeout is not None:
            kwargs["timeout"] = self.config.request_timeout
        return OpenAI(**kwargs)

    @property
    def chat_client(self) -> "OpenAI":
        if self._chat_client is None:
            self._chat_client = self._make_client(self.config.chat_base_url)
        return self._chat_client

    @property
    def image_client(self) -> "OpenAI":
        if self._image_client is None:
            self._image_client = self._make_client(self.config.image_base_url)
        return self._image_client

    # ------------------------------------------------------------------ #
    # public
    # ------------------------------------------------------------------ #
    def extract(self, pdf_path: str | Path, toc_pages: list[int]) -> list[TocItem]:
        """PDF의 지정 TOC page에서 목차 항목을 추출한다."""

        pages = sorted(dict.fromkeys(toc_pages))
        if not pages:
            return []
        if self.config.mode == "text":
            page_texts = extract_selected_page_texts(Path(pdf_path), pages)
            return self.extract_from_pages(page_texts)
        if self.config.mode == "image":
            images = self._render_images(Path(pdf_path), pages)
            return self._extract_from_images(images)
        raise ValueError(f"알 수 없는 mode다: {self.config.mode!r}")

    def extract_from_pages(self, pages: list[PdfPageText]) -> list[TocItem]:
        """이미 추출한 TOC page text에서 항목을 추출한다(text 경로 핵심)."""

        if not pages:
            return []
        prompt_text = self._build_text_prompt(pages)
        raw_items = self._call_text(prompt_text)
        valid_pages = {page.pdf_page for page in pages}
        fallback_page = min(valid_pages)
        return [
            self._to_item(raw, default_source=fallback_page, valid_pages=valid_pages)
            for raw in raw_items
            if raw.get("title")
        ]

    # ------------------------------------------------------------------ #
    # text 경로
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_text_prompt(pages: list[PdfPageText]) -> str:
        blocks: list[str] = []
        for page in pages:
            body = "\n".join(page.lines) if page.lines else page.text
            blocks.append(f"--- PDF page {page.pdf_page} ---\n{body}")
        return "\n\n".join(blocks)

    def _call_text(self, prompt_text: str) -> list[dict[str, Any]]:
        schema = build_toc_schema(nullable_page=True, include_source_page=True)
        kwargs: dict[str, Any] = {
            "model": self.config.text_model,
            "messages": [
                {"role": "system", "content": self.config.system_prompt},
                {"role": "user", "content": prompt_text},
            ],
            "response_format": schema,
            "temperature": self.config.temperature,
        }
        if self.config.max_completion_tokens is not None:
            kwargs["max_tokens"] = self.config.max_completion_tokens
        response = self.chat_client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or "{}"
        return json.loads(content).get("items", [])

    # ------------------------------------------------------------------ #
    # image 경로
    # ------------------------------------------------------------------ #
    def _render_images(
        self, pdf_path: Path, toc_pages: list[int]
    ) -> list[tuple[int, str]]:
        images: list[tuple[int, str]] = []
        with fitz.open(pdf_path) as document:
            for pdf_page in toc_pages[: self.config.max_image_pages]:
                pix = document.load_page(pdf_page - 1).get_pixmap(
                    dpi=self.config.image_dpi
                )
                b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
                images.append((pdf_page, b64))
        return images

    def _extract_from_images(self, images: list[tuple[int, str]]) -> list[TocItem]:
        # information-extract는 content에 이미지 1개만 허용하므로 page별로 호출한다.
        schema = build_toc_schema(nullable_page=False, include_source_page=False)
        items: list[TocItem] = []
        for pdf_page, b64 in images:
            kwargs: dict[str, Any] = {
                "model": self.config.image_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{self.config.image_mime};base64,{b64}"
                                },
                            }
                        ],
                    }
                ],
                "response_format": schema,
            }
            if self.config.max_completion_tokens is not None:
                kwargs["max_tokens"] = self.config.max_completion_tokens
            response = self.image_client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or "{}"
            for raw in json.loads(content).get("items", []):
                if not raw.get("title"):
                    continue
                items.append(
                    self._to_item(
                        raw,
                        default_source=pdf_page,
                        valid_pages={pdf_page},
                        force_source=pdf_page,
                    )
                )
        return items

    # ------------------------------------------------------------------ #
    # 변환
    # ------------------------------------------------------------------ #
    def _to_item(
        self,
        raw: dict[str, Any],
        *,
        default_source: int,
        valid_pages: set[int],
        force_source: int | None = None,
    ) -> TocItem:
        title = normalize_text(str(raw.get("title", "")).strip())
        level = int(raw.get("level") or 1)
        page_value = raw.get("printed_page")
        printed_page = int(page_value) if page_value else None
        if force_source is not None:
            source = force_source
        else:
            source_value = raw.get("source_pdf_page")
            source = (
                int(source_value)
                if isinstance(source_value, int) and source_value in valid_pages
                else default_source
            )
        return TocItem(
            title=title,
            level=level,
            printed_page=printed_page,
            raw_text=title,
            source_pdf_page=source,
            confidence=self.config.default_item_confidence,
        )
