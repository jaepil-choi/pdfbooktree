"""실험 016: PRD 3단계 LLM fallback으로 TOC page range를 복구한다.

목적
- PRD §7.8~7.11(15.1)의 3단계 fallback 구조를 결정적 detector 위에 얹어,
  현재 로컬 5권의 TOC page range를 100% 정확히 잡을 수 있는지 검증한다.
- 1단계 start page accept, 2단계 backtrack_start, 3단계 sequential recovery를
  순서대로 적용하고, end는 contiguous expansion으로 늘린다.
- baseline(결정적 detector)과 fallback 결과를 GT 대비 함께 비교해
  3단계가 어디서 얼마나 개선하는지 본다.

규칙
- LLM은 Upstage Solar chat(solar-pro3) 텍스트 경로만 쓴다. Information Extraction은 과금이라 금지.
- 모든 page 번호는 1-based PDF page다.
- real data + live call. 합성/mock 입력으로 성공을 주장하지 않는다.

이 파일은 AGENTS.md §3에 따라 monolithic PoC script로 작성한다.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from pdfbooktree.metrics.toc_pages import compare_toc_pages
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.toc.detect import detect_toc_pages
from pdfbooktree.toc.features import calculate_page_features

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "016_llm_toc_range_3stage_fallback"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
LABELS_JSON = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
MODEL = "solar-pro3"
TEMPERATURE = 0.0

# fallback 파라미터
SCAN_PAGES = 40  # 앞부분 몇 page까지 page text를 미리 확보할지
MAX_BACKTRACK = 8  # 2단계: 앞으로 최대 몇 page 되짚을지
MAX_SEQUENTIAL = 40  # 3단계: page 1부터 최대 몇 page를 순차 검토할지
MAX_END_EXPAND = 30  # end expansion 시 start 기준 최대 span
END_GAP_TOLERANCE = 0  # TOC page는 contiguous하다고 보고 첫 non-TOC에서 멈춘다
PROMPT_MAX_CHARS = 4500

DECISION_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "toc_page_decision",
        "schema": {
            "type": "object",
            "properties": {
                "is_toc_page": {
                    "type": "boolean",
                    "description": (
                        "이 페이지가 책의 목차(Table of Contents / 차례 / Contents)"
                        "또는 간략 목차(Contents in brief)의 일부이면 true."
                    ),
                },
                "is_toc_start": {
                    "type": "boolean",
                    "description": (
                        "이 페이지가 목차가 시작되는 첫 페이지이면 true. "
                        "바로 앞 페이지는 목차가 아니어야 한다."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "판정 근거를 한국어로 한두 문장.",
                },
            },
            "required": ["is_toc_page", "is_toc_start", "reason"],
        },
    },
}

SYSTEM_PROMPT = (
    "당신은 PDF 책의 페이지가 목차(Table of Contents) 페이지인지 판정하는 분류기다.\n"
    "규칙:\n"
    "- 상세 목차(Contents)와 간략 목차(Contents in brief / Brief Contents)는 모두 목차로 본다.\n"
    "- 목차 항목은 장/절 제목과 함께 '책 본문의 페이지 번호'를 가리킨다.\n"
    "  제목 옆/끝에 본문 페이지 번호(예: ...... 23)가 줄마다 붙어 있는 형태가 핵심 신호다.\n"
    "- 페이지 번호 없이 외부 웹사이트 자료나 노트 제목만 나열한 목록(예: 웹사이트 technical notes 목록)은\n"
    "  목차가 아니다.\n"
    "- 표지, 헌사, 판권지, 서문/머리말, 본문 첫 페이지는 목차가 아니다.\n"
    "- is_toc_start는 '이 페이지부터 목차가 시작'할 때만 true다.\n"
    "- 반드시 주어진 JSON schema로만 답한다."
)

# 평가 대상: 현재 로컬에 존재하는 5권. GT는 answer_toc_ranges_manual.json에서 읽는다.
TARGET_IDS = [
    "john_hull",
    "shreve_binomial",
    "luenberger_investment_science",
    "algorithm_nine",
    "algorithms_to_live_by",
]


def load_labels() -> dict[str, dict[str, Any]]:
    data = json.loads(LABELS_JSON.read_text(encoding="utf-8"))
    return {label["id"]: label for label in data["labels"]}


def build_page_text_map(pdf_path: Path) -> tuple[dict[int, str], int]:
    """앞부분 page text를 1-based dict로 만든다. total_pages도 반환한다."""

    import fitz

    with fitz.open(pdf_path) as document:
        total_pages = document.page_count
    pages = extract_page_texts(pdf_path, max_pages=min(SCAN_PAGES, total_pages))
    return {page.pdf_page: page.text for page in pages}, total_pages


class PageProbe:
    """page text를 LLM에 보내 (is_toc_page, is_toc_start)를 판정하고 캐시한다."""

    def __init__(self, client: OpenAI, page_text: dict[int, str]) -> None:
        self.client = client
        self.page_text = page_text
        self.cache: dict[int, dict[str, Any]] = {}
        self.call_count = 0

    def probe(self, pdf_page: int) -> dict[str, Any]:
        if pdf_page in self.cache:
            return self.cache[pdf_page]

        text = self.page_text.get(pdf_page, "")
        snippet = text[:PROMPT_MAX_CHARS]
        user_prompt = (
            f"다음은 PDF의 {pdf_page}번째 페이지(1-based) 텍스트다.\n"
            f"이 페이지가 목차 페이지인지 판정하라.\n\n"
            f"---PAGE {pdf_page} TEXT START---\n{snippet}\n---PAGE TEXT END---"
        )
        response = self.client.chat.completions.create(
            model=MODEL,
            temperature=TEMPERATURE,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format=DECISION_SCHEMA,
        )
        self.call_count += 1
        decision = json.loads(response.choices[0].message.content)
        decision["pdf_page"] = pdf_page
        self.cache[pdf_page] = decision
        return decision


def find_anchor(
    probe: PageProbe, detector_start: int | None, total_pages: int
) -> tuple[int | None, str, list[dict[str, Any]]]:
    """3단계 fallback으로 'TOC인 것이 확실한' anchor page 하나를 찾는다.

    PRD §7.9~7.11 구조를 따른다. start 경계 자체는 anchor에서 backward merge로 정한다.
    """

    trace: list[dict[str, Any]] = []
    scan_limit = min(MAX_SEQUENTIAL, total_pages, SCAN_PAGES)

    # detector 후보가 없으면 바로 3단계 sequential recovery.
    if detector_start is None:
        return _sequential_recovery(probe, scan_limit, trace)

    s_decision = probe.probe(detector_start)
    trace.append({"stage": "probe_detector_start", **s_decision})

    # 1단계: start page accept (S가 TOC 첫 page) → anchor = S
    if s_decision["is_toc_page"] and s_decision["is_toc_start"]:
        return detector_start, "stage1_accept", trace

    # 2단계: S가 TOC이지만 첫 page가 아님 → anchor = S (backward merge가 경계 처리)
    if s_decision["is_toc_page"]:
        return detector_start, "stage2_backtrack", trace

    # 3단계: S가 TOC가 아님 → page 1부터 sequential recovery
    return _sequential_recovery(probe, scan_limit, trace)


def _sequential_recovery(
    probe: PageProbe, scan_limit: int, trace: list[dict[str, Any]]
) -> tuple[int | None, str, list[dict[str, Any]]]:
    """page 1부터 순차 검토해 첫 TOC page를 anchor로 잡는다."""

    for page in range(1, scan_limit + 1):
        d = probe.probe(page)
        trace.append({"stage": "sequential", **d})
        if d["is_toc_page"]:
            return page, "stage3_sequential_recovery", trace
    return None, "stage3_failed", trace


def grow_block(probe: PageProbe, anchor: int, total_pages: int) -> tuple[int, int]:
    """anchor에서 양방향으로 contiguous한 TOC page를 모아 (start, end)를 만든다.

    backward 확장은 brief contents 같은 인접 TOC segment를 merge한다.
    forward 확장은 본문 직전까지 TOC를 따라간다. 둘 다 작은 gap을 허용한다.
    """

    start = anchor
    gap = 0
    page = anchor - 1
    while page >= 1 and page >= anchor - MAX_BACKTRACK:
        d = probe.probe(page)
        if d["is_toc_page"]:
            start = page
            gap = 0
        else:
            gap += 1
            if gap > END_GAP_TOLERANCE:
                break
        page -= 1

    end = anchor
    gap = 0
    page = anchor + 1
    span_limit = min(anchor + MAX_END_EXPAND, total_pages, SCAN_PAGES)
    while page <= span_limit:
        d = probe.probe(page)
        if d["is_toc_page"]:
            end = page
            gap = 0
        else:
            gap += 1
            if gap > END_GAP_TOLERANCE:
                break
        page += 1
    return start, end


def run_book(client: OpenAI, label: dict[str, Any]) -> dict[str, Any]:
    pdf_path = ROOT_DIR / label["input_pdf"]
    if not pdf_path.exists():
        return {"id": label["id"], "status": "blocked", "reason": f"PDF 없음: {pdf_path}"}

    page_text, total_pages = build_page_text_map(pdf_path)
    features = calculate_page_features(
        [
            p
            for p in extract_page_texts(pdf_path, max_pages=min(SCAN_PAGES, total_pages))
        ],
        total_pages,
    )
    detection = detect_toc_pages(features)
    baseline_pages = list(detection.pages)

    probe = PageProbe(client, page_text)
    anchor, stage, trace = find_anchor(probe, detection.start_page, total_pages)

    if anchor is None:
        fallback_pages: list[int] = []
    else:
        start, end = grow_block(probe, anchor, total_pages)
        fallback_pages = list(range(start, end + 1))

    expected = label["toc_pages"]
    baseline_cmp = compare_toc_pages(baseline_pages, expected)
    fallback_cmp = compare_toc_pages(fallback_pages, expected)

    return {
        "id": label["id"],
        "status": "ok",
        "total_pages": total_pages,
        "expected_pages": expected,
        "detector": {
            "pages": baseline_pages,
            "start_page": detection.start_page,
            "end_page": detection.end_page,
            "confidence": detection.confidence,
            "precision": baseline_cmp.precision,
            "recall": baseline_cmp.recall,
            "segment_iou": baseline_cmp.segment_iou,
            "missing": baseline_cmp.missing_pages,
            "extra": baseline_cmp.extra_pages,
        },
        "fallback": {
            "stage_used": stage,
            "pages": fallback_pages,
            "precision": fallback_cmp.precision,
            "recall": fallback_cmp.recall,
            "segment_iou": fallback_cmp.segment_iou,
            "start_page_error": fallback_cmp.start_page_error,
            "end_page_error": fallback_cmp.end_page_error,
            "missing": fallback_cmp.missing_pages,
            "extra": fallback_cmp.extra_pages,
            "llm_calls": probe.call_count,
        },
        "trace": trace,
    }


def is_perfect(cmp: dict[str, Any]) -> bool:
    return cmp.get("precision") == 1.0 and cmp.get("recall") == 1.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", default=None, help="실행할 book id 제한")
    args = parser.parse_args()

    load_dotenv(ROOT_DIR / ".env")
    api_key = os.environ.get("UPSTAGE_API_KEY")
    if not api_key:
        raise SystemExit("UPSTAGE_API_KEY가 .env에 없다. 실험을 실행할 수 없다.")

    client = OpenAI(api_key=api_key, base_url=UPSTAGE_BASE_URL)
    labels = load_labels()
    target_ids = args.only or TARGET_IDS

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for book_id in target_ids:
        if book_id not in labels:
            print(f"[skip] {book_id}: label 없음")
            continue
        print(f"[run ] {book_id}")
        result = run_book(client, labels[book_id])
        results.append(result)
        (OUTPUT_DIR / f"{book_id}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if result["status"] == "ok":
            fb = result["fallback"]
            det = result["detector"]
            print(
                f"       detector P{det['precision']} R{det['recall']} "
                f"-> fallback[{fb['stage_used']}] P{fb['precision']} R{fb['recall']} "
                f"pages={fb['pages']} calls={fb['llm_calls']}"
            )
        else:
            print(f"       {result['status']}: {result.get('reason')}")

    ok = [r for r in results if r["status"] == "ok"]
    perfect = [r for r in ok if is_perfect(r["fallback"])]
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "model": MODEL,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "book_count": len(ok),
        "perfect_count": len(perfect),
        "perfect_ids": [r["id"] for r in perfect],
        "imperfect": [
            {
                "id": r["id"],
                "stage_used": r["fallback"]["stage_used"],
                "precision": r["fallback"]["precision"],
                "recall": r["fallback"]["recall"],
                "missing": r["fallback"]["missing"],
                "extra": r["fallback"]["extra"],
            }
            for r in ok
            if not is_perfect(r["fallback"])
        ],
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
