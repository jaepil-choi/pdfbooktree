"""experiment 040: 현재 src/ production 흐름을 그대로 타되, TOC range page만 Upstage
Document Parse로 재-OCR해 그 word box로 계층/항목 추출을 돌린다.

배경 / 039와의 차이
- 039는 "OCR 소스만 교체"라고 했지만 실제로는 src Processor를 타지 않고, GT contents
  page에 대해 028/029 클러스터+LLM 순서 다운스트림만 실험 스크립트에서 재구현해 Parse를
  먹였다. 즉 TOC page 탐지/range 보정, offset 추정, heading alignment, bookmark 생성 같은
  src의 나머지 흐름이 빠져 있었다. 사용자 불만의 핵심이 이것이다.
- 040은 src Processor.run()이 거치는 단계를 그대로 따라가되, "최초 input만 Document Parse"
  원칙으로 TOC range page의 줄 신호 source만 Parse로 바꾼다. 나머지는 전부 현재 src
  production 함수를 직접 호출한다.

사용자 확정 제약
- TOC range 탐지: Document Parse를 쓰지 않고 기존 src production(ML detector + LLM per-page
  range review) 그대로 진행한다.
- TOC range page는 page per page로 Parse한다(한 호출당 1 page). 여러 page를 한꺼번에
  Parse하지 않는다.
- offset은 Document Parse로 하지 않는다. 이미 검증된 src 결정론 추정(estimate_page_offset)을
  그대로 쓴다.
- Document OCR(model=ocr)은 과금되므로 사용 금지. Document Parse만 쓴다.

두 arm(같은 책, 같은 src 탐지/offset/align, TOC range page 줄 source만 다름)
- baseline       : src SizeAwareStagedTocExtractor.extract(pdf, toc_pages) = 현재 production
                   (PyMuPDF span에서 줄을 만든다).
- upstage_parse  : TOC range page를 page per page로 Document Parse(words=true, coordinates=true)
                   해 ClusteredTocLine을 만들고, 동일 extractor.extract_from_clustered_lines로
                   계층/항목 추출을 돌린다.

평가
- TOC page 탐지 품질(두 arm 공통): GT toc_pages 대비 precision/recall.
- 계층: bookmark weak ref(rel_depth/abs) — 3권(hull/shreve/luenberger).
- printed page 채널: coverage + 순서 단조성(monotonicity).
- end-to-end: offset 적용 후 bookmark placeable 비율.

출력: experiments/outputs/040_upstage_parse_src_endtoend/
실행: uv run python experiments/040_upstage_parse_src_endtoend.py
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
from pdfbooktree.models import HeadingCandidate, TocItem
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
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "040_upstage_parse_src_endtoend"
CACHE_DIR = OUTPUT_DIR / "cache"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "040_upstage_parse_src_endtoend"

# 로컬에 실제로 존재하는 책 세트(016~039의 5권은 현재 로컬에 없다). 001/010/015/032~038에서
# 쓰던 책들이며 모두 GT toc_pages와 기존 bookmark를 가진다.
TARGET_IDS = [
    "zvi_bodie_investments",
    "kim_econometrics_note1",
    "kim_econometrics_note2",
    "quant_world",
    "hankyung_reader",
]
# 전부 bookmark가 있다(hankyung은 flat depth0이라 rel/abs 의미는 약하지만 weakref는 계산된다).
BOOKMARKED_IDS = {
    "zvi_bodie_investments",
    "kim_econometrics_note1",
    "kim_econometrics_note2",
    "quant_world",
    "hankyung_reader",
}

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
RENDER_DPI = 200

# parse element category 중 본문 TOC가 아닌 것(머리말/꼬리말/각주)은 줄 재구성에서 제외.
PARSE_DROP_CATEGORIES = {"header", "footer", "footnote"}

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")


def is_content_text(text: str) -> bool:
    s = text.strip()
    return bool(s and (_HANGUL.search(s) or _LATIN2.search(s)))


# ---------------------------------------------------------------------------
# Upstage Document Parse 호출 (디스크 캐시: 같은 page는 재호출하지 않는다)
# page per page: 한 호출당 정확히 1 page만 보낸다.
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
    """Document Parse를 단일 page PNG로 호출한다. (page,model,extra) 단위로 캐시."""
    extra = {"output_formats": '["text"]', "coordinates": "true", "words": "true"}
    h = hashlib.sha1(png).hexdigest()[:16]
    tag = "document-parse_" + "_".join(f"{k}{v}" for k, v in sorted(extra.items()))
    tag = re.sub(r"[^0-9A-Za-z._-]+", "", tag)[:60]
    cache = CACHE_DIR / f"{tag}_{h}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    data = {"model": "document-parse", **extra}
    # free tier는 RPS 제한이 있어 429가 잦다. 지수 backoff로 재시도한다.
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
# Parse word -> 줄 재구성 (039와 동일 방법론: 기존 피쳐 그대로)
# word = (text, conf, x1, y1, x2, y2, category)
# ---------------------------------------------------------------------------
def _parse_words(resp: dict[str, Any]) -> list[tuple]:
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
            words.append(
                (
                    w["text"],
                    float(w.get("confidence", 1.0)),
                    float(min(xs)),
                    float(min(ys)),
                    float(max(xs)),
                    float(max(ys)),
                    cat,
                )
            )
    return words


def group_words_to_lines(words: list[tuple], pdf_page: int) -> list[ClusteredTocLine]:
    """normalized word box(page_width=1.0 기준)를 줄로 묶어 ClusteredTocLine을 만든다."""
    if not words:
        return []
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

    out: list[ClusteredTocLine] = []
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
        # trailing page: 039와 동일 — 줄 텍스트의 마지막 정수(맨 오른쪽 정수 규칙 폐기).
        nums = re.findall(r"\d+", " ".join(w[0].strip() for w in ln if w[0].strip()))
        out.append(
            ClusteredTocLine(
                pdf_page=pdf_page,
                text=text,
                height=round(height, 3),
                title_x=round(title_x, 3),
                page_width=1.0,
                is_bold=False,  # Parse는 font weight 미제공 → bold 축 비활성.
                font_type="reocr",  # Parse는 font family 미제공 → category를 feature로 안 씀.
                trailing_page=int(nums[-1]) if nums else None,
            )
        )
    return out


def parse_toc_range_lines(pdf: Path, toc_pages: list[int]) -> list[ClusteredTocLine]:
    """TOC range page를 page per page로 Document Parse해 ClusteredTocLine을 만든다."""
    lines: list[ClusteredTocLine] = []
    for pno in toc_pages:
        png = render_png(pdf, pno)
        resp = parse_page(png)
        lines.extend(group_words_to_lines(_parse_words(resp), pno))
    return lines


# ---------------------------------------------------------------------------
# heading 후보 (Processor._build_heading_candidates와 동일)
# ---------------------------------------------------------------------------
def build_heading_candidates(
    pdf: Path,
    items: list[TocItem],
    offset: int | None,
    total_pages: int,
    window: int,
) -> dict[int, list[HeadingCandidate]]:
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


# ---------------------------------------------------------------------------
# 지표 (039와 동일 정의)
# ---------------------------------------------------------------------------
def range_metrics(detected: list[int], gt: list[int]) -> dict[str, Any]:
    dset, gset = set(detected), set(gt)
    inter = len(dset & gset)
    precision = round(inter / len(dset), 4) if dset else 0.0
    recall = round(inter / len(gset), 4) if gset else 0.0
    return {
        "detected": detected,
        "gt": gt,
        "precision": precision,
        "recall": recall,
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
# arm 실행: 같은 src 탐지/offset/align, TOC range page 줄 source만 다르다.
# ---------------------------------------------------------------------------
def run_arm(
    arm: str,
    pdf: Path,
    toc_pages: list[int],
    offset_value: int | None,
    total_pages: int,
    extractor: SizeAwareStagedTocExtractor,
    config: ProcessingConfig,
    bms,
) -> tuple[dict[str, Any], list[TocItem]]:
    if arm == "baseline":
        # 현재 production: src extractor가 PyMuPDF span에서 줄을 만든다.
        items = extractor.extract(pdf, toc_pages)
        line_source = "pymupdf_span"
    else:
        # upstage_parse: TOC range page를 page per page로 Parse해 줄을 만들고
        # 동일 src extractor의 clustered-line 진입점으로 계층/항목 추출을 돌린다.
        parse_lines = parse_toc_range_lines(pdf, toc_pages)
        if not parse_lines:
            return {"status": "no_parse_lines"}, []
        items = extractor.extract_from_clustered_lines(parse_lines, toc_pages)
        line_source = "document_parse_per_page"

    if not items:
        return {"status": "no_items", "line_source": line_source}, []

    # offset 적용 후 heading alignment + content range (src 그대로).
    candidates = build_heading_candidates(
        pdf, items, offset_value, total_pages, config.heading_search_window
    )
    offset_estimate = _OffsetView(offset_value)
    aligned = align_toc_items(items, offset_estimate, candidates)
    ranges = calculate_content_ranges(aligned, total_pages)
    placeable = sum(1 for a in aligned if a.matched_pdf_page is not None)

    rec = {
        "status": "ok",
        "line_source": line_source,
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
    if bms is not None:
        rec["weakref"] = weakref_metrics(items, bms)
    return rec, items


class _OffsetView:
    """align_toc_items가 기대하는 offset 인터페이스(.offset)만 제공하는 래퍼."""

    def __init__(self, offset: int | None) -> None:
        self.offset = offset


# ---------------------------------------------------------------------------
# book 실행: TOC range 탐지(src) -> offset(src) -> arm별 추출/align.
# ---------------------------------------------------------------------------
def run_book(label, config: ProcessingConfig) -> dict[str, Any]:
    pdf = ROOT_DIR / label["input_pdf"]
    cid = _cid(label["id"])
    rec: dict[str, Any] = {"id": label["id"], "input_pdf": label["input_pdf"], "arms": {}}
    if not pdf.exists():
        rec["status"] = "missing_pdf"
        return rec

    with fitz.open(pdf) as document:
        total_pages = document.page_count

    # 1) TOC range 탐지: Document Parse 미사용, src production 그대로.
    pages = extract_page_texts(pdf, max_pages=config.max_toc_search_pages)
    features = calculate_page_features(pages, total_pages)
    toc_detection = detect_toc_pages(features, config.toc_detection)
    reviewer = LlmTocRangeReviewer(config.llm_range_review)
    review = reviewer.review(pdf, toc_detection, total_pages)
    toc_pages = review.pages if review.pages else toc_detection.pages
    rec["toc_pages"] = toc_pages
    rec["range_vs_gt"] = range_metrics(toc_pages, label.get("toc_pages", []))

    if not toc_pages:
        rec["status"] = "no_toc_pages"
        return rec

    # 2) offset: src 결정론 추정. clean하지 않으면 fast-fail이므로 잡아서 None 처리.
    try:
        offset_estimate = estimate_page_offset(pdf, config.offset)
        offset_value = offset_estimate.offset
        rec["offset"] = {"offset": offset_value, "confidence": offset_estimate.confidence}
    except OffsetEstimationError as exc:
        offset_value = None
        rec["offset"] = {"offset": None, "confidence": 0.0, "error": str(exc)[:200]}

    bms = extract_existing_bookmarks(pdf) if label["id"] in BOOKMARKED_IDS else None
    extractor = SizeAwareStagedTocExtractor(config.llm_staged_extraction)

    # 3) arm별: baseline(현재 production) vs upstage_parse(TOC range page만 Parse).
    for arm in ("baseline", "upstage_parse"):
        try:
            armrec, items = run_arm(
                arm, pdf, toc_pages, offset_value, total_pages, extractor, config, bms
            )
        except Exception as exc:  # arm 하나 실패해도 나머지는 본다.
            rec["arms"][arm] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            continue
        rec["arms"][arm] = armrec
        if items:
            (OUTPUT_DIR / f"{cid}_{arm}_tree.txt").write_text(
                "\n".join(render_tree(items)) + "\n", encoding="utf-8"
            )
            (OUTPUT_DIR / f"{cid}_{arm}_items.json").write_text(
                json.dumps(
                    [
                        {
                            "title": it.title,
                            "level": it.level,
                            "printed_page": it.printed_page,
                            "source_pdf_page": it.source_pdf_page,
                        }
                        for it in items
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    rec["status"] = "ok"
    return rec


def build_finding(results) -> str:
    parts = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        rv = r["range_vs_gt"]
        seg = [f"{r['id']}(range P{rv['precision']}/R{rv['recall']}, offset={r['offset'].get('offset')})"]
        for arm in ("baseline", "upstage_parse"):
            a = r["arms"].get(arm, {})
            if a.get("status") != "ok":
                seg.append(f"{arm}={a.get('status')}")
                continue
            pc, bk = a["page_channel"], a["bookmark"]
            piece = (
                f"{arm}: page_cov {pc['with_printed_page']}/{pc['items']}({pc['coverage']}) "
                f"mono={pc['monotonicity']} placeable={bk['placeable']}/{bk['items']}"
            )
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
            "현재 src/ production 흐름을 그대로 타되, 최초 input만 Document Parse 원칙으로 "
            "TOC range page의 줄 신호 source만 Document Parse(page per page, 한 호출당 1 page)로 "
            "바꾼다. TOC range 탐지는 Document Parse를 쓰지 않고 기존 src production(ML detector + "
            "LLM per-page range review)으로, offset은 Document Parse 없이 src 결정론 "
            "estimate_page_offset으로 진행한다. 두 arm(baseline=src extractor의 PyMuPDF span, "
            "upstage_parse=TOC range page Parse 후 동일 extractor.extract_from_clustered_lines)을 "
            "같은 탐지/offset/align 위에서 비교한다. 평가축은 GT range P/R, bookmark weak ref "
            "rel_depth/abs, printed page coverage/monotonicity, offset 적용 후 bookmark placeable."
        ),
        "inputs": [lab["input_pdf"] for lab in summary["_labels_used"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "experiments\\labels\\answer_toc_ranges_manual.json",
        "models": ["document-parse", "solar-pro3"],
        "temperature": 0.0,
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
        # 부분 진행 보존: 매 책마다 summary를 갱신해 둔다.
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

    print("\n=== exp 040: src end-to-end flow, TOC range page만 Document Parse ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']} ({r.get('status')}) {r.get('error','')}")
            continue
        rv = r["range_vs_gt"]
        print(
            f"\n- {r['id']}  toc_pages={r['toc_pages']} (GT P{rv['precision']}/R{rv['recall']})"
            f"  offset={r['offset'].get('offset')}"
        )
        for arm in ("baseline", "upstage_parse"):
            a = r.get("arms", {}).get(arm, {})
            if a.get("status") != "ok":
                print(f"    {arm:14s}: {a.get('status')} {a.get('error','')}")
                continue
            pc, h, bk = a["page_channel"], a["hierarchy"], a["bookmark"]
            line = (
                f"    {arm:14s}: items={pc['items']:3d} page_cov={pc['with_printed_page']}/{pc['items']}"
                f"({pc['coverage']}) mono={pc['monotonicity']} placeable={bk['placeable']}/{bk['items']}"
                f" levels={h['level_distribution']}"
            )
            if "weakref" in a and a["weakref"].get("matched"):
                line += f" rel={a['weakref'].get('rel_depth_agreement')} abs={a['weakref'].get('abs_level_agreement')}"
            print(line)
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
