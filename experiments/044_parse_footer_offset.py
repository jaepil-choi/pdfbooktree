"""experiment 044: offset 추정을 042의 offset_suspect 4권만 대상으로 새 방식으로 다시 풀어본다.

배경
- 042에서 offset_suspect로 재분류된 4권(Kaggle Book/Bishop PRML/Refactoring/Erik Westra)은
  기존 src `estimate_page_offset`이 "clean한 offset을 못 찾겠다"며 실패한 책들이다(dominance_ratio/
  run 같은 통계 기준 미달). 이 추정기는 fitz native text로 본문 여러 page의 footer/header 숫자를
  긁어 모아 통계적으로 다수결을 낸다 — 스캔본이나 배치가 특이한 책에서 통계가 안 깨끗하면 그냥
  포기한다.

새 방식(Document Parse footer/header OCR 직접 읽기)
- 우리가 Document Parse를 부를 때 지금까지는 category가 header/footer인 element를 "TOC 줄이
  아니다"라며 버리기만 했다(PARSE_DROP_CATEGORIES). 그런데 본문 page에서는 그 header/footer
  영역이 바로 인쇄 페이지 번호 그 자체다.
- 본문 전체에서 총 페이지수 기준으로 고르게 K개 sample page를 뽑아 Document Parse로 OCR하고,
  category가 header 또는 footer인 element의 text에서 고립된 정수(페이지 번호로 그럴듯한 범위)를
  읽는다. (pdf_page, printed_page) 쌍을 모아 `pdf_page - printed_page`의 최빈값을 offset으로
  채택한다. 통계적 "clean함" 기준(dominance_ratio 등) 없이, 실측값 다수결이라 더 관대하다.

평가
- 새 offset을 기존 src의 heading-match 정렬(align_toc_items)에 그대로 꽂아서, 042와 동일한
  page_channel_stats(=Stage C: title 매칭된 pair 중 matched_pdf_page가 bookmark의 실제 pdf_page와
  얼마나 맞는지)를 old(전부 missing)와 new로 나란히 비교한다.

대상: 042 summary.json에서 diagnosis == "offset_suspect"였던 4권만.

실행 (Document Parse + solar-pro3 호출):
    uv run --with truststore python experiments/044_parse_footer_offset.py

출력: experiments/outputs/044_parse_footer_offset/
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
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, title_has_letter
from pdfbooktree.pdf.text import extract_selected_page_texts
from pdfbooktree.toc.staged_llm_extract import ClusteredTocLine, SizeAwareStagedTocExtractor
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "044_parse_footer_offset"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
# 042가 이 4권의 toc range page를 이미 Parse해 캐싱해뒀다(hybrid 줄 재구성용). 공유해서 재호출을 줄인다.
CACHE_DIR = ROOT_DIR / "experiments" / "outputs" / "042_bookmark_gt_hybrid_confusion" / "cache"
PRIOR_SUMMARY = ROOT_DIR / "experiments" / "outputs" / "042_bookmark_gt_hybrid_confusion" / "summary.json"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"

# 042에서 diagnosis == "offset_suspect"였던 4권(고정). toc_pages는 042가 이미 찾아둔 값을 그대로 쓴다
# (range 탐지는 이 실험의 대상이 아니다).
TARGETS: list[dict[str, Any]] = [
    {
        "id": "Konrad_Banachewicz_Luca_Massaron_The_Kaggle_Book_Packt_2022",
        "pdf": r"data\300STUDY\textbooks\Konrad Banachewicz, Luca Massaron - The Kaggle Book-Packt (2022).pdf",
        "toc_pages": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35],
    },
    {
        "id": "Christopher_M_Bishop_Pattern_Recognition_and_Machine_Learning_Springer_2011",
        "pdf": r"data\300STUDY\textbooks\Christopher M. Bishop - Pattern Recognition and Machine Learning-Springer (2011).pdf",
        "toc_pages": [11, 12, 13, 14, 15, 16, 17, 18],
    },
    {
        "id": "Addison_Wesley_Object_Technology_Series_Martin_Fowler_Refactoring_Improving_the_",
        "pdf": r"data\300STUDY\textbooks\(Addison-Wesley Object Technology Series) Martin Fowler - Refactoring_ Improving the Design of Existing Code-Addison-Wesley Professional (2018)[cs].pdf",
        "toc_pages": list(range(2, 27)),
    },
    {
        "id": "Erik_Westra_Modular_Programming_with_Python_introducing_modular_techniques_for_b",
        "pdf": r"data\300STUDY\textbooks\Erik Westra - Modular Programming with Python_ introducing modular techniques for building sophisticated programs using Python (2016, Packt Publishing) - libgen.lc.pdf",
        "toc_pages": [8, 9, 10, 11],
    },
]

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
RENDER_DPI = 200
PARSE_DROP_CATEGORIES = {"footnote"}  # header/footer는 이번엔 버리지 않는다 — 오히려 이게 목표 신호다.

# offset sample 파라미터
N_SAMPLES = 16
EDGE_MARGIN = 5  # 앞/뒤 이 만큼은 표지/색인이라 페이지 번호가 불안정해 샘플에서 뺀다.
MIN_SUPPORT = 3  # 최빈 offset을 지지하는 sample 수가 이 이상이어야 채택한다.

ITEM_MATCH_CUTOFF = 88.0
PAGE_TOLERANCE = 1

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_SUBSET = re.compile(r"^[A-Z]{6}\+")
_NUM = re.compile(r"\d+")


def is_content_text(text: str) -> bool:
    s = text.strip()
    return bool(s and (_HANGUL.search(s) or _LATIN2.search(s)))


def base_font(name: str) -> str:
    return _SUBSET.sub("", name).split("-")[0].split(",")[0].lower()


def span_is_bold(span: dict[str, Any]) -> bool:
    return bool(span["flags"] & 2**4) or ("bold" in str(span["font"]).lower())


def last_int(text: str) -> int | None:
    nums = _NUM.findall(text)
    return int(nums[-1]) if nums else None


# ---------------------------------------------------------------------------
# Document Parse
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
# 줄 추출: fitz backbone + Parse 텍스트/페이지번호 이식 (042와 동일 로직, TOC page용)
# ---------------------------------------------------------------------------
def fitz_lines(pdf: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
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
        if el.get("category", "") in {"header", "footer", "footnote"}:
            continue
        for w in el.get("words", []) or []:
            c = w.get("coordinates")
            if not c:
                continue
            xs = [p["x"] for p in c]
            ys = [p["y"] for p in c]
            words.append((w["text"], float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))))
    return words


def parse_lines(pdf: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
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


def hybrid_lines(fitz_rows: list[dict[str, Any]], parse_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    DY_GATE, TEXT_MIN = 0.05, 50.0
    parse_by_page: dict[int, list[int]] = {}
    for j, p in enumerate(parse_rows):
        parse_by_page.setdefault(p["pdf_page"], []).append(j)
    merged: list[dict[str, Any]] = []
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
        merged.append(new)
    return merged


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
# 새 offset: 본문 sample page의 Parse header/footer OCR에서 인쇄 페이지 번호를 직접 읽는다.
# ---------------------------------------------------------------------------
def pick_sample_pages(total_pages: int, toc_pages: list[int], n: int) -> list[int]:
    lo, hi = EDGE_MARGIN + 1, max(EDGE_MARGIN + 1, total_pages - EDGE_MARGIN)
    if hi <= lo:
        return []
    toc_set = set(toc_pages)
    step = max(1, (hi - lo) // n)
    pages = []
    p = lo
    while p <= hi and len(pages) < n * 2:
        if p not in toc_set:
            pages.append(p)
        p += step
    return pages[:n]


def read_printed_page(resp: dict[str, Any], pdf_page: int, total_pages: int) -> int | None:
    """header/footer element 텍스트에서 페이지 번호로 그럴듯한 고립 정수를 고른다."""
    candidates: list[int] = []
    for el in resp.get("elements", []):
        if el.get("category", "") not in {"header", "footer"}:
            continue
        text = el.get("content", {}).get("text", "")
        for tok in re.findall(r"\b\d{1,4}\b", text):
            n = int(tok)
            # 연도(19xx/20xx)나 total_pages를 크게 벗어나는 값은 페이지 번호가 아닐 가능성이 높다.
            if 1 <= n <= total_pages + 100 and not (1900 <= n <= 2100):
                candidates.append(n)
    if not candidates:
        return None
    # header/footer에 숫자가 여럿이면(ISBN 조각 등) pdf_page와 가장 가까운 값을 페이지 번호로 본다.
    return min(candidates, key=lambda n: abs(n - pdf_page))


def estimate_offset_via_parse_footer(pdf: Path, total_pages: int, toc_pages: list[int]) -> dict[str, Any]:
    samples = pick_sample_pages(total_pages, toc_pages, N_SAMPLES)
    readings: list[dict[str, Any]] = []
    for pno in samples:
        resp = parse_page(render_png(pdf, pno))
        printed = read_printed_page(resp, pno, total_pages)
        readings.append({"pdf_page": pno, "printed_page": printed})
    diffs = [r["pdf_page"] - r["printed_page"] for r in readings if r["printed_page"] is not None]
    if not diffs:
        return {"offset": None, "support": 0, "samples": len(samples), "readings": readings}
    counts = Counter(diffs)
    offset, support = counts.most_common(1)[0]
    if support < MIN_SUPPORT:
        return {"offset": None, "support": support, "samples": len(samples), "readings": readings}
    return {"offset": offset, "support": support, "samples": len(samples), "readings": readings}


# ---------------------------------------------------------------------------
# heading 후보 (src Processor와 동일)
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
# 평가: 042와 동일한 Stage C(page channel)
# ---------------------------------------------------------------------------
def normalize_bookmark_levels_kept(bms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [b for b in bms if title_has_letter(b["title"])]
    if not kept:
        return []
    mn = min(b["level"] for b in kept)
    return [
        {"title": b["title"], "level": b["level"] - mn + 1, "order": b["order"], "pdf_page": b["pdf_page"]}
        for b in kept
    ]


def match_pairs(aligned_items, ref: list[dict[str, Any]]) -> list[tuple[dict[str, Any], Any]]:
    if not ref or not aligned_items:
        return []
    norms = [normalize_for_match(it.title) for it in aligned_items]
    idx_by: dict[str, int] = {}
    choices: list[str] = []
    for i, n in enumerate(norms):
        if n and n not in idx_by:
            idx_by[n] = i
            choices.append(n)
    pairs = []
    for bm in ref:
        bn = normalize_for_match(bm["title"])
        if not bn:
            continue
        r = process.extractOne(bn, choices, scorer=fuzz.token_set_ratio, score_cutoff=ITEM_MATCH_CUTOFF)
        if r:
            pairs.append((bm, aligned_items[idx_by[r[0]]]))
    return pairs


def page_channel_stats(pairs: list[tuple[dict[str, Any], Any]]) -> dict[str, Any]:
    exact = near = off = missing = 0
    for bm, it in pairs:
        pred, gt = it.matched_pdf_page, bm["pdf_page"]
        if pred is None or gt is None:
            missing += 1
            continue
        diff = abs(pred - gt)
        if diff == 0:
            exact += 1
        elif diff <= PAGE_TOLERANCE:
            near += 1
        else:
            off += 1
    n = len(pairs)
    checked = exact + near + off
    return {
        "pairs": n,
        "exact": exact,
        "near": near,
        "off": off,
        "missing": missing,
        "exact_or_near_rate": round((exact + near) / checked, 4) if checked else None,
    }


# ---------------------------------------------------------------------------
# 책 1권 실행
# ---------------------------------------------------------------------------
def run_book(target: dict[str, Any], config: ProcessingConfig, old_by_id: dict[str, Any]) -> dict[str, Any]:
    pdf = ROOT_DIR / target["pdf"]
    rec: dict[str, Any] = {"id": target["id"], "input_pdf": target["pdf"]}
    if not pdf.exists():
        rec["status"] = "missing_pdf"
        return rec

    with fitz.open(pdf) as document:
        total_pages = document.page_count

    bms = extract_existing_bookmarks(pdf)
    ref = normalize_bookmark_levels_kept(bms)
    toc_pages = target["toc_pages"]

    fr = fitz_lines(pdf, toc_pages)
    pr = parse_lines(pdf, toc_pages)
    hr = hybrid_lines(fr, pr)

    extractor = SizeAwareStagedTocExtractor(config.llm_staged_extraction)
    items = extractor.extract_from_clustered_lines(to_clustered(hr), None)
    rec["item_count"] = len(items)
    if not items:
        rec["status"] = "no_items"
        return rec

    new_offset = estimate_offset_via_parse_footer(pdf, total_pages, toc_pages)
    rec["new_offset"] = {k: v for k, v in new_offset.items() if k != "readings"}
    rec["new_offset_readings"] = new_offset["readings"]

    candidates = build_heading_candidates(pdf, items, new_offset["offset"], total_pages, config.heading_search_window)
    aligned = align_toc_items(items, _OffsetView(new_offset["offset"]), candidates)
    pairs = match_pairs(aligned, ref)
    rec["stage_c_new"] = page_channel_stats(pairs)
    rec["item_recall"] = round(len(pairs) / len(ref), 4) if ref else None

    old = old_by_id.get(target["id"], {})
    rec["old_offset"] = old.get("offset")
    rec["stage_c_old"] = old.get("stage_c_page_channel")
    rec["status"] = "ok"
    return rec


def build_finding(results: list[dict[str, Any]]) -> str:
    parts = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: status={r.get('status')}")
            continue
        no, nc = r["new_offset"], r["stage_c_new"]
        oo, oc = r.get("old_offset"), r.get("stage_c_old") or {}
        parts.append(
            f"{r['id']}: old_offset={oo and oo.get('offset')}(exact={oc.get('exact')},missing={oc.get('missing')}) "
            f"-> new_offset={no.get('offset')}(support={no.get('support')}/{no.get('samples')}) "
            f"exact={nc['exact']} near={nc['near']} off={nc['off']} missing={nc['missing']}"
        )
    return " || ".join(parts)


def record_experiment(summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "042에서 diagnosis=offset_suspect였던 4권만 대상으로, fitz native text 통계 기반 "
            "estimate_page_offset(dominance_ratio/run 등 clean 기준 미달 시 포기) 대신 본문 sample "
            "page를 Document Parse로 OCR해 header/footer category에서 인쇄 페이지 번호를 직접 읽고 "
            "pdf_page-printed_page 최빈값으로 offset을 잡는 실측 기반 방식을 검증한다. 평가는 042와 "
            "동일한 Stage C(page channel: title 매칭된 pair의 matched_pdf_page vs bookmark 실제 "
            "pdf_page)로 old(전부 missing)/new를 비교한다."
        ),
        "inputs": [t["pdf"] for t in TARGETS],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "data/300STUDY 기존 bookmark(042와 동일 golden 재활용)",
        "models": ["document-parse", "solar-pro3"],
        "temperature": 0.0,
        "source_experiment": "042_bookmark_gt_hybrid_confusion",
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


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = ProcessingConfig(use_llm=True)

    old_by_id: dict[str, Any] = {}
    if PRIOR_SUMMARY.exists():
        prior = json.loads(PRIOR_SUMMARY.read_text(encoding="utf-8"))
        old_by_id = {r["id"]: r for r in prior.get("results", [])}

    results = []
    for target in TARGETS:
        print(f"\n... running {target['id']}", flush=True)
        try:
            results.append(run_book(target, config, old_by_id))
        except Exception as exc:  # noqa: BLE001
            print(f"    !! 실패: {type(exc).__name__}: {exc}", flush=True)
            results.append({"id": target["id"], "input_pdf": target["pdf"], "status": "error", "error": f"{type(exc).__name__}: {exc}"})
        (OUTPUT_DIR / "summary_partial.json").write_text(
            json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "finding": build_finding(results),
        "results": results,
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    record_experiment(summary)

    print("\n=== exp 044: Parse footer/header OCR 기반 offset 재추정 (offset_suspect 4권) ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"- {r['id']}: {r.get('status')}")
            continue
        print(
            f"- {r['id']}: new_offset={r['new_offset'].get('offset')} "
            f"(support={r['new_offset'].get('support')}/{r['new_offset'].get('samples')}) "
            f"stage_c={r['stage_c_new']}"
        )
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
