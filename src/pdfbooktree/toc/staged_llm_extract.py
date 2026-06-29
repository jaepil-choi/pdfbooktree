"""멀티피처 클러스터 기반 TOC item 추출기다.

experiment 029/030에서 채택한 최신 전략을 제품 코드로 옮긴 모듈이다. 줄마다
LLM이 level을 판단하지 않고, 코드가 먼저 height/indent/bold/font signature로
시각 클러스터를 만든다. LLM은 소수 클러스터의 순서와 병합만 결정하고, 이후
페이지별 추출 단계에서는 이미 확정된 ``[Ln]`` level marker를 복사만 한다.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from html import escape
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
_DIGIT = re.compile(r"\d+")
_FONT_SUBSET = re.compile(r"^[A-Z]{6}\+")
_TITLE_WORDS = {
    "목차",
    "목 차",
    "차례",
    "contents",
    "contents in brief",
    "brief contents",
    "table of contents",
}

COLUMN_GAP_FRAC = 0.03
COLUMN_MIN_SUPPORT = 2
COLUMN_RELIABLE_STD_FRAC = 0.025


@dataclass(frozen=True)
class ClusteredTocLine:
    """클러스터링과 LLM 추출에 쓰는 TOC 줄 신호다."""

    pdf_page: int
    text: str
    height: float
    title_x: float
    page_width: float
    is_bold: bool
    font_type: str
    trailing_page: int | None


def is_content_span(text: str) -> bool:
    """글자를 담은 span인지 판정한다(불릿/구분자/순수 숫자는 제외)."""

    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def is_title_word(text: str) -> bool:
    """목차 page 머리말 단독 줄인지 판정한다."""

    return normalize_for_match(text) in _TITLE_WORDS


def base_font(name: str) -> str:
    """PDF subset prefix와 세부 weight suffix를 제거한 font family를 반환한다."""

    return _FONT_SUBSET.sub("", name).split("-")[0].split(",")[0].lower()


def span_is_bold(span: dict[str, Any]) -> bool:
    """PyMuPDF span에서 bold 신호를 읽는다."""

    return (
        bool(span.get("flags", 0) & 2**4) or "bold" in str(span.get("font", "")).lower()
    )


def extract_toc_visual_lines(
    pdf_path: str | Path, toc_pages: list[int]
) -> list[TocVisualLine]:
    """호환용 public helper: TOC page에서 줄 텍스트와 대표 글씨 높이를 추출한다."""

    return [
        TocVisualLine(
            pdf_page=line.pdf_page,
            height=line.height,
            text=line.text,
            x1=line.title_x,
        )
        for line in extract_clustered_toc_lines(pdf_path, toc_pages)
    ]


def extract_clustered_toc_lines(
    pdf_path: str | Path, toc_pages: list[int]
) -> list[ClusteredTocLine]:
    """TOC page들에서 클러스터링용 줄 신호를 추출한다."""

    pages = set(toc_pages)
    lines: list[ClusteredTocLine] = []
    with fitz.open(Path(pdf_path)) as document:
        for pdf_page in sorted(pages):
            page = document.load_page(pdf_page - 1)
            page_width = float(page.rect.width) or 1.0
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    spans = [span for span in line["spans"] if span["text"].strip()]
                    content_spans = [
                        span for span in spans if is_content_span(span["text"])
                    ]
                    if not content_spans:
                        continue
                    content_spans.sort(key=lambda span: span["bbox"][0])
                    head = content_spans[0]
                    heights = [
                        round(float(span["bbox"][3] - span["bbox"][1]), 2)
                        for span in content_spans
                    ]
                    parts = [span["text"].strip() for span in spans]
                    numbers = _DIGIT.findall(" ".join(parts))
                    lines.append(
                        ClusteredTocLine(
                            pdf_page=pdf_page,
                            text=normalize_text(" ".join(parts)),
                            height=max(heights),
                            title_x=round(float(head["bbox"][0]), 2),
                            page_width=page_width,
                            is_bold=span_is_bold(head),
                            font_type=base_font(str(head["font"])),
                            trailing_page=int(numbers[-1]) if numbers else None,
                        )
                    )
    return lines


def cluster_height_cut_points(heights: list[float]) -> list[float]:
    """height 1D 분포의 봉우리 사이 골짜기를 tier 경계로 찾는다."""

    return cluster_cut_points(heights)


def cluster_cut_points(values: list[float]) -> list[float]:
    """1D 값 분포의 KDE valley를 cut point로 반환한다."""

    if not values:
        return []
    arr = np.asarray(values, dtype=float)
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
    return sorted(
        float(grid[index])
        for index in valley_idx
        if min(peaks) < float(grid[index]) < max(peaks)
    )


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
    """호환용 helper: 머리말을 뺀 content tier를 level로 매핑한다."""

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
    """호환용 helper: 한 TOC page를 tier 태그가 붙은 prompt 텍스트로 만든다."""

    out = [f"--- PDF page {pdf_page} ---"]
    for line in lines:
        if line.pdf_page != pdf_page:
            continue
        tier = assign_tier(line.height, cut_points)
        out.append(
            f'<T{tier} x1="{line.x1:.1f}">{escape(line.text, quote=False)}</T{tier}>'
        )
    return "\n".join(out)


def build_columns(lines: list[ClusteredTocLine]) -> list[float]:
    """title_x 분포에서 robust indent column 중심을 만든다."""

    content = [line for line in lines if not is_title_word(line.text)]
    if not content:
        return []
    gap = content[0].page_width * COLUMN_GAP_FRAC
    xs = sorted(line.title_x for line in content)
    clusters: list[list[float]] = [[xs[0]]]
    for value in xs[1:]:
        if value - clusters[-1][-1] <= gap:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return sorted(
        float(np.mean(cluster))
        for cluster in clusters
        if len(cluster) >= COLUMN_MIN_SUPPORT
    )


def columns_reliable(lines: list[ClusteredTocLine], centers: list[float]) -> bool:
    """indent column이 OCR jitter보다 충분히 또렷한지 판정한다."""

    if len(centers) < 2:
        return False
    content = [line for line in lines if not is_title_word(line.text)]
    if not content:
        return False
    page_width = content[0].page_width
    devs = [
        line.title_x - min(centers, key=lambda center: abs(line.title_x - center))
        for line in content
    ]
    return float(np.std(devs)) < COLUMN_RELIABLE_STD_FRAC * page_width


def assign_column(title_x: float, centers: list[float]) -> int:
    """가장 가까운 indent column 번호를 반환한다."""

    if not centers:
        return 1
    return min(range(len(centers)), key=lambda idx: abs(title_x - centers[idx])) + 1


def build_clusters(
    lines: list[ClusteredTocLine],
) -> tuple[dict[int, int], list[dict[str, Any]], dict[str, Any]]:
    """줄을 멀티피처 signature 클러스터로 묶는다."""

    cuts = cluster_cut_points([line.height for line in lines])
    centers = build_columns(lines)
    reliable = columns_reliable(lines, centers)
    use_centers = centers if reliable else []

    signatures: dict[int, tuple[int, int, bool, str]] = {}
    for index, line in enumerate(lines):
        signatures[index] = (
            assign_column(line.title_x, use_centers),
            assign_tier(line.height, cuts),
            line.is_bold,
            line.font_type,
        )

    members: dict[tuple[int, int, bool, str], list[int]] = {}
    for index, line in enumerate(lines):
        if is_title_word(line.text):
            continue
        members.setdefault(signatures[index], []).append(index)

    signature_order = sorted(members.keys())
    signature_to_id = {
        signature: cluster_id for cluster_id, signature in enumerate(signature_order)
    }

    clusters: list[dict[str, Any]] = []
    for signature in signature_order:
        indexes = members[signature]
        ordered = sorted(indexes, key=lambda idx: (lines[idx].pdf_page, idx))
        if len(ordered) <= 4:
            picks = ordered
        else:
            step = len(ordered) / 4.0
            picks = [ordered[int(offset * step)] for offset in range(4)]
        page_known = sum(1 for idx in indexes if lines[idx].trailing_page is not None)
        clusters.append(
            {
                "cluster_id": signature_to_id[signature],
                "col": signature[0],
                "height_tier": signature[1],
                "is_bold": signature[2],
                "font_type": signature[3],
                "count": len(indexes),
                "mean_height": round(
                    float(np.mean([lines[idx].height for idx in indexes])), 2
                ),
                "page_number_frac": round(page_known / len(indexes), 2),
                "examples": [lines[idx].text[:70] for idx in picks],
            }
        )

    line_cluster = {
        index: signature_to_id[signatures[index]]
        for index in range(len(lines))
        if signatures[index] in signature_to_id
    }
    debug = {
        "height_cuts": [round(cut, 2) for cut in cuts],
        "column_centers": [round(center, 1) for center in centers],
        "columns_reliable": reliable,
        "n_clusters": len(clusters),
    }
    return line_cluster, clusters, debug


def build_cluster_order_schema() -> dict[str, Any]:
    """클러스터별 level 응답 schema다."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "cluster_levels",
            "schema": {
                "type": "object",
                "properties": {
                    "clusters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "cluster_id": {"type": "integer"},
                                "level": {"type": "integer"},
                            },
                            "required": ["cluster_id", "level"],
                        },
                    }
                },
                "required": ["clusters"],
            },
        },
    }


def build_staged_extract_schema() -> dict[str, Any]:
    """페이지별 항목 분리 응답 schema다. LLM은 level marker만 복사한다."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_split",
            "schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "level": {"type": "integer"},
                                "title": {"type": "string"},
                                "printed_page": {"type": ["integer", "null"]},
                            },
                            "required": ["level", "title", "printed_page"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
    }


def build_title_correction_schema() -> dict[str, Any]:
    """제목 OCR 교정 응답 schema다."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_title_correction",
            "schema": {
                "type": "object",
                "properties": {
                    "titles": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["titles"],
            },
        },
    }


def levels_from_clusters(
    line_cluster: dict[int, int],
    clusters: list[dict[str, Any]],
    cluster_level: dict[int, int],
) -> dict[int, int]:
    """클러스터 level을 dense-rank 후 각 줄에 부여한다."""

    cluster_ids = [int(cluster["cluster_id"]) for cluster in clusters]
    fallback = max(cluster_level.values(), default=1) + 1
    raw_level = {
        cluster_id: cluster_level.get(cluster_id, fallback)
        for cluster_id in cluster_ids
    }
    distinct = sorted(set(raw_level.values()))
    rank = {level: index + 1 for index, level in enumerate(distinct)}
    ranked = {cluster_id: rank[raw_level[cluster_id]] for cluster_id in cluster_ids}
    deepest = max(ranked.values(), default=1)
    return {index: ranked.get(line_cluster[index], deepest) for index in line_cluster}


def annotate_page_levels(
    lines: list[ClusteredTocLine], pdf_page: int, line_level: dict[int, int]
) -> str:
    """한 TOC page를 확정 level marker가 붙은 prompt 텍스트로 만든다."""

    out = [f"--- PDF page {pdf_page} ---"]
    for index, line in enumerate(lines):
        if line.pdf_page != pdf_page or is_title_word(line.text):
            continue
        if index not in line_level:
            continue
        out.append(f"[L{line_level[index]}] {escape(line.text, quote=False)}")
    return "\n".join(out)


def _normalize_items_levels(items: list[TocItem]) -> list[TocItem]:
    """level이 1부터 시작하도록 보정한다."""

    if not items:
        return items
    shift = min(item.level for item in items) - 1
    if shift <= 0:
        return items
    return [
        TocItem(
            title=item.title,
            level=item.level - shift,
            printed_page=item.printed_page,
            raw_text=item.raw_text,
            source_pdf_page=item.source_pdf_page,
            confidence=item.confidence,
        )
        for item in items
    ]


class SizeAwareStagedTocExtractor:
    """최신 클러스터 기반 staged TOC item extractor다."""

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
        """PDF의 TOC page에서 최신 staged 방식으로 목차 항목을 추출한다."""

        pages = sorted(dict.fromkeys(toc_pages))
        if not pages:
            return []
        lines = extract_clustered_toc_lines(pdf_path, pages)
        return self.extract_from_clustered_lines(lines, pages)

    def extract_from_lines(
        self, lines: list[TocVisualLine], toc_pages: list[int] | None = None
    ) -> list[TocItem]:
        """테스트/호환용 visual line 입력을 클러스터 line으로 변환해 추출한다."""

        converted = [
            ClusteredTocLine(
                pdf_page=line.pdf_page,
                text=line.text,
                height=line.height,
                title_x=line.x1,
                page_width=600.0,
                is_bold=False,
                font_type="unknown",
                trailing_page=_last_number(line.text),
            )
            for line in lines
        ]
        pages = toc_pages or sorted({line.pdf_page for line in lines})
        return self.extract_from_clustered_lines(converted, pages)

    def extract_from_clustered_lines(
        self,
        lines: list[ClusteredTocLine],
        toc_pages: list[int] | None = None,
    ) -> list[TocItem]:
        """이미 추출한 clustered line에서 최신 staged 추출을 수행한다."""

        if not lines:
            return []
        pages = toc_pages or sorted({line.pdf_page for line in lines})
        line_cluster, clusters, _debug = build_clusters(lines)
        if not clusters:
            return []
        cluster_levels = self._decide_cluster_levels(clusters)
        line_levels = levels_from_clusters(line_cluster, clusters, cluster_levels)
        if not line_levels:
            return []

        max_level = max(line_levels.values(), default=1)
        items: list[TocItem] = []
        for pdf_page in pages:
            page_text = annotate_page_levels(lines, pdf_page, line_levels)
            if len(page_text.splitlines()) <= 1:
                continue
            items.extend(self._extract_page(page_text, pdf_page, max_level))

        items = _normalize_items_levels(items)
        return self._correct_titles_by_page(items)

    def _decide_cluster_levels(self, clusters: list[dict[str, Any]]) -> dict[int, int]:
        payload = [
            {
                "cluster_id": cluster["cluster_id"],
                "font_type": cluster["font_type"],
                "is_bold": cluster["is_bold"],
                "mean_height": cluster["mean_height"],
                "indent_col": cluster["col"],
                "count": cluster["count"],
                "page_number_frac": cluster["page_number_frac"],
                "examples": cluster["examples"],
            }
            for cluster in clusters
        ]
        user = "클러스터 목록:\n" + json.dumps(payload, ensure_ascii=False, indent=2)
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.cluster_system_prompt},
                {"role": "user", "content": user},
            ],
            "response_format": build_cluster_order_schema(),
            "temperature": self.config.temperature,
        }
        if self.config.max_completion_tokens is not None:
            kwargs["max_tokens"] = self.config.max_completion_tokens
        response = self.chat_client.chat.completions.create(**kwargs)
        payload = json.loads(response.choices[0].message.content or "{}")
        raw = payload.get("clusters", [])
        return {
            int(item["cluster_id"]): int(item["level"])
            for item in raw
            if "cluster_id" in item and "level" in item
        }

    def _extract_page(
        self, page_text: str, pdf_page: int, max_level: int
    ) -> list[TocItem]:
        user = f"[추출할 목차 페이지]\n{page_text}"
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
        payload = json.loads(response.choices[0].message.content or "{}")
        raw_items = payload.get("items", [])
        items: list[TocItem] = []
        for raw in raw_items:
            title = normalize_text(str(raw.get("title", "")).strip())
            if not _keep_title(title):
                continue
            page_value = raw.get("printed_page")
            items.append(
                TocItem(
                    title=title,
                    level=max(1, min(int(raw.get("level") or 1), max_level)),
                    printed_page=int(page_value) if page_value else None,
                    raw_text=title,
                    source_pdf_page=pdf_page,
                    confidence=self.config.default_item_confidence,
                )
            )
        return items

    def _correct_titles_by_page(self, items: list[TocItem]) -> list[TocItem]:
        """page별로 제목 OCR 교정을 적용하되 항목 개수/순서/level은 보존한다."""

        if not items:
            return items
        by_page: dict[int, list[int]] = {}
        for index, item in enumerate(items):
            by_page.setdefault(item.source_pdf_page, []).append(index)

        titles = [item.title for item in items]
        for indexes in by_page.values():
            corrected = self._correct_titles([items[index].title for index in indexes])
            for index, title in zip(indexes, corrected):
                titles[index] = title

        return [
            TocItem(
                title=titles[index],
                level=item.level,
                printed_page=item.printed_page,
                raw_text=item.raw_text,
                source_pdf_page=item.source_pdf_page,
                confidence=item.confidence,
            )
            for index, item in enumerate(items)
        ]

    def _correct_titles(self, titles: list[str]) -> list[str]:
        if not titles:
            return titles
        user = "교정할 목차 제목들(순서 유지):\n" + json.dumps(
            titles, ensure_ascii=False, indent=2
        )
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.correction_system_prompt},
                {"role": "user", "content": user},
            ],
            "response_format": build_title_correction_schema(),
            "temperature": self.config.temperature,
        }
        if self.config.max_completion_tokens is not None:
            kwargs["max_tokens"] = self.config.max_completion_tokens
        response = self.chat_client.chat.completions.create(**kwargs)
        payload = json.loads(response.choices[0].message.content or "{}")
        corrected = payload.get("titles", [])
        if len(corrected) != len(titles):
            return titles
        return [
            normalize_text(str(title).strip()) or titles[index]
            for index, title in enumerate(corrected)
        ]

    @staticmethod
    def _correct_tier_from_visual_line(
        title: str,
        llm_tier: int,
        page_lines: list[TocVisualLine],
        cut_points: list[float],
    ) -> int:
        """이전 public helper 호환용 tier 보정 함수다."""

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

        if best_score >= 65.0:
            return best_tier
        return llm_tier


def _last_number(text: str) -> int | None:
    numbers = _DIGIT.findall(text)
    return int(numbers[-1]) if numbers else None


def _keep_title(title: str) -> bool:
    if not title or is_title_word(title):
        return False
    return len(normalize_for_match(title).replace(" ", "")) >= 2
