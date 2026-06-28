"""experiment 027: font+indent ordinal 힌트만 주고 계층은 LLM이 결정.

배경/방침(사용자)
- lexical 채널은 일단 제외. font + indent만 쓴다.
- 계층 결정권은 LLM에게 둔다. 코드는 '최대한 좋은 위치/폰트 힌트'만 만들어 준다.

힌트 설계(코드, robust ordinal)
- font=T{tier}: height 클러스터 tier(021 유효). 큰 글씨일수록 T가 작다(상위 후보).
- indent=C{col}: 026의 robust gap 컬럼 rank. 왼쪽일수록 C가 작다(상위 후보).
  (raw x는 024에서 noisy, page폭 10-bin은 025에서 too coarse로 입증 -> ordinal 컬럼 채택.)
- 사용자 선택: indent 힌트는 ordinal C만 준다(정규화 raw 위치는 안 줌).

왜 023처럼 안 망가지나
- 023은 raw 신호로 LLM이 level을 자유 추론 -> over-deepening 붕괴. 027은 LLM이 concrete
  ordinal anchor(C rank)를 보고 결정하므로 깊이를 지어낼 여지가 준다. 그리고 025의 치명적
  실수(레벨 수를 tier로 cap)는 제거 -- 레벨 수는 LLM이 결정한다.
- hull 드리프트(같은 '장'이 C1/C2로 갈림)는 LLM이 제목 텍스트를 읽고 스스로 통합한다
  (lexical 채널 없이 LLM 언어 이해가 그 일을 함).

workflow(LLM 결정)
- Stage 1: 첫 페이지 + 힌트 + 전역 요약 -> 계층 schema(레벨 수/cue)를 LLM이 결정(cap 없음).
- Stage 2: schema + 줄별 힌트 -> 항목별 level 부여 + 합쳐진 줄 분리 + 순서 유지.
- Stage 3: 제목 OCR 교정(025 검증).
- baseline: 026 HC(결정론)도 같이 내어 'LLM 결정 vs 코드 결정' 비교.

평가: rel_depth_agreement + abs_level + bookmark weakref. luenberger bookmark는 Part/Chapter
까지만이라 정답 아님 -> 그 두 레벨만 참고하고 절 계층은 육안 검수.

출력: experiments/outputs/027_toc_hint_llm_decides/
실행: uv run python experiments/027_toc_hint_llm_decides.py
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
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "027_toc_hint_llm_decides"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "027_toc_hint_llm_decides"

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

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_TITLE_WORDS = {
    "목차", "목 차", "차례", "contents", "contents in brief",
    "brief contents", "table of contents",
}


def is_content_span(text: str) -> bool:
    s = text.strip()
    return bool(s and (_HANGUL.search(s) or _LATIN2.search(s)))


def is_title_word(text: str) -> bool:
    return normalize_for_match(text) in _TITLE_WORDS


# ---------------------------------------------------------------------------
# 줄 신호 추출 + tier + robust 컬럼 (026 재사용)
# ---------------------------------------------------------------------------
def extract_toc_lines(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
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
                        if not span["text"].strip():
                            continue
                        parts.append(span["text"].strip())
                        if is_content_span(span["text"]):
                            heights.append(round(span["bbox"][3] - span["bbox"][1], 2))
                            x_lefts.append(float(span["bbox"][0]))
                    if not heights:
                        continue
                    trailing = re.findall(r"\d+", " ".join(parts))
                    lines.append(
                        {
                            "pdf_page": pno,
                            "text": normalize_text(" ".join(parts)),
                            "height": max(heights),
                            "title_x": round(min(x_lefts), 2),
                            "page_width": page_width,
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
    centers = [float(np.mean(c)) for c in clusters if len(c) >= COLUMN_MIN_SUPPORT]
    return sorted(centers)


def assign_column(title_x: float, centers: list[float]) -> int:
    if not centers:
        return 1
    return min(range(len(centers)), key=lambda i: abs(title_x - centers[i])) + 1


# ---------------------------------------------------------------------------
# 026 HC 결정론 baseline
# ---------------------------------------------------------------------------
def hc_depths(lines: list[dict[str, Any]]) -> dict[int, int]:
    cuts = cluster_cut_points([ln["height"] for ln in lines])
    centers = build_columns(lines)
    content_idx = [i for i, ln in enumerate(lines) if not is_title_word(ln["text"])]
    tier_of = {i: assign_tier(lines[i]["height"], cuts) for i in range(len(lines))}
    col_of = {i: assign_column(lines[i]["title_x"], centers) for i in range(len(lines))}
    keys = sorted({(col_of[i], tier_of[i]) for i in content_idx})
    rank = {k: idx + 1 for idx, k in enumerate(keys)}
    mx = max(rank.values(), default=1)
    return {i: rank.get((col_of[i], tier_of[i]), mx) for i in range(len(lines))}


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
_CLIENT: Any = None
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def client() -> Any:
    global _CLIENT
    if _CLIENT is None:
        from openai import OpenAI
        key = os.environ.get("UPSTAGE_API_KEY")
        if not key:
            raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
        _CLIENT = OpenAI(api_key=key, base_url=UPSTAGE_BASE_URL)
    return _CLIENT


def loads_lenient(content: str | None) -> dict[str, Any]:
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


def chat(system: str, user: str, fmt: dict[str, Any]) -> dict[str, Any]:
    resp = client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format=fmt,
        temperature=0.0,
    )
    return loads_lenient(resp.choices[0].message.content)


def annotate_page(lines, pno, cuts, centers) -> str:
    out = [f"--- PDF page {pno} ---"]
    for ln in lines:
        if ln["pdf_page"] != pno:
            continue
        t = assign_tier(ln["height"], cuts)
        c = assign_column(ln["title_x"], centers)
        out.append(f'[font=T{t} indent=C{c}] {escape(ln["text"], quote=False)}')
    return "\n".join(out)


# Stage 1: schema (레벨 수 cap 없음).
SCHEMA_SYSTEM = (
    "너는 책 목차의 계층(level) schema를 결정하는 도구다. 각 줄 앞 대괄호에 두 힌트가 있다.\n"
    "- font=Tn: 글씨 크기 tier. n이 작을수록 큰 글씨(상위 계층 후보).\n"
    "- indent=Cn: 들여쓰기 컬럼. n이 작을수록 왼쪽(상위 계층 후보).\n"
    "규칙:\n"
    "- font와 indent를 종합해 이 책 목차에 몇 개의 계층 레벨이 있는지 네가 결정하라. 어느 한 "
    "신호가 레벨 수를 제한하지 않는다(글씨가 균일해도 들여쓰기가 다르면 여러 레벨일 수 있고, "
    "들여쓰기가 같아도 글씨 크기가 다르면 여러 레벨일 수 있다).\n"
    "- 힌트가 가끔 흔들릴 수 있다(같은 계층인데 indent 컬럼이 한 칸 어긋나는 등). 제목 텍스트의 "
    "의미도 함께 보고 같은 계층이면 같은 레벨로 묶어라.\n"
    "각 레벨에 level(1부터 연속), name, cues(어떤 font/indent/제목 특징이면 이 레벨인지), "
    "examples(첫 페이지의 해당 제목 1~3개)를 적는다. '목차'/'Contents' 머리말은 제외한다. "
    "이 schema는 이후 모든 목차 페이지에 일관 적용된다."
)


def flexible_schema_fmt() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "hierarchy_schema",
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
                                "examples": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["level", "name", "cues", "examples"],
                        },
                    }
                },
                "required": ["levels"],
            },
        },
    }


def stage1_schema(first_page_text, n_tiers, columns) -> dict[str, Any]:
    col_desc = ", ".join(
        f"C{rank + 1}(x≈{int(c)})" for rank, c in enumerate(columns)
    ) or "컬럼 미검출"
    user = (
        f"관측: font tier {n_tiers}개, indent 컬럼 {len(columns)}개 [{col_desc}].\n"
        f"이 신호로 계층 레벨을 결정하라.\n\n[첫 목차 페이지]\n{first_page_text}"
    )
    return chat(SCHEMA_SYSTEM, user, flexible_schema_fmt())


# Stage 2: assign level.
EXTRACT_SYSTEM = (
    "너는 책 목차 페이지에서 항목을 추출하는 도구다. 아래 [계층 schema]를 이 책 전체에 일관 "
    "적용한다. 각 줄 앞 [font=Tn indent=Cn]은 그 줄의 힌트다.\n"
    "각 항목에 대해:\n"
    "- level: [schema]와 그 줄의 힌트, 제목 의미를 종합해 정한다. schema에 정의된 레벨만 쓰고 "
    "더 깊은 레벨을 새로 만들지 마라. 힌트가 한 칸 어긋나도 같은 계층의 제목이면 같은 level로 묶어라.\n"
    "- 항목 분리: 한 줄에 'I'/'|'/'·'/'•' 구분자와 페이지 번호로 여러 항목이 합쳐져 있으면 분리하고, "
    "조각은 같은 level을 공유한다.\n"
    "- printed_page: 제목 뒤 인쇄 페이지 번호, 없으면 null.\n"
    "- 깨진 제목도 빼지 말고 낸다(교정은 다음 단계). 머리말 한 마디 줄은 만들지 않고, 순서 유지."
)

EXTRACT_FMT = {
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


def stage2_extract(page_text, schema) -> list[dict[str, Any]]:
    user = (
        f"[계층 schema - 일관 적용]\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        f"[추출할 목차 페이지]\n{page_text}"
    )
    return chat(EXTRACT_SYSTEM, user, EXTRACT_FMT).get("items", [])


# Stage 3: 제목 교정 (025).
CORRECT_SYSTEM = (
    "너는 OCR로 깨진 목차 제목을 교정하는 도구다. title의 OCR 오인식/깨진 글자/붙은 띄어쓰기만 "
    "고친다.\n절대 규칙: 항목 개수/순서/level/printed_page를 바꾸지 마라. 입력과 1:1 대응하는 "
    "교정 title만 같은 순서로 반환한다. 확신 없으면 원문을 둔다."
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


def stage3_correct(titles: list[str]) -> list[str]:
    if not titles:
        return titles
    user = "교정할 제목들(순서 유지):\n" + json.dumps(titles, ensure_ascii=False, indent=2)
    res = chat(CORRECT_SYSTEM, user, CORRECT_FMT).get("titles", [])
    if len(res) != len(titles):
        return titles
    return [normalize_text(str(t).strip()) or titles[i] for i, t in enumerate(res)]


# ---------------------------------------------------------------------------
# items 변환 / 정규화
# ---------------------------------------------------------------------------
def raw_to_items(raw_items, pno) -> list[TocItem]:
    items: list[TocItem] = []
    for raw in raw_items:
        title = normalize_text(str(raw.get("title", "")).strip())
        if not title or is_title_word(title):
            continue
        if len(normalize_for_match(title).replace(" ", "")) < 2:
            continue
        pv = raw.get("printed_page")
        items.append(
            TocItem(
                title=title,
                level=max(1, int(raw.get("level") or 1)),
                printed_page=int(pv) if pv else None,
                raw_text=title,
                source_pdf_page=pno,
                confidence=0.8,
            )
        )
    return items


def lines_to_items(lines, depth) -> list[TocItem]:
    items: list[TocItem] = []
    for i, ln in enumerate(lines):
        if is_title_word(ln["text"]):
            continue
        if len(normalize_for_match(ln["text"]).replace(" ", "")) < 2:
            continue
        items.append(
            TocItem(
                title=ln["text"], level=depth[i], printed_page=ln["trailing_page"],
                raw_text=ln["text"], source_pdf_page=ln["pdf_page"], confidence=0.8,
            )
        )
    return normalize_levels(items)


def normalize_levels(items: list[TocItem]) -> list[TocItem]:
    if not items:
        return items
    shift = min(it.level for it in items) - 1
    if shift <= 0:
        return items
    return [
        TocItem(title=it.title, level=it.level - shift, printed_page=it.printed_page,
                raw_text=it.raw_text, source_pdf_page=it.source_pdf_page,
                confidence=it.confidence)
        for it in items
    ]


def correct_titles(items: list[TocItem]) -> list[TocItem]:
    by_page: dict[int, list[int]] = {}
    for idx, it in enumerate(items):
        by_page.setdefault(it.source_pdf_page, []).append(idx)
    new = [it.title for it in items]
    for _, idxs in sorted(by_page.items()):
        for i, c in zip(idxs, stage3_correct([items[i].title for i in idxs])):
            new[i] = c
    return [
        TocItem(title=new[i], level=it.level, printed_page=it.printed_page,
                raw_text=it.raw_text, source_pdf_page=it.source_pdf_page,
                confidence=it.confidence)
        for i, it in enumerate(items)
    ]


# ---------------------------------------------------------------------------
# weakref 지표 (024/025/026)
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

    cuts = cluster_cut_points([ln["height"] for ln in lines])
    centers = build_columns(lines)
    n_tiers = len({assign_tier(ln["height"], cuts) for ln in lines if not is_title_word(ln["text"])})

    # baseline 026 HC (결정론).
    items_hc = lines_to_items(lines, hc_depths(lines))

    # LLM 결정 경로.
    schema = stage1_schema(annotate_page(lines, toc_pages[0], cuts, centers), n_tiers, centers)
    raw_dump = {}
    items_llm: list[TocItem] = []
    for pno in toc_pages:
        raw = stage2_extract(annotate_page(lines, pno, cuts, centers), schema)
        raw_dump[str(pno)] = raw
        items_llm.extend(raw_to_items(raw, pno))
    items_llm = normalize_levels(items_llm)
    items_llm_corr = correct_titles(items_llm)

    (OUTPUT_DIR / f"{cid}_schema.json").write_text(
        json.dumps({"n_tiers": n_tiers, "columns": [round(c, 1) for c in centers],
                    "schema": schema}, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / f"{cid}_raw.json").write_text(
        json.dumps(raw_dump, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, items in [("HC", items_hc), ("LLM", items_llm), ("LLM_corrected", items_llm_corr)]:
        (OUTPUT_DIR / f"{cid}_tree_{name}.txt").write_text(
            "\n".join(render_tree(items)) + "\n", encoding="utf-8")

    rec["status"] = "ok"
    rec["n_tiers"] = n_tiers
    rec["columns"] = [round(c, 1) for c in centers]
    rec["arm_hc"] = hmetrics(items_hc)
    rec["arm_llm"] = hmetrics(items_llm)
    rec["llm_corrected_preview"] = render_tree(items_llm_corr)[:22]
    if label["id"] in BOOKMARKED_IDS:
        bms = extract_existing_bookmarks(pdf)
        rec["weakref_hc"] = weakref_metrics(items_hc, bms)
        rec["weakref_llm"] = weakref_metrics(items_llm, bms)
        rec["weakref_llm_corrected"] = weakref_metrics(items_llm_corr, bms)
    return rec


def build_finding(results):
    parts = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        p = (f"{r['id']}(tiers={r['n_tiers']},cols={r['columns']}): "
             f"HC={r['arm_hc']['level_distribution']} LLM={r['arm_llm']['level_distribution']}")
        if "weakref_llm" in r:
            p += (f". rel_depth HC={r['weakref_hc'].get('rel_depth_agreement')}"
                  f"/LLM={r['weakref_llm'].get('rel_depth_agreement')}"
                  f" abs HC={r['weakref_hc'].get('abs_level_agreement')}"
                  f"/LLM={r['weakref_llm'].get('abs_level_agreement')}"
                  f" match {r['weakref_llm'].get('match_rate')}")
        parts.append(p)
    return " | ".join(parts)


def record_experiment(summary):
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "font tier + robust indent 컬럼을 ordinal 힌트(T/C)로만 주고 계층 레벨은 LLM이 "
            "결정한다(레벨 수 cap 없음). Stage1 schema 결정 / Stage2 level 부여 / Stage3 제목 "
            "교정. 026 HC(결정론)와 비교하고 bookmark weak ref로 rel_depth/abs를 잰다. lexical "
            "채널은 제외. luenberger bookmark는 Part/Chapter까지뿐이라 정답 아님."
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
        "experiment_id": EXPERIMENT_ID, "scope": "hierarchy_llm_decides_font_indent",
        "model": MODEL, "ran_at": datetime.now().isoformat(timespec="seconds"),
        "finding": build_finding(results), "results": results, "_labels_used": used,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "_labels_used"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    record_experiment(summary)

    print("\n=== exp 027: font+indent 힌트 / LLM 결정 (vs 026 HC) ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']}: {r.get('status')}")
            continue
        print(f"\n- {r['id']} (tiers={r['n_tiers']}, cols={r['columns']})")
        print(f"    HC : {r['arm_hc']['level_distribution']}")
        print(f"    LLM: {r['arm_llm']['level_distribution']}")
        if "weakref_llm" in r:
            print(f"    rel_depth HC={r['weakref_hc'].get('rel_depth_agreement')} "
                  f"LLM={r['weakref_llm'].get('rel_depth_agreement')} | "
                  f"abs HC={r['weakref_hc'].get('abs_level_agreement')} "
                  f"LLM={r['weakref_llm'].get('abs_level_agreement')}")
        print("    LLM(corrected) preview:")
        for line in r["llm_corrected_preview"][:14]:
            print(f"      {line}")
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
