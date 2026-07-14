"""experiment 023: 목차 계층 신호 융합(height + 들여쓰기 x0 + 번호구조).

배경
- showcase 006에서 multi-level 영어 책 계층이 모두 붕괴했다(Hull {1:1,2:558},
  Luenberger {3:514} starts_at_level_1=false, Shreve {1:53}). 원인은 staged
  extractor 계층이 오직 글씨 height 1D 클러스터에서만 나오기 때문이다. height는
  영어 책에서 약한 신호다(장/절 글씨 차이 미미, OCR height 노이즈).

가설
- 계층 신호를 height 단일에서 "번호구조 + 들여쓰기(x0) + height" 하이브리드로 바꾸고,
  LLM이 이 신호들로 level을 추론하되 번호 깊이가 명시된 항목은 코드가 결정론적으로
  정정(sanity-check)하면, 영어 책 장/절/부 계층이 복원되고 한국어 OCR 책(번호 없음)도
  height fallback으로 유지된다.

설계
- Arm A (baseline): exp 021 그대로. height-only tier->level, LLM은 tier만 복사.
- Arm B (llm_reasoned): 각 줄에 [h x num] 신호를 붙여 prompt에 넣고, LLM이 level을
  직접 추론한다(완화 지점). 추출 후 코드가 번호 깊이로 reconciliation한다.
- TOC page는 GT 라벨(answer_toc_ranges_manual.json)을 쓰되 brief/detailed 중복
  confound를 피하려고 kind=="contents"(상세) segment page만 사용한다.
- bookmark 보유 3권은 기존 bookmark를 weak reference로 level 깊이 일치율을 잰다.
  (Luenberger bookmark는 Part/Chapter만 담아 절 level 검증 불가 -> 일치율만 본다.)

범위
- 계층(level)만 다룬다. printed_page 추출 붕괴와 brief/detailed 범위 선택은 다음 라운드.

출력: experiments/outputs/023_toc_hierarchy_signal_fusion/
    - <id>_schema.json        : Arm B 1단계 LLM schema + 코드 reconciliation 매핑
    - <id>_tree_armA.txt       : Arm A 추출 트리
    - <id>_tree_armB.txt       : Arm B 추출 트리
    - <id>_armB_page{n}.json   : Arm B 페이지별 추출
    - summary.json
실행:
    uv run python experiments/023_toc_hierarchy_signal_fusion.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from dotenv import load_dotenv
from rapidfuzz import fuzz, process
from scipy.signal import argrelextrema
from scipy.stats import gaussian_kde

from pdfbooktree.models import TocItem
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, title_has_letter
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "023_toc_hierarchy_signal_fusion"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "023_toc_hierarchy_signal_fusion"

# 다중계층 타깃 3권 + 회귀 가드 2권.
TARGET_IDS = [
    "john_hull",
    "luenberger_investment_science",
    "shreve_binomial",
    "algorithms_to_live_by",
    "algorithm_nine",
]
# bookmark weak reference로 level 깊이를 검증할 수 있는 책.
BOOKMARKED_IDS = {"john_hull", "luenberger_investment_science", "shreve_binomial"}

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
MODEL = "solar-pro3"

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_TITLE_WORDS = {
    "목차",
    "차례",
    "contents",
    "contents in brief",
    "brief contents",
    "table of contents",
}

# 번호 구조 판정. 영어 part/chapter/appendix 키워드와 한국어 N부/N장,
# 소수점 깊이(N. / N.M / N.M.K)를 결정론적으로 인식한다.
_PART_RE = re.compile(r"^\s*(?:part\b|제?\s*\d+\s*부\b|\d+\s*부\b)", re.IGNORECASE)
_CHAPTER_RE = re.compile(
    r"^\s*(?:chapter\b|appendix\b|제?\s*\d+\s*장\b|\d+\s*장\b)", re.IGNORECASE
)
_DECIMAL_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)")
_SINGLE_NUM_RE = re.compile(r"^\s*\d+(?:\.|\s|$)")


# ---------------------------------------------------------------------------
# 공통: TOC 줄 신호 추출 (height + x0 + number_kind)
# ---------------------------------------------------------------------------
def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def is_title_word(text: str) -> bool:
    return normalize_for_match(text) in _TITLE_WORDS


def detect_number(title: str) -> tuple[str, int | None]:
    """제목 앞부분의 번호 구조를 (kind, rank)로 판정한다.

    rank가 작을수록 상위 계층이다. part=0, chapter/N장/단일번호=1, N.M=2, N.M.K=3.
    번호가 없으면 (none, None)이다.
    """

    t = normalize_text(title)
    if _PART_RE.match(t):
        return ("part", 0)
    if _CHAPTER_RE.match(t):
        return ("chapter", 1)
    decimal = _DECIMAL_RE.match(t)
    if decimal:
        depth = decimal.group(1).count(".") + 1
        return (f"n{depth}", depth)
    if _SINGLE_NUM_RE.match(t):
        return ("n1", 1)
    return ("none", None)


def extract_toc_lines(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """TOC page들에서 줄별 text, 대표 height, 정규화 x0, number_kind를 뽑는다."""

    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pno in toc_pages:
            page = document.load_page(pno - 1)
            page_width = float(page.rect.width) or 1.0
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    heights: list[float] = []
                    parts: list[str] = []
                    x_lefts: list[float] = []
                    for span in line["spans"]:
                        text = span["text"]
                        if not text.strip():
                            continue
                        parts.append(text.strip())
                        if is_content_span(text):
                            heights.append(round(span["bbox"][3] - span["bbox"][1], 2))
                            x_lefts.append(float(span["bbox"][0]))
                    if not heights:
                        continue
                    title = normalize_text(" ".join(parts))
                    number_kind, number_rank = detect_number(title)
                    lines.append(
                        {
                            "pdf_page": pno,
                            "height": max(heights),
                            "x0": round(min(x_lefts) / page_width, 3),
                            "text": title,
                            "number_kind": number_kind,
                            "number_rank": number_rank,
                        }
                    )
    return lines


# ---------------------------------------------------------------------------
# height 클러스터 (Arm A와 Arm B의 tier hint 공통)
# ---------------------------------------------------------------------------
def cluster_cut_points(heights: list[float]) -> list[float]:
    arr = np.asarray(heights, dtype=float)
    if arr.size == 0 or np.unique(arr).size == 1:
        return []
    kde = gaussian_kde(arr)
    grid = np.linspace(arr.min() - 1.0, arr.max() + 1.0, 1024)
    density = kde(grid)
    peak_idx = argrelextrema(density, np.greater)[0]
    valley_idx = argrelextrema(density, np.less)[0]
    if peak_idx.size == 0:
        return []
    peaks = [float(grid[i]) for i in peak_idx]
    cuts = [float(grid[vi]) for vi in valley_idx if peaks[0] < grid[vi] < peaks[-1]]
    return sorted(cuts)[: max(len(peaks) - 1, 0)]


def assign_tier(height: float, cut_points: list[float]) -> int:
    tier = 1
    for cut in sorted(cut_points, reverse=True):
        if height >= cut:
            return tier
        tier += 1
    return tier


def content_tier_to_level(
    lines: list[dict[str, Any]], cuts: list[float]
) -> dict[int, int]:
    """머리말을 뺀 content tier를 상위 tier=level 1로 매핑한다(Arm A baseline)."""

    content_tiers = sorted(
        {
            assign_tier(ln["height"], cuts)
            for ln in lines
            if not is_title_word(ln["text"])
        }
    )
    return {tier: idx + 1 for idx, tier in enumerate(content_tiers)}


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------
_CLIENT: Any = None

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def loads_lenient(content: str | None) -> dict[str, Any]:
    """LLM 응답에서 JSON 객체를 견고하게 파싱한다.

    free-form 응답이 ```json 코드펜스나 앞뒤 산문을 섞어 내도 첫 '{'부터 마지막 '}'
    까지를 잘라 파싱한다. 그래도 실패하면 빈 dict를 반환한다.
    """

    if not content:
        return {}
    text = content.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


def client() -> Any:
    global _CLIENT
    if _CLIENT is None:
        from openai import OpenAI

        api_key = os.environ.get("UPSTAGE_API_KEY")
        if not api_key:
            raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
        _CLIENT = OpenAI(api_key=api_key, base_url=UPSTAGE_BASE_URL)
    return _CLIENT


# ---------------------------------------------------------------------------
# Arm A: exp 021 baseline (height tier -> level, LLM은 tier만 복사)
# ---------------------------------------------------------------------------
ARM_A_SCHEMA_SYSTEM = (
    "너는 책 목차의 '첫 페이지'를 보고 이 책 목차의 계층 스키마를 정의하는 도구다. "
    "각 줄 앞 [Tn]은 글씨 크기 tier다(T1이 가장 큰 글씨).\n"
    "중요: 계층 레벨 수는 이미 글씨 크기 클러스터로 정해졌다. 사용자가 알려주는 tier "
    "개수만큼만 레벨을 정의하고, 같은 글씨 크기를 번호·문장부호만으로 더 쪼개거나 합치지 "
    "마라. 큰 글씨 tier가 상위 레벨(1)이다.\n"
    "각 레벨에 level(1부터), name, cues, examples를 적는다. '목차'/'Contents' 같은 "
    "페이지 머리말은 레벨에서 제외한다. 이 스키마는 이후 이 책의 모든 목차 페이지에 똑같이 적용된다."
)

ARM_A_EXTRACT_SYSTEM = (
    "너는 책 목차 페이지에서 항목을 추출하는 도구다. 아래 [계층 스키마]는 이 책 전체에 "
    "일관 적용되는 레벨 정의이고, 각 줄 앞 [Tn]은 그 줄의 글씨 크기 tier다.\n"
    "절대 규칙: 계층/레벨/tier는 네가 정하지 않는다. 각 항목의 tier는 그 항목이 나온 줄의 "
    "[Tn] 숫자(n)를 '그대로 복사'만 한다. tier를 바꾸거나 새로 만들거나 추론하지 마라. "
    "한 줄을 여러 항목으로 쪼개면 모든 조각은 그 줄과 같은 tier를 받는다.\n"
    "너가 하는 일은 다음뿐이다.\n"
    "- 깨진 OCR 글씨 복원: 깨진 제목을 깨끗하게 고친다. 없는 내용을 지어내지 않는다.\n"
    "- 항목 분리: 한 줄에 여러 항목이 'I'/'|'/'·'/'•' 구분자와 페이지 번호로 합쳐져 있으면 분리한다.\n"
    "- 페이지 번호: printed_page는 제목 뒤의 인쇄 페이지 번호. 없으면 null.\n"
    "- 글씨가 깨진 줄도 빼지 말고 반드시 항목으로 낸다.\n"
    "- '목차'/'Contents' 같은 머리말 한 마디 줄은 항목으로 만들지 않는다.\n"
    "- 항목은 이 페이지에 나온 순서 그대로 반환한다."
)

ARM_A_RESPONSE_FORMAT = {
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
                                "description": "그 항목이 나온 줄의 [Tn] 숫자를 그대로 복사.",
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


def build_hierarchy_schema_format(n_levels: int) -> dict[str, Any]:
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


def annotate_page_tier(lines: list[dict[str, Any]], pno: int, cuts: list[float]) -> str:
    out = [f"--- PDF page {pno} ---"]
    for line in lines:
        if line["pdf_page"] != pno:
            continue
        out.append(f"[T{assign_tier(line['height'], cuts)}] {line['text']}")
    return "\n".join(out)


def arm_a_decide_schema(
    first_page_text: str, tier_levels: dict[int, int]
) -> dict[str, Any]:
    n_levels = len(tier_levels)
    tier_map_desc = ", ".join(
        f"T{tier}=level {lvl}" for tier, lvl in sorted(tier_levels.items())
    )
    user = (
        f"글씨 크기 클러스터 결과, 이 책 목차의 content 글씨 tier는 {n_levels}개다 "
        f"({tier_map_desc}). 따라서 레벨도 정확히 {n_levels}개로 정의하라. 더 쪼개거나 "
        f"합치지 마라.\n\n[첫 목차 페이지]\n{first_page_text}"
    )
    response = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": ARM_A_SCHEMA_SYSTEM},
            {"role": "user", "content": user},
        ],
        response_format=build_hierarchy_schema_format(n_levels),
        temperature=0.0,
    )
    return loads_lenient(response.choices[0].message.content)


def arm_a_extract_page(
    page_text: str, schema: dict[str, Any], pno: int, tier_levels: dict[int, int]
) -> list[TocItem]:
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
    user = (
        f"[계층 스키마 — 이 책 전체에 일관 적용]\n{schema_str}\n\n"
        f"[추출할 목차 페이지]\n{page_text}"
    )
    response = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": ARM_A_EXTRACT_SYSTEM},
            {"role": "user", "content": user},
        ],
        response_format=ARM_A_RESPONSE_FORMAT,
        temperature=0.0,
    )
    raw_items = loads_lenient(response.choices[0].message.content).get("items", [])
    max_level = max(tier_levels.values()) if tier_levels else 1
    items: list[TocItem] = []
    for raw in raw_items:
        title = normalize_text(str(raw.get("title", "")).strip())
        if not title or is_title_word(title):
            continue
        tier = int(raw.get("tier") or 1)
        level = tier_levels.get(tier, max_level)
        page_value = raw.get("printed_page")
        items.append(
            TocItem(
                title=title,
                level=level,
                printed_page=int(page_value) if page_value else None,
                raw_text=title,
                source_pdf_page=pno,
                confidence=0.8,
            )
        )
    return items


def run_arm_a(
    lines: list[dict[str, Any]], toc_pages: list[int]
) -> list[TocItem]:
    cuts = cluster_cut_points([ln["height"] for ln in lines])
    tier_levels = content_tier_to_level(lines, cuts)
    if not tier_levels:
        return []
    first_page_text = annotate_page_tier(lines, toc_pages[0], cuts)
    schema = arm_a_decide_schema(first_page_text, tier_levels)
    items: list[TocItem] = []
    for pno in toc_pages:
        page_text = annotate_page_tier(lines, pno, cuts)
        items.extend(arm_a_extract_page(page_text, schema, pno, tier_levels))
    return items


# ---------------------------------------------------------------------------
# Arm B: enriched 신호 + LLM-reasoned level + 결정론적 번호 reconciliation
# ---------------------------------------------------------------------------
ARM_B_SCHEMA_SYSTEM = (
    "너는 책 목차의 앞부분을 보고 이 책 목차의 계층(level) 스키마를 정의하는 도구다.\n"
    "각 줄 앞 대괄호에는 세 가지 신호가 있다.\n"
    "- h: 글씨 높이(클수록 상위 계층일 가능성).\n"
    "- x: 들여쓰기 비율 0~1(작을수록 왼쪽=상위, 클수록 들여써짐=하위).\n"
    "- num: 번호 구조. part=부, chapter=장, n1=최상위 번호(예: '1.'), n2='1.1', "
    "n3='1.1.1', none=번호 없음.\n"
    "규칙:\n"
    "- 세 신호를 종합해 계층 레벨을 정의하라. 번호 구조(num)가 가장 강한 신호다. "
    "part가 있으면 part가 최상위, 그다음 chapter, 그다음 n2, n3 순으로 깊어진다.\n"
    "- 번호가 없는 책은 h(글씨 크기)와 x(들여쓰기)로 계층을 정한다.\n"
    "- 글씨 크기 tier 수를 참고 hint로 주지만, 번호 깊이가 더 깊으면 번호 깊이를 우선한다.\n"
    "각 레벨에 level(1부터 연속), name(예: 부/장/절, part/chapter/section), "
    "cues(어떤 h/x/num이면 이 레벨인지), examples(앞 페이지의 해당 제목 1~3개)를 적는다. "
    "'목차'/'Contents' 같은 페이지 머리말은 레벨에서 제외한다. 이 스키마는 이후 이 책의 "
    "모든 목차 페이지에 일관 적용된다."
)

ARM_B_EXTRACT_SYSTEM = (
    "너는 책 목차 페이지에서 항목을 추출하는 도구다. 아래 [계층 스키마]를 이 책 전체에 "
    "일관 적용한다. 각 줄 앞 대괄호 [h x num]은 그 줄의 신호다(h=글씨높이, x=들여쓰기비율, "
    "num=번호구조).\n"
    "각 항목에 대해 다음을 한다.\n"
    "- level: [계층 스키마]와 그 줄의 [h x num] 신호를 종합해 레벨을 정한다. 번호 구조가 "
    "있으면 번호 깊이를 우선한다(part<chapter<n2<n3 순으로 깊어짐).\n"
    "- title: 깨진 OCR 글씨를 깨끗하게 복원한다. 없는 내용을 지어내지 않는다.\n"
    "- printed_page: 제목 뒤의 인쇄 페이지 번호. 없으면 null.\n"
    "- 항목 분리: 한 줄에 'I'/'|'/'·'/'•' 구분자와 페이지 번호로 여러 항목이 합쳐져 있으면 "
    "각 항목으로 분리하고, 분리된 조각은 같은 줄의 신호(레벨)를 공유한다.\n"
    "- 글씨가 깨진 줄도 빼지 말고 반드시 항목으로 낸다.\n"
    "- '목차'/'Contents' 같은 머리말 한 마디 줄은 항목으로 만들지 않는다.\n"
    "- 항목은 이 페이지에 나온 순서 그대로 반환한다."
)

ARM_B_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "toc_page_extraction_leveled",
        "schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "level": {
                                "type": "integer",
                                "description": "스키마와 [h x num] 신호로 정한 계층 레벨(1부터).",
                            },
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


def annotate_page_signals(lines: list[dict[str, Any]], pno: int) -> str:
    out = [f"--- PDF page {pno} ---"]
    for line in lines:
        if line["pdf_page"] != pno:
            continue
        out.append(
            f"[h={line['height']} x={line['x0']} num={line['number_kind']}] {line['text']}"
        )
    return "\n".join(out)


def build_flexible_hierarchy_schema_format() -> dict[str, Any]:
    """Arm B 1단계 응답 형식. level 수는 고정하지 않되 JSON 객체 출력은 강제한다."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "flexible_hierarchy_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "levels": {
                        "type": "array",
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


def arm_b_decide_schema(
    first_page_text: str, tier_hint: int, rank_levels: dict[int, int]
) -> dict[str, Any]:
    rank_desc = (
        ", ".join(f"rank {r}->level {lvl}" for r, lvl in sorted(rank_levels.items()))
        if rank_levels
        else "번호 구조 없음"
    )
    user = (
        f"글씨 크기 tier 수 hint는 {tier_hint}개다. 번호 구조 기반 권장 매핑: {rank_desc}.\n"
        f"이 신호들을 종합해 계층 레벨을 정의하라.\n\n[첫 목차 페이지]\n{first_page_text}"
    )
    response = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": ARM_B_SCHEMA_SYSTEM},
            {"role": "user", "content": user},
        ],
        response_format=build_flexible_hierarchy_schema_format(),
        temperature=0.0,
    )
    return loads_lenient(response.choices[0].message.content)


def arm_b_extract_page(
    page_text: str, schema: dict[str, Any], pno: int
) -> list[dict[str, Any]]:
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
    user = (
        f"[계층 스키마 — 이 책 전체에 일관 적용]\n{schema_str}\n\n"
        f"[추출할 목차 페이지]\n{page_text}"
    )
    response = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": ARM_B_EXTRACT_SYSTEM},
            {"role": "user", "content": user},
        ],
        response_format=ARM_B_RESPONSE_FORMAT,
        temperature=0.0,
    )
    return loads_lenient(response.choices[0].message.content).get("items", [])


def build_rank_levels(lines: list[dict[str, Any]]) -> dict[int, int]:
    """번호 rank가 있는 줄들의 rank를 1부터의 level로 정규화 매핑한다."""

    ranks = sorted(
        {ln["number_rank"] for ln in lines if ln["number_rank"] is not None}
    )
    return {rank: idx + 1 for idx, rank in enumerate(ranks)}


def reconcile_levels(
    raw_items: list[dict[str, Any]],
    pno: int,
    rank_levels: dict[int, int],
) -> tuple[list[TocItem], int]:
    """LLM level을 받아 번호 깊이로 결정론적 정정한다. 충돌 건수도 반환한다.

    번호 구조가 있는 항목은 rank->level 매핑으로 강제하고, 번호가 없으면 LLM level을
    유지한다. 최종 정규화(1부터 시작)는 호출부에서 전체 항목에 적용한다.
    """

    items: list[TocItem] = []
    conflicts = 0
    for raw in raw_items:
        title = normalize_text(str(raw.get("title", "")).strip())
        if not title or is_title_word(title):
            continue
        if len(normalize_for_match(title).replace(" ", "")) < 2:
            continue
        llm_level = int(raw.get("level") or 1)
        _, rank = detect_number(title)
        if rank is not None and rank in rank_levels:
            forced = rank_levels[rank]
            if forced != llm_level:
                conflicts += 1
            level = forced
        else:
            level = llm_level
        page_value = raw.get("printed_page")
        items.append(
            TocItem(
                title=title,
                level=level,
                printed_page=int(page_value) if page_value else None,
                raw_text=title,
                source_pdf_page=pno,
                confidence=0.8,
            )
        )
    return items, conflicts


def normalize_levels_to_one(items: list[TocItem]) -> list[TocItem]:
    """전체 항목 level의 최솟값이 1이 되도록 균일 시프트한다."""

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


def run_arm_b(
    lines: list[dict[str, Any]], toc_pages: list[int], case_id: str
) -> tuple[list[TocItem], dict[str, Any], int]:
    cuts = cluster_cut_points([ln["height"] for ln in lines])
    tier_hint = len(content_tier_to_level(lines, cuts)) or 1
    rank_levels = build_rank_levels(lines)

    first_page_text = annotate_page_signals(lines, toc_pages[0])
    schema = arm_b_decide_schema(first_page_text, tier_hint, rank_levels)

    items: list[TocItem] = []
    total_conflicts = 0
    for pno in toc_pages:
        page_text = annotate_page_signals(lines, pno)
        raw_items = arm_b_extract_page(page_text, schema, pno)
        (OUTPUT_DIR / f"{_case_id(case_id)}_armB_page{pno}.json").write_text(
            json.dumps(raw_items, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        page_items, conflicts = reconcile_levels(raw_items, pno, rank_levels)
        total_conflicts += conflicts
        items.extend(page_items)

    items = normalize_levels_to_one(items)
    schema_record = {
        "tier_hint": tier_hint,
        "rank_to_level": {str(r): lvl for r, lvl in sorted(rank_levels.items())},
        "llm_schema": schema,
    }
    return items, schema_record, total_conflicts


# ---------------------------------------------------------------------------
# bookmark weak-reference 계층 비교
# ---------------------------------------------------------------------------
def normalize_bookmark_levels(bookmarks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """글자 있는 bookmark만 남기고 level 최솟값을 1로 정규화한다."""

    kept = [bm for bm in bookmarks if title_has_letter(bm["title"])]
    if not kept:
        return []
    min_level = min(bm["level"] for bm in kept)
    return [
        {"title": bm["title"], "level": bm["level"] - min_level + 1}
        for bm in kept
    ]


def weakref_level_agreement(
    items: list[TocItem], bookmarks: list[dict[str, Any]], score_cutoff: float = 88.0
) -> dict[str, Any]:
    """bookmark를 weak ref로 매칭해 level 깊이 일치율을 잰다.

    각 bookmark를 최선의 추출 항목과 fuzzy 매칭하고(점수>=cutoff), 매칭된 쌍에서
    정규화 level이 같은 비율을 본다. Luenberger처럼 bookmark가 일부 계층만 담아도
    '매칭된 항목의 level 깊이 일치'만 측정한다(전체 tree 정확도가 아니다).
    """

    ref = normalize_bookmark_levels(bookmarks)
    if not ref or not items:
        return {
            "bookmark_letter_count": len(ref),
            "matched": 0,
            "agreement": None,
            "match_rate": 0.0,
        }

    item_norms = [normalize_for_match(item.title) for item in items]
    index_by_norm: dict[str, int] = {}
    choices: list[str] = []
    for idx, norm in enumerate(item_norms):
        if norm and norm not in index_by_norm:
            index_by_norm[norm] = idx
            choices.append(norm)

    matched = 0
    agree = 0
    for bm in ref:
        bm_norm = normalize_for_match(bm["title"])
        if not bm_norm:
            continue
        result = process.extractOne(
            bm_norm, choices, scorer=fuzz.token_set_ratio, score_cutoff=score_cutoff
        )
        if result is None:
            continue
        matched += 1
        item_idx = index_by_norm[result[0]]
        if items[item_idx].level == bm["level"]:
            agree += 1

    return {
        "bookmark_letter_count": len(ref),
        "matched": matched,
        "match_rate": round(matched / len(ref), 4) if ref else 0.0,
        "agreement": round(agree / matched, 4) if matched else None,
        "agree_count": agree,
    }


# ---------------------------------------------------------------------------
# 트리 / 지표 / 실행
# ---------------------------------------------------------------------------
def _case_id(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_")[:80]


def render_tree(items: list[TocItem]) -> list[str]:
    out: list[str] = []
    for item in items:
        indent = "    " * max(item.level - 1, 0)
        page = item.printed_page if item.printed_page is not None else "-"
        out.append(f"{indent}[{page}] L{item.level} {item.title}")
    return out


def hierarchy_metrics(items: list[TocItem]) -> dict[str, Any]:
    levels = [item.level for item in items]
    dist = {str(k): v for k, v in sorted(Counter(levels).items())}
    return {
        "item_count": len(items),
        "level_distribution": dist,
        "distinct_levels": len(set(levels)),
        "min_level": min(levels) if levels else None,
        "max_level": max(levels) if levels else None,
        "starts_at_level_1": bool(levels) and min(levels) == 1,
    }


def contents_segment_pages(label: dict[str, Any]) -> list[int]:
    """brief/detailed 중복을 피하려고 kind=='contents' segment page만 모은다."""

    segments = label.get("toc_segments") or []
    pages: list[int] = []
    for seg in segments:
        if seg.get("kind") == "contents":
            pages.extend(range(seg["start_page"], seg["end_page"] + 1))
    if not pages:
        pages = list(label["toc_pages"])
    return sorted(dict.fromkeys(pages))


def run_book(label: dict[str, Any]) -> dict[str, Any]:
    pdf_path = ROOT_DIR / label["input_pdf"]
    case_id = label["id"]
    toc_pages = contents_segment_pages(label)
    record: dict[str, Any] = {
        "id": case_id,
        "input_pdf": label["input_pdf"],
        "contents_pages": toc_pages,
    }
    if not pdf_path.exists():
        record["status"] = "missing_pdf"
        return record

    lines = extract_toc_lines(pdf_path, toc_pages)
    if not lines:
        record["status"] = "no_lines"
        return record

    # Arm A baseline.
    items_a = run_arm_a(lines, toc_pages)
    (OUTPUT_DIR / f"{_case_id(case_id)}_tree_armA.txt").write_text(
        "\n".join(render_tree(items_a)) + "\n", encoding="utf-8"
    )

    # Arm B llm_reasoned + reconciliation.
    items_b, schema_record, conflicts = run_arm_b(lines, toc_pages, case_id)
    (OUTPUT_DIR / f"{_case_id(case_id)}_tree_armB.txt").write_text(
        "\n".join(render_tree(items_b)) + "\n", encoding="utf-8"
    )
    (OUTPUT_DIR / f"{_case_id(case_id)}_schema.json").write_text(
        json.dumps(schema_record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    record["status"] = "ok"
    record["number_kind_distribution"] = {
        k: v for k, v in sorted(Counter(ln["number_kind"] for ln in lines).items())
    }
    record["arm_a"] = hierarchy_metrics(items_a)
    record["arm_b"] = hierarchy_metrics(items_b)
    record["arm_b"]["reconcile_conflict_count"] = conflicts
    record["arm_b_tree_preview"] = render_tree(items_b)[:24]

    # bookmark weak-ref 비교.
    if case_id in BOOKMARKED_IDS:
        bookmarks = extract_existing_bookmarks(pdf_path)
        record["weakref_arm_a"] = weakref_level_agreement(items_a, bookmarks)
        record["weakref_arm_b"] = weakref_level_agreement(items_b, bookmarks)

    return record


def record_experiment(summary: dict[str, Any]) -> None:
    """experiments.json에 이번 실험 결과를 append/갱신한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "목차 계층 신호를 글씨 height 단일에서 번호구조+들여쓰기(x0)+height "
            "하이브리드로 확장하고, LLM이 level을 추론하되 번호 깊이로 결정론적 "
            "정정(reconciliation)한다. Arm A(height-only baseline)와 Arm B(신호 융합)를 "
            "비교하고 bookmark weak ref로 level 깊이 일치율을 잰다."
        ),
        "inputs": [label["input_pdf"] for label in summary["_labels_used"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "experiments\\labels\\answer_toc_ranges_manual.json",
        "model": MODEL,
        "temperature": 0.0,
        "finding": summary["finding"],
        "ran_at": summary["ran_at"],
    }
    experiments = data.get("experiments", data) if isinstance(data, dict) else data
    experiments = [item for item in experiments if item.get("id") != EXPERIMENT_ID]
    experiments.append(entry)
    if isinstance(data, dict):
        data["experiments"] = experiments
    else:
        data = experiments
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def build_finding(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        a = r["arm_a"]
        b = r["arm_b"]
        piece = (
            f"{r['id']}: ArmA level={a['level_distribution']}(starts1={a['starts_at_level_1']}) "
            f"-> ArmB level={b['level_distribution']}(starts1={b['starts_at_level_1']}, "
            f"conflicts={b['reconcile_conflict_count']})"
        )
        if "weakref_arm_b" in r:
            wa = r["weakref_arm_a"]
            wb = r["weakref_arm_b"]
            piece += (
                f". weakref level agreement ArmA={wa['agreement']}"
                f"(matched {wa['matched']}/{wa['bookmark_letter_count']}) "
                f"-> ArmB={wb['agreement']}(matched {wb['matched']}/{wb['bookmark_letter_count']})"
            )
        parts.append(piece)
    return " | ".join(parts)


def main() -> None:
    from datetime import datetime

    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = {
        lab["id"]: lab
        for lab in json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]
    }
    used_labels = [labels[i] for i in TARGET_IDS if i in labels]
    results = [run_book(label) for label in used_labels]

    finding = build_finding(results)
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "purpose": (
            "목차 계층 신호 융합(height+x0+번호구조)과 LLM-reasoned level + 결정론적 "
            "번호 reconciliation을 height-only baseline과 비교한다."
        ),
        "model": MODEL,
        "labels_source": str(LABELS_PATH.relative_to(ROOT_DIR)),
        "scope": "hierarchy_only",
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "finding": finding,
        "results": results,
        "_labels_used": used_labels,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(
            {k: v for k, v in summary.items() if k != "_labels_used"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    record_experiment(summary)

    print("=== exp 023: 목차 계층 신호 융합 (Arm A baseline vs Arm B 신호융합) ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']}: {r.get('status')}")
            continue
        print(f"\n- {r['id']} (pages={r['contents_pages']})")
        print(f"    num_kind: {r['number_kind_distribution']}")
        print(
            f"    Arm A: {r['arm_a']['level_distribution']} "
            f"starts1={r['arm_a']['starts_at_level_1']}"
        )
        print(
            f"    Arm B: {r['arm_b']['level_distribution']} "
            f"starts1={r['arm_b']['starts_at_level_1']} "
            f"conflicts={r['arm_b']['reconcile_conflict_count']}"
        )
        if "weakref_arm_b" in r:
            print(
                f"    weakref agreement A={r['weakref_arm_a']['agreement']} "
                f"B={r['weakref_arm_b']['agreement']}"
            )
        print("    Arm B tree preview:")
        for line in r["arm_b_tree_preview"][:16]:
            print(f"      {line}")
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
