"""experiment 045: 계층(level) 판정을 042의 hierarchy_suspect 6권만 대상으로 완전히 다른 방식으로
다시 풀어본다 — font geometry 클러스터링을 버리고 solar-pro3에게 번호 패턴/의미로 직접 판정시킨다.

배경
- 042에서 hierarchy_suspect로 찍힌 6권을 직접 열어보니 두 가지 실패 패턴이 있었다.
  1) 압축(collapse): Rosebrock 책은 chapter(L1)/section(L2) 제목의 폰트 크기·들여쓰기가 사실상
     같아서 둘 다 같은 클러스터로 뭉친다 — geometry 신호 자체가 부족한 케이스.
  2) 역전(inversion): Learning SQL 책은 상위 헤더("Preface")가 오히려 하위 클러스터로 잡히고
     그 하위 섹션이 상위로 나온다 — geometry 클러스터링 로직이 뒤집힌 케이스.
- 두 경우 모두 TOC 줄 텍스트 자체에는 훨씬 강한 계층 신호가 있다: 번호 체계("3" vs "3.1" vs
  "3.1.1")와 "Preface/Chapter/Appendix/Part" 같은 의미 표지. 지금 파이프라인은 이 신호를 전혀
  안 쓰고 height/title_x/bold/font만 본다.

새 방식(항목 추출은 그대로 두고 level만 solar-pro3로 재판정)
- item(title/printed_page/raw_text) 추출 자체는 042 hybrid에서 이미 잘 작동한다(Stage B item
  recall 0.94~1.0). 그러니 추출 파이프라인은 그대로 재사용하고, 오직 level 채널만 별도로
  solar-pro3 1회 호출로 교체한다 — 바뀌는 변수를 hierarchy 판정 로직 하나로 좁혀서 A/B를
  깨끗하게 비교하기 위함이다.
- LLM에게는 각 item의 raw_text(번호·페이지 포함 원문)만 순서대로 주고, font/좌표 힌트는 전혀
  주지 않는다. 번호 깊이와 "Preface/Chapter/Part/Appendix/부록" 같은 의미만으로 level을 매기게
  한다.

평가
- 042와 동일한 hierarchy_stats(abs_level_agreement/rel_depth_agreement, title 매칭된 pair 기준)를
  이 실험 안에서 baseline(geometry-level)과 new(LLM-level) 양쪽 다 새로 계산해 나란히 비교한다.

대상: 042 summary.json에서 diagnosis == "hierarchy_suspect"였던 6권만.

실행 (Document Parse + solar-pro3 호출):
    uv run --with truststore python experiments/045_llm_native_hierarchy.py

출력: experiments/outputs/045_llm_native_hierarchy/
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
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
from pdfbooktree.models import TocItem
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
EXPERIMENT_ID = "045_llm_native_hierarchy"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
CACHE_DIR = ROOT_DIR / "experiments" / "outputs" / "042_bookmark_gt_hybrid_confusion" / "cache"
PRIOR_SUMMARY = ROOT_DIR / "experiments" / "outputs" / "042_bookmark_gt_hybrid_confusion" / "summary.json"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"

# 042에서 diagnosis == "hierarchy_suspect"였던 6권(고정). toc_pages/offset은 042가 이미 찾아둔
# 값을 그대로 쓴다(이 실험의 대상은 hierarchy뿐이다).
TARGETS: list[dict[str, Any]] = [
    {
        "id": "Joshua_D_Angrist_J_rn_Steffen_Pischke_Mostly_Harmless_Econometrics_An_Empiricist",
        "pdf": r"data\300STUDY\NOW_READING\books\Joshua D. Angrist_ Jörn-Steffen Pischke - Mostly Harmless Econometrics_ An Empiricist’s Companion-Princeton University Press (2009)[econ micro stats book].pdf",
        "toc_pages": [6, 7, 8, 9, 10, 11],
        "offset": 19,
    },
    {
        "id": "For_Dummies_Business_Personal_Finance_Tiana_Laurence_Seoyoung_Kim_NFTs_For_Dummi",
        "pdf": r"data\300STUDY\a_books\textbook\(For Dummies (Business & Personal Finance)) Tiana Laurence, Seoyoung Kim - NFTs For Dummies-Wiley (2021).pdf",
        "toc_pages": [5, 6, 7, 8, 9],
        "offset": 10,
    },
    {
        "id": "Adrian_Rosebrock_Deep_Learning_for_Computer_Visi_z_lib_org",
        "pdf": r"data\300STUDY\textbooks\pyimagesearch\Adrian_Rosebrock_Deep_Learning_for_Computer_Visi(z-lib.org).pdf",
        "toc_pages": [7, 8, 9, 10, 11],
        "offset": 2,
    },
    {
        "id": "Jules_S_Damji_Brooke_Wenig_Tathagata_Das_Denny_Lee_Learning_Spark_Lightning_Fast",
        "pdf": r"data\300STUDY\textbooks\Jules S. Damji, Brooke Wenig, Tathagata Das, Denny Lee - Learning Spark_ Lightning-Fast Data Analytics-O'Reilly Media (2020).pdf",
        "toc_pages": [7, 8, 9, 10, 11, 12, 13],
        "offset": 24,
    },
    {
        "id": "The_economics_of_money_banking_and_financial_markets",
        "pdf": r"data\300STUDY\others\The-economics-of-money-banking-and-financial-markets.pdf",
        "toc_pages": [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33],
        "offset": 1,
    },
    {
        "id": "Alan_Beaulieu_Learning_SQL_Generate_Manipulate_and_Retrieve_Data_O_Reilly_Media_",
        "pdf": r"data\300STUDY\textbooks\Alan Beaulieu - Learning SQL_ Generate, Manipulate, and Retrieve Data-O'Reilly Media (2020).pdf",
        "toc_pages": [5, 6, 7, 8, 9, 10, 11],
        "offset": 18,
    },
]

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
LLM_MODEL = "solar-pro3"
RENDER_DPI = 200

ITEM_MATCH_CUTOFF = 88.0

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
# 줄 추출: fitz backbone + Parse 텍스트/페이지번호 이식 (042와 동일)
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
# 새 level: solar-pro3에게 raw_text 순서만 주고 번호/의미로 판정시킨다(geometry 힌트 없음).
# ---------------------------------------------------------------------------
def _llm_client():
    from openai import OpenAI

    return OpenAI(api_key=_api_key(), base_url=UPSTAGE_BASE_URL)


def relevel_with_llm(items: list[TocItem]) -> list[int] | None:
    lines = [{"index": i, "text": it.raw_text or it.title} for i, it in enumerate(items)]
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_levels",
            "schema": {
                "type": "object",
                "properties": {
                    "levels": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "level": {"type": "integer", "description": "1=최상위(chapter/part), 숫자가 클수록 더 깊은 하위 항목."},
                            },
                            "required": ["index", "level"],
                        },
                    }
                },
                "required": ["levels"],
            },
        },
    }
    system_prompt = (
        "너는 책 목차(TOC) 줄 목록을 보고 각 줄의 계층 level을 정하는 전문가다. "
        "폰트 크기나 들여쓰기 같은 시각 정보는 전혀 주어지지 않는다. 오직 (1) 번호 체계의 깊이"
        "(예: '3'은 1단계, '3.1'은 2단계, '3.1.1'은 3단계) (2) 'Preface/Introduction/Chapter/Part/"
        "Appendix/부록/서문' 같은 의미상 최상위 표지만 근거로 판단하라. 번호가 없는 줄은 앞뒤 문맥"
        "(직전에 나온 상위 항목)으로 미루어 판단하라. 반드시 입력과 같은 개수, 같은 순서로 모든 "
        "index에 대해 level을 반환하라."
    )
    blob = "\n".join(f"[{ln['index']}] {ln['text']}" for ln in lines)
    client = _llm_client()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0.0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": blob},
        ],
        response_format=schema,
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    levels_by_index = {row["index"]: row["level"] for row in data.get("levels", [])}
    if len(levels_by_index) != len(items):
        return None
    try:
        return [levels_by_index[i] for i in range(len(items))]
    except KeyError:
        return None


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
# 평가: 042와 동일한 hierarchy_stats(title 매칭된 pair 기준)
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


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def hierarchy_stats(pairs: list[tuple[dict[str, Any], Any]]) -> dict[str, Any]:
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


# ---------------------------------------------------------------------------
# 책 1권 실행
# ---------------------------------------------------------------------------
def run_book(target: dict[str, Any], config: ProcessingConfig) -> dict[str, Any]:
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
    offset = target["offset"]

    fr = fitz_lines(pdf, toc_pages)
    pr = parse_lines(pdf, toc_pages)
    hr = hybrid_lines(fr, pr)

    extractor = SizeAwareStagedTocExtractor(config.llm_staged_extraction)
    items = extractor.extract_from_clustered_lines(to_clustered(hr), None)
    rec["item_count"] = len(items)
    if not items:
        rec["status"] = "no_items"
        return rec

    # baseline: 기존 geometry-cluster level 그대로.
    base_candidates = build_heading_candidates(pdf, items, offset, total_pages, config.heading_search_window)
    base_aligned = align_toc_items(items, _OffsetView(offset), base_candidates)
    base_pairs = match_pairs(base_aligned, ref)
    rec["baseline_hierarchy"] = hierarchy_stats(base_pairs)
    rec["baseline_level_distribution"] = _level_dist(it.level for it in items)

    # new: level만 solar-pro3로 재판정(geometry 힌트 없음), title/printed_page는 그대로.
    new_levels = relevel_with_llm(items)
    if new_levels is None:
        rec["status"] = "llm_relevel_failed"
        return rec
    new_items = [
        TocItem(
            title=it.title,
            level=lv,
            printed_page=it.printed_page,
            raw_text=it.raw_text,
            source_pdf_page=it.source_pdf_page,
            confidence=it.confidence,
        )
        for it, lv in zip(items, new_levels)
    ]
    new_candidates = build_heading_candidates(pdf, new_items, offset, total_pages, config.heading_search_window)
    new_aligned = align_toc_items(new_items, _OffsetView(offset), new_candidates)
    new_pairs = match_pairs(new_aligned, ref)
    rec["new_hierarchy"] = hierarchy_stats(new_pairs)
    rec["new_level_distribution"] = _level_dist(new_levels)
    rec["status"] = "ok"
    return rec


def _level_dist(levels) -> dict[str, int]:
    from collections import Counter

    return {str(k): v for k, v in sorted(Counter(levels).items())}


def build_finding(results: list[dict[str, Any]]) -> str:
    parts = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: status={r.get('status')}")
            continue
        b, n = r["baseline_hierarchy"], r["new_hierarchy"]
        parts.append(
            f"{r['id']}: baseline(abs={b['abs_level_agreement']},rel={b['rel_depth_agreement']},"
            f"levels={r['baseline_level_distribution']}) -> "
            f"llm(abs={n['abs_level_agreement']},rel={n['rel_depth_agreement']},"
            f"levels={r['new_level_distribution']})"
        )
    return " || ".join(parts)


def record_experiment(summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "042에서 diagnosis=hierarchy_suspect였던 6권만 대상으로, height/title_x/is_bold/font_type "
            "geometry 클러스터링으로 level을 정하던 기존 방식 대신 solar-pro3에게 item raw_text(번호 "
            "체계·Preface/Chapter 등 의미 표지)만 순서대로 주고 level만 재판정시킨다. item(title/"
            "printed_page) 추출은 042 hybrid 파이프라인을 그대로 재사용해 바뀌는 변수를 level 채널 "
            "하나로 좁힌다. 평가는 042와 동일한 hierarchy_stats(title 매칭된 pair의 abs_level_"
            "agreement/rel_depth_agreement)를 baseline/new 양쪽 새로 계산해 비교한다."
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

    results = []
    for target in TARGETS:
        print(f"\n... running {target['id']}", flush=True)
        try:
            results.append(run_book(target, config))
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

    print("\n=== exp 045: solar-pro3 번호/의미 기반 level 재판정 (hierarchy_suspect 6권) ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"- {r['id']}: {r.get('status')}")
            continue
        b, n = r["baseline_hierarchy"], r["new_hierarchy"]
        print(
            f"- {r['id']}: abs {b['abs_level_agreement']} -> {n['abs_level_agreement']}  "
            f"rel {b['rel_depth_agreement']} -> {n['rel_depth_agreement']}  "
            f"levels {r['baseline_level_distribution']} -> {r['new_level_distribution']}"
        )
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
