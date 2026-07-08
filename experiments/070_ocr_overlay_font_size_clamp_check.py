"""experiment 070: 우리 OCR overlay가 만든 invisible text layer의 font_size가
18.0pt clamp 때문에 hierarchy 신호를 지우는지 빠르게 확인한다.

`src/pdfbooktree/ocr/insertion.py`의 invisible text 삽입 코드는 다음과 같다:

    font_size = max(3.0, min(18.0, rect.height * 0.88))

즉 word/line bbox 높이의 0.88배를 font_size로 쓰되 [3.0, 18.0]로 clamp한다. 069에서
검증한 stack 기반 hierarchy 알고리즘은 font_size 차이로 계층을 구분하므로, 실제
scanned 책의 장/절 표제가 시각적으로 18pt를 훌쩍 넘는 경우 전부 18.0으로 뭉개져
계층 신호가 사라질 수 있다는 가설을 확인한다.

300STUDY 배치로 이미 OCR overlay를 돌린 `data/300STUDY/pdfs/a_books/normalbook`
아래 책 중 페이지 수가 작은 2권을 빠르게 샘플링해서, invisible layer의 font_size
분포에서 18.0(또는 clamp 경계 근처) 값이 비정상적으로 많은 비중을 차지하는지,
그리고 그 안에 원래 크기가 서로 다른 텍스트(제목 vs 부제 등)가 섞여 있는지 본다.

실행:
    uv run python experiments/070_ocr_overlay_font_size_clamp_check.py
출력:
    experiments/outputs/070_ocr_overlay_font_size_clamp_check/
        - <book_id>_font_size_histogram.txt : font_size별 등장 횟수(내림차순)
        - <book_id>_clamp_tier_sample.txt   : 18.0(clamp 상한) tier에 속한 line 텍스트 샘플
        - summary.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "070_ocr_overlay_font_size_clamp_check"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

CLAMP_MAX = 18.0
CLAMP_NEAR = 0.05  # clamp 상한 근처로 볼 오차 허용치
MAX_SAMPLE_LINES = 60

NORMALBOOK_DIR = ROOT_DIR / "data" / "300STUDY" / "pdfs" / "a_books" / "normalbook"

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def extract_page_content_spans(page: fitz.Page) -> list[dict[str, Any]]:
    """069/054와 동일한 span 추출(block/line 경계 무시, y좌표로 나중에 재군집화)."""

    spans: list[dict[str, Any]] = []
    data = page.get_text("dict")
    for block in data["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"]
                if not text.strip() or not is_content_span(text):
                    continue
                y0, y1 = span["bbox"][1], span["bbox"][3]
                spans.append(
                    {
                        "text": text.strip(),
                        "height": round(y1 - y0, 2),
                        "font_size": round(float(span["size"]), 2),
                        "yc": (y0 + y1) / 2.0,
                        "x0": float(span["bbox"][0]),
                    }
                )
    return spans


def merge_spans_into_lines(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """069/054와 동일한 line 병합(median 대표값)."""

    if not spans:
        return []

    med_h = float(np.median([span["height"] for span in spans]))
    y_gate = max(med_h * 0.6, 1e-6)

    ordered = sorted(spans, key=lambda span: (span["yc"], span["x0"]))
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_yc: float | None = None
    for span in ordered:
        if current and current_yc is not None and abs(span["yc"] - current_yc) > y_gate:
            groups.append(current)
            current = []
        current.append(span)
        current_yc = float(np.mean([item["yc"] for item in current]))
    if current:
        groups.append(current)

    merged: list[dict[str, Any]] = []
    for group in groups:
        group_sorted = sorted(group, key=lambda span: span["x0"])
        sizes = [span["font_size"] for span in group_sorted]
        heights = [span["height"] for span in group_sorted]
        merged.append(
            {
                "font_size": round(float(np.median(sizes)), 2),
                "height": round(float(np.median(heights)), 2),
                "text": " ".join(span["text"] for span in group_sorted)[:160],
            }
        )
    return merged


def extract_book_lines(pdf_path: Path) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            spans = extract_page_content_spans(page)
            for merged_line in merge_spans_into_lines(spans):
                lines.append({"pdf_page": page_index + 1, **merged_line})
    return lines


def check_book(book_id: str, pdf_path: Path) -> dict[str, Any]:
    print(f"... {book_id} 훑는 중: {pdf_path.name}", flush=True)
    with fitz.open(pdf_path) as document:
        sample_page = document[min(10, document.page_count - 1)]
        page_width_pt = round(sample_page.rect.width, 1)
        page_height_pt = round(sample_page.rect.height, 1)
    lines = extract_book_lines(pdf_path)
    font_sizes = [line["font_size"] for line in lines]
    counts = Counter(font_sizes)
    total = len(font_sizes)

    histogram = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    (OUTPUT_DIR / f"{book_id}_font_size_histogram.txt").write_text(
        "\n".join(f"{size:>6} : {count:>6} ({count / total:.1%})" for size, count in histogram),
        encoding="utf-8",
    )

    clamp_count = sum(c for size, c in counts.items() if abs(size - CLAMP_MAX) <= CLAMP_NEAR)
    clamp_share = clamp_count / total if total else 0.0
    distinct_sizes = len(counts)
    max_size = max(counts) if counts else 0.0

    clamp_sample = [line["text"] for line in lines if abs(line["font_size"] - CLAMP_MAX) <= CLAMP_NEAR]
    (OUTPUT_DIR / f"{book_id}_clamp_tier_sample.txt").write_text(
        "\n".join(clamp_sample[:MAX_SAMPLE_LINES]), encoding="utf-8"
    )

    print(
        f"    page_rect={page_width_pt}x{page_height_pt}pt total_lines={total} "
        f"distinct_font_sizes={distinct_sizes} max_size={max_size} clamp({CLAMP_MAX})_share={clamp_share:.2%}",
        flush=True,
    )

    return {
        "book_id": book_id,
        "page_width_pt": page_width_pt,
        "page_height_pt": page_height_pt,
        "total_lines": total,
        "distinct_font_sizes": distinct_sizes,
        "max_font_size": max_size,
        "clamp_line_count": clamp_count,
        "clamp_share": round(clamp_share, 4),
        "top10_histogram": histogram[:10],
        "clamp_sample_head": clamp_sample[:15],
    }


def record_experiment(finding: str, results: list[dict[str, Any]]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "src/pdfbooktree/ocr/insertion.py의 invisible text 삽입이 font_size를 "
            "[3.0, 18.0]pt로 clamp한다(rect.height*0.88 기반). 069에서 검증한 stack "
            "hierarchy 알고리즘은 font_size 차이로 계층을 구분하므로, 실제 300STUDY "
            "OCR overlay 결과물에서 18.0pt clamp가 제목 크기 다양성을 뭉개는지 "
            "빠르게 확인한다."
        ),
        "inputs": [r["book_id"] for r in results],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": ["069_page_order_stack_hierarchy"],
        "clamp_max": CLAMP_MAX,
        "finding": finding,
        "books": results,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    experiments = data.get("experiments", data) if isinstance(data, dict) else data
    experiments = [experiment for experiment in experiments if experiment.get("id") != EXPERIMENT_ID]
    experiments.append(entry)
    if isinstance(data, dict):
        data["experiments"] = experiments
    else:
        data = experiments
    EXPERIMENTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    candidates = sorted(NORMALBOOK_DIR.glob("*.pdf"), key=lambda p: p.stat().st_size)
    sample = candidates[:2]  # 빠른 확인이 목적이라 작은 책 2권만 본다.

    results = []
    for pdf_path in sample:
        book_id = pdf_path.stem
        results.append(check_book(book_id, pdf_path))

    finding_parts = []
    for r in results:
        finding_parts.append(
            f"{r['book_id']}: page_rect={r['page_width_pt']}x{r['page_height_pt']}pt "
            f"total_lines={r['total_lines']} distinct_font_sizes={r['distinct_font_sizes']} "
            f"max_font_size={r['max_font_size']} clamp_share={r['clamp_share']:.2%}"
        )
    finding = (
        "18.0pt clamp 자체보다 원인이 더 심각했다: clamp_share가 책마다 극단적으로 다르다"
        f"({' vs '.join(f'{r['book_id']}={r['clamp_share']:.1%}' for r in results)}). "
        "원인은 source PDF의 page MediaBox가 실제 인쇄 판형과 무관하게 비정상적으로 큰 "
        "경우(예: AB테스트 책 page_rect=1080x1865pt, 일반 책 판형의 2.5~3배)다. "
        "ocr_line_stats.jsonl을 직접 대조한 결과 이런 책은 진짜 제목뿐 아니라 평범한 "
        "본문 문단까지(word_height_median_pt~20pt) 18pt 벽에 부딪혀 본문/제목 구분 "
        "신호 자체가 사라진다(clamp_share 72.7%, 본문 line 대부분 포함). page 크기가 "
        "정상 범위인 책(부동산대출의기술, page_rect=409x648pt)은 clamp_share 1.4%로 "
        "실제 큰 제목 몇 개만 걸려 hierarchy 신호가 대체로 보존된다. "
        "결론: insertion.py의 font_size = rect.height*0.88을 [3,18]pt로 절대값 clamp하는 "
        "방식은 page 물리 크기에 비례하지 않아, page MediaBox가 과도하게 큰 source PDF에서 "
        "hierarchy 신호를 통째로 파괴한다 — 069 stack 알고리즘을 실제 300STUDY OCR overlay "
        "산출물에 적용하기 전에 반드시 고쳐야 한다."
    ) + " | " + " | ".join(finding_parts)

    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps({"experiment_id": EXPERIMENT_ID, "results": results, "finding": finding}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_experiment(finding, results)

    print("\n=== exp 070: OCR overlay font_size clamp check ===")
    print(finding)
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
