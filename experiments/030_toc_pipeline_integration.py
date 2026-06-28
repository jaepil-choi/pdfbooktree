"""experiment 030: 채택 아키텍처(029) end-to-end 통합 + luenberger 계층 분리 개선.

배경
- experiment 029: '결정론 멀티피처 클러스터(028) + LLM이 클러스터 순서(레벨)만 결정'이 전 실험
  통틀어 최고였다(hull abs 0.02->0.955, shreve abs 0.84->0.895). 분업 확정:
  계층=코드 클러스터, 순서/병합=LLM 1콜.
- experiment 025: Call2 항목분리(한 줄 다항목 -> 분리, level은 코드 소유)와 Call3 제목 OCR
  교정이 둘 다 성공했다(한국어 제목 극적 개선). 그러나 025의 계층은 tier-cap이라 영어
  다단계를 평탄화했다 -> 029 클러스터 계층으로 교체해야 한다.

이 실험(030)이 합치는 것
- 029의 (1) 결정론 클러스터 + (2) LLM 클러스터 순서/병합으로 줄별 level을 결정론적으로 확정.
- 그 level을 [Ln] 마커로 줄에 입혀 (3) Call: 페이지별 항목분리(한국어 2단 목차의 한 줄 다항목
  분리, printed_page 추출). level은 LLM이 못 만들고 [Ln]을 복사만 한다(025 Arm L 정신).
- (4) Call: 제목 OCR 교정(계층/개수/순서 불변, 025 Call3).
- 비교 baseline B: 029처럼 줄=항목 1:1, 분리/교정 없음. full F: 분리+교정.

luenberger 개선(029 남은 과제)
- 029는 luenberger의 Section(times,258)/Subsection(helvetica,208)을 한 L2로 병합했다.
  028 클러스터는 글꼴로 둘을 이미 갈라 놓는다 -> Call(순서)에서 병합되지 않게, 클러스터
  요약에 글꼴/굵기/평균높이를 더 또렷이 주고 '같은 글씨라도 서로 다른 글꼴 계열이고 예시가
  서로 다른 구조 단위면 별도 level로 두라'고 명시(단, 예시가 같은 단위면 병합 허용=hull 보존).

평가(024~029 계승): rel_depth_agreement(주력) + abs_level + bookmark weakref. 추가로 분리
이득(split_gain=full item수-baseline item수)과 교정 전후 match_rate.

출력: experiments/outputs/030_toc_pipeline_integration/
실행: uv run python experiments/030_toc_pipeline_integration.py
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
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
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "030_toc_pipeline_integration"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "030_toc_pipeline_integration"

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
COLUMN_GAP_FRAC = 0.03
COLUMN_MIN_SUPPORT = 2
COLUMN_RELIABLE_STD_FRAC = 0.025

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_SUBSET = re.compile(r"^[A-Z]{6}\+")
_TITLE_WORDS = {
    "목차", "목 차", "차례", "contents", "contents in brief",
    "brief contents", "table of contents",
}


def is_content_span(text: str) -> bool:
    s = text.strip()
    return bool(s and (_HANGUL.search(s) or _LATIN2.search(s)))


def is_title_word(text: str) -> bool:
    return normalize_for_match(text) in _TITLE_WORDS


def base_font(name: str) -> str:
    return _SUBSET.sub("", name).split("-")[0].split(",")[0].lower()


def span_is_bold(span: dict[str, Any]) -> bool:
    return bool(span["flags"] & 2**4) or ("bold" in span["font"].lower())


# ---------------------------------------------------------------------------
# 1) 줄 신호 추출 + tier + robust 컬럼 (029 재사용)
# ---------------------------------------------------------------------------
def extract_toc_lines(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pno in toc_pages:
            page = document.load_page(pno - 1)
            page_width = float(page.rect.width) or 1.0
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    spans = [s for s in line["spans"] if s["text"].strip()]
                    content_spans = [s for s in spans if is_content_span(s["text"])]
                    if not content_spans:
                        continue
                    content_spans.sort(key=lambda s: s["bbox"][0])
                    head = content_spans[0]
                    heights = [round(s["bbox"][3] - s["bbox"][1], 2) for s in content_spans]
                    parts = [s["text"].strip() for s in spans]
                    trailing = re.findall(r"\d+", " ".join(parts))
                    lines.append(
                        {
                            "pdf_page": pno,
                            "text": normalize_text(" ".join(parts)),
                            "height": max(heights),
                            "title_x": round(float(head["bbox"][0]), 2),
                            "page_width": page_width,
                            "is_bold": span_is_bold(head),
                            "font_type": base_font(head["font"]),
                            "trailing_page": int(trailing[-1]) if trailing else None,
                        }
                    )
    return lines


def cluster_cut_points(values: list[float]) -> list[float]:
    if not values:
        return []
    arr = np.asarray(values, dtype=float)
    if np.unique(arr).size <= 1:
        return []
    std = float(np.std(arr, ddof=1))
    if std <= 0.0:
        return []
    bw = 1.06 * std * (len(arr) ** -0.2)
    if bw <= 0.0 or not math.isfinite(bw):
        return []
    grid = np.linspace(float(arr.min()) - 1.0, float(arr.max()) + 1.0, 1024)
    z = (grid[:, None] - arr[None, :]) / bw
    density = np.exp(-0.5 * z * z).sum(axis=1)
    peak = [i for i in range(1, len(density) - 1)
            if density[i - 1] < density[i] > density[i + 1]]
    if not peak:
        return []
    valley = [i for i in range(1, len(density) - 1)
              if density[i - 1] > density[i] < density[i + 1]]
    peaks = [float(grid[i]) for i in peak]
    return sorted(float(grid[i]) for i in valley if min(peaks) < float(grid[i]) < max(peaks))


def assign_tier(height: float, cuts: list[float]) -> int:
    tier = 1
    for cut in sorted(cuts, reverse=True):
        if height >= cut:
            return tier
        tier += 1
    return tier


def build_columns(lines: list[dict[str, Any]]) -> list[float]:
    content = [ln for ln in lines if not is_title_word(ln["text"])]
    if not content:
        return []
    gap = content[0]["page_width"] * COLUMN_GAP_FRAC
    xs = sorted(ln["title_x"] for ln in content)
    clusters: list[list[float]] = [[xs[0]]]
    for v in xs[1:]:
        if v - clusters[-1][-1] <= gap:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return sorted(float(np.mean(c)) for c in clusters if len(c) >= COLUMN_MIN_SUPPORT)


def columns_reliable(lines, centers) -> bool:
    if len(centers) < 2:
        return False
    content = [ln for ln in lines if not is_title_word(ln["text"])]
    pw = content[0]["page_width"]
    devs = [ln["title_x"] - min(centers, key=lambda c: abs(ln["title_x"] - c)) for ln in content]
    return float(np.std(devs)) < COLUMN_RELIABLE_STD_FRAC * pw


def assign_column(title_x: float, centers: list[float]) -> int:
    if not centers:
        return 1
    return min(range(len(centers)), key=lambda i: abs(title_x - centers[i])) + 1


# ---------------------------------------------------------------------------
# 2) 결정론 멀티피처 클러스터 (028/029 동일)
# ---------------------------------------------------------------------------
def build_clusters(
    lines: list[dict[str, Any]],
) -> tuple[dict[int, int], list[dict[str, Any]], dict[str, Any]]:
    cuts = cluster_cut_points([ln["height"] for ln in lines])
    centers = build_columns(lines)
    reliable = columns_reliable(lines, centers)
    use_centers = centers if reliable else []

    sig_of: dict[int, tuple] = {}
    for i, ln in enumerate(lines):
        sig_of[i] = (
            assign_column(ln["title_x"], use_centers),
            assign_tier(ln["height"], cuts),
            ln["is_bold"],
            ln["font_type"],
        )

    members: dict[tuple, list[int]] = defaultdict(list)
    for i, ln in enumerate(lines):
        if is_title_word(ln["text"]):
            continue
        members[sig_of[i]].append(i)

    sigs = sorted(members.keys())
    sig_to_id = {sig: cid for cid, sig in enumerate(sigs)}

    clusters: list[dict[str, Any]] = []
    for sig in sigs:
        idxs = members[sig]
        ordered = sorted(idxs, key=lambda i: (lines[i]["pdf_page"], i))
        if len(ordered) <= 4:
            picks = ordered
        else:
            step = len(ordered) / 4.0
            picks = [ordered[int(k * step)] for k in range(4)]
        page_known = sum(1 for i in idxs if lines[i]["trailing_page"] is not None)
        clusters.append(
            {
                "cluster_id": sig_to_id[sig],
                "col": sig[0],
                "height_tier": sig[1],
                "is_bold": sig[2],
                "font_type": sig[3],
                "count": len(idxs),
                "mean_height": round(float(np.mean([lines[i]["height"] for i in idxs])), 2),
                "page_number_frac": round(page_known / len(idxs), 2),
                "examples": [lines[i]["text"][:70] for i in picks],
            }
        )

    line_cluster = {
        i: sig_to_id[sig_of[i]] for i in range(len(lines)) if sig_of[i] in sig_to_id
    }
    debug = {
        "height_cuts": [round(c, 2) for c in cuts],
        "column_centers": [round(c, 1) for c in centers],
        "columns_reliable": reliable,
        "n_clusters": len(clusters),
    }
    return line_cluster, clusters, debug


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------
_CLIENT: Any = None
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def client():
    global _CLIENT
    if _CLIENT is None:
        from openai import OpenAI
        key = os.environ.get("UPSTAGE_API_KEY")
        if not key:
            raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
        _CLIENT = OpenAI(api_key=key, base_url=UPSTAGE_BASE_URL)
    return _CLIENT


def loads_lenient(content):
    if not content:
        return {}
    t = content.strip()
    for cand in (t, (_FENCE.search(t).group(1) if _FENCE.search(t) else None)):
        if cand:
            try:
                return json.loads(cand)
            except json.JSONDecodeError:
                pass
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e > s:
        try:
            return json.loads(t[s : e + 1])
        except json.JSONDecodeError:
            pass
    return {}


def chat(system: str, user: str, response_format: dict[str, Any]) -> dict[str, Any]:
    resp = client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format=response_format,
        temperature=0.0,
    )
    return loads_lenient(resp.choices[0].message.content)


# ---------------------------------------------------------------------------
# 3) Call A: 클러스터 순서(레벨)만 결정 — 029 + 글꼴 분리 강화
# ---------------------------------------------------------------------------
ORDER_SYSTEM = (
    "너는 책 목차의 계층을 정하는 도구다. 입력은 목차 줄들을 이미 묶어 놓은 '클러스터' 목록이다. "
    "각 클러스터에는 글꼴(font_type), 굵기(is_bold), 평균 글씨 높이(mean_height), 들여쓰기 "
    "컬럼(indent_col, 작을수록 왼쪽), 줄 수(count), 페이지번호 비율(page_number_frac), 대표 제목 "
    "예시(examples)가 있다.\n"
    "네 일은 '각 클러스터의 계층 level을 정하는 것'뿐이다(1=최상위). 규칙:\n"
    "- 줄을 다시 묶거나 나누지 마라. 오직 클러스터마다 level 정수 하나만 부여한다.\n"
    "- 큰 글씨/굵게/왼쪽일수록, 그리고 예시 제목이 장/부(chapter/part)처럼 상위 단위면 상위 "
    "level이다. 작은 글씨/들여쓰기/세부 항목 예시는 하위 level이다.\n"
    "- 병합(같은 level): 여러 클러스터가 '같은 구조 단위'면 같은 level을 줘라. 예: 예시가 둘 다 "
    "'Chapter N'으로 시작하는데 들여쓰기 컬럼만 살짝 다른 두 클러스터는 OCR 드리프트이니 같은 "
    "level로 합쳐라.\n"
    "- 분리(다른 level): 글꼴 계열(font_type)이 서로 다르고 예시 제목이 서로 다른 구조 단위(예: 한쪽은 "
    "큰 단원 제목, 다른 쪽은 그 아래 세부 절)면, 글씨 높이가 비슷해도 별도 level로 둬라. "
    "본문 절은 serif, 세부 소절은 sans-serif처럼 글꼴이 계층을 나누는 책이 있다.\n"
    "- 예시 제목의 의미를 반드시 활용하라(신호가 애매하면 제목이 최종 판단 근거다)."
)

ORDER_FMT = {
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


def llm_cluster_levels(clusters: list[dict[str, Any]]) -> dict[int, int]:
    payload = [
        {
            "cluster_id": c["cluster_id"],
            "font_type": c["font_type"],
            "is_bold": c["is_bold"],
            "mean_height": c["mean_height"],
            "indent_col": c["col"],
            "count": c["count"],
            "page_number_frac": c["page_number_frac"],
            "examples": c["examples"],
        }
        for c in clusters
    ]
    user = "클러스터 목록:\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    raw = chat(ORDER_SYSTEM, user, ORDER_FMT).get("clusters", [])
    return {int(r["cluster_id"]): int(r["level"]) for r in raw if "cluster_id" in r and "level" in r}


def levels_from_clusters(
    line_cluster: dict[int, int], clusters: list[dict[str, Any]], cluster_level: dict[int, int]
) -> dict[int, int]:
    all_ids = [c["cluster_id"] for c in clusters]
    max_assigned = max(cluster_level.values(), default=1)
    raw_level = {cid: cluster_level.get(cid, max_assigned + 1) for cid in all_ids}
    distinct = sorted(set(raw_level.values()))
    rank = {lv: i + 1 for i, lv in enumerate(distinct)}
    cid_level = {cid: rank[raw_level[cid]] for cid in all_ids}
    deepest = max(cid_level.values(), default=1)
    return {i: cid_level.get(line_cluster[i], deepest) for i in line_cluster}


# ---------------------------------------------------------------------------
# 4) Call B: 페이지별 항목 분리 (level은 [Ln] 복사만, 025 Arm L 정신)
# ---------------------------------------------------------------------------
def annotate_page_levels(
    lines: list[dict[str, Any]], pno: int, line_level: dict[int, int]
) -> str:
    out = [f"--- PDF page {pno} ---"]
    for i, ln in enumerate(lines):
        if ln["pdf_page"] != pno or is_title_word(ln["text"]) or i not in line_level:
            continue
        out.append(f'[L{line_level[i]}] {escape(ln["text"], quote=False)}')
    return "\n".join(out)


SPLIT_SYSTEM = (
    "너는 책 목차 페이지에서 항목을 추출하는 도구다. 각 줄 앞 [Ln]은 그 줄의 계층 level이다(이미 "
    "결정됨).\n"
    "절대 규칙: 계층/level은 네가 정하지 않는다. 각 항목의 level은 그 항목이 나온 줄의 [Ln] 숫자(n)를 "
    "그대로 복사만 한다. 한 줄을 여러 항목으로 쪼개면 모든 조각은 그 줄과 같은 level을 받는다.\n"
    "너가 하는 일은 다음뿐이다.\n"
    "- 항목 분리: 한 줄에 'I'/'|'/'·'/'•'/탭 같은 구분자와 페이지 번호로 여러 항목이 합쳐져 있으면 "
    "각각의 항목으로 분리한다(스캔 OCR이 2단 목차를 한 줄로 합치는 경우).\n"
    "- printed_page: 제목 뒤 인쇄 페이지 번호, 없으면 null.\n"
    "- 제목 글씨가 깨진 줄도 빼지 말고 반드시 항목으로 낸다(교정은 다음 단계).\n"
    "- '목차'/'Contents' 같은 머리말 한 마디 줄은 항목으로 만들지 않는다.\n"
    "- 항목은 이 페이지에 나온 순서 그대로 반환한다."
)

SPLIT_FMT = {
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


def call_split_page(page_text: str) -> list[dict[str, Any]]:
    user = f"[추출할 목차 페이지]\n{page_text}"
    return chat(SPLIT_SYSTEM, user, SPLIT_FMT).get("items", [])


# ---------------------------------------------------------------------------
# 5) Call C: 제목 OCR 교정 (계층/개수/순서 불변, 025 Call3)
# ---------------------------------------------------------------------------
CORRECT_SYSTEM = (
    "너는 OCR로 깨진 목차 제목을 교정하는 도구다. 입력 항목들의 title에서 OCR 오인식/깨진 글자/붙은 "
    "띄어쓰기만 자연스럽게 고친다.\n"
    "절대 규칙:\n"
    "- 항목 개수, 순서를 절대 바꾸지 마라. 입력과 1:1로 대응하는 교정된 title만 같은 순서로 반환한다.\n"
    "- 없는 내용을 지어내지 말고, 의미가 분명한 OCR 오류만 고친다. 확신이 없으면 원문을 둔다."
)

CORRECT_FMT = {
    "type": "json_schema",
    "json_schema": {
        "name": "toc_title_correction",
        "schema": {
            "type": "object",
            "properties": {"titles": {"type": "array", "items": {"type": "string"}}},
            "required": ["titles"],
        },
    },
}


def call_correct(titles: list[str]) -> list[str]:
    if not titles:
        return titles
    user = "교정할 목차 제목들(순서 유지):\n" + json.dumps(titles, ensure_ascii=False, indent=2)
    result = chat(CORRECT_SYSTEM, user, CORRECT_FMT).get("titles", [])
    if len(result) != len(titles):
        return titles
    return [normalize_text(str(t).strip()) or titles[i] for i, t in enumerate(result)]


# ---------------------------------------------------------------------------
# 줄/raw -> items
# ---------------------------------------------------------------------------
def _keep_title(title: str) -> bool:
    if not title or is_title_word(title):
        return False
    return len(normalize_for_match(title).replace(" ", "")) >= 2


def baseline_items(lines, line_level) -> list[TocItem]:
    """029식 1:1 줄=항목, 분리/교정 없음."""

    items = []
    for i, ln in enumerate(lines):
        if is_title_word(ln["text"]) or i not in line_level:
            continue
        if not _keep_title(ln["text"]):
            continue
        items.append(
            TocItem(title=ln["text"], level=line_level[i], printed_page=ln["trailing_page"],
                    raw_text=ln["text"], source_pdf_page=ln["pdf_page"], confidence=0.8)
        )
    return normalize_levels(items)


def split_items(raw_items, pno, max_level) -> list[TocItem]:
    items = []
    for raw in raw_items:
        title = normalize_text(str(raw.get("title", "")).strip())
        if not _keep_title(title):
            continue
        level = max(1, min(int(raw.get("level") or 1), max_level))
        page_value = raw.get("printed_page")
        items.append(
            TocItem(title=title, level=level,
                    printed_page=int(page_value) if page_value else None,
                    raw_text=title, source_pdf_page=pno, confidence=0.8)
        )
    return items


def apply_correction(items: list[TocItem]) -> list[TocItem]:
    by_page: dict[int, list[int]] = {}
    for idx, it in enumerate(items):
        by_page.setdefault(it.source_pdf_page, []).append(idx)
    new_titles = [it.title for it in items]
    for _, idxs in sorted(by_page.items()):
        corrected = call_correct([items[i].title for i in idxs])
        for i, c in zip(idxs, corrected):
            new_titles[i] = c
    return [
        TocItem(title=new_titles[i], level=it.level, printed_page=it.printed_page,
                raw_text=it.raw_text, source_pdf_page=it.source_pdf_page, confidence=it.confidence)
        for i, it in enumerate(items)
    ]


def normalize_levels(items):
    if not items:
        return items
    shift = min(it.level for it in items) - 1
    if shift <= 0:
        return items
    return [
        TocItem(title=it.title, level=it.level - shift, printed_page=it.printed_page,
                raw_text=it.raw_text, source_pdf_page=it.source_pdf_page, confidence=it.confidence)
        for it in items
    ]


# ---------------------------------------------------------------------------
# bookmark weak-ref 지표 (029 계승)
# ---------------------------------------------------------------------------
def normalize_bookmark_levels(bms):
    kept = [b for b in bms if title_has_letter(b["title"])]
    if not kept:
        return []
    mn = min(b["level"] for b in kept)
    return [{"title": b["title"], "level": b["level"] - mn + 1, "order": b["order"]} for b in kept]


def _sign(x):
    return (x > 0) - (x < 0)


def weakref_metrics(items, bms):
    ref = normalize_bookmark_levels(bms)
    if not ref or not items:
        return {"bookmark_letter_count": len(ref), "matched": 0}
    norms = [normalize_for_match(it.title) for it in items]
    idx_by, choices = {}, []
    for i, n in enumerate(norms):
        if n and n not in idx_by:
            idx_by[n] = i
            choices.append(n)
    pairs = []
    for bm in ref:
        bn = normalize_for_match(bm["title"])
        if not bn:
            continue
        r = process.extractOne(bn, choices, scorer=fuzz.token_set_ratio, score_cutoff=88.0)
        if r:
            pairs.append((bm, items[idx_by[r[0]]]))
    matched = len(pairs)
    abs_a = sum(1 for bm, it in pairs if bm["level"] == it.level)
    ps = sorted(pairs, key=lambda p: p[0]["order"])
    tt = ta = 0
    for (ba, ia), (bb, ib) in zip(ps, ps[1:]):
        tt += 1
        if _sign(bb["level"] - ba["level"]) == _sign(ib.level - ia.level):
            ta += 1
    return {
        "bookmark_letter_count": len(ref), "matched": matched,
        "match_rate": round(matched / len(ref), 4),
        "abs_level_agreement": round(abs_a / matched, 4) if matched else None,
        "rel_depth_agreement": round(ta / tt, 4) if tt else None,
    }


# ---------------------------------------------------------------------------
# 트리/지표/실행
# ---------------------------------------------------------------------------
def render_tree(items):
    out = []
    for it in items:
        ind = "    " * max(it.level - 1, 0)
        pg = it.printed_page if it.printed_page is not None else "-"
        out.append(f"{ind}[{pg}] L{it.level} {it.title}")
    return out


def hmetrics(items):
    lv = [it.level for it in items]
    return {
        "item_count": len(items),
        "level_distribution": {str(k): v for k, v in sorted(Counter(lv).items())},
        "distinct_levels": len(set(lv)),
        "starts_at_level_1": bool(lv) and min(lv) == 1,
    }


def contents_pages(label):
    pages = []
    for seg in label.get("toc_segments") or []:
        if seg.get("kind") == "contents":
            pages.extend(range(seg["start_page"], seg["end_page"] + 1))
    return sorted(dict.fromkeys(pages or list(label["toc_pages"])))


def _cid(t):
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", t).strip("_")[:80]


def run_book(label):
    pdf = ROOT_DIR / label["input_pdf"]
    cid = _cid(label["id"])
    toc_pages = contents_pages(label)
    rec = {"id": label["id"], "input_pdf": label["input_pdf"], "contents_pages": toc_pages}
    if not pdf.exists():
        rec["status"] = "missing_pdf"
        return rec
    lines = extract_toc_lines(pdf, toc_pages)
    if not lines:
        rec["status"] = "no_lines"
        return rec

    # 1+2) 결정론 클러스터, 3) LLM 클러스터 순서.
    line_cluster, clusters, debug = build_clusters(lines)
    cluster_level = llm_cluster_levels(clusters)
    line_level = levels_from_clusters(line_cluster, clusters, cluster_level)
    max_level = max(line_level.values(), default=1)

    # baseline B: 029식 1:1.
    items_base = baseline_items(lines, line_level)

    # 4) Call: 페이지별 항목 분리(level은 [Ln] 복사).
    items_split: list[TocItem] = []
    raw_dump: dict[str, Any] = {}
    for pno in toc_pages:
        page_text = annotate_page_levels(lines, pno, line_level)
        if not page_text.splitlines()[1:]:
            continue
        raw = call_split_page(page_text)
        raw_dump[str(pno)] = raw
        items_split.extend(split_items(raw, pno, max_level))
    items_split = normalize_levels(items_split)

    # 5) Call: 제목 OCR 교정.
    items_full = apply_correction(items_split)

    (OUTPUT_DIR / f"{cid}_clusters.json").write_text(
        json.dumps({"debug": debug, "clusters": clusters,
                    "llm_levels": {str(k): v for k, v in cluster_level.items()}},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / f"{cid}_split_raw.json").write_text(
        json.dumps(raw_dump, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, items in [("B_baseline", items_base), ("F_split", items_split), ("F_full", items_full)]:
        (OUTPUT_DIR / f"{cid}_tree_{name}.txt").write_text(
            "\n".join(render_tree(items)) + "\n", encoding="utf-8")

    rec["status"] = "ok"
    rec["debug"] = debug
    rec["llm_cluster_levels"] = {str(c["cluster_id"]): cluster_level.get(c["cluster_id"]) for c in clusters}
    rec["arm_baseline"] = hmetrics(items_base)
    rec["arm_full"] = hmetrics(items_full)
    rec["split_gain"] = hmetrics(items_full)["item_count"] - hmetrics(items_base)["item_count"]
    rec["full_tree_preview"] = render_tree(items_full)[:26]
    if label["id"] in BOOKMARKED_IDS:
        bms = extract_existing_bookmarks(pdf)
        rec["weakref_baseline"] = weakref_metrics(items_base, bms)
        rec["weakref_full"] = weakref_metrics(items_full, bms)
    return rec


def build_finding(results):
    parts = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        p = (f"{r['id']}(clusters={r['debug']['n_clusters']},reliable_cols="
             f"{r['debug']['columns_reliable']}): base={r['arm_baseline']['level_distribution']}"
             f"(items {r['arm_baseline']['item_count']}) full={r['arm_full']['level_distribution']}"
             f"(items {r['arm_full']['item_count']}, split_gain={r['split_gain']})")
        if "weakref_full" in r:
            p += (f". rel_depth base={r['weakref_baseline'].get('rel_depth_agreement')}"
                  f"/full={r['weakref_full'].get('rel_depth_agreement')}"
                  f" abs base={r['weakref_baseline'].get('abs_level_agreement')}"
                  f"/full={r['weakref_full'].get('abs_level_agreement')}"
                  f" match base={r['weakref_baseline'].get('match_rate')}"
                  f"->full {r['weakref_full'].get('match_rate')}")
        parts.append(p)
    return " | ".join(parts)


def record_experiment(summary):
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "채택 아키텍처(029: 결정론 멀티피처 클러스터 + LLM이 클러스터 순서만 결정)를 end-to-end로 "
            "통합한다. LLM 클러스터 순서로 줄별 level을 확정한 뒤, [Ln] 마커를 입혀 (Call) 페이지별 "
            "항목분리(한국어 2단 한 줄 다항목 분리, level은 복사만)와 (Call) 제목 OCR 교정을 얹는다. "
            "029식 1:1 baseline과 비교하고, luenberger Section/Subsection 분리를 위해 클러스터 순서 "
            "prompt에 글꼴 분리 규칙을 강화한다. bookmark weak ref로 rel_depth/abs/match_rate를 잰다."
        ),
        "inputs": [lab["input_pdf"] for lab in summary["_labels_used"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "experiments\\labels\\answer_toc_ranges_manual.json",
        "model": MODEL, "temperature": 0.0,
        "finding": summary["finding"], "ran_at": summary["ran_at"],
    }
    exps = data.get("experiments", data) if isinstance(data, dict) else data
    exps = [e for e in exps if e.get("id") != EXPERIMENT_ID]
    exps.append(entry)
    if isinstance(data, dict):
        data["experiments"] = exps
    else:
        data = exps
    EXPERIMENTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = {lab["id"]: lab for lab in json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]}
    used = [labels[i] for i in TARGET_IDS if i in labels]
    results = []
    for lab in used:
        print(f"... running {lab['id']}", flush=True)
        results.append(run_book(lab))

    summary = {
        "experiment_id": EXPERIMENT_ID, "scope": "pipeline_integration_cluster_order_split_correct",
        "model": MODEL, "ran_at": datetime.now().isoformat(timespec="seconds"),
        "finding": build_finding(results), "results": results, "_labels_used": used,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "_labels_used"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    record_experiment(summary)

    print("\n=== exp 030: 통합 파이프라인 (클러스터+LLM순서 -> 분리 -> 교정) ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']}: {r.get('status')}")
            continue
        print(f"\n- {r['id']} (clusters={r['debug']['n_clusters']}, "
              f"reliable_cols={r['debug']['columns_reliable']})")
        print(f"    LLM cluster->level: {r['llm_cluster_levels']}")
        print(f"    base: {r['arm_baseline']['level_distribution']} "
              f"(items {r['arm_baseline']['item_count']})")
        print(f"    full: {r['arm_full']['level_distribution']} "
              f"(items {r['arm_full']['item_count']}, split_gain={r['split_gain']})")
        if "weakref_full" in r:
            print(f"    rel_depth base={r['weakref_baseline'].get('rel_depth_agreement')} "
                  f"full={r['weakref_full'].get('rel_depth_agreement')} | "
                  f"abs base={r['weakref_baseline'].get('abs_level_agreement')} "
                  f"full={r['weakref_full'].get('abs_level_agreement')} | "
                  f"match {r['weakref_baseline'].get('match_rate')}"
                  f"->{r['weakref_full'].get('match_rate')}")
        print("    full tree preview:")
        for line in r["full_tree_preview"][:14]:
            print(f"      {line}")
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
