"""글씨 height tier를 고정한 staged LLM TOC item 추출기다.

experiment 017/021의 결론을 제품 코드로 옮긴 모듈이다. TOC 줄의 대표 글씨
높이로 tier를 만들고, 머리말을 제외한 content tier를 level로 매핑한다. LLM은
1단계에서 스키마 이름/cue만 정하고, 2단계에서 각 항목이 나온 줄의 tier를
그대로 복사한다. 최종 level은 코드가 tier->level 매핑으로 부여한다.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import fitz
import numpy as np
from rapidfuzz import fuzz

from pdfbooktree.config import LlmStagedTocExtractionConfig
from pdfbooktree.models import TocItem, TocVisualLine
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

if TYPE_CHECKING:
    from openai import OpenAI


_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_TITLE_WORDS = {
    "목차",
    "목 차",
    "차례",
    "contents",
    "contents in brief",
    "brief contents",
    "table of contents",
}


def is_content_span(text: str) -> bool:
    """글자를 담은 span인지 판정한다(불릿/구분자/순수 숫자는 제외)."""

    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def is_title_word(text: str) -> bool:
    """목차 page 머리말 단독 줄인지 판정한다."""

    return normalize_for_match(text) in _TITLE_WORDS


def extract_toc_visual_lines(
    pdf_path: str | Path, toc_pages: list[int]
) -> list[TocVisualLine]:
    """TOC page들에서 줄 텍스트와 대표 글씨 높이를 추출한다."""

    pages = set(toc_pages)
    lines: list[TocVisualLine] = []
    with fitz.open(Path(pdf_path)) as document:
        for pdf_page in sorted(pages):
            page = document.load_page(pdf_page - 1)
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    heights: list[float] = []
                    parts: list[str] = []
                    for span in line["spans"]:
                        text = span["text"]
                        if not text.strip():
                            continue
                        parts.append(text.strip())
                        if is_content_span(text):
                            height = float(span["bbox"][3] - span["bbox"][1])
                            heights.append(round(height, 2))
                    if not heights:
                        continue
                    lines.append(
                        TocVisualLine(
                            pdf_page=pdf_page,
                            height=max(heights),
                            text=normalize_text(" ".join(parts)),
                        )
                    )
    return lines


def cluster_height_cut_points(heights: list[float]) -> list[float]:
    """height 1D 분포의 봉우리 사이 골짜기를 tier 경계로 찾는다.

    experiment 017의 gaussian_kde 흐름을 제품 의존성을 늘리지 않게 numpy로 직접
    계산한다. Scott 계열 bandwidth로 density를 만들고 local maxima/minima를 찾는다.
    """

    if not heights:
        return []
    arr = np.asarray(heights, dtype=float)
    if np.unique(arr).size <= 1:
        return []

    std = float(np.std(arr, ddof=1))
    if std <= 0.0:
        return []
    bandwidth = 1.06 * std * (len(arr) ** -0.2)
    if bandwidth <= 0.0 or not math.isfinite(bandwidth):
        return []

    grid = np.linspace(float(arr.min()) - 1.0, float(arr.max()) + 1.0, 1024)
    z = (grid[:, None] - arr[None, :]) / bandwidth
    density = np.exp(-0.5 * z * z).sum(axis=1)

    peak_idx = [
        index
        for index in range(1, len(density) - 1)
        if density[index - 1] < density[index] > density[index + 1]
    ]
    if not peak_idx:
        return []
    valley_idx = [
        index
        for index in range(1, len(density) - 1)
        if density[index - 1] > density[index] < density[index + 1]
    ]
    peaks = [float(grid[index]) for index in peak_idx]
    cuts = [
        float(grid[index])
        for index in valley_idx
        if min(peaks) < float(grid[index]) < max(peaks)
    ]
    return sorted(cuts)[: max(len(peaks) - 1, 0)]


def assign_tier(height: float, cut_points: list[float]) -> int:
    """height를 tier로 매핑한다. T1이 가장 큰 글씨다."""

    tier = 1
    for cut in sorted(cut_points, reverse=True):
        if height >= cut:
            return tier
        tier += 1
    return tier


def content_tier_to_level(
    lines: list[TocVisualLine], cut_points: list[float]
) -> dict[int, int]:
    """머리말을 뺀 content tier를 상위 tier=level 1로 매핑한다."""

    content_tiers = sorted(
        {
            assign_tier(line.height, cut_points)
            for line in lines
            if not is_title_word(line.text)
        }
    )
    return {tier: index + 1 for index, tier in enumerate(content_tiers)}


def annotate_page(
    lines: list[TocVisualLine], pdf_page: int, cut_points: list[float]
) -> str:
    """한 TOC page를 [Tn] 마커가 붙은 prompt 텍스트로 만든다."""

    out = [f"--- PDF page {pdf_page} ---"]
    for line in lines:
        if line.pdf_page != pdf_page:
            continue
        tier = assign_tier(line.height, cut_points)
        out.append(f"[T{tier}] {line.text}")
    return "\n".join(out)


def build_hierarchy_schema_format(n_levels: int) -> dict[str, Any]:
    """1단계 schema 응답 형식. level 수를 정확히 고정한다."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "hierarchy_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "levels": {
                        "type": "array",
                        "minItems": n_levels,
                        "maxItems": n_levels,
                        "items": {
                            "type": "object",
                            "properties": {
                                "level": {"type": "integer"},
                                "name": {"type": "string"},
                                "cues": {"type": "string"},
                                "examples": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["level", "name", "cues", "examples"],
                        },
                    }
                },
                "required": ["levels"],
            },
        },
    }


def build_staged_extract_schema() -> dict[str, Any]:
    """2단계 page extraction 응답 형식. LLM은 tier만 반환한다."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_page_extraction",
            "schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tier": {
                                    "type": "integer",
                                    "description": "항목이 나온 줄의 [Tn] 숫자.",
                                },
                                "title": {"type": "string"},
                                "printed_page": {"type": ["integer", "null"]},
                            },
                            "required": ["tier", "title", "printed_page"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
    }


class SizeAwareStagedTocExtractor:
    """글씨 height tier를 고정한 staged TOC item extractor다."""

    def __init__(
        self,
        config: LlmStagedTocExtractionConfig | None = None,
        *,
        chat_client: "OpenAI | None" = None,
    ) -> None:
        self.config = config or LlmStagedTocExtractionConfig()
        self._chat_client = chat_client

    def _make_client(self) -> "OpenAI":
        from openai import OpenAI

        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise RuntimeError(f"환경변수 {self.config.api_key_env}가 설정되지 않았다.")
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": self.config.base_url,
        }
        if self.config.request_timeout is not None:
            kwargs["timeout"] = self.config.request_timeout
        return OpenAI(**kwargs)

    @property
    def chat_client(self) -> "OpenAI":
        if self._chat_client is None:
            self._chat_client = self._make_client()
        return self._chat_client

    def extract(self, pdf_path: str | Path, toc_pages: list[int]) -> list[TocItem]:
        """PDF의 TOC page에서 staged 방식으로 목차 항목을 추출한다."""

        pages = sorted(dict.fromkeys(toc_pages))
        if not pages:
            return []
        lines = extract_toc_visual_lines(pdf_path, pages)
        return self.extract_from_lines(lines, pages)

    def extract_from_lines(
        self, lines: list[TocVisualLine], toc_pages: list[int] | None = None
    ) -> list[TocItem]:
        """이미 추출한 visual line에서 staged 추출을 수행한다."""

        if not lines:
            return []
        pages = toc_pages or sorted({line.pdf_page for line in lines})
        cut_points = cluster_height_cut_points([line.height for line in lines])
        tier_levels = content_tier_to_level(lines, cut_points)
        if not tier_levels:
            return []

        first_page_text = annotate_page(lines, pages[0], cut_points)
        schema = self._decide_schema(first_page_text, tier_levels)

        items: list[TocItem] = []
        for pdf_page in pages:
            page_text = annotate_page(lines, pdf_page, cut_points)
            page_lines = [line for line in lines if line.pdf_page == pdf_page]
            items.extend(
                self._extract_page(
                    page_text,
                    schema,
                    pdf_page,
                    tier_levels,
                    page_lines,
                    cut_points,
                )
            )
        return items

    def _decide_schema(
        self, first_page_text: str, tier_levels: dict[int, int]
    ) -> dict[str, Any]:
        tier_map_desc = ", ".join(
            f"T{tier}=level {level}" for tier, level in sorted(tier_levels.items())
        )
        user = (
            f"글씨 크기 클러스터 결과, 이 책 목차의 content 글씨 tier는 "
            f"{len(tier_levels)}개다 ({tier_map_desc}). 따라서 레벨도 정확히 "
            f"{len(tier_levels)}개로 정의하라. 더 쪼개거나 합치지 마라.\n\n"
            f"[첫 목차 페이지]\n{first_page_text}"
        )
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.schema_system_prompt},
                {"role": "user", "content": user},
            ],
            "response_format": build_hierarchy_schema_format(len(tier_levels)),
            "temperature": self.config.temperature,
        }
        if self.config.max_completion_tokens is not None:
            kwargs["max_tokens"] = self.config.max_completion_tokens
        response = self.chat_client.chat.completions.create(**kwargs)
        return json.loads(response.choices[0].message.content or "{}")

    def _extract_page(
        self,
        page_text: str,
        schema: dict[str, Any],
        pdf_page: int,
        tier_levels: dict[int, int],
        page_lines: list[TocVisualLine],
        cut_points: list[float],
    ) -> list[TocItem]:
        schema_text = json.dumps(schema, ensure_ascii=False, indent=2)
        user = (
            f"[계층 스키마 - 이 책 전체에 일관 적용]\n{schema_text}\n\n"
            f"[추출할 목차 페이지]\n{page_text}"
        )
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.extract_system_prompt},
                {"role": "user", "content": user},
            ],
            "response_format": build_staged_extract_schema(),
            "temperature": self.config.temperature,
        }
        if self.config.max_completion_tokens is not None:
            kwargs["max_tokens"] = self.config.max_completion_tokens
        response = self.chat_client.chat.completions.create(**kwargs)
        raw_items = json.loads(response.choices[0].message.content or "{}").get(
            "items", []
        )
        max_level = max(tier_levels.values()) if tier_levels else 1
        items: list[TocItem] = []
        for raw in raw_items:
            title = normalize_text(str(raw.get("title", "")).strip())
            if not title or is_title_word(title):
                continue
            if len(normalize_for_match(title).replace(" ", "")) < 2:
                continue
            tier = int(raw.get("tier") or 1)
            tier = self._correct_tier_from_visual_line(
                title, tier, page_lines, cut_points
            )
            level = tier_levels.get(tier, max_level)
            page_value = raw.get("printed_page")
            items.append(
                TocItem(
                    title=title,
                    level=level,
                    printed_page=int(page_value) if page_value else None,
                    raw_text=title,
                    source_pdf_page=pdf_page,
                    confidence=self.config.default_item_confidence,
                )
            )
        return items

    @staticmethod
    def _correct_tier_from_visual_line(
        title: str,
        llm_tier: int,
        page_lines: list[TocVisualLine],
        cut_points: list[float],
    ) -> int:
        """LLM이 복사한 tier가 원문 line tier와 충돌하면 원문 tier로 보정한다."""

        title_norm = normalize_for_match(title)
        if not title_norm:
            return llm_tier

        best_score = 0.0
        best_tier = llm_tier
        for line in page_lines:
            if is_title_word(line.text):
                continue
            line_norm = normalize_for_match(line.text)
            if not line_norm:
                continue
            score = fuzz.partial_ratio(title_norm, line_norm)
            if score > best_score:
                best_score = score
                best_tier = assign_tier(line.height, cut_points)

        # 제목 복원 후에도 원문과 충분히 겹치는 경우에는 시각 tier를 신뢰한다.
        if best_score >= 65.0:
            return best_tier
        return llm_tier
