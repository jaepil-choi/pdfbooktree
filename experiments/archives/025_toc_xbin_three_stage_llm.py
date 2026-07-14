"""experiment 025: Tier + xbin(10) 신호 / 3-stage LLM 목차 추출.

배경
- experiment 017/021에서 글씨 height tier로 계층 수를 잡는 것은 유효했다.
- experiment 024는 raw title_x 들여쓰기를 깊이 신호로 쓰자 OCR x-jitter가 KDE
  봉우리를 과생성해 john_hull이 7 level로 붕괴했다.
- experiment 023은 LLM에 level을 자유 추론시키자 번호 없는 줄이 무한 over-deepening
  됐다(hull weakref 0.90->0.07).

아이디어(사용자 제안)
- (1) height tier는 그대로 쓴다(유효).
- (2) x 좌표는 raw로 주지 말고 page 폭 기준 10 bin으로 이산화해 bin 번호를 준다.
  bin 경계가 px jitter보다 넓어 024의 과분할을 누른다.
- (3) workflow를 3개 LLM call로 분리한다.
    Call 1: 첫 목차 페이지 text 전체로 '계층 schema'만 결정.
    Call 2: 그 schema에 맞춰 페이지별로 목차 item을 채운다.
    Call 3: 제목 OCR 오탈자 등 correction만 한다(계층 불변, 단일 1패스).

회귀 방지 비교(Call 2를 두 arm으로)
- Arm L (lookup): level은 코드가 (tier,xbin)->schema 매핑으로 부여. LLM은 항목
  분리/페이지번호만(021 정신: 계층은 코드 소유).
- Arm R (reasoned-bounded): LLM이 level을 정하되 schema의 level 집합 밖으로 못
  나간다. 023 over-deepening이 bound로 막히는지 본다.

평가(024 계승): rel_depth_agreement(주력) + abs_level_agreement + bookmark weakref,
그리고 Call 3 전/후 bookmark match_rate로 교정 품질을 본다.

범위: 계층 + 제목 교정. brief/detailed 범위 선택은 다음 라운드.

출력: experiments/outputs/025_toc_xbin_three_stage_llm/
실행: uv run python experiments/025_toc_xbin_three_stage_llm.py
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from dotenv import load_dotenv
from rapidfuzz import fuzz, process

from pdfbooktree.models import TocItem
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, title_has_letter
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "025_toc_xbin_three_stage_llm"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "025_toc_xbin_three_stage_llm"

TARGET_IDS = [
    "john_hull",
    "luenberger_investment_science",
    "shreve_binomial",
    "algorithms_to_live_by",
    "algorithm_nine",
]
BOOKMARKED_IDS = {"john_hull", "luenberger_investment_science", "shreve_binomial"}

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
MODEL = "solar-pro3"
N_XBINS = 10

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
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def is_title_word(text: str) -> bool:
    return normalize_for_match(text) in _TITLE_WORDS


# ---------------------------------------------------------------------------
# 1단계: 줄 신호 추출 (height + xbin)
# ---------------------------------------------------------------------------
def extract_toc_lines(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """TOC page들에서 줄별 text, 대표 height, page 폭 상대 xbin을 뽑는다."""

    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pno in toc_pages:
            page = document.load_page(pno - 1)
            page_width = float(page.rect.width) or 1.0
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    heights: list[float] = []
                    x_lefts: list[float] = []
                    parts: list[str] = []
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
                    title_x = min(x_lefts)
                    xbin = min(N_XBINS - 1, max(0, int(title_x / page_width * N_XBINS)))
                    lines.append(
                        {
                            "pdf_page": pno,
                            "text": normalize_text(" ".join(parts)),
                            "height": max(heights),
                            "xbin": xbin,
                        }
                    )
    return lines


def cluster_cut_points(values: list[float]) -> list[float]:
    """1D 값의 봉우리 사이 골짜기 경계(height tier용)."""

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
        i for i in range(1, len(density) - 1)
        if density[i - 1] < density[i] > density[i + 1]
    ]
    if not peak_idx:
        return []
    valley_idx = [
        i for i in range(1, len(density) - 1)
        if density[i - 1] > density[i] < density[i + 1]
    ]
    peaks = [float(grid[i]) for i in peak_idx]
    return sorted(
        float(grid[i]) for i in valley_idx if min(peaks) < float(grid[i]) < max(peaks)
    )


def assign_tier(height: float, cuts: list[float]) -> int:
    tier = 1
    for cut in sorted(cuts, reverse=True):
        if height >= cut:
            return tier
        tier += 1
    return tier


def content_tier_to_level(
    lines: list[dict[str, Any]], cuts: list[float]
) -> dict[int, int]:
    content_tiers = sorted(
        {assign_tier(ln["height"], cuts) for ln in lines if not is_title_word(ln["text"])}
    )
    return {tier: idx + 1 for idx, tier in enumerate(content_tiers)}


def annotate_page(lines: list[dict[str, Any]], pno: int, cuts: list[float]) -> str:
    out = [f"--- PDF page {pno} ---"]
    for line in lines:
        if line["pdf_page"] != pno:
            continue
        tier = assign_tier(line["height"], cuts)
        out.append(
            f'[T{tier} x{line["xbin"]}] {escape(line["text"], quote=False)}'
        )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------
_CLIENT: Any = None
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def client() -> Any:
    global _CLIENT
    if _CLIENT is None:
        from openai import OpenAI

        api_key = os.environ.get("UPSTAGE_API_KEY")
        if not api_key:
            raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
        _CLIENT = OpenAI(api_key=api_key, base_url=UPSTAGE_BASE_URL)
    return _CLIENT


def loads_lenient(content: str | None) -> dict[str, Any]:
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
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


def chat(system: str, user: str, response_format: dict[str, Any]) -> dict[str, Any]:
    response = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=response_format,
        temperature=0.0,
    )
    return loads_lenient(response.choices[0].message.content)


# ---------------------------------------------------------------------------
# Call 1: 계층 schema 결정
# ---------------------------------------------------------------------------
SCHEMA_SYSTEM = (
    "너는 책 목차의 '첫 페이지'를 보고 이 책 목차의 계층 schema를 정의하는 도구다.\n"
    "각 줄 앞 대괄호에는 두 신호가 있다.\n"
    "- T: 글씨 크기 tier(T1이 가장 큰 글씨, 작을수록 상위 계층 가능성).\n"
    "- x: 줄 시작 위치를 page 폭 기준 0~9로 나눈 들여쓰기 bin(작을수록 왼쪽=상위, "
    "클수록 들여써짐=하위).\n"
    "규칙:\n"
    "- 계층 레벨 수는 글씨 크기 클러스터로 이미 정해졌다. 사용자가 주는 tier 개수만큼만 "
    "레벨을 정의하고 더 쪼개거나 합치지 마라.\n"
    "- 각 레벨에 어떤 (T, x) 조합이 속하는지 매핑 규칙을 cues에 명확히 적어라.\n"
    "각 레벨에 level(1부터 연속), name(부/장/절 또는 part/chapter/section 등), "
    "cues((T,x) 매핑 규칙), examples(첫 페이지의 해당 제목 1~3개)를 적는다. "
    "'목차'/'Contents' 같은 페이지 머리말은 레벨에서 제외한다. 이 schema는 이후 이 책의 "
    "모든 목차 페이지에 일관 적용된다."
)


def schema_format(n_levels: int) -> dict[str, Any]:
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


def call1_schema(first_page_text: str, tier_levels: dict[int, int]) -> dict[str, Any]:
    n = len(tier_levels)
    tier_desc = ", ".join(f"T{t}=level {lv}" for t, lv in sorted(tier_levels.items()))
    user = (
        f"글씨 크기 클러스터 결과, 이 책 목차의 content tier는 {n}개다 ({tier_desc}). "
        f"따라서 레벨도 정확히 {n}개로 정의하라.\n\n[첫 목차 페이지]\n{first_page_text}"
    )
    return chat(SCHEMA_SYSTEM, user, schema_format(n))


# ---------------------------------------------------------------------------
# Call 2: 항목 채우기 (Arm L lookup / Arm R reasoned-bounded)
# ---------------------------------------------------------------------------
EXTRACT_SYSTEM_L = (
    "너는 책 목차 페이지에서 항목을 추출하는 도구다. 각 줄 앞 [Tn xk]은 그 줄의 글씨 "
    "tier와 들여쓰기 bin이다.\n"
    "절대 규칙: 계층/레벨은 네가 정하지 않는다. 각 항목의 tier는 그 항목이 나온 줄의 "
    "[Tn] 숫자(n)를 그대로 복사만 한다. 한 줄을 여러 항목으로 쪼개면 모든 조각은 그 줄과 "
    "같은 tier를 받는다.\n"
    "너가 하는 일은 다음뿐이다.\n"
    "- 항목 분리: 한 줄에 'I'/'|'/'·'/'•' 구분자와 페이지 번호로 여러 항목이 합쳐져 있으면 분리한다.\n"
    "- 페이지 번호: printed_page는 제목 뒤 인쇄 페이지 번호, 없으면 null.\n"
    "- 제목 글씨가 깨진 줄도 빼지 말고 반드시 항목으로 낸다(교정은 다음 단계에서 한다).\n"
    "- '목차'/'Contents' 같은 머리말 한 마디 줄은 항목으로 만들지 않는다.\n"
    "- 항목은 이 페이지에 나온 순서 그대로 반환한다."
)

EXTRACT_FORMAT_L = {
    "type": "json_schema",
    "json_schema": {
        "name": "toc_extract_tier",
        "schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tier": {"type": "integer"},
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

EXTRACT_SYSTEM_R = (
    "너는 책 목차 페이지에서 항목을 추출하는 도구다. 아래 [계층 schema]를 이 책 전체에 "
    "일관 적용한다. 각 줄 앞 [Tn xk]은 그 줄의 글씨 tier와 들여쓰기 bin이다.\n"
    "각 항목에 대해:\n"
    "- level: [계층 schema]의 cues와 그 줄의 [Tn xk]를 종합해 정한다. 반드시 schema에 "
    "정의된 level 중 하나여야 하며 schema 밖의 더 깊은 level을 새로 만들지 마라.\n"
    "- 항목 분리: 구분자/페이지번호로 합쳐진 줄은 각 항목으로 분리하고, 조각은 같은 level을 공유한다.\n"
    "- printed_page: 제목 뒤 인쇄 페이지 번호, 없으면 null.\n"
    "- 제목 글씨가 깨진 줄도 빼지 말고 반드시 낸다(교정은 다음 단계).\n"
    "- 머리말 한 마디 줄은 만들지 않고, 항목은 나온 순서대로 반환한다."
)

EXTRACT_FORMAT_R = {
    "type": "json_schema",
    "json_schema": {
        "name": "toc_extract_level",
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


def call2_extract_page(
    page_text: str, schema: dict[str, Any], arm: str
) -> list[dict[str, Any]]:
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)
    user = (
        f"[계층 schema - 이 책 전체에 일관 적용]\n{schema_str}\n\n"
        f"[추출할 목차 페이지]\n{page_text}"
    )
    system = EXTRACT_SYSTEM_L if arm == "L" else EXTRACT_SYSTEM_R
    fmt = EXTRACT_FORMAT_L if arm == "L" else EXTRACT_FORMAT_R
    return chat(system, user, fmt).get("items", [])


# ---------------------------------------------------------------------------
# Call 3: 제목 OCR 교정 (계층 불변, 단일 1패스)
# ---------------------------------------------------------------------------
CORRECT_SYSTEM = (
    "너는 OCR로 깨진 목차 제목을 교정하는 도구다. 입력 항목들의 title에서 OCR 오인식/"
    "깨진 글자/붙은 띄어쓰기만 자연스럽게 고친다.\n"
    "절대 규칙:\n"
    "- 항목 개수, 순서, level, printed_page를 절대 바꾸지 마라. 입력과 1:1로 대응하는 "
    "교정된 title만 같은 순서로 반환한다.\n"
    "- 없는 내용을 지어내지 말고, 의미가 분명한 OCR 오류만 고친다. 확신이 없으면 원문을 둔다."
)

CORRECT_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "toc_title_correction",
        "schema": {
            "type": "object",
            "properties": {
                "titles": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["titles"],
        },
    },
}


def call3_correct(titles: list[str]) -> list[str]:
    if not titles:
        return titles
    user = "교정할 목차 제목들(순서 유지):\n" + json.dumps(
        titles, ensure_ascii=False, indent=2
    )
    result = chat(CORRECT_SYSTEM, user, CORRECT_FORMAT).get("titles", [])
    # 개수가 어긋나면 안전하게 원문 유지.
    if len(result) != len(titles):
        return titles
    return [normalize_text(str(t).strip()) or titles[i] for i, t in enumerate(result)]


# ---------------------------------------------------------------------------
# 줄 -> items (arm별)
# ---------------------------------------------------------------------------
def best_line_tier(
    title: str, page_lines: list[dict[str, Any]], cuts: list[float]
) -> int | None:
    """제목과 가장 겹치는 원문 줄의 tier(보정용). 매칭 약하면 None."""

    title_norm = normalize_for_match(title)
    if not title_norm:
        return None
    best_score, best_tier = 0.0, None
    for ln in page_lines:
        if is_title_word(ln["text"]):
            continue
        ln_norm = normalize_for_match(ln["text"])
        if not ln_norm:
            continue
        score = fuzz.partial_ratio(title_norm, ln_norm)
        if score > best_score:
            best_score, best_tier = score, assign_tier(ln["height"], cuts)
    return best_tier if best_score >= 65.0 else None


def build_items_arm_l(
    raw_items: list[dict[str, Any]],
    pno: int,
    tier_levels: dict[int, int],
    page_lines: list[dict[str, Any]],
    cuts: list[float],
) -> list[TocItem]:
    max_level = max(tier_levels.values()) if tier_levels else 1
    items: list[TocItem] = []
    for raw in raw_items:
        title = normalize_text(str(raw.get("title", "")).strip())
        if not title or is_title_word(title):
            continue
        if len(normalize_for_match(title).replace(" ", "")) < 2:
            continue
        tier = int(raw.get("tier") or 1)
        corrected = best_line_tier(title, page_lines, cuts)
        if corrected is not None:
            tier = corrected
        items.append(_mk(title, tier_levels.get(tier, max_level), raw, pno))
    return items


def build_items_arm_r(
    raw_items: list[dict[str, Any]], pno: int, n_levels: int
) -> list[TocItem]:
    items: list[TocItem] = []
    for raw in raw_items:
        title = normalize_text(str(raw.get("title", "")).strip())
        if not title or is_title_word(title):
            continue
        if len(normalize_for_match(title).replace(" ", "")) < 2:
            continue
        level = int(raw.get("level") or 1)
        level = max(1, min(level, n_levels))  # schema bound 강제.
        items.append(_mk(title, level, raw, pno))
    return items


def _mk(title: str, level: int, raw: dict[str, Any], pno: int) -> TocItem:
    page_value = raw.get("printed_page")
    return TocItem(
        title=title,
        level=level,
        printed_page=int(page_value) if page_value else None,
        raw_text=title,
        source_pdf_page=pno,
        confidence=0.8,
    )


def apply_correction(items: list[TocItem]) -> list[TocItem]:
    """Call 3을 페이지 그룹별로 호출해 title만 교정한다(계층 불변)."""

    by_page: dict[int, list[int]] = {}
    for idx, it in enumerate(items):
        by_page.setdefault(it.source_pdf_page, []).append(idx)

    new_titles = [it.title for it in items]
    for _, idxs in sorted(by_page.items()):
        corrected = call3_correct([items[i].title for i in idxs])
        for i, c in zip(idxs, corrected):
            new_titles[i] = c

    return [
        TocItem(
            title=new_titles[i],
            level=it.level,
            printed_page=it.printed_page,
            raw_text=it.raw_text,
            source_pdf_page=it.source_pdf_page,
            confidence=it.confidence,
        )
        for i, it in enumerate(items)
    ]


def normalize_levels_to_one(items: list[TocItem]) -> list[TocItem]:
    if not items:
        return items
    shift = min(it.level for it in items) - 1
    if shift <= 0:
        return items
    return [
        TocItem(
            title=it.title,
            level=it.level - shift,
            printed_page=it.printed_page,
            raw_text=it.raw_text,
            source_pdf_page=it.source_pdf_page,
            confidence=it.confidence,
        )
        for it in items
    ]


# ---------------------------------------------------------------------------
# bookmark weak-ref 지표 (024 계승)
# ---------------------------------------------------------------------------
def normalize_bookmark_levels(bookmarks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [bm for bm in bookmarks if title_has_letter(bm["title"])]
    if not kept:
        return []
    min_level = min(bm["level"] for bm in kept)
    return [
        {"title": bm["title"], "level": bm["level"] - min_level + 1, "order": bm["order"]}
        for bm in kept
    ]


def match_pairs(
    items: list[TocItem], ref: list[dict[str, Any]], score_cutoff: float = 88.0
) -> list[tuple[dict[str, Any], TocItem]]:
    item_norms = [normalize_for_match(it.title) for it in items]
    index_by_norm: dict[str, int] = {}
    choices: list[str] = []
    for idx, norm in enumerate(item_norms):
        if norm and norm not in index_by_norm:
            index_by_norm[norm] = idx
            choices.append(norm)
    pairs: list[tuple[dict[str, Any], TocItem]] = []
    for bm in ref:
        bm_norm = normalize_for_match(bm["title"])
        if not bm_norm:
            continue
        result = process.extractOne(
            bm_norm, choices, scorer=fuzz.token_set_ratio, score_cutoff=score_cutoff
        )
        if result is None:
            continue
        pairs.append((bm, items[index_by_norm[result[0]]]))
    return pairs


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def weakref_metrics(
    items: list[TocItem], bookmarks: list[dict[str, Any]]
) -> dict[str, Any]:
    ref = normalize_bookmark_levels(bookmarks)
    if not ref or not items:
        return {"bookmark_letter_count": len(ref), "matched": 0}
    pairs = match_pairs(items, ref)
    matched = len(pairs)
    abs_agree = sum(1 for bm, it in pairs if bm["level"] == it.level)
    pairs_sorted = sorted(pairs, key=lambda p: p[0]["order"])
    trans_total, trans_agree = 0, 0
    for (bm_a, it_a), (bm_b, it_b) in zip(pairs_sorted, pairs_sorted[1:]):
        trans_total += 1
        if _sign(bm_b["level"] - bm_a["level"]) == _sign(it_b.level - it_a.level):
            trans_agree += 1
    return {
        "bookmark_letter_count": len(ref),
        "matched": matched,
        "match_rate": round(matched / len(ref), 4) if ref else 0.0,
        "abs_level_agreement": round(abs_agree / matched, 4) if matched else None,
        "rel_depth_agreement": round(trans_agree / trans_total, 4) if trans_total else None,
    }


# ---------------------------------------------------------------------------
# 트리/지표/실행
# ---------------------------------------------------------------------------
def render_tree(items: list[TocItem]) -> list[str]:
    out: list[str] = []
    for it in items:
        indent = "    " * max(it.level - 1, 0)
        page = it.printed_page if it.printed_page is not None else "-"
        out.append(f"{indent}[{page}] L{it.level} {it.title}")
    return out


def hierarchy_metrics(items: list[TocItem]) -> dict[str, Any]:
    levels = [it.level for it in items]
    return {
        "item_count": len(items),
        "level_distribution": {str(k): v for k, v in sorted(Counter(levels).items())},
        "distinct_levels": len(set(levels)),
        "starts_at_level_1": bool(levels) and min(levels) == 1,
    }


def contents_segment_pages(label: dict[str, Any]) -> list[int]:
    pages: list[int] = []
    for seg in label.get("toc_segments") or []:
        if seg.get("kind") == "contents":
            pages.extend(range(seg["start_page"], seg["end_page"] + 1))
    if not pages:
        pages = list(label["toc_pages"])
    return sorted(dict.fromkeys(pages))


def _case_id(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_")[:80]


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

    cuts = cluster_cut_points([ln["height"] for ln in lines])
    tier_levels = content_tier_to_level(lines, cuts)
    n_levels = len(tier_levels) or 1

    # Call 1: schema.
    first_page_text = annotate_page(lines, toc_pages[0], cuts)
    schema = call1_schema(first_page_text, tier_levels)

    # Call 2: 두 arm.
    items_l: list[TocItem] = []
    items_r: list[TocItem] = []
    raw_dump: dict[str, Any] = {"L": {}, "R": {}}
    for pno in toc_pages:
        page_text = annotate_page(lines, pno, cuts)
        page_lines = [ln for ln in lines if ln["pdf_page"] == pno]

        raw_l = call2_extract_page(page_text, schema, "L")
        raw_dump["L"][str(pno)] = raw_l
        items_l.extend(build_items_arm_l(raw_l, pno, tier_levels, page_lines, cuts))

        raw_r = call2_extract_page(page_text, schema, "R")
        raw_dump["R"][str(pno)] = raw_r
        items_r.extend(build_items_arm_r(raw_r, pno, n_levels))

    items_l = normalize_levels_to_one(items_l)
    items_r = normalize_levels_to_one(items_r)

    # Call 3: 교정(주 arm은 R; lookup arm은 비교용으로 교정 전만 둔다).
    items_r_corr = apply_correction(items_r)

    cid = _case_id(case_id)
    (OUTPUT_DIR / f"{cid}_schema.json").write_text(
        json.dumps({"tier_levels": {str(k): v for k, v in tier_levels.items()},
                    "schema": schema}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / f"{cid}_raw.json").write_text(
        json.dumps(raw_dump, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name, items in [
        ("L", items_l), ("R", items_r), ("R_corrected", items_r_corr)
    ]:
        (OUTPUT_DIR / f"{cid}_tree_{name}.txt").write_text(
            "\n".join(render_tree(items)) + "\n", encoding="utf-8"
        )

    record["status"] = "ok"
    record["n_levels_hint"] = n_levels
    record["tier_levels"] = {str(k): v for k, v in tier_levels.items()}
    record["arm_l"] = hierarchy_metrics(items_l)
    record["arm_r"] = hierarchy_metrics(items_r)
    record["r_corrected_preview"] = render_tree(items_r_corr)[:20]

    if case_id in BOOKMARKED_IDS:
        bookmarks = extract_existing_bookmarks(pdf_path)
        record["weakref_l"] = weakref_metrics(items_l, bookmarks)
        record["weakref_r"] = weakref_metrics(items_r, bookmarks)
        record["weakref_r_corrected"] = weakref_metrics(items_r_corr, bookmarks)
    return record


def build_finding(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        piece = (
            f"{r['id']}(n={r['n_levels_hint']}): "
            f"L={r['arm_l']['level_distribution']} "
            f"R={r['arm_r']['level_distribution']}"
        )
        if "weakref_r" in r:
            piece += (
                f". rel_depth L={r['weakref_l'].get('rel_depth_agreement')}"
                f"/R={r['weakref_r'].get('rel_depth_agreement')}"
                f" abs L={r['weakref_l'].get('abs_level_agreement')}"
                f"/R={r['weakref_r'].get('abs_level_agreement')}"
                f" match {r['weakref_r'].get('match_rate')}"
                f"->corr {r['weakref_r_corrected'].get('match_rate')}"
            )
        parts.append(piece)
    return " | ".join(parts)


def record_experiment(summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "height tier(유효)는 유지하고 x를 page 폭 기준 10 bin으로 이산화해 신호로 준다. "
            "workflow를 3개 LLM call로 분리한다(Call1 schema 결정 / Call2 항목 채우기 / "
            "Call3 제목 교정). Call2는 Arm L(코드가 tier->level) vs Arm R(LLM이 schema "
            "bound 안에서 level 추론)로 비교하고 bookmark weak ref로 rel_depth/abs level "
            "일치율과 교정 전후 match_rate를 잰다."
        ),
        "inputs": [lab["input_pdf"] for lab in summary["_labels_used"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "experiments\\labels\\answer_toc_ranges_manual.json",
        "model": MODEL,
        "temperature": 0.0,
        "finding": summary["finding"],
        "ran_at": summary["ran_at"],
    }
    experiments = data.get("experiments", data) if isinstance(data, dict) else data
    experiments = [e for e in experiments if e.get("id") != EXPERIMENT_ID]
    experiments.append(entry)
    if isinstance(data, dict):
        data["experiments"] = experiments
    else:
        data = experiments
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = {
        lab["id"]: lab
        for lab in json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]
    }
    used_labels = [labels[i] for i in TARGET_IDS if i in labels]

    results: list[dict[str, Any]] = []
    for lab in used_labels:
        print(f"... running {lab['id']}", flush=True)
        results.append(run_book(lab))

    finding = build_finding(results)
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "scope": "hierarchy_and_title_correction",
        "model": MODEL,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "finding": finding,
        "results": results,
        "_labels_used": used_labels,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(
            {k: v for k, v in summary.items() if k != "_labels_used"},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    record_experiment(summary)

    print("\n=== exp 025: Tier+xbin / 3-stage LLM (Arm L lookup vs Arm R bounded) ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']}: {r.get('status')}")
            continue
        print(f"\n- {r['id']} (n_levels={r['n_levels_hint']}, tiers={r['tier_levels']})")
        print(f"    L: {r['arm_l']['level_distribution']}")
        print(f"    R: {r['arm_r']['level_distribution']}")
        if "weakref_r" in r:
            print(
                f"    rel_depth L={r['weakref_l'].get('rel_depth_agreement')} "
                f"R={r['weakref_r'].get('rel_depth_agreement')} | "
                f"abs L={r['weakref_l'].get('abs_level_agreement')} "
                f"R={r['weakref_r'].get('abs_level_agreement')}"
            )
            print(
                f"    match_rate R={r['weakref_r'].get('match_rate')} "
                f"-> corrected {r['weakref_r_corrected'].get('match_rate')}"
            )
        print("    R(corrected) preview:")
        for line in r["r_corrected_preview"][:12]:
            print(f"      {line}")
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
