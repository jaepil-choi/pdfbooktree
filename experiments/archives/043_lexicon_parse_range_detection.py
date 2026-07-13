"""experiment 043: TOC range 탐지를 042의 range_suspect 5권만 대상으로 새 방식으로 다시 풀어본다.

배경
- 042 진단에서 raw_line_recall(=bookmark 제목이 탐지된 range page 안에서 fuzzy로 발견되는 비율)이
  낮은 5권이 있었다. 직접 tree를 까본 결과(뉴욕주민 책) detect_toc_pages+LLM range review가
  일러두기/범례 페이지를 목차로 오인하는 진짜 range 실패였다.
- 지금 방식(fitz native text 기반 통계 detector + LLM per-page 순차 판정)은 스캔/비영어 논픽션에서
  취약하다. Document Parse와 solar-pro3를 사실상 무제한으로 쓸 수 있다는 전제로, 완전히 다른
  방식을 작게 검증한다.

새 방식(lexicon + Document Parse page-per-page + LLM 1회 정제)
1) 앞부분(최대 config.max_toc_search_pages page)을 Document Parse로 page-per-page OCR한다.
   fitz native text가 아니라 Parse를 쓰는 이유: 스캔본은 native text가 아예 없거나 깨져서
   lexicon 매칭 자체가 안 될 수 있다. Parse는 스캔/네이티브 구분 없이 항상 OCR 텍스트를 준다.
2) 각 page의 Parse 텍스트에서 lexicon(목차/차례/Contents/Table of Contents)을 정규식으로 찾아
   anchor 후보를 만든다. 이건 002에서 41번(hybrid) 실험과 달리 결정론적 1차 필터라
   LLM 없이도 비용이 거의 안 든다.
3) anchor 후보가 있으면, anchor부터 앞뒤 몇 page를 묶어 LLM(solar-pro3) 1회 호출로 정확한
   시작/끝 page(연속 구간)를 정제한다. 지금 src처럼 page마다 LLM을 부르는 순차 확장이 아니라,
   후보 구간 텍스트를 한 번에 보여주고 구조화된 응답(start_page/end_page)을 받는다.
4) 평가: 새 toc_pages로 042와 동일한 raw_line_recall(=Stage A proxy)을 계산해 042 저장값과
   나란히 비교한다.

대상: 042 summary.json에서 diagnosis == "range_suspect"였던 5권만.

실행 (Document Parse + solar-pro3 호출):
    uv run --with truststore python experiments/043_lexicon_parse_range_detection.py

출력: experiments/outputs/043_lexicon_parse_range_detection/
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

from pdfbooktree.config import ProcessingConfig
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, title_has_letter
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
EXPERIMENT_ID = "043_lexicon_parse_range_detection"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
# 042가 이미 이 5권의 (탐지된) toc range page를 Parse해 캐싱해뒀다. 앞부분 전체를 새로 훑을
# 때도 같은 캐시를 공유해 겹치는 page는 재호출을 피한다.
CACHE_DIR = ROOT_DIR / "experiments" / "outputs" / "042_bookmark_gt_hybrid_confusion" / "cache"
PRIOR_SUMMARY = ROOT_DIR / "experiments" / "outputs" / "042_bookmark_gt_hybrid_confusion" / "summary.json"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"

# 042에서 diagnosis == "range_suspect"였던 5권(고정).
TARGETS: list[dict[str, str]] = [
    {
        "id": "뉴욕주민의_진짜_미국식_주식투자_stock_investment_finance_book",
        "pdf": r"data\300STUDY\NOW_READING\books\뉴욕주민의_진짜_미국식_주식투자[stock investment finance book].pdf",
    },
    {
        "id": "2022_CFA_Level_I_SchweserNotes_Book_5_Portfolio_Management_and_Ethical_and_Profe",
        "pdf": r"data\300STUDY\textbooks\cfa\cfa 2022\level 1\2022 CFA© Level I SchweserNotes Book 5 Portfolio Management and Ethical and Professional Standards (Kaplan Schweser) (z-lib.org).pdf",
    },
    {
        "id": "Palgrave_Advances_in_Bioeconomy_Economics_and_Policies_Chris_Giotitsas_Open_Sour",
        "pdf": r"data\300STUDY\opensource books\books\(Palgrave Advances in Bioeconomy_ Economics and Policies) Chris Giotitsas - Open Source Agriculture_ Grassroots Technology in the Digital Era-Springer International Publishing_Palgrave Pivot (2019).pdf",
    },
    {
        "id": "ETF투자_무작정_따라하기_finance_investment_stock_book",
        "pdf": r"data\300STUDY\NOW_READING\books\ETF투자_무작정_따라하기[finance investment stock book].pdf",
    },
    {
        "id": "Wiley_Trading_Ernest_P_Chan_Machine_Trading_Deploying_Computer_Algorithms_to_Con",
        "pdf": r"data\300STUDY\a_books\textbook\(Wiley Trading) Ernest P. Chan - Machine Trading_ Deploying Computer Algorithms to Conquer the Markets-Wiley (2017).pdf",
    },
]

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
DIGITIZE_URL = f"{UPSTAGE_BASE_URL}/document-digitization"
LLM_MODEL = "solar-pro3"
RENDER_DPI = 200
MAX_FRONT_PAGES = 80  # ProcessingConfig.max_toc_search_pages와 동일 창

RANGE_RECALL_CUTOFF = 80.0
LEXICON_PATTERN = re.compile(
    r"(목\s*차|차\s*례|table\s+of\s+contents|^\s*contents\b|^\s*index\s+of\s+contents)",
    re.IGNORECASE,
)

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
# Document Parse (042와 동일한 캐시 공유)
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


def parse_page_text(resp: dict[str, Any]) -> str:
    """page 전체 텍스트(모든 element 이어붙임). lexicon 매칭용이라 header/footer도 포함한다."""
    parts = [el.get("content", {}).get("text", "") for el in resp.get("elements", [])]
    return "\n".join(p for p in parts if p)


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


def parse_lines_for_pages(pdf: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """042의 parse_lines와 동일: word box를 줄로 묶는다(hybrid 없이 parse 단독 줄)."""
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
            out.append({"pdf_page": pno, "text": text})
    return out


# ---------------------------------------------------------------------------
# lexicon 1차 필터
# ---------------------------------------------------------------------------
def find_lexicon_anchors(page_texts: dict[int, str]) -> list[int]:
    hits = []
    for pno, text in sorted(page_texts.items()):
        if LEXICON_PATTERN.search(text):
            hits.append(pno)
    return hits


# ---------------------------------------------------------------------------
# LLM 1회 정제: anchor 주변 구간에서 정확한 [start, end]를 고른다.
# ---------------------------------------------------------------------------
def _llm_client():
    from openai import OpenAI

    return OpenAI(api_key=_api_key(), base_url=UPSTAGE_BASE_URL)


def refine_range_with_llm(page_texts: dict[int, str], anchor: int, total_pages: int) -> dict[str, Any]:
    window_start = max(1, anchor - 3)
    window_end = min(total_pages, anchor + 20)
    snippet_pages = [p for p in range(window_start, window_end + 1) if p in page_texts]
    blob = "\n\n".join(f"[page {p}]\n{page_texts[p][:1200]}" for p in snippet_pages)
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_range",
            "schema": {
                "type": "object",
                "properties": {
                    "start_page": {"type": "integer", "description": "목차가 시작되는 page 번호(위 [page N] 중 하나)."},
                    "end_page": {"type": "integer", "description": "목차가 끝나는 page 번호(연속 구간의 마지막)."},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string", "description": "한국어로 한두 문장."},
                },
                "required": ["start_page", "end_page", "confidence", "reason"],
            },
        },
    }
    user_prompt = (
        f"아래는 어떤 책 앞부분 page {window_start}~{window_end}의 OCR 텍스트다. page {anchor}에 "
        f"목차(Table of Contents/차례/목차) 관련 키워드가 있었다. 실제로 챕터 제목과 페이지 번호가 "
        f"나열된 목차 본문이 정확히 어느 page부터 어느 page까지 연속으로 이어지는지 판단하라. "
        f"일러두기/범례/저작권 page처럼 목차가 아닌 page는 절대 포함하지 마라.\n\n{blob}"
    )
    client = _llm_client()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0.0,
        messages=[
            {
                "role": "system",
                "content": "너는 책 PDF의 OCR 텍스트를 보고 목차(TOC) page 범위를 정확히 찾아내는 전문가다.",
            },
            {"role": "user", "content": user_prompt},
        ],
        response_format=schema,
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


# ---------------------------------------------------------------------------
# Stage A 평가: raw_line_recall (042와 동일 정의)
# ---------------------------------------------------------------------------
def normalize_bookmark_titles(bms: list[dict[str, Any]]) -> list[str]:
    return [b["title"] for b in bms if title_has_letter(b["title"])]


def raw_line_recall(rows: list[dict[str, Any]], gt_titles: list[str]) -> dict[str, Any]:
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


# ---------------------------------------------------------------------------
# 책 1권 실행
# ---------------------------------------------------------------------------
def run_book(target: dict[str, str], config: ProcessingConfig, old_by_id: dict[str, Any]) -> dict[str, Any]:
    pdf = ROOT_DIR / target["pdf"]
    rec: dict[str, Any] = {"id": target["id"], "input_pdf": target["pdf"]}
    if not pdf.exists():
        rec["status"] = "missing_pdf"
        return rec

    with fitz.open(pdf) as document:
        total_pages = document.page_count

    bms = extract_existing_bookmarks(pdf)
    gt_titles = normalize_bookmark_titles(bms)

    front = list(range(1, min(MAX_FRONT_PAGES, total_pages) + 1))
    print(f"    Parse page 1..{front[-1]} 스캔 중", flush=True)
    page_texts: dict[int, str] = {}
    for pno in front:
        resp = parse_page(render_png(pdf, pno))
        page_texts[pno] = parse_page_text(resp)

    anchors = find_lexicon_anchors(page_texts)
    rec["lexicon_anchors"] = anchors
    if not anchors:
        rec["status"] = "no_lexicon_hit"
        rec["new_toc_pages"] = []
        rec["stage_a_new"] = {"matched": 0, "total": len(gt_titles), "recall": None}
    else:
        decision = refine_range_with_llm(page_texts, anchors[0], total_pages)
        rec["llm_decision"] = decision
        start, end = decision.get("start_page"), decision.get("end_page")
        if not (isinstance(start, int) and isinstance(end, int) and start <= end):
            rec["status"] = "llm_bad_range"
            new_toc_pages = []
        else:
            new_toc_pages = list(range(start, end + 1))
            rec["status"] = "ok"
        rec["new_toc_pages"] = new_toc_pages
        rows = parse_lines_for_pages(pdf, new_toc_pages) if new_toc_pages else []
        rec["stage_a_new"] = raw_line_recall(rows, gt_titles)

    old = old_by_id.get(target["id"], {})
    rec["old_toc_pages"] = old.get("toc_pages")
    rec["stage_a_old"] = old.get("stage_a_range_recall")
    return rec


def build_finding(results: list[dict[str, Any]]) -> str:
    parts = []
    for r in results:
        old_recall = (r.get("stage_a_old") or {}).get("recall")
        new_recall = (r.get("stage_a_new") or {}).get("recall")
        parts.append(
            f"{r['id']}: old_range={r.get('old_toc_pages')}(recall={old_recall}) "
            f"-> new_range={r.get('new_toc_pages')}(recall={new_recall}) anchors={r.get('lexicon_anchors')}"
        )
    return " || ".join(parts)


def record_experiment(summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "042에서 diagnosis=range_suspect였던 5권만 대상으로, 기존 fitz-native-text 통계 detector"
            "+LLM per-page 순차 확장 대신 (1) Document Parse page-per-page OCR로 lexicon(목차/차례/"
            "Contents/Table of Contents)을 찾고 (2) anchor 주변 구간을 LLM 1회 호출로 정제하는 완전히 "
            "다른 range 탐지 방식을 검증한다. Parse는 스캔/네이티브 구분 없이 항상 OCR 텍스트를 주므로 "
            "native text가 없는 책에서도 lexicon 매칭이 가능하다. 평가는 042와 동일한 raw_line_recall"
            "(Stage A proxy)로 old/new를 나란히 비교한다."
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

    print("\n=== exp 043: lexicon + Parse + LLM range 재탐지 (range_suspect 5권) ===")
    for r in results:
        old_recall = (r.get("stage_a_old") or {}).get("recall")
        new_recall = (r.get("stage_a_new") or {}).get("recall")
        print(f"- {r['id']}: recall {old_recall} -> {new_recall}  new_range={r.get('new_toc_pages')}")
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
