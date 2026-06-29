r"""experiment 031: 300STUDY bookmark 보유 PDF 랜덤 10권 matching 평가.

목적:
- ``C:\Users\chlje\My Drive\300STUDY`` 아래 PDF 중 실제 bookmark가 있는 책을 찾는다.
- 기존 bookmark 필터 흐름을 따라 너무 짧은 제목, 숫자/기호만 있는 제목, 숫자/OCR
  아티팩트 bookmark 비율이 높은 PDF를 제외한다.
- 필터를 통과한 PDF에서 seed 고정 random 10권을 뽑는다.
- bookmark를 보지 않는 학습된 ML TOC page detector로 목차 page range를 찾는다.
- 탐지된 목차 page를 page별로 LLM에 보내 title/level/printed_page를 추출한다.
- 실제 bookmark tree를 golden answer label로 보고 title matching, recall, level 일치율을
  평가한다.

실행:
    uv run python experiments/031_random_bookmark_matching_eval.py
"""

from __future__ import annotations

import csv
import json
import os
import random
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
from dotenv import load_dotenv
from openai import OpenAI
from rapidfuzz import fuzz

from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks
from pdfbooktree.pdf.text import extract_page_texts, extract_selected_page_texts
from pdfbooktree.toc.detect import detect_toc_pages
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
STUDY_ROOT = Path(r"C:\Users\chlje\My Drive\300STUDY")
EXPERIMENT_ID = "031_random_bookmark_matching_eval"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"

RANDOM_SEED = 31031
SAMPLE_SIZE = 10
MIN_TOTAL_PAGES = 50
MAX_TEXT_PAGES = 80
MAX_LLM_TOC_PAGES = 20

MIN_CLEAN_BOOKMARKS = 10
MIN_TITLE_CHARS = 4
NO_LETTER_THRESHOLD = 0.5
MATCH_THRESHOLD = 82.0

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
MODEL = "solar-pro3"

LETTER_RE = re.compile(r"[A-Za-z가-힣]")
NUMERIC_ONLY_RE = re.compile(r"^[\W\d_]+$")
FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


TOC_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "toc_page_items",
        "schema": {
            "type": "object",
            "properties": {
                "is_toc_page": {
                    "type": "boolean",
                    "description": (
                        "입력 page가 실제 목차 항목을 담은 page이면 true, 표지/서문/"
                        "본문/List of Pages/광고/빈 page 등 목차가 아니면 false."
                    ),
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "level": {"type": "integer"},
                            "printed_page": {"type": ["integer", "null"]},
                        },
                        "required": ["title", "level", "printed_page"],
                    },
                }
            },
            "required": ["is_toc_page", "items"],
        },
    },
}

SYSTEM_PROMPT = (
    "너는 책 목차(Table of Contents) 페이지에서 목차 항목을 구조화해 추출하는 도구다. "
    "입력은 한 PDF page의 text layer다. 각 목차 항목을 title, level, printed_page로 "
    "추출하라.\n"
    "규칙:\n"
    "- 먼저 입력 page가 실제 목차 항목을 담은 page인지 판단한다. 표지, 서문, 본문, "
    "List of Pages, 광고, 빈 page처럼 목차 항목 page가 아니면 is_toc_page=false와 "
    "items=[]를 반환한다.\n"
    "- title에는 장/절 번호가 있으면 포함한다(예: '1.2', 'Chapter 3', '제4장').\n"
    "- level은 최상위 장/부/appendix를 1로 두고, 하위 절은 2, 더 하위는 3처럼 둔다.\n"
    "- printed_page는 목차 줄 끝이나 오른쪽에 인쇄된 페이지 번호다. 없으면 null이다.\n"
    "- 목차 항목이 아닌 머리말, running header, 페이지 번호만 있는 줄은 제외한다.\n"
    "- OCR로 깨진 제목은 합리적으로만 복원하고 없는 항목은 만들지 않는다.\n"
    "- 항목은 page에 나온 순서 그대로 반환한다."
)


def clean_title(title: str) -> str:
    """비교와 출력에 쓸 bookmark/TOC 제목을 정리한다."""

    title = normalize_text(title)
    return title.strip()


def title_is_usable(title: str) -> bool:
    """짧거나 숫자/기호만 있는 bookmark 제목을 제외한다."""

    title = clean_title(title)
    compact = normalize_for_match(title).replace(" ", "")
    if len(compact) < MIN_TITLE_CHARS:
        return False
    if NUMERIC_ONLY_RE.fullmatch(title):
        return False
    return bool(LETTER_RE.search(title))


def relative_path(path: Path) -> str:
    """300STUDY 기준 상대경로를 문자열로 반환한다."""

    try:
        return str(path.relative_to(STUDY_ROOT))
    except ValueError:
        return str(path)


def filtered_bookmarks(bookmarks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """평가 golden으로 쓸 수 있는 bookmark만 남기고 level을 1부터 다시 맞춘다."""

    kept = [
        {
            "order": bookmark["order"],
            "level": int(bookmark["level"]),
            "title": clean_title(bookmark["title"]),
            "pdf_page": bookmark["pdf_page"],
        }
        for bookmark in bookmarks
        if title_is_usable(str(bookmark.get("title", "")))
    ]
    if not kept:
        return []
    min_level = min(bookmark["level"] for bookmark in kept)
    return [
        {**bookmark, "level": bookmark["level"] - min_level + 1}
        for bookmark in kept
    ]


def bookmark_quality(pdf_path: Path) -> dict[str, Any]:
    """단일 PDF의 bookmark 품질 지표와 후보 통과 여부를 계산한다."""

    result: dict[str, Any] = {
        "pdf": str(pdf_path),
        "root_relative_pdf": relative_path(pdf_path),
        "status": "ok",
        "is_candidate": False,
    }
    try:
        with fitz.open(pdf_path) as document:
            result["total_pages"] = document.page_count
        if result["total_pages"] < MIN_TOTAL_PAGES:
            result["status"] = "short_pdf"
            return result
        bookmarks = extract_existing_bookmarks(pdf_path)
    except Exception as exc:  # noqa: BLE001 - 실험에서는 실패 PDF를 기록하고 계속 진행한다.
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    titles = [clean_title(bookmark["title"]) for bookmark in bookmarks]
    no_letter_count = sum(1 for title in titles if not LETTER_RE.search(title))
    short_count = sum(
        1
        for title in titles
        if len(normalize_for_match(title).replace(" ", "")) < MIN_TITLE_CHARS
    )
    usable = filtered_bookmarks(bookmarks)
    pages = [bookmark["pdf_page"] for bookmark in usable if bookmark["pdf_page"]]
    non_decreasing = 1.0
    if len(pages) > 1:
        non_decreasing = sum(
            1 for left, right in zip(pages, pages[1:], strict=False) if right >= left
        ) / (len(pages) - 1)

    frac_no_letter = no_letter_count / len(titles) if titles else 1.0
    result.update(
        {
            "bookmark_count": len(bookmarks),
            "usable_bookmark_count": len(usable),
            "frac_no_letter": round(frac_no_letter, 4),
            "frac_short_title": round(short_count / len(titles), 4) if titles else 1.0,
            "level_count": len({bookmark["level"] for bookmark in usable}),
            "page_monotonicity": round(non_decreasing, 4),
        }
    )
    result["is_candidate"] = (
        len(usable) >= MIN_CLEAN_BOOKMARKS
        and frac_no_letter <= NO_LETTER_THRESHOLD
        and result["level_count"] >= 2
        and non_decreasing >= 0.75
    )
    return result


def collect_candidate_pool() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """300STUDY 아래 모든 PDF를 훑어 후보 pool을 만든다."""

    rows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for pdf_path in sorted(STUDY_ROOT.rglob("*.pdf")):
        row = bookmark_quality(pdf_path)
        rows.append(row)
        if row.get("is_candidate"):
            candidates.append(row)
    return candidates, rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """후보 pool CSV를 저장한다."""

    fields = [
        "status",
        "is_candidate",
        "root_relative_pdf",
        "total_pages",
        "bookmark_count",
        "usable_bookmark_count",
        "frac_no_letter",
        "frac_short_title",
        "level_count",
        "page_monotonicity",
        "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def detect_toc_page_range(pdf_path: Path) -> dict[str, Any]:
    """bookmark를 쓰지 않고 학습된 ML detector로 TOC page를 탐지한다."""

    pages = extract_page_texts(pdf_path, max_pages=MAX_TEXT_PAGES)
    with fitz.open(pdf_path) as document:
        total_pages = document.page_count
    features = calculate_page_features(pages, total_pages)
    detection = detect_toc_pages(features)
    return {
        "pages": detection.pages,
        "start_page": detection.start_page,
        "end_page": detection.end_page,
        "confidence": detection.confidence,
        "method": detection.method,
        "candidates": detection.candidates,
    }


def build_page_prompt(pdf_page: int, lines: list[str], text: str) -> str:
    """LLM에 줄 page marker와 함께 한 페이지 목차 텍스트를 준다."""

    body = "\n".join(lines) if lines else text
    return f"--- PDF page {pdf_page} ---\n{body}"


def parse_json(content: str | None) -> dict[str, Any]:
    """LLM 응답에서 JSON object를 최대한 보수적으로 읽는다."""

    if not content:
        return {}
    text = content.strip()
    candidates = [text]
    match = FENCE_RE.search(text)
    if match:
        candidates.append(match.group(1))
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return {}


def call_llm_extract(client: OpenAI, pdf_page: int, lines: list[str], text: str) -> list[dict[str, Any]]:
    """한 TOC page에서 LLM으로 목차 항목을 추출한다."""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_page_prompt(pdf_page, lines, text)},
        ],
        response_format=TOC_SCHEMA,
        temperature=0.0,
    )
    payload = parse_json(response.choices[0].message.content)
    if payload.get("is_toc_page") is False:
        return []
    items: list[dict[str, Any]] = []
    for raw in payload.get("items", []):
        title = clean_title(str(raw.get("title", "")))
        if not title_is_usable(title):
            continue
        printed_page = raw.get("printed_page")
        items.append(
            {
                "title": title,
                "level": max(1, int(raw.get("level") or 1)),
                "printed_page": int(printed_page) if printed_page else None,
                "source_pdf_page": pdf_page,
            }
        )
    return normalize_item_levels(items)


def normalize_item_levels(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """추출 항목 level이 1부터 시작하게 보정한다."""

    if not items:
        return items
    min_level = min(int(item["level"]) for item in items)
    if min_level <= 1:
        return items
    return [{**item, "level": int(item["level"]) - min_level + 1} for item in items]


def extract_toc_items(client: OpenAI, pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """탐지된 TOC page range를 순회하며 LLM 추출을 수행한다."""

    pages = toc_pages[:MAX_LLM_TOC_PAGES]
    texts = extract_selected_page_texts(pdf_path, pages)
    items: list[dict[str, Any]] = []
    for page in texts:
        items.extend(call_llm_extract(client, page.pdf_page, page.lines, page.text))
    return normalize_item_levels(items)


def norm_title(title: str) -> str:
    """matching용 title 정규화 문자열을 만든다."""

    return normalize_for_match(title).replace("contents", "").strip()


def greedy_match(
    items: list[dict[str, Any]],
    bookmarks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """추출 항목과 bookmark를 title fuzzy score 기준으로 1:1 matching한다."""

    scored: list[dict[str, Any]] = []
    for item_index, item in enumerate(items):
        item_title = norm_title(item["title"])
        if not item_title:
            continue
        for bookmark_index, bookmark in enumerate(bookmarks):
            bookmark_title = norm_title(bookmark["title"])
            if not bookmark_title:
                continue
            score = fuzz.token_set_ratio(item_title, bookmark_title)
            if score >= MATCH_THRESHOLD:
                scored.append(
                    {
                        "score": score,
                        "item_index": item_index,
                        "bookmark_index": bookmark_index,
                        "item": item,
                        "bookmark": bookmark,
                    }
                )

    used_items: set[int] = set()
    used_bookmarks: set[int] = set()
    matches: list[dict[str, Any]] = []
    for row in sorted(scored, key=lambda value: value["score"], reverse=True):
        if row["item_index"] in used_items or row["bookmark_index"] in used_bookmarks:
            continue
        used_items.add(row["item_index"])
        used_bookmarks.add(row["bookmark_index"])
        matches.append(row)
    return sorted(matches, key=lambda value: value["bookmark"]["order"])


def sign(value: int) -> int:
    """상대 level 변화 방향을 계산한다."""

    return (value > 0) - (value < 0)


def evaluate(items: list[dict[str, Any]], bookmarks: list[dict[str, Any]]) -> dict[str, Any]:
    """bookmark를 golden으로 보고 추출 결과의 matching 성능을 계산한다."""

    matches = greedy_match(items, bookmarks)
    matched_count = len(matches)
    item_count = len(items)
    bookmark_count = len(bookmarks)
    precision = matched_count / item_count if item_count else 0.0
    recall = matched_count / bookmark_count if bookmark_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    abs_level = (
        sum(1 for match in matches if match["item"]["level"] == match["bookmark"]["level"])
        / matched_count
        if matched_count
        else None
    )

    transitions = 0
    transition_agree = 0
    for left, right in zip(matches, matches[1:], strict=False):
        transitions += 1
        bookmark_delta = right["bookmark"]["level"] - left["bookmark"]["level"]
        item_delta = right["item"]["level"] - left["item"]["level"]
        if sign(bookmark_delta) == sign(item_delta):
            transition_agree += 1
    rel_depth = transition_agree / transitions if transitions else None

    return {
        "item_count": item_count,
        "bookmark_count": bookmark_count,
        "matched_count": matched_count,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "abs_level_agreement": round(abs_level, 4) if abs_level is not None else None,
        "rel_depth_agreement": round(rel_depth, 4) if rel_depth is not None else None,
        "mean_match_score": (
            round(sum(match["score"] for match in matches) / matched_count, 2)
            if matched_count
            else None
        ),
    }


def item_level_distribution(items: list[dict[str, Any]]) -> dict[str, int]:
    """항목 level 분포를 출력용 dict로 만든다."""

    return {str(level): count for level, count in sorted(Counter(item["level"] for item in items).items())}


def run_one(client: OpenAI, selected: dict[str, Any]) -> dict[str, Any]:
    """단일 PDF에 detection -> LLM extraction -> bookmark 평가를 수행한다."""

    pdf_path = Path(selected["pdf"])
    bookmarks = filtered_bookmarks(extract_existing_bookmarks(pdf_path))
    record: dict[str, Any] = {
        "pdf": str(pdf_path),
        "root_relative_pdf": relative_path(pdf_path),
        "total_pages": selected["total_pages"],
        "bookmark_count": selected["bookmark_count"],
        "usable_bookmark_count": len(bookmarks),
        "status": "ok",
    }
    try:
        detection = detect_toc_page_range(pdf_path)
        record["detection"] = {
            key: value for key, value in detection.items() if key != "candidates"
        }
        if not detection["pages"]:
            record["status"] = "toc_not_detected"
            record["evaluation"] = evaluate([], bookmarks)
            return record
        items = extract_toc_items(client, pdf_path, detection["pages"])
        metrics = evaluate(items, bookmarks)
    except Exception as exc:  # noqa: BLE001 - 실험 결과에는 실패도 포함한다.
        record["status"] = "failed"
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["evaluation"] = evaluate([], bookmarks)
        return record

    safe_name = re.sub(r"[^0-9A-Za-z가-힣]+", "_", pdf_path.stem).strip("_")[:80]
    matches = greedy_match(items, bookmarks)
    detail = {
        **record,
        "items": items,
        "bookmarks": bookmarks,
        "matches": [
            {
                "score": match["score"],
                "item": match["item"],
                "bookmark": match["bookmark"],
            }
            for match in matches
        ],
    }
    (OUTPUT_DIR / f"{safe_name}.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    record["evaluation"] = metrics
    record["item_level_distribution"] = item_level_distribution(items)
    record["bookmark_level_distribution"] = item_level_distribution(bookmarks)
    record["preview_items"] = items[:12]
    return record


def build_summary(
    candidates: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """전체 실험 summary를 만든다."""

    ok_results = [row for row in results if row.get("status") == "ok"]
    detected = [row for row in results if row.get("detection", {}).get("pages")]

    def avg(metric: str) -> float | None:
        values = [
            row["evaluation"].get(metric)
            for row in ok_results
            if row.get("evaluation", {}).get(metric) is not None
        ]
        return round(sum(values) / len(values), 4) if values else None

    return {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "study_root": str(STUDY_ROOT),
        "random_seed": RANDOM_SEED,
        "sample_size": SAMPLE_SIZE,
        "model": MODEL,
        "match_threshold": MATCH_THRESHOLD,
        "filter": {
            "min_total_pages": MIN_TOTAL_PAGES,
            "min_clean_bookmarks": MIN_CLEAN_BOOKMARKS,
            "min_title_chars": MIN_TITLE_CHARS,
            "no_letter_threshold": NO_LETTER_THRESHOLD,
            "min_page_monotonicity": 0.75,
        },
        "pool": {
            "total_pdf_count": len(all_rows),
            "candidate_count": len(candidates),
            "failed_count": sum(1 for row in all_rows if row.get("status") == "failed"),
            "short_pdf_count": sum(1 for row in all_rows if row.get("status") == "short_pdf"),
        },
        "selected": [
            {
                "root_relative_pdf": row["root_relative_pdf"],
                "total_pages": row["total_pages"],
                "bookmark_count": row["bookmark_count"],
                "usable_bookmark_count": row["usable_bookmark_count"],
            }
            for row in selected
        ],
        "aggregate": {
            "ok_count": len(ok_results),
            "detected_count": len(detected),
            "toc_not_detected_count": sum(1 for row in results if row.get("status") == "toc_not_detected"),
            "failed_count": sum(1 for row in results if row.get("status") == "failed"),
            "macro_precision": avg("precision"),
            "macro_recall": avg("recall"),
            "macro_f1": avg("f1"),
            "macro_abs_level_agreement": avg("abs_level_agreement"),
            "macro_rel_depth_agreement": avg("rel_depth_agreement"),
        },
        "results": results,
    }


def build_finding(summary: dict[str, Any]) -> str:
    """experiments.json에 들어갈 finding 문자열을 만든다."""

    aggregate = summary["aggregate"]
    parts = [
        f"300STUDY PDF {summary['pool']['total_pdf_count']}개를 스캔해 bookmark 품질 필터 통과 후보 "
        f"{summary['pool']['candidate_count']}개를 만들고 seed {RANDOM_SEED}로 10권을 랜덤 선택했다.",
        f"ML TOC detector는 {aggregate['detected_count']}/10권에서 목차 page를 찾았다.",
        f"LLM({MODEL}) page별 추출 후 bookmark golden과 title fuzzy matching(threshold {MATCH_THRESHOLD:g})으로 평가한 "
        f"macro precision/recall/f1은 {aggregate['macro_precision']}/"
        f"{aggregate['macro_recall']}/{aggregate['macro_f1']}이다.",
        f"matching된 항목의 macro abs level agreement는 {aggregate['macro_abs_level_agreement']}, "
        f"relative depth agreement는 {aggregate['macro_rel_depth_agreement']}이다.",
    ]
    worst = sorted(
        (
            row
            for row in summary["results"]
            if row.get("evaluation") and row["evaluation"].get("f1") is not None
        ),
        key=lambda row: row["evaluation"]["f1"],
    )[:3]
    if worst:
        parts.append(
            "하위 사례: "
            + "; ".join(
                f"{Path(row['root_relative_pdf']).name[:45]} f1={row['evaluation']['f1']} "
                f"det={row.get('detection', {}).get('pages', [])[:1]}-{row.get('detection', {}).get('pages', [])[-1:]}"
                for row in worst
            )
            + "."
        )
    return " ".join(parts)


def update_experiments_json(summary: dict[str, Any]) -> None:
    """실험 registry에 이번 결과를 기록한다."""

    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "300STUDY에서 bookmark가 있는 PDF 중 너무 짧거나 숫자/기호만 있는 bookmark 제목이 많은 "
            "책을 제외하고 랜덤 10권을 골라, bookmark를 golden answer label로 두고 ML TOC page "
            "detection -> page별 LLM 목차 extraction -> bookmark matching 성능을 평가한다."
        ),
        "inputs": [str(STUDY_ROOT)],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "model": MODEL,
        "temperature": 0.0,
        "finding": summary["finding"],
        "ran_at": summary["ran_at"],
    }
    registry["experiments"] = [
        experiment
        for experiment in registry["experiments"]
        if experiment.get("id") != EXPERIMENT_ID
    ]
    registry["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """실험 entrypoint."""

    load_dotenv(ROOT_DIR / ".env")
    api_key = os.environ.get("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
    client = OpenAI(api_key=api_key, base_url=UPSTAGE_BASE_URL)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/4] bookmark 후보 pool 수집...")
    candidates, all_rows = collect_candidate_pool()
    write_csv(OUTPUT_DIR / "candidate_pool.csv", all_rows)
    if len(candidates) < SAMPLE_SIZE:
        raise RuntimeError(f"후보 PDF가 부족하다: {len(candidates)} < {SAMPLE_SIZE}")

    selected = random.Random(RANDOM_SEED).sample(candidates, SAMPLE_SIZE)
    (OUTPUT_DIR / "selected_pdfs.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[2/4] 후보 {len(candidates)}개 중 랜덤 {len(selected)}개 선택")
    results: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        print(f"[3/4] ({index}/{len(selected)}) {row['root_relative_pdf']}")
        result = run_one(client, row)
        results.append(result)
        evaluation = result.get("evaluation", {})
        print(
            f"      status={result['status']} toc={result.get('detection', {}).get('pages')} "
            f"f1={evaluation.get('f1')} recall={evaluation.get('recall')}"
        )

    summary = build_summary(candidates, all_rows, selected, results)
    summary["finding"] = build_finding(summary)
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    update_experiments_json(summary)

    print("[4/4] 완료")
    print(json.dumps(summary["aggregate"], ensure_ascii=False, indent=2))
    print(summary["finding"])


if __name__ == "__main__":
    main()
