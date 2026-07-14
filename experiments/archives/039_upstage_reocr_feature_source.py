"""experiment 039: 기존 PDF OCR 텍스트 레이어를 버리고, TOC page를 Upstage로 다시 OCR해서
height/x1(indent) feature를 처음부터 재구성한다. Upstage document-digitization의 두 모델
(model=ocr / model=document-parse)을 같은 다운스트림(028/029 클러스터 + LLM 순서)에 꽂아
비교한다.

배경
- impl note 028: 계층(level)은 클러스터링으로 풀렸지만, production 핵심인 printed page
  추출이 깨졌다(Shreve 74/237, Luenberger 0/486). 원인은 기존 PDF의 OCR 텍스트 레이어
  품질(특히 luenberger adobeOCR)과 dot leader 때문에 오른쪽 page number 토큰이 깨지거나
  title에 흡수된 것이다.
- 사용자 결정: hybrid가 아니라 아예 전면적으로 해당 page를 Upstage로 재-OCR/parse해서
  그 word/element 좌표로 우리가 원래 쓰던 textbox height, x1 bin 같은 feature를 다시 만든다.
  즉 "기존 pdf의 ocr을 신뢰하지 않고 처음부터 OCR" 한다.

두 arm(같은 책, 같은 다운스트림, feature source만 다름)
- baseline : 기존 PDF text layer(PyMuPDF span). 029와 동일 경로 = 현재 production 재현.
- upstage_parse : model=document-parse(words=true, coordinates=true). element word box
  (normalized) → 줄 재구성. category는 header/footer 제거에만 쓰고, hierarchy feature로는
  쓰지 않는다(기존 방법론 그대로).

제약(사용자 확정): TOC page OCR은 반드시 Document Parse로만 한다. Document OCR(model=ocr)은
과금되므로 사용 금지(Parse는 special initiative로 무료). 그리고 "OCR 소스만 교체하고 기존 피쳐·
방법론은 그대로 쓴다" — 즉 새로운 '맨 오른쪽 정수' 규칙을 만들지 않고, 줄 feature는 baseline과
동일하게 만든다: height(letter word box 높이), title_x(letter word 최소 x), trailing_page(줄
텍스트의 마지막 정수, 정규식). is_bold/font_type은 Parse가 weight/family를 안 주므로 비활성.

평가
- 계층: bookmark weak ref(rel_depth/abs) — 3권(hull/shreve/luenberger).
- printed page: items_with_printed_page coverage + 순서 단조성(monotonicity). 028이 깨진 채널.

출력: experiments/outputs/039_upstage_reocr_feature_source/
실행: uv run python experiments/039_upstage_reocr_feature_source.py
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import numpy as np
import requests
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
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "039_upstage_reocr_feature_source"
CACHE_DIR = OUTPUT_DIR / "cache"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "039_upstage_reocr_feature_source"

TARGET_IDS = [
    "john_hull",
    "luenberger_investment_science",
    "shreve_binomial",
    "algorithms_to_live_by",
    "algorithm_nine",
]
BOOKMARKED_IDS = {"john_hull", "luenberger_investment_science", "shreve_binomial"}

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
MODEL = "solar-pro3"
RENDER_DPI = 200

COLUMN_GAP_FRAC = 0.03
COLUMN_MIN_SUPPORT = 2
COLUMN_RELIABLE_STD_FRAC = 0.025

# parse element category 중 본문 TOC가 아닌 것(머리말/꼬리말/각주)은 줄 재구성에서 제외.
PARSE_DROP_CATEGORIES = {"header", "footer", "footnote"}

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_SUBSET = re.compile(r"^[A-Z]{6}\+")
_TITLE_WORDS = {
    "목차", "목 차", "차례", "contents", "contents in brief",
    "brief contents", "table of contents",
}


def is_content_text(text: str) -> bool:
    s = text.strip()
    return bool(s and (_HANGUL.search(s) or _LATIN2.search(s)))


def is_title_word(text: str) -> bool:
    return normalize_for_match(text) in _TITLE_WORDS


def base_font(name: str) -> str:
    return _SUBSET.sub("", name).split("-")[0].split(",")[0].lower()


def span_is_bold(span: dict[str, Any]) -> bool:
    return bool(span["flags"] & 2**4) or ("bold" in span["font"].lower())


# ---------------------------------------------------------------------------
# Upstage 호출 (디스크 캐시: 같은 page는 재호출하지 않는다)
# ---------------------------------------------------------------------------
def render_png(pdf: Path, page_1based: int, dpi: int = RENDER_DPI) -> bytes:
    with fitz.open(pdf) as document:
        page = document.load_page(page_1based - 1)
        return page.get_pixmap(dpi=dpi).tobytes("png")


def _api_key() -> str:
    key = os.environ.get("UPSTAGE_API_KEY")
    if not key:
        raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
    return key


def digitize(png: bytes, model: str, extra: dict[str, str] | None = None) -> dict[str, Any]:
    """model=ocr 또는 document-parse 호출. (book,page,model,extra) 단위로 캐시."""
    h = hashlib.sha1(png).hexdigest()[:16]
    tag = model + ("_" + "_".join(f"{k}{v}" for k, v in sorted((extra or {}).items())) if extra else "")
    tag = re.sub(r"[^0-9A-Za-z._-]+", "", tag)[:60]
    cache = CACHE_DIR / f"{tag}_{h}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    data = {"model": model}
    if extra:
        data.update(extra)
    # free tier는 RPS 제한이 있어 429가 잦다. 지수 backoff로 재시도하고, 성공 후에도
    # 다음 호출까지 짧게 throttle 한다.
    delay = 6.0
    last_exc: Exception | None = None
    for attempt in range(7):
        resp = requests.post(
            DIGITIZE_URL, headers={"Authorization": f"Bearer {_api_key()}"},
            files={"document": ("page.png", io.BytesIO(png), "image/png")},
            data=data, timeout=180,
        )
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", delay))
            print(f"      429 rate-limited, {wait:.0f}s 대기 (attempt {attempt + 1})", flush=True)
            time.sleep(wait)
            delay = min(delay * 1.6, 60.0)
            continue
        try:
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(delay)
            delay = min(delay * 1.6, 60.0)
            continue
        out = resp.json()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        time.sleep(1.2)
        return out
    raise last_exc or RuntimeError("Upstage digitization 반복 429로 실패")


# ---------------------------------------------------------------------------
# word -> 줄 재구성 (ocr/parse 공통)
# word = (text, conf, x1, y1, x2, y2, category)
# ---------------------------------------------------------------------------
def _parse_words(resp: dict[str, Any]) -> tuple[list[tuple], float]:
    # normalized 좌표 → page_width=1.0 기준으로 일관 유지.
    words = []
    for el in resp.get("elements", []):
        cat = el.get("category", "")
        if cat in PARSE_DROP_CATEGORIES:
            continue
        for w in el.get("words", []) or []:
            c = w.get("coordinates")
            if not c:
                continue
            xs = [p["x"] for p in c]
            ys = [p["y"] for p in c]
            words.append((w["text"], float(w.get("confidence", 1.0)),
                          float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)), cat))
    return words, 1.0


def group_words_to_lines(words: list[tuple], page_width: float, pdf_page: int) -> list[dict[str, Any]]:
    if not words:
        return []
    # letter word 높이 중앙값으로 줄 분리 임계값 결정.
    letter_h = [w[5] - w[3] for w in words if is_content_text(w[0])]
    med_h = float(np.median(letter_h)) if letter_h else float(np.median([w[5] - w[3] for w in words]))
    thr = max(med_h * 0.6, 1e-6)

    ordered = sorted(words, key=lambda w: ((w[3] + w[5]) / 2.0, w[2]))
    lines: list[list[tuple]] = []
    cur: list[tuple] = []
    cur_yc = None
    for w in ordered:
        yc = (w[3] + w[5]) / 2.0
        if cur and abs(yc - cur_yc) > thr:
            lines.append(cur)
            cur = []
        cur.append(w)
        cur_yc = float(np.mean([(x[3] + x[5]) / 2.0 for x in cur]))
    if cur:
        lines.append(cur)

    out = []
    for ln in lines:
        ln = sorted(ln, key=lambda w: w[2])
        content = [w for w in ln if is_content_text(w[0])]
        if not content:
            continue
        text = normalize_text(" ".join(w[0].strip() for w in ln if w[0].strip()))
        if not text:
            continue
        height = max(w[5] - w[3] for w in content)
        title_x = min(w[2] for w in content)
        # trailing page: 기존 방법론 그대로 — 줄 텍스트의 마지막 정수를 채택한다(맨 오른쪽
        # 정수 위치 규칙은 폐기). baseline lines_baseline과 동일 로직.
        nums = re.findall(r"\d+", " ".join(w[0].strip() for w in ln if w[0].strip()))
        trailing = int(nums[-1]) if nums else None
        out.append({
            "pdf_page": pdf_page,
            "text": text,
            "height": round(height, 3),
            "title_x": round(title_x, 3),
            "page_width": page_width,
            "is_bold": False,      # Parse는 font weight를 안 줌 → 기존 bold 축 비활성.
            "font_type": "reocr",  # Parse는 font family를 안 줌 → category를 feature로 쓰지 않음.
            "trailing_page": trailing,
        })
    return out


# ---------------------------------------------------------------------------
# arm별 줄 추출
# ---------------------------------------------------------------------------
def lines_baseline(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """기존 PDF text layer(PyMuPDF span). 029 extract_toc_lines와 동일."""
    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pno in toc_pages:
            page = document.load_page(pno - 1)
            page_width = float(page.rect.width) or 1.0
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    spans = [s for s in line["spans"] if s["text"].strip()]
                    content_spans = [s for s in spans if is_content_text(s["text"])]
                    if not content_spans:
                        continue
                    content_spans.sort(key=lambda s: s["bbox"][0])
                    head = content_spans[0]
                    heights = [round(s["bbox"][3] - s["bbox"][1], 2) for s in content_spans]
                    parts = [s["text"].strip() for s in spans]
                    trailing = re.findall(r"\d+", " ".join(parts))
                    lines.append({
                        "pdf_page": pno,
                        "text": normalize_text(" ".join(parts)),
                        "height": max(heights),
                        "title_x": round(float(head["bbox"][0]), 2),
                        "page_width": page_width,
                        "is_bold": span_is_bold(head),
                        "font_type": base_font(head["font"]),
                        "trailing_page": int(trailing[-1]) if trailing else None,
                    })
    return lines


def lines_upstage_parse(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for pno in toc_pages:
        png = render_png(pdf_path, pno)
        resp = digitize(png, "document-parse",
                        {"output_formats": '["text"]', "coordinates": "true", "words": "true"})
        words, pw = _parse_words(resp)
        lines.extend(group_words_to_lines(words, pw, pno))
    return lines


# ---------------------------------------------------------------------------
# 클러스터 형성 + LLM 순서 (029 그대로)
# ---------------------------------------------------------------------------
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


def build_clusters(lines):
    cuts = cluster_cut_points([ln["height"] for ln in lines])
    centers = build_columns(lines)
    reliable = columns_reliable(lines, centers)
    use_centers = centers if reliable else []

    sig_of: dict[int, tuple] = {}
    for i, ln in enumerate(lines):
        sig_of[i] = (assign_column(ln["title_x"], use_centers),
                     assign_tier(ln["height"], cuts), ln["is_bold"], ln["font_type"])

    members: dict[tuple, list[int]] = defaultdict(list)
    for i, ln in enumerate(lines):
        if is_title_word(ln["text"]):
            continue
        members[sig_of[i]].append(i)

    sigs = sorted(members.keys(), key=lambda s: (str(s[3]), s[0], s[1], s[2]))
    sig_to_id = {sig: cid for cid, sig in enumerate(sigs)}

    clusters = []
    for sig in sigs:
        idxs = members[sig]
        ordered = sorted(idxs, key=lambda i: (lines[i]["pdf_page"], i))
        if len(ordered) <= 4:
            picks = ordered
        else:
            step = len(ordered) / 4.0
            picks = [ordered[int(k * step)] for k in range(4)]
        clusters.append({
            "cluster_id": sig_to_id[sig], "col": sig[0], "height_tier": sig[1],
            "is_bold": sig[2], "font_type": sig[3], "count": len(idxs),
            "mean_height": round(float(np.mean([lines[i]["height"] for i in idxs])), 3),
            "examples": [lines[i]["text"][:70] for i in picks],
        })
    line_cluster = {i: sig_to_id[sig_of[i]] for i in range(len(lines)) if sig_of[i] in sig_to_id}
    debug = {
        "height_cuts": [round(c, 3) for c in cuts],
        "column_centers": [round(c, 1) for c in centers],
        "columns_reliable": reliable, "n_clusters": len(clusters),
    }
    return line_cluster, clusters, debug


_CLIENT: Any = None
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def client():
    global _CLIENT
    if _CLIENT is None:
        from openai import OpenAI
        _CLIENT = OpenAI(api_key=_api_key(), base_url=UPSTAGE_BASE_URL)
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
            return json.loads(t[s:e + 1])
        except json.JSONDecodeError:
            pass
    return {}


ORDER_SYSTEM = (
    "너는 책 목차의 계층을 정하는 도구다. 입력은 목차 줄들을 이미 묶어 놓은 '클러스터' 목록이다. "
    "각 클러스터에는 글꼴(font_type), 굵기(is_bold), 평균 글씨 높이(mean_height), 들여쓰기 "
    "컬럼(col, 작을수록 왼쪽), 줄 수(count), 대표 제목 예시(examples)가 있다.\n"
    "네 일은 '각 클러스터의 계층 level을 정하는 것'뿐이다(1=최상위). 규칙:\n"
    "- 줄을 다시 묶거나 나누지 마라. 오직 클러스터마다 level 정수 하나만 부여한다.\n"
    "- 큰 글씨/굵게/왼쪽일수록, 그리고 예시 제목이 장/부(chapter/part)처럼 상위 단위면 상위 level이다.\n"
    "- 여러 클러스터가 같은 계층이면 같은 level을 줘도 된다(병합).\n"
    "- 예시 제목의 의미를 반드시 활용하라(신호가 애매하면 제목이 판단 근거다)."
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


def llm_cluster_levels(clusters):
    payload = [{
        "cluster_id": c["cluster_id"], "font_type": c["font_type"], "is_bold": c["is_bold"],
        "mean_height": c["mean_height"], "indent_col": c["col"], "count": c["count"],
        "examples": c["examples"],
    } for c in clusters]
    user = "클러스터 목록:\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    resp = client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": ORDER_SYSTEM}, {"role": "user", "content": user}],
        response_format=ORDER_FMT, temperature=0.0,
    )
    raw = loads_lenient(resp.choices[0].message.content).get("clusters", [])
    return {int(r["cluster_id"]): int(r["level"]) for r in raw if "cluster_id" in r and "level" in r}


def levels_from_clusters(line_cluster, clusters, cluster_level):
    all_ids = [c["cluster_id"] for c in clusters]
    max_assigned = max(cluster_level.values(), default=1)
    raw_level = {cid: cluster_level.get(cid, max_assigned + 1) for cid in all_ids}
    distinct = sorted(set(raw_level.values()))
    rank = {lv: i + 1 for i, lv in enumerate(distinct)}
    cid_level = {cid: rank[raw_level[cid]] for cid in all_ids}
    deepest = max(cid_level.values(), default=1)
    return {i: cid_level.get(line_cluster[i], deepest) for i in line_cluster}


# ---------------------------------------------------------------------------
# items / 지표
# ---------------------------------------------------------------------------
def to_items(lines, depth) -> list[TocItem]:
    items = []
    for i, ln in enumerate(lines):
        if is_title_word(ln["text"]):
            continue
        if len(normalize_for_match(ln["text"]).replace(" ", "")) < 2:
            continue
        items.append(TocItem(
            title=ln["text"], level=depth.get(i, 1), printed_page=ln["trailing_page"],
            raw_text=ln["text"], source_pdf_page=ln["pdf_page"], confidence=0.8))
    return normalize_levels(items)


def normalize_levels(items):
    if not items:
        return items
    shift = min(it.level for it in items) - 1
    if shift <= 0:
        return items
    return [TocItem(title=it.title, level=it.level - shift, printed_page=it.printed_page,
                    raw_text=it.raw_text, source_pdf_page=it.source_pdf_page,
                    confidence=it.confidence) for it in items]


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


def page_metrics(items):
    """printed page 채널 품질: coverage + 순서 단조성."""
    n = len(items)
    pages = [it.printed_page for it in items]
    have = [p for p in pages if p is not None]
    cov = round(len(have) / n, 4) if n else 0.0
    tt = ok = 0
    prev = None
    for p in pages:
        if p is None:
            continue
        if prev is not None:
            tt += 1
            if p >= prev:
                ok += 1
        prev = p
    return {
        "items": n, "with_printed_page": len(have), "coverage": cov,
        "monotonicity": round(ok / tt, 4) if tt else None,
    }


def hmetrics(items):
    lv = [it.level for it in items]
    return {
        "item_count": len(items),
        "level_distribution": {str(k): v for k, v in sorted(Counter(lv).items())},
        "distinct_levels": len(set(lv)),
    }


def render_tree(items):
    out = []
    for it in items:
        ind = "    " * max(it.level - 1, 0)
        pg = it.printed_page if it.printed_page is not None else "-"
        out.append(f"{ind}[{pg}] L{it.level} {it.title}")
    return out


def contents_pages(label):
    pages = []
    for seg in label.get("toc_segments") or []:
        if seg.get("kind") in ("contents", "contents_in_brief"):
            pages.extend(range(seg["start_page"], seg["end_page"] + 1))
    return sorted(dict.fromkeys(pages or list(label["toc_pages"])))


def _cid(t):
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", t).strip("_")[:80]


# Document OCR(model=ocr)은 과금되어 사용 금지. Parse만 사용한다.
ARMS = ["baseline", "upstage_parse"]


def run_arm(arm, pdf, toc_pages, bms):
    if arm == "baseline":
        lines = lines_baseline(pdf, toc_pages)
    else:
        lines = lines_upstage_parse(pdf, toc_pages)
    if not lines:
        return {"status": "no_lines"}
    line_cluster, clusters, debug = build_clusters(lines)
    cluster_level = llm_cluster_levels(clusters)
    items = to_items(lines, levels_from_clusters(line_cluster, clusters, cluster_level))
    rec = {
        "status": "ok", "debug": debug, "hierarchy": hmetrics(items),
        "page_channel": page_metrics(items), "tree_preview": render_tree(items)[:24],
    }
    if bms is not None:
        rec["weakref"] = weakref_metrics(items, bms)
    return rec, items, clusters, cluster_level


def run_book(label):
    pdf = ROOT_DIR / label["input_pdf"]
    cid = _cid(label["id"])
    toc_pages = contents_pages(label)
    rec = {"id": label["id"], "input_pdf": label["input_pdf"], "contents_pages": toc_pages, "arms": {}}
    if not pdf.exists():
        rec["status"] = "missing_pdf"
        return rec
    bms = extract_existing_bookmarks(pdf) if label["id"] in BOOKMARKED_IDS else None
    for arm in ARMS:
        try:
            out = run_arm(arm, pdf, toc_pages, bms)
        except Exception as exc:  # arm 하나 실패해도 나머지는 본다.
            rec["arms"][arm] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            continue
        if isinstance(out, dict):
            rec["arms"][arm] = out
            continue
        armrec, items, clusters, cluster_level = out
        rec["arms"][arm] = armrec
        (OUTPUT_DIR / f"{cid}_{arm}_tree.txt").write_text(
            "\n".join(render_tree(items)) + "\n", encoding="utf-8")
        (OUTPUT_DIR / f"{cid}_{arm}_clusters.json").write_text(
            json.dumps({"clusters": clusters,
                        "llm_levels": {str(k): v for k, v in cluster_level.items()}},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    rec["status"] = "ok"
    return rec


def build_finding(results):
    parts = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        seg = [r["id"]]
        for arm in ARMS:
            a = r["arms"].get(arm, {})
            if a.get("status") != "ok":
                seg.append(f"{arm}={a.get('status')}")
                continue
            pc = a["page_channel"]
            piece = f"{arm}: page_cov {pc['with_printed_page']}/{pc['items']}({pc['coverage']}) mono={pc['monotonicity']}"
            if "weakref" in a and a["weakref"].get("matched"):
                piece += f" rel={a['weakref'].get('rel_depth_agreement')} abs={a['weakref'].get('abs_level_agreement')}"
            seg.append(piece)
        parts.append("; ".join(seg))
    return " || ".join(parts)


def record_experiment(summary):
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "기존 PDF OCR 텍스트 레이어를 신뢰하지 않고 TOC page를 Upstage Document Parse로 처음부터 "
            "재-OCR해 height/x1 feature를 재구성한다(Document OCR은 과금되어 사용 금지). word box는 "
            "Parse words=true에서 얻고, 'OCR 소스만 교체하고 기존 피쳐·방법론은 그대로 쓴다' 원칙에 따라 "
            "줄 feature(height/title_x/trailing_page=마지막 정수)와 028/029 클러스터+LLM 순서 다운스트림을 "
            "baseline과 동일하게 둔다. category는 header/footer 제거에만 쓰고 hierarchy feature로는 안 쓴다. "
            "핵심 평가축은 impl note 028이 깨뜨린 printed page coverage/monotonicity, 계층은 bookmark weak ref."
        ),
        "inputs": [lab["input_pdf"] for lab in summary["_labels_used"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "experiments\\labels\\answer_toc_ranges_manual.json",
        "models": ["document-parse", MODEL], "temperature": 0.0,
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
        "experiment_id": EXPERIMENT_ID, "model": MODEL,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "finding": build_finding(results), "results": results, "_labels_used": used,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "_labels_used"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    record_experiment(summary)

    print("\n=== exp 039: re-OCR feature source (baseline vs upstage_parse; Document OCR은 과금이라 제외) ===")
    for r in results:
        print(f"\n- {r['id']} ({r.get('status')})  contents_pages={r.get('contents_pages')}")
        for arm in ARMS:
            a = r.get("arms", {}).get(arm, {})
            if a.get("status") != "ok":
                print(f"    {arm:13s}: {a.get('status')} {a.get('error','')}")
                continue
            pc, h = a["page_channel"], a["hierarchy"]
            line = (f"    {arm:13s}: items={pc['items']:3d} page_cov={pc['with_printed_page']}/{pc['items']}"
                    f"({pc['coverage']}) mono={pc['monotonicity']} levels={h['level_distribution']}"
                    f" clusters={a['debug']['n_clusters']}")
            if "weakref" in a and a["weakref"].get("matched"):
                line += f" rel={a['weakref'].get('rel_depth_agreement')} abs={a['weakref'].get('abs_level_agreement')}"
            print(line)
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
