"""experiment 041: 040의 결과(Parse가 페이지번호 채널은 살리지만 계층은 평탄화)를 받아,
fitz(계층 geometry) + Document Parse(깨끗한 텍스트·페이지번호)를 줄 매칭으로 합치는 hybrid를
검증한다. Parse는 전 책에 적용한다(native는 기존 bookmark가 있어 production 대상이 아니므로
책별 gate를 따로 두지 않는다).

배경
- 040: 현재 src 흐름을 그대로 타되 TOC range page만 Document Parse로 교체했더니, 스캔-OCR
  책의 printed page 채널이 극적으로 살아났다(kim1 placeable 0->38, hankyung 33->110,
  quant 26->42). 그러나 계층(abs level)이 평탄화됐다. 원인은 Parse가 font weight/family를
  주지 않아 멀티피처 클러스터의 is_bold/font_type 축이 죽고, chapter/section을 못 가른 것.

핵심 관찰(분업)
- src SizeAwareStagedTocExtractor는 최종 printed_page를 '줄 텍스트'에서 LLM이 읽어 만든다
  (line.trailing_page 필드가 아니다). 따라서 Parse의 깨끗한 페이지번호를 항목에 넣으려면
  줄 '텍스트'를 Parse 텍스트로 바꿔야 한다.
- 그러므로 hybrid는 fitz 줄을 backbone으로 두고(클러스터=baseline과 동일 -> 계층 보존),
  같은 page에서 매칭된 Parse 줄의 깨끗한 텍스트(제목+페이지번호)만 이식한다. 계층은 fitz
  geometry(height/title_x/is_bold/font_type)가 그대로 소유한다.

세 arm(같은 src 탐지/offset/align, TOC range page 줄만 다름)
- baseline : fitz(PyMuPDF span) 줄 = 현재 production.
- parse    : 040과 동일, Parse 줄(is_bold=False, font_type=reocr) -> 계층 평탄화.
- hybrid   : fitz 줄 backbone + 매칭된 Parse 줄의 텍스트/페이지번호 이식.

매칭(page 단위)
- fitz 줄과 Parse 줄을 같은 page에서 reading-order 정규화 y로 근접(|dy|<DY_GATE)시키고, 텍스트
  fuzzy(token_set_ratio)가 가장 큰 쌍을 1:1 greedy로 고른다. ratio>=TEXT_MIN이면 fitz 줄의
  text/trailing_page를 Parse 줄 것으로 교체, 아니면 fitz 원문 유지.

평가
- TOC range 탐지 품질(arm 공통): GT toc_pages 대비 precision/recall.
- 계층: bookmark weak ref(rel_depth/abs).
- printed page: coverage + monotonicity.
- end-to-end: offset 적용 후 bookmark placeable.
- hybrid 진단: 매칭률(이식된 줄 수/전체 fitz 줄).

출력: experiments/outputs/041_parse_fitz_hybrid_lines/
실행: uv run --with truststore python experiments/041_parse_fitz_hybrid_lines.py
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import numpy as np
import requests
from dotenv import load_dotenv
from rapidfuzz import fuzz, process

from pdfbooktree.alignment.headings import extract_heading_candidates
from pdfbooktree.alignment.match import align_toc_items
from pdfbooktree.alignment.offset import OffsetEstimationError, estimate_page_offset
from pdfbooktree.alignment.ranges import calculate_content_ranges
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, title_has_letter
from pdfbooktree.pdf.text import extract_page_texts, extract_selected_page_texts
from pdfbooktree.toc.detect import detect_toc_pages
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.toc.llm_range_review import LlmTocRangeReviewer
from pdfbooktree.toc.staged_llm_extract import (
    ClusteredTocLine,
    SizeAwareStagedTocExtractor,
)
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 사내 TLS 가로채기 프록시(self-signed root) 환경에서 Upstage 호출이 SSL 검증으로 막힌다.
# truststore가 있으면 OS(Windows) 신뢰 저장소를 쓰게 해 안전하게 통과시킨다(verify=False 금지).
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "041_parse_fitz_hybrid_lines"
# 040과 같은 page를 Parse하므로 040 캐시를 공유해 재호출을 줄인다.
CACHE_DIR = ROOT_DIR / "experiments" / "outputs" / "040_upstage_parse_src_endtoend" / "cache"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "041_parse_fitz_hybrid_lines"

TARGET_IDS = [
    "zvi_bodie_investments",
    "kim_econometrics_note1",
    "kim_econometrics_note2",
    "quant_world",
    "hankyung_reader",
]
BOOKMARKED_IDS = set(TARGET_IDS)

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
RENDER_DPI = 200
PARSE_DROP_CATEGORIES = {"header", "footer", "footnote"}

# hybrid 매칭 파라미터
DY_GATE = 0.05  # 같은 줄로 볼 정규화 y 거리 상한
TEXT_MIN = 50.0  # 텍스트 이식을 허용할 token_set_ratio 하한

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_SUBSET = re.compile(r"^[A-Z]{6}\+")


def is_content_text(text: str) -> bool:
    s = text.strip()
    return bool(s and (_HANGUL.search(s) or _LATIN2.search(s)))


def base_font(name: str) -> str:
    return _SUBSET.sub("", name).split("-")[0].split(",")[0].lower()


def span_is_bold(span: dict[str, Any]) -> bool:
    return bool(span["flags"] & 2**4) or ("bold" in str(span["font"]).lower())


def last_int(text: str) -> int | None:
    nums = re.findall(r"\d+", text)
    return int(nums[-1]) if nums else None


# ---------------------------------------------------------------------------
# Document Parse 호출 (page per page, 040 캐시 공유)
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


def parse_page(png: bytes) -> dict[str, Any]:
    extra = {"output_formats": '["text"]', "coordinates": "true", "words": "true"}
    h = hashlib.sha1(png).hexdigest()[:16]
    tag = "document-parse_" + "_".join(f"{k}{v}" for k, v in sorted(extra.items()))
    tag = re.sub(r"[^0-9A-Za-z._-]+", "", tag)[:60]
    cache = CACHE_DIR / f"{tag}_{h}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    data = {"model": "document-parse", **extra}
    delay = 6.0
    last_exc: Exception | None = None
    for attempt in range(7):
        resp = requests.post(
            DIGITIZE_URL,
            headers={"Authorization": f"Bearer {_api_key()}"},
            files={"document": ("page.png", io.BytesIO(png), "image/png")},
            data=data,
            timeout=180,
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
    raise last_exc or RuntimeError("Document Parse 반복 429로 실패")


# ---------------------------------------------------------------------------
# 줄 추출: fitz / parse. 둘 다 정규화 y(yc_norm)를 들고 와 hybrid 매칭에 쓴다.
# ---------------------------------------------------------------------------
def fitz_lines(pdf: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """현재 production과 동일한 PyMuPDF span 줄 + 정규화 y."""
    out: list[dict[str, Any]] = []
    with fitz.open(pdf) as document:
        for pno in toc_pages:
            page = document.load_page(pno - 1)
            page_width = float(page.rect.width) or 1.0
            page_height = float(page.rect.height) or 1.0
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
                    y0 = min(s["bbox"][1] for s in content_spans)
                    y1 = max(s["bbox"][3] for s in content_spans)
                    out.append(
                        {
                            "pdf_page": pno,
                            "text": normalize_text(" ".join(parts)),
                            "height": max(heights),
                            "title_x": round(float(head["bbox"][0]), 2),
                            "page_width": page_width,
                            "is_bold": span_is_bold(head),
                            "font_type": base_font(str(head["font"])),
                            "trailing_page": last_int(" ".join(parts)),
                            "yc_norm": ((y0 + y1) / 2.0) / page_height,
                        }
                    )
    return out


def _parse_words(resp: dict[str, Any]) -> list[tuple]:
    words = []
    for el in resp.get("elements", []):
        if el.get("category", "") in PARSE_DROP_CATEGORIES:
            continue
        for w in el.get("words", []) or []:
            c = w.get("coordinates")
            if not c:
                continue
            xs = [p["x"] for p in c]
            ys = [p["y"] for p in c]
            words.append(
                (
                    w["text"],
                    float(min(xs)),
                    float(min(ys)),
                    float(max(xs)),
                    float(max(ys)),
                )
            )
    return words


def parse_lines(pdf: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """Document Parse(page per page) word box를 줄로 묶는다. 좌표는 정규화(0~1)."""
    out: list[dict[str, Any]] = []
    for pno in toc_pages:
        words = _parse_words(parse_page(render_png(pdf, pno)))
        if not words:
            continue
        letter_h = [w[4] - w[2] for w in words if is_content_text(w[0])]
        med_h = float(np.median(letter_h)) if letter_h else float(np.median([w[4] - w[2] for w in words]))
        thr = max(med_h * 0.6, 1e-6)
        ordered = sorted(words, key=lambda w: ((w[2] + w[4]) / 2.0, w[1]))
        groups: list[list[tuple]] = []
        cur: list[tuple] = []
        cur_yc = None
        for w in ordered:
            yc = (w[2] + w[4]) / 2.0
            if cur and abs(yc - cur_yc) > thr:
                groups.append(cur)
                cur = []
            cur.append(w)
            cur_yc = float(np.mean([(x[2] + x[4]) / 2.0 for x in cur]))
        if cur:
            groups.append(cur)
        for ln in groups:
            ln = sorted(ln, key=lambda w: w[1])
            content = [w for w in ln if is_content_text(w[0])]
            if not content:
                continue
            joined = " ".join(w[0].strip() for w in ln if w[0].strip())
            text = normalize_text(joined)
            if not text:
                continue
            out.append(
                {
                    "pdf_page": pno,
                    "text": text,
                    "height": round(max(w[4] - w[2] for w in content), 4),
                    "title_x": round(min(w[1] for w in content), 4),
                    "page_width": 1.0,
                    "trailing_page": last_int(joined),
                    "yc_norm": float(np.mean([(w[2] + w[4]) / 2.0 for w in content])),
                }
            )
    return out


# ---------------------------------------------------------------------------
# hybrid: fitz backbone + 매칭된 parse 줄 텍스트 이식
# ---------------------------------------------------------------------------
def hybrid_lines(
    fitz_rows: list[dict[str, Any]], parse_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    parse_by_page: dict[int, list[int]] = {}
    for j, p in enumerate(parse_rows):
        parse_by_page.setdefault(p["pdf_page"], []).append(j)

    merged: list[dict[str, Any]] = []
    transplanted = 0
    for row in fitz_rows:
        cands = parse_by_page.get(row["pdf_page"], [])
        fn = normalize_for_match(row["text"])
        best_j, best_score = None, -1.0
        for j in cands:
            p = parse_rows[j]
            if p.get("_used"):
                continue
            if abs(p["yc_norm"] - row["yc_norm"]) > DY_GATE:
                continue
            score = fuzz.token_set_ratio(fn, normalize_for_match(p["text"]))
            if score > best_score:
                best_score, best_j = score, j
        new = dict(row)
        if best_j is not None and best_score >= TEXT_MIN:
            parse_rows[best_j]["_used"] = True
            new["text"] = parse_rows[best_j]["text"]
            new["trailing_page"] = parse_rows[best_j]["trailing_page"]
            transplanted += 1
        merged.append(new)
    return merged, {"fitz_lines": len(fitz_rows), "transplanted": transplanted}


def to_clustered(rows: list[dict[str, Any]]) -> list[ClusteredTocLine]:
    return [
        ClusteredTocLine(
            pdf_page=r["pdf_page"],
            text=r["text"],
            height=r["height"],
            title_x=r["title_x"],
            page_width=r["page_width"],
            is_bold=r.get("is_bold", False),
            font_type=r.get("font_type", "reocr"),
            trailing_page=r.get("trailing_page"),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# heading 후보 (Processor._build_heading_candidates와 동일)
# ---------------------------------------------------------------------------
def build_heading_candidates(pdf, items, offset, total_pages, window):
    if offset is None:
        return {}
    estimated_by_index: dict[int, int] = {}
    needed: set[int] = set()
    for index, item in enumerate(items):
        if item.printed_page is None:
            continue
        estimated = item.printed_page + offset
        estimated_by_index[index] = estimated
        for page in range(estimated - window, estimated + window + 1):
            if 1 <= page <= total_pages:
                needed.add(page)
    if not needed:
        return {}
    heading_pages = extract_selected_page_texts(pdf, sorted(needed))
    return {
        index: extract_heading_candidates(heading_pages, estimated, window)
        for index, estimated in estimated_by_index.items()
    }


class _OffsetView:
    def __init__(self, offset: int | None) -> None:
        self.offset = offset


# ---------------------------------------------------------------------------
# 지표 (040과 동일)
# ---------------------------------------------------------------------------
def range_metrics(detected, gt):
    dset, gset = set(detected), set(gt)
    inter = len(dset & gset)
    return {
        "detected": detected,
        "gt": gt,
        "precision": round(inter / len(dset), 4) if dset else 0.0,
        "recall": round(inter / len(gset), 4) if gset else 0.0,
        "missing": sorted(gset - dset),
        "extra": sorted(dset - gset),
    }


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
        "bookmark_letter_count": len(ref),
        "matched": matched,
        "match_rate": round(matched / len(ref), 4),
        "abs_level_agreement": round(abs_a / matched, 4) if matched else None,
        "rel_depth_agreement": round(ta / tt, 4) if tt else None,
    }


def page_metrics(items):
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
        "items": n,
        "with_printed_page": len(have),
        "coverage": cov,
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


def _cid(t):
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", t).strip("_")[:80]


# ---------------------------------------------------------------------------
# arm 실행
# ---------------------------------------------------------------------------
def run_arm(arm, lines_by_arm, match_stats, offset_value, total_pages, pdf, extractor, config, bms):
    rows = lines_by_arm[arm]
    if not rows:
        return {"status": "no_lines"}, []
    items = extractor.extract_from_clustered_lines(to_clustered(rows), None)
    if not items:
        return {"status": "no_items"}, []
    candidates = build_heading_candidates(pdf, items, offset_value, total_pages, config.heading_search_window)
    aligned = align_toc_items(items, _OffsetView(offset_value), candidates)
    ranges = calculate_content_ranges(aligned, total_pages)
    placeable = sum(1 for a in aligned if a.matched_pdf_page is not None)
    rec = {
        "status": "ok",
        "hierarchy": hmetrics(items),
        "page_channel": page_metrics(items),
        "bookmark": {
            "items": len(items),
            "placeable": placeable,
            "placeable_ratio": round(placeable / len(items), 4) if items else 0.0,
            "ranges": len(ranges),
        },
        "tree_preview": render_tree(items)[:24],
    }
    if arm == "hybrid":
        rec["match_stats"] = match_stats
    if bms is not None:
        rec["weakref"] = weakref_metrics(items, bms)
    return rec, items


def run_book(label, config):
    pdf = ROOT_DIR / label["input_pdf"]
    cid = _cid(label["id"])
    rec: dict[str, Any] = {"id": label["id"], "input_pdf": label["input_pdf"], "arms": {}}
    if not pdf.exists():
        rec["status"] = "missing_pdf"
        return rec

    with fitz.open(pdf) as document:
        total_pages = document.page_count

    # 1) TOC range 탐지: src production 그대로(Parse 미사용).
    pages = extract_page_texts(pdf, max_pages=config.max_toc_search_pages)
    features = calculate_page_features(pages, total_pages)
    toc_detection = detect_toc_pages(features, config.toc_detection)
    review = LlmTocRangeReviewer(config.llm_range_review).review(pdf, toc_detection, total_pages)
    toc_pages = review.pages if review.pages else toc_detection.pages
    rec["toc_pages"] = toc_pages
    rec["range_vs_gt"] = range_metrics(toc_pages, label.get("toc_pages", []))
    if not toc_pages:
        rec["status"] = "no_toc_pages"
        return rec

    # 2) offset: src 결정론 추정(Parse 미사용).
    try:
        oe = estimate_page_offset(pdf, config.offset)
        offset_value = oe.offset
        rec["offset"] = {"offset": offset_value, "confidence": oe.confidence}
    except OffsetEstimationError as exc:
        offset_value = None
        rec["offset"] = {"offset": None, "confidence": 0.0, "error": str(exc)[:200]}

    # 3) 줄 추출(arm 공통 원천). Parse는 전 책에 적용.
    fr = fitz_lines(pdf, toc_pages)
    pr = parse_lines(pdf, toc_pages)
    hr, match_stats = hybrid_lines(fr, pr)
    lines_by_arm = {"baseline": fr, "parse": pr, "hybrid": hr}

    bms = extract_existing_bookmarks(pdf) if label["id"] in BOOKMARKED_IDS else None
    extractor = SizeAwareStagedTocExtractor(config.llm_staged_extraction)

    for arm in ("baseline", "parse", "hybrid"):
        try:
            armrec, items = run_arm(
                arm, lines_by_arm, match_stats, offset_value, total_pages, pdf, extractor, config, bms
            )
        except Exception as exc:  # noqa: BLE001
            rec["arms"][arm] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            continue
        rec["arms"][arm] = armrec
        if items:
            (OUTPUT_DIR / f"{cid}_{arm}_tree.txt").write_text(
                "\n".join(render_tree(items)) + "\n", encoding="utf-8"
            )
    rec["status"] = "ok"
    return rec


def build_finding(results):
    parts = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        rv = r["range_vs_gt"]
        seg = [f"{r['id']}(range P{rv['precision']}/R{rv['recall']}, offset={r['offset'].get('offset')})"]
        for arm in ("baseline", "parse", "hybrid"):
            a = r["arms"].get(arm, {})
            if a.get("status") != "ok":
                seg.append(f"{arm}={a.get('status')}")
                continue
            pc, bk = a["page_channel"], a["bookmark"]
            piece = (
                f"{arm}: cov {pc['with_printed_page']}/{pc['items']}({pc['coverage']}) "
                f"mono={pc['monotonicity']} placeable={bk['placeable']}/{bk['items']}"
            )
            if arm == "hybrid" and "match_stats" in a:
                ms = a["match_stats"]
                piece += f" transplanted={ms['transplanted']}/{ms['fitz_lines']}"
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
            "040에서 Parse가 printed page 채널은 살리지만 계층을 평탄화한 문제를, fitz(계층 "
            "geometry: height/title_x/is_bold/font_type)와 Document Parse(깨끗한 텍스트·페이지번호)를 "
            "줄 매칭으로 합쳐 푼다. Parse는 전 책에 적용한다(native는 기존 bookmark가 있어 production "
            "대상이 아니므로 책별 gate 없음). hybrid는 fitz 줄을 backbone(클러스터=baseline 동일 -> 계층 "
            "보존)으로 두고, 같은 page에서 정규화 y 근접+텍스트 fuzzy로 1:1 매칭된 Parse 줄의 텍스트/"
            "페이지번호만 이식한다(src staged extractor는 printed_page를 줄 텍스트에서 LLM이 읽으므로 "
            "텍스트 교체가 필요). TOC range 탐지/offset은 040과 동일하게 src production·결정론. "
            "baseline/parse/hybrid 3-arm을 GT range P/R, weakref rel/abs, page coverage/monotonicity, "
            "offset 적용 후 placeable로 비교한다."
        ),
        "inputs": [lab["input_pdf"] for lab in summary["_labels_used"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "experiments\\labels\\answer_toc_ranges_manual.json",
        "models": ["document-parse", "solar-pro3"],
        "temperature": 0.0,
        "source_experiment": "040_upstage_parse_src_endtoend",
        "finding": summary["finding"],
        "ran_at": summary["ran_at"],
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
    config = ProcessingConfig(use_llm=True)
    labels = {lab["id"]: lab for lab in json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]}
    used = [labels[i] for i in TARGET_IDS if i in labels]

    results = []
    for lab in used:
        print(f"... running {lab['id']}", flush=True)
        try:
            results.append(run_book(lab, config))
        except Exception as exc:  # noqa: BLE001
            print(f"    !! {lab['id']} 실패: {type(exc).__name__}: {exc}", flush=True)
            results.append({"id": lab["id"], "status": "error", "error": f"{type(exc).__name__}: {exc}"})
        (OUTPUT_DIR / "summary_partial.json").write_text(
            json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "finding": build_finding(results),
        "results": results,
        "_labels_used": used,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "_labels_used"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_experiment(summary)

    print("\n=== exp 041: fitz(계층) + parse(텍스트·페이지번호) hybrid ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']} ({r.get('status')}) {r.get('error','')}")
            continue
        rv = r["range_vs_gt"]
        print(f"\n- {r['id']}  toc_pages={r['toc_pages']} (GT P{rv['precision']}/R{rv['recall']})  offset={r['offset'].get('offset')}")
        for arm in ("baseline", "parse", "hybrid"):
            a = r.get("arms", {}).get(arm, {})
            if a.get("status") != "ok":
                print(f"    {arm:9s}: {a.get('status')} {a.get('error','')}")
                continue
            pc, h, bk = a["page_channel"], a["hierarchy"], a["bookmark"]
            line = (
                f"    {arm:9s}: items={pc['items']:3d} cov={pc['with_printed_page']}/{pc['items']}"
                f"({pc['coverage']}) mono={pc['monotonicity']} placeable={bk['placeable']}/{bk['items']}"
                f" levels={h['level_distribution']}"
            )
            if arm == "hybrid" and "match_stats" in a:
                line += f" transplanted={a['match_stats']['transplanted']}/{a['match_stats']['fitz_lines']}"
            if "weakref" in a and a["weakref"].get("matched"):
                line += f" rel={a['weakref'].get('rel_depth_agreement')} abs={a['weakref'].get('abs_level_agreement')}"
            print(line)
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
