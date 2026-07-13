"""experiment 042: data/300STUDY에서 뽑은 bookmark-보유 PDF를 golden answer 삼아
041의 hybrid(fitz 계층 backbone + Document Parse 텍스트/페이지번호 이식) 파이프라인을
end-to-end로 돌리고, 실패가 어느 단계에서 났는지 구분하는 confusion-matrix류 지표를 낸다.

배경
- 040/041은 experiments/labels/answer_toc_ranges_manual.json에 수기로 라벨링한 5권만 썼다.
  이번엔 수작업 라벨 없이, data/300STUDY의 "기존 bookmark"를 golden TOC로 재활용한다.
  (production에서는 bookmark 있는 책은 애초에 skip 대상이지만, 040/041과 동일하게 평가용으로만
  bookmark를 golden 삼아 추출 파이프라인을 '있다고 안 치고' 통째로 태운다.)

후보 필터
1) 기존 bookmark(TOC)가 존재할 것
2) 전체 페이지 50페이지 미만 제외
3) bookmark 제목이 전부 숫자뿐인 것(letter 없는 것) 제외 -> has_letter_bookmark
4) bookmark 개수가 10개 이하인 PDF 제외 -> bookmark가 거의 없는 책은 부실/잘못된 bookmark로
   보고(추후 이런 책은 전부 overwrite 대상), golden answer 후보에서 뺀다 -> MIN_BOOKMARK_COUNT

N_BOOKS권은 필터를 통과한 후보 중 고정 seed로 random sample한다(재현 가능).

왜 단순 P/R이 아니라 4단계로 나누는가
- 수기 TOC range 라벨이 없어서 detect_toc_pages의 range precision/recall은 직접 못 잰다.
  대신 "그 range page들에서 뽑힌 raw 줄 텍스트 안에 실제 bookmark 제목이 얼마나 fuzzy로
  발견되는가"(raw_line_recall)를 range 품질의 proxy로 쓴다. range가 완전히 엉뚱한 페이지를
  잡았다면 raw_line_recall 자체가 낮게 나온다.
- raw_line_recall은 높은데 최종 item title match_rate(=item_recall)가 낮으면, range는 맞았고
  그 다음 LLM staged extraction/dedup 단계에서 항목을 잃어버린 것으로 본다.
- title이 매칭된 pair에 한해서만 page 채널(matched_pdf_page vs bookmark의 실제 pdf_page)과
  계층(item.level vs bookmark 정규화 level)을 따로 채점한다. 이러면 "제목은 맞았는데 페이지가
  틀렸다"와 "제목/페이지는 맞았는데 계층이 틀렸다"를 분리해서 볼 수 있다.
- 계층은 책마다 절대 level 스케일이 달라서, 최소값을 1로 맞추고 3 이상은 "3+"로 묶어
  3x3 confusion matrix(GT bucket x predicted bucket)로 전 책 합산한다.

단계별 verdict(휴리스틱, 임계값은 상단 상수로 조정 가능)
- range_suspect      : raw_line_recall < RANGE_SUSPECT_THRESHOLD
- extraction_suspect : raw_line_recall은 괜찮은데 item_recall과의 gap이 큼
- page_suspect       : title 매칭된 pair 중 page exact/near 비율이 낮음
- hierarchy_suspect  : title 매칭된 pair 중 abs level agreement가 낮음
- ok                 : 위 전부 통과

실행 (Document Parse 호출이 있어 오래 걸리고 API 과금 발생):
    uv run --with truststore python experiments/042_bookmark_gt_hybrid_confusion.py

후보만 미리 보고 싶으면(Parse 호출 없음):
    uv run python experiments/042_bookmark_gt_hybrid_confusion.py --dry-run

출력: experiments/outputs/042_bookmark_gt_hybrid_confusion/
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
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
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, has_letter_bookmark, title_has_letter
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

# 사내 TLS 가로채기 프록시 환경에서 Upstage 호출이 SSL 검증으로 막힌다. truststore가 있으면
# OS(Windows) 신뢰 저장소를 쓰게 해 우회한다(verify=False 금지).
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_SUBDIR = "300STUDY"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "042_bookmark_gt_hybrid_confusion"
CACHE_DIR = OUTPUT_DIR / "cache"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "042_bookmark_gt_hybrid_confusion"

# 후보 필터
MIN_TOTAL_PAGES = 50
# bookmark가 10개 이하인 PDF는 잘못/부실 bookmark(추후 전부 overwrite 대상)로 보고 후보에서 뺀다.
MIN_BOOKMARK_COUNT = 10

# 선택
SEED = 123
N_BOOKS = 20

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
RENDER_DPI = 200
PARSE_DROP_CATEGORIES = {"header", "footer", "footnote"}

# hybrid 매칭 파라미터 (041과 동일)
DY_GATE = 0.05
TEXT_MIN = 50.0

# 단계 진단 임계값
RANGE_RECALL_CUTOFF = 80.0  # raw line <-> bookmark title fuzzy cutoff
ITEM_MATCH_CUTOFF = 88.0  # item title <-> bookmark title fuzzy cutoff (041과 동일)
PAGE_TOLERANCE = 1  # matched_pdf_page vs bookmark pdf_page 허용 오차(page)

RANGE_SUSPECT_THRESHOLD = 0.4
EXTRACTION_GAP_THRESHOLD = 0.25
PAGE_SUSPECT_THRESHOLD = 0.6
HIER_SUSPECT_THRESHOLD = 0.6

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


def _cid(t: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", t).strip("_")[:80]


# ---------------------------------------------------------------------------
# 1) 후보 discovery + 필터 + 선택
# ---------------------------------------------------------------------------
def discover_candidates(data_dir: Path) -> list[dict[str, Any]]:
    """data_dir 아래 PDF 중 (bookmark 존재) and (총 페이지>=MIN_TOTAL_PAGES)
    and (bookmark 제목에 letter 하나 이상)을 만족하는 후보를 모은다."""

    pdfs = sorted(data_dir.rglob("*.pdf"))
    print(f"discovery: {len(pdfs)}개 PDF 스캔", flush=True)
    candidates: list[dict[str, Any]] = []
    for i, pdf in enumerate(pdfs, start=1):
        if i % 100 == 0:
            print(f"  ... {i}/{len(pdfs)} 스캔, 후보 {len(candidates)}개", flush=True)
        try:
            with fitz.open(pdf) as document:
                page_count = document.page_count
                toc_raw = document.get_toc(simple=False)
        except Exception:
            continue
        if page_count < MIN_TOTAL_PAGES:
            continue
        if not toc_raw:
            continue
        bookmarks = [
            {
                "order": order,
                "level": int(item[0]),
                "title": normalize_text(str(item[1])),
                "pdf_page": int(item[2]) if int(item[2]) > 0 else None,
            }
            for order, item in enumerate(toc_raw, start=1)
        ]
        if not has_letter_bookmark(bookmarks):
            continue
        if len(bookmarks) <= MIN_BOOKMARK_COUNT:
            continue
        candidates.append(
            {
                "pdf": str(pdf.relative_to(ROOT_DIR)).replace("/", "\\"),
                "page_count": page_count,
                "bookmark_count": len(bookmarks),
                "letter_bookmark_count": sum(1 for b in bookmarks if title_has_letter(b["title"])),
            }
        )
    print(f"discovery 완료: 후보 {len(candidates)}개 (전체 {len(pdfs)}개 중)", flush=True)
    return candidates


def select_books(candidates: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    pool = list(candidates)
    rng.shuffle(pool)
    return pool[:n]


# ---------------------------------------------------------------------------
# 2) Document Parse 호출
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
# 3) 줄 추출: fitz backbone + Document Parse 텍스트/페이지번호 이식 (041과 동일 로직)
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
        if el.get("category", "") in PARSE_DROP_CATEGORIES:
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
# 4) heading 후보 (Processor._build_heading_candidates와 동일)
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
# 5) 4단계 진단 지표
# ---------------------------------------------------------------------------
def normalize_bookmark_levels_kept(bms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """letter 있는 bookmark만 남기고 level을 1부터 시작하도록 정규화한다.
    (041과 달리 pdf_page도 그대로 들고 온다 — page 채널 채점에 필요)"""

    kept = [b for b in bms if title_has_letter(b["title"])]
    if not kept:
        return []
    mn = min(b["level"] for b in kept)
    return [
        {
            "title": b["title"],
            "level": b["level"] - mn + 1,
            "order": b["order"],
            "pdf_page": b["pdf_page"],
        }
        for b in kept
    ]


def raw_line_recall(rows: list[dict[str, Any]], gt_titles: list[str]) -> dict[str, Any]:
    """Stage A: 탐지된 toc range page의 raw 줄 텍스트 안에 실제 bookmark 제목이
    얼마나 fuzzy로 발견되는지 -> range 탐지 품질의 proxy."""

    texts = [normalize_for_match(r["text"]) for r in rows if r["text"].strip()]
    total = len(gt_titles)
    if total == 0 or not texts:
        return {"matched": 0, "total": total, "recall": None}
    matched = 0
    for t in gt_titles:
        tn = normalize_for_match(t)
        if not tn:
            total -= 1
            continue
        hit = process.extractOne(tn, texts, scorer=fuzz.token_set_ratio, score_cutoff=RANGE_RECALL_CUTOFF)
        if hit:
            matched += 1
    return {"matched": matched, "total": total, "recall": round(matched / total, 4) if total else None}


def match_pairs(aligned_items, ref: list[dict[str, Any]]) -> list[tuple[dict[str, Any], Any]]:
    """Stage B 입력: bookmark(ref) <-> 최종 aligned item을 title fuzzy 1:1로 짝짓는다."""

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
    """Stage C: title이 맞은 pair에서 최종 배치 page(matched_pdf_page)가 bookmark의
    실제 pdf_page와 얼마나 맞는지."""

    exact = near = off = missing = 0
    for bm, it in pairs:
        pred = it.matched_pdf_page
        gt = bm["pdf_page"]
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
        "exact_rate": round(exact / checked, 4) if checked else None,
        "exact_or_near_rate": round((exact + near) / checked, 4) if checked else None,
    }


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def hierarchy_stats(pairs: list[tuple[dict[str, Any], Any]]) -> dict[str, Any]:
    """Stage D: title이 맞은 pair에서 계층(level)이 얼마나 맞는지.
    절대 일치(abs)와, order 순서상 인접 pair끼리 깊이 변화 방향이 맞는지(rel)를 같이 본다."""

    abs_ok = sum(1 for bm, it in pairs if bm["level"] == it.level)
    ordered = sorted(pairs, key=lambda p: p[0]["order"])
    tt = ta = 0
    for (ba, ia), (bb, ib) in zip(ordered, ordered[1:]):
        tt += 1
        if _sign(bb["level"] - ba["level"]) == _sign(ib.level - ia.level):
            ta += 1
    n = len(pairs)
    return {
        "pairs": n,
        "abs_level_agreement": round(abs_ok / n, 4) if n else None,
        "rel_depth_agreement": round(ta / tt, 4) if tt else None,
    }


def level_bucket(level: int, min_level: int) -> str:
    b = level - min_level + 1
    return "3+" if b >= 3 else str(b)


def accumulate_confusion(
    matrix: dict[str, dict[str, int]], pairs: list[tuple[dict[str, Any], Any]], items_levels: list[int]
) -> None:
    """전 책 합산 3x3(GT bucket x predicted bucket) confusion matrix."""

    if not pairs:
        return
    gt_min = 1  # ref 이미 normalize_bookmark_levels_kept에서 1부터 시작
    pred_min = min(items_levels) if items_levels else 1
    for bm, it in pairs:
        gt_b = level_bucket(bm["level"], gt_min)
        pred_b = level_bucket(it.level, pred_min)
        matrix.setdefault(gt_b, {"1": 0, "2": 0, "3+": 0})
        matrix[gt_b][pred_b] += 1


def diagnose(range_recall: float | None, item_recall: float | None, page: dict, hier: dict) -> str:
    if range_recall is None:
        return "no_gt_titles"
    if range_recall < RANGE_SUSPECT_THRESHOLD:
        return "range_suspect"
    if item_recall is not None and (range_recall - item_recall) > EXTRACTION_GAP_THRESHOLD:
        return "extraction_suspect"
    if page["exact_or_near_rate"] is None:
        # title은 매칭됐는데 page 채널 자체를 못 잰 경우 -> 대개 offset 추정 실패(전부 missing).
        # 이전 버전은 이 케이스를 그냥 통과시켜 hierarchy만 괜찮으면 "ok"로 잘못 찍었다.
        if page["pairs"] > 0:
            return "offset_suspect"
    elif page["exact_or_near_rate"] < PAGE_SUSPECT_THRESHOLD:
        return "page_suspect"
    if hier["abs_level_agreement"] is not None and hier["abs_level_agreement"] < HIER_SUSPECT_THRESHOLD:
        return "hierarchy_suspect"
    return "ok"


def render_tree(items) -> list[str]:
    out = []
    for it in items:
        ind = "    " * max(it.level - 1, 0)
        pg = it.printed_page if it.printed_page is not None else "-"
        out.append(f"{ind}[{pg}] L{it.level} {it.title}")
    return out


# ---------------------------------------------------------------------------
# 6) 책 1권 실행 (hybrid arm만)
# ---------------------------------------------------------------------------
def run_book(entry: dict[str, Any], config: ProcessingConfig) -> dict[str, Any]:
    pdf = ROOT_DIR / entry["pdf"]
    cid = _cid(pdf.stem)
    rec: dict[str, Any] = {"id": cid, "input_pdf": entry["pdf"]}
    if not pdf.exists():
        rec["status"] = "missing_pdf"
        return rec

    with fitz.open(pdf) as document:
        total_pages = document.page_count

    bms = extract_existing_bookmarks(pdf)
    ref = normalize_bookmark_levels_kept(bms)
    gt_titles = [b["title"] for b in ref]
    rec["gt_bookmark_count"] = len(bms)
    rec["gt_letter_bookmark_count"] = len(ref)

    # 1) TOC range 탐지: src production 그대로.
    pages = extract_page_texts(pdf, max_pages=config.max_toc_search_pages)
    features = calculate_page_features(pages, total_pages)
    toc_detection = detect_toc_pages(features, config.toc_detection)
    review = LlmTocRangeReviewer(config.llm_range_review).review(pdf, toc_detection, total_pages)
    toc_pages = review.pages if review.pages else toc_detection.pages
    rec["toc_pages"] = toc_pages
    if not toc_pages:
        rec["status"] = "no_toc_pages"
        rec["diagnosis"] = "range_suspect"
        return rec

    # 2) offset: src 결정론 추정.
    try:
        oe = estimate_page_offset(pdf, config.offset)
        offset_value = oe.offset
        rec["offset"] = {"offset": offset_value, "confidence": oe.confidence}
    except OffsetEstimationError as exc:
        offset_value = None
        rec["offset"] = {"offset": None, "confidence": 0.0, "error": str(exc)[:200]}

    # 3) 줄 추출: fitz backbone + Parse 텍스트/페이지번호 이식(hybrid만 돈다).
    fr = fitz_lines(pdf, toc_pages)
    pr = parse_lines(pdf, toc_pages)
    hr, match_stats = hybrid_lines(fr, pr)
    rec["match_stats"] = match_stats

    # Stage A: range 탐지 proxy — raw hybrid 줄 텍스트 안에 bookmark 제목이 있는가.
    rec["stage_a_range_recall"] = raw_line_recall(hr, gt_titles)

    if not hr:
        rec["status"] = "no_lines"
        rec["diagnosis"] = "range_suspect"
        return rec

    extractor = SizeAwareStagedTocExtractor(config.llm_staged_extraction)
    items = extractor.extract_from_clustered_lines(to_clustered(hr), None)
    if not items:
        rec["status"] = "no_items"
        rec["diagnosis"] = "extraction_suspect"
        return rec

    candidates = build_heading_candidates(pdf, items, offset_value, total_pages, config.heading_search_window)
    aligned = align_toc_items(items, _OffsetView(offset_value), candidates)

    pairs = match_pairs(aligned, ref)
    range_recall = rec["stage_a_range_recall"]["recall"]
    item_recall = round(len(pairs) / len(ref), 4) if ref else None

    page_stats = page_channel_stats(pairs)
    hier_stats = hierarchy_stats(pairs)

    rec["stage_b_item_recall"] = {"matched": len(pairs), "total": len(ref), "recall": item_recall}
    rec["stage_c_page_channel"] = page_stats
    rec["stage_d_hierarchy"] = hier_stats
    rec["diagnosis"] = diagnose(range_recall, item_recall, page_stats, hier_stats)
    rec["item_count"] = len(items)
    rec["item_levels"] = [it.level for it in items]
    rec["status"] = "ok"

    (OUTPUT_DIR / f"{cid}_hybrid_tree.txt").write_text("\n".join(render_tree(items)) + "\n", encoding="utf-8")
    (OUTPUT_DIR / f"{cid}_bookmark_gt.txt").write_text(
        "\n".join(f"{'  ' * (b['level'] - 1)}[{b['pdf_page']}] L{b['level']} {b['title']}" for b in ref) + "\n",
        encoding="utf-8",
    )

    return rec, pairs, [it.level for it in items]  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 7) 요약 + experiments.json 기록
# ---------------------------------------------------------------------------
def build_finding(results: list[dict[str, Any]], confusion: dict[str, dict[str, int]]) -> str:
    parts = []
    diag_counts = Counter(r.get("diagnosis", r.get("status")) for r in results)
    parts.append(f"진단 분포: {dict(diag_counts)}")
    for r in results:
        if r.get("status") not in ("ok",):
            parts.append(f"{r['id']}: status={r.get('status')} diagnosis={r.get('diagnosis')}")
            continue
        a, b, c, d = r["stage_a_range_recall"], r["stage_b_item_recall"], r["stage_c_page_channel"], r["stage_d_hierarchy"]
        parts.append(
            f"{r['id']}: diag={r['diagnosis']} rangeRecall={a['recall']}({a['matched']}/{a['total']}) "
            f"itemRecall={b['recall']}({b['matched']}/{b['total']}) "
            f"page(exact={c['exact']},near={c['near']},off={c['off']},missing={c['missing']}) "
            f"hier(abs={d['abs_level_agreement']},rel={d['rel_depth_agreement']},n={d['pairs']})"
        )
    parts.append(f"hierarchy confusion matrix(GT x Pred): {confusion}")
    return " || ".join(parts)


def record_experiment(summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "data/300STUDY에서 (bookmark 존재, 총 페이지>=50, bookmark 제목이 전부 숫자는 아님, "
            "bookmark 개수>10) 조건으로 필터링한 후(bookmark<=10은 부실/잘못된 bookmark로 보고 "
            "제외) 고정 seed로 N권을 뽑아, 041의 hybrid(fitz 계층 backbone + "
            "Document Parse 텍스트/페이지번호 이식) 파이프라인을 기존 bookmark를 golden TOC 삼아 "
            "end-to-end로 돌린다. 수기 range 라벨이 없어 range 탐지 품질은 raw 줄 텍스트 안 bookmark "
            "제목 발견율(stage A)로 proxy하고, item title 매칭률(stage B), title 매칭된 pair의 page "
            "채널 정확도(stage C), 계층 정확도(stage D)를 단계별로 분리해 어느 단계에서 오류가 나는지 "
            "구분한다. 계층은 GT/예측 각각 최소 level을 1로 맞추고 3 이상은 3+로 묶어 전 책 합산 "
            "confusion matrix로도 낸다."
        ),
        "inputs": [r["input_pdf"] for r in summary["results"] if "input_pdf" in r],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "data/300STUDY 기존 bookmark(golden 재활용, 수기 라벨 아님)",
        "models": ["document-parse", "solar-pro3"],
        "temperature": 0.0,
        "source_experiment": "041_parse_fitz_hybrid_lines",
        "selection": {"seed": SEED, "n_books": N_BOOKS, "candidate_count": summary["candidate_count"]},
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=N_BOOKS, help="선택할 책 수")
    parser.add_argument("--seed", type=int, default=SEED, help="선택 seed")
    parser.add_argument("--dry-run", action="store_true", help="후보 discovery/선택만 하고 추출은 돌리지 않는다")
    args = parser.parse_args()

    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data_dir = ROOT_DIR / "data" / DATA_SUBDIR
    candidates = discover_candidates(data_dir)
    (OUTPUT_DIR / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    selected = select_books(candidates, args.n, args.seed)
    (OUTPUT_DIR / "selected.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n선택된 {len(selected)}권 (seed={args.seed}):")
    for e in selected:
        print(f"  - {e['pdf']} (page={e['page_count']}, bookmark={e['bookmark_count']})")

    if args.dry_run:
        print("\n--dry-run: 여기서 종료(Document Parse 호출 없음)")
        return

    config = ProcessingConfig(use_llm=True)
    results: list[dict[str, Any]] = []
    confusion: dict[str, dict[str, int]] = {}
    for entry in selected:
        print(f"\n... running {entry['pdf']}", flush=True)
        try:
            out = run_book(entry, config)
            if isinstance(out, tuple):
                rec, pairs, item_levels = out
                accumulate_confusion(confusion, pairs, item_levels)
            else:
                rec = out
            results.append(rec)
        except Exception as exc:  # noqa: BLE001
            print(f"    !! {entry['pdf']} 실패: {type(exc).__name__}: {exc}", flush=True)
            results.append({"id": _cid(Path(entry["pdf"]).stem), "input_pdf": entry["pdf"], "status": "error", "error": f"{type(exc).__name__}: {exc}"})
        (OUTPUT_DIR / "summary_partial.json").write_text(
            json.dumps({"results": results, "confusion_matrix": confusion}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_count": len(candidates),
        "finding": build_finding(results, confusion),
        "results": results,
        "confusion_matrix": confusion,
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    record_experiment(summary)

    print("\n=== exp 042: bookmark-GT hybrid 4단계 진단 ===")
    diag_counts = Counter(r.get("diagnosis", r.get("status")) for r in results)
    print(f"진단 분포: {dict(diag_counts)}")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']} ({r.get('status')}) diagnosis={r.get('diagnosis')}")
            continue
        a, b, c, d = r["stage_a_range_recall"], r["stage_b_item_recall"], r["stage_c_page_channel"], r["stage_d_hierarchy"]
        print(
            f"\n- {r['id']}  diag={r['diagnosis']}\n"
            f"    A(range proxy)  recall={a['recall']} ({a['matched']}/{a['total']})\n"
            f"    B(item text)    recall={b['recall']} ({b['matched']}/{b['total']})\n"
            f"    C(page channel) exact={c['exact']} near={c['near']} off={c['off']} missing={c['missing']}\n"
            f"    D(hierarchy)    abs={d['abs_level_agreement']} rel={d['rel_depth_agreement']} n={d['pairs']}"
        )
    print(f"\nhierarchy confusion matrix (GT bucket x Pred bucket): {confusion}")
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
