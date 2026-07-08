"""experiment 071: page-relative font_size clamp 수정 후, 069 stack hierarchy
알고리즘을 실제 300STUDY OCR overlay 산출물 2권에 다시 돌려서 검증한다.

070에서 발견한 문제: `src/pdfbooktree/ocr/insertion.py`의 invisible text
font_size가 절대값 [3.0, 18.0]pt로 clamp돼, source PDF의 page MediaBox가
비정상적으로 큰 책(AB테스트_무작정따라하기, page_rect=1080x1865pt)에서는 본문
문단까지 18pt 벽에 부딪혀 heading/본문 구분 신호가 사라졌다(clamp_share 72.7%).

이 실험은 insertion.py를 page 세로 길이에 비례한 clamp로 고친 뒤(기존
document_parse_cache를 그대로 재사용해 API 재호출 없이 두 책을 다시 overlay),
(1) clamp_share가 정상화됐는지 재확인하고 (2) 069에서 검증한 stack 기반
hierarchy 알고리즘(mode_and_smaller body 제외)을 두 책에 그대로 적용해
inferred_bookmark_tree를 만든다. 두 책 모두 bookmark 정답이 없으므로 F1
검증은 하지 않고, 사람이 실제 목차와 육안 대조할 수 있도록 결과만 저장한다.

실행:
    uv run python experiments/071_relative_clamp_stack_hierarchy_verification.py
출력:
    experiments/outputs/071_relative_clamp_stack_hierarchy_verification/<book_id>/
        - font_size_histogram.txt      : 070과 동일한 clamp 재확인용 히스토그램
        - stack_trace.txt              : 069와 동일한 stack 처리 로그
        - inferred_bookmark_tree.txt/json : 사람이 육안 검토할 결과
        - summary.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from scipy.signal import argrelextrema
from scipy.stats import gaussian_kde

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "071_relative_clamp_stack_hierarchy_verification"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

MIN_TIER_COUNT = 5
CLAMP_MAX = 18.0
CLAMP_NEAR = 0.05
MAX_STACK_TRACE_LINES = 4000

BOOKS = [
    {
        "id": "AB테스트_무작정따라하_-_오서준",
        "pdf": ROOT_DIR
        / "data"
        / "300STUDY"
        / "pdfs"
        / "a_books"
        / "normalbook"
        / "AB테스트_무작정따라하_-_오서준.pdf",
    },
    {
        "id": "부동산대출의기술_-_주지현",
        "pdf": ROOT_DIR
        / "data"
        / "300STUDY"
        / "pdfs"
        / "a_books"
        / "normalbook"
        / "부동산대출의기술_-_주지현.pdf",
    },
]

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_NORM_STRIP = re.compile(r"[^a-z0-9가-힣 ]")
_MULTI_SPACE = re.compile(r"\s+")


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def extract_page_content_spans(page: fitz.Page) -> list[dict[str, Any]]:
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


def cluster_by_density(values: list[float]) -> dict[str, Any]:
    arr = np.asarray(values, dtype=float)
    uniq = np.unique(arr)
    if uniq.size == 1:
        return {"tier_count": 1, "cut_points": [], "peaks": [float(uniq[0])]}
    if uniq.size < 3:
        return {
            "tier_count": int(uniq.size),
            "cut_points": [float((uniq[i] + uniq[i + 1]) / 2.0) for i in range(uniq.size - 1)],
            "peaks": sorted((float(v) for v in uniq), reverse=True),
        }

    kde = gaussian_kde(arr)
    grid = np.linspace(arr.min() - 1.0, arr.max() + 1.0, 4096)
    density = kde(grid)

    peak_idx = argrelextrema(density, np.greater)[0]
    valley_idx = argrelextrema(density, np.less)[0]
    if peak_idx.size == 0:
        return {"tier_count": 1, "cut_points": [], "peaks": [float(np.median(arr))]}

    peaks = [float(grid[i]) for i in peak_idx]
    cut_points = [float(grid[vi]) for vi in valley_idx if peaks[0] < grid[vi] < peaks[-1]]
    cut_points = sorted(cut_points)[: max(len(peaks) - 1, 0)]

    return {"tier_count": len(peaks), "cut_points": cut_points, "peaks": sorted(peaks, reverse=True)}


def assign_tier(value: float, cut_points: list[float]) -> int:
    tier = 1
    for cut in sorted(cut_points, reverse=True):
        if value >= cut:
            return tier
        tier += 1
    return tier


def merge_tiers_by_min_count(
    values: list[float], peaks: list[float], cut_points: list[float], min_count: int
) -> tuple[list[float], list[float]]:
    peaks_desc = sorted(peaks, reverse=True)
    cuts_desc = sorted(cut_points, reverse=True)

    while len(peaks_desc) > 1:
        counts = Counter(assign_tier(value, cuts_desc) for value in values)
        tier_counts = [counts.get(i + 1, 0) for i in range(len(peaks_desc))]
        min_idx = min(range(len(tier_counts)), key=lambda i: tier_counts[i])
        if tier_counts[min_idx] >= min_count:
            break

        if min_idx == 0:
            merge_with = 1
        elif min_idx == len(peaks_desc) - 1:
            merge_with = min_idx - 1
        else:
            left_gap = peaks_desc[min_idx - 1] - peaks_desc[min_idx]
            right_gap = peaks_desc[min_idx] - peaks_desc[min_idx + 1]
            merge_with = min_idx - 1 if left_gap <= right_gap else min_idx + 1

        lo_idx, hi_idx = sorted([min_idx, merge_with])
        del cuts_desc[lo_idx]
        peaks_desc[lo_idx] = (peaks_desc[lo_idx] + peaks_desc[hi_idx]) / 2.0
        del peaks_desc[hi_idx]

    return peaks_desc, cuts_desc


def compute_tiers(values: list[float], min_count: int) -> dict[str, Any]:
    raw = cluster_by_density(values)
    final_peaks, final_cuts = merge_tiers_by_min_count(values, raw["peaks"], raw["cut_points"], min_count)
    return {
        "raw_tier_count": raw["tier_count"],
        "final_peaks": final_peaks,
        "final_cuts": final_cuts,
        "final_tier_count": len(final_peaks),
    }


def exclude_body_tiers(tier_of_line: list[int], tier_count: int) -> set[int]:
    """069의 mode_and_smaller와 동일: 최빈 tier와 그보다 작은 tier를 전부 제외한다."""

    counts = Counter(tier_of_line)
    mode_tier = max(counts, key=counts.get)
    return set(range(mode_tier, tier_count + 1))


@dataclass
class HeadingCandidate:
    pdf_page: int
    text: str
    font_size: float
    tier_value: float
    tier: int
    level: int = 0
    stack_action: str = ""
    stack_after: list[float] = field(default_factory=list)


def assign_levels_by_stack(candidates: list[HeadingCandidate]) -> list[str]:
    """069와 동일한 stack 알고리즘(tier 대표값으로 비교)."""

    stack: list[float] = []
    trace: list[str] = []
    for candidate in candidates:
        size = candidate.tier_value
        while stack and stack[-1] < size:
            popped = stack.pop()
            trace.append(f"  pop {popped} (< {size})")
        if stack and stack[-1] == size:
            candidate.level = len(stack)
            candidate.stack_action = "sibling"
        else:
            stack.append(size)
            candidate.level = len(stack)
            candidate.stack_action = "push"
        candidate.stack_after = list(stack)
        trace.append(
            f"p{candidate.pdf_page:>4} size={size:>6} tier=T{candidate.tier} "
            f"action={candidate.stack_action:<7} level={candidate.level} "
            f"stack={stack!r} text={candidate.text[:60]!r}"
        )
    return trace


def check_count_monotonicity(candidates: list[HeadingCandidate]) -> dict[str, Any]:
    counts = Counter(candidate.level for candidate in candidates)
    max_level = max(counts) if counts else 0
    level_counts = [counts.get(level, 0) for level in range(1, max_level + 1)]
    violations = [
        {"level": level, "count": level_counts[level - 1], "next_level": level + 1, "next_count": level_counts[level]}
        for level in range(1, max_level)
        if level_counts[level - 1] > level_counts[level]
    ]
    return {
        "level_counts": {str(i + 1): c for i, c in enumerate(level_counts)},
        "max_level": max_level,
        "violations": violations,
        "is_monotonic": len(violations) == 0,
    }


def check_level_jumps(candidates: list[HeadingCandidate]) -> int:
    jumps = 0
    for prev, cur in zip(candidates, candidates[1:]):
        if cur.level - prev.level > 1:
            jumps += 1
    return jumps


def check_clamp(book_id: str, lines: list[dict[str, Any]], book_output_dir: Path) -> dict[str, Any]:
    """070과 동일한 clamp 재확인. font_size 절대값 18.0에 몰린 비중이 정상화됐는지 본다."""

    font_sizes = [line["font_size"] for line in lines]
    counts = Counter(font_sizes)
    total = len(font_sizes)
    histogram = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    (book_output_dir / "font_size_histogram.txt").write_text(
        "\n".join(f"{size:>6} : {count:>6} ({count / total:.1%})" for size, count in histogram),
        encoding="utf-8",
    )
    clamp_count = sum(c for size, c in counts.items() if abs(size - CLAMP_MAX) <= CLAMP_NEAR)
    return {
        "distinct_font_sizes": len(counts),
        "max_font_size": max(counts) if counts else 0.0,
        "clamp_18_share": round(clamp_count / total, 4) if total else 0.0,
    }


def run_book(config: dict[str, Any]) -> dict[str, Any]:
    book_id = config["id"]
    pdf_path: Path = config["pdf"]
    book_output_dir = OUTPUT_DIR / book_id
    book_output_dir.mkdir(parents=True, exist_ok=True)

    print(f"... {book_id} 훑는 중: {pdf_path.name}", flush=True)
    with fitz.open(pdf_path) as document:
        sample_page = document[min(10, document.page_count - 1)]
        page_width_pt = round(sample_page.rect.width, 1)
        page_height_pt = round(sample_page.rect.height, 1)

    lines = extract_book_lines(pdf_path)
    clamp_info = check_clamp(book_id, lines, book_output_dir)
    print(
        f"    page_rect={page_width_pt}x{page_height_pt}pt total_lines={len(lines)} "
        f"clamp_18_share={clamp_info['clamp_18_share']:.2%} (070 이전 수치와 비교)",
        flush=True,
    )

    font_sizes = [line["font_size"] for line in lines]
    tiers = compute_tiers(font_sizes, MIN_TIER_COUNT)
    print(
        f"    font_size tiers: raw={tiers['raw_tier_count']} -> final={tiers['final_tier_count']} "
        f"peaks={[round(p, 2) for p in tiers['final_peaks']]}",
        flush=True,
    )

    tier_of_line = [assign_tier(v, tiers["final_cuts"]) for v in font_sizes]
    body_tiers = exclude_body_tiers(tier_of_line, tiers["final_tier_count"])

    candidates = [
        HeadingCandidate(
            pdf_page=line["pdf_page"],
            text=line["text"],
            font_size=line["font_size"],
            tier_value=tiers["final_peaks"][tier - 1],
            tier=tier,
        )
        for line, tier in zip(lines, tier_of_line)
        if tier not in body_tiers
    ]

    trace = assign_levels_by_stack(candidates)
    (book_output_dir / "stack_trace.txt").write_text("\n".join(trace[:MAX_STACK_TRACE_LINES]), encoding="utf-8")

    monotonicity = check_count_monotonicity(candidates)
    level_jumps = check_level_jumps(candidates)

    tree = [
        {"pdf_page": c.pdf_page, "level": c.level, "title": c.text, "font_size": c.font_size, "tier": c.tier}
        for c in candidates
    ]
    (book_output_dir / "inferred_bookmark_tree.json").write_text(
        json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tree_text = [f"총 {len(tree)}개 heading candidate (body_mode=mode_and_smaller, ground truth 없음)", ""]
    for node in tree:
        tree_text.append(f"{'  ' * (node['level'] - 1)}L{node['level']} p.{node['pdf_page']} {node['title']}")
    (book_output_dir / "inferred_bookmark_tree.txt").write_text("\n".join(tree_text), encoding="utf-8")

    print(
        f"    candidates={len(candidates)} max_level={monotonicity['max_level']} "
        f"level_jumps={level_jumps} monotonic={monotonicity['is_monotonic']}",
        flush=True,
    )

    book_summary = {
        "book_id": book_id,
        "page_width_pt": page_width_pt,
        "page_height_pt": page_height_pt,
        "total_lines": len(lines),
        "clamp": clamp_info,
        "tiers": {
            "raw_tier_count": tiers["raw_tier_count"],
            "final_tier_count": tiers["final_tier_count"],
            "final_peaks": [round(p, 2) for p in tiers["final_peaks"]],
        },
        "candidate_count": len(candidates),
        "monotonicity": monotonicity,
        "level_jumps": level_jumps,
        "inferred_bookmark_tree_nodes": len(tree),
        "inferred_bookmark_tree_path": str((book_output_dir / "inferred_bookmark_tree.txt").relative_to(ROOT_DIR)),
    }
    (book_output_dir / "summary.json").write_text(json.dumps(book_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return book_summary


def record_experiment(finding: str, book_summaries: list[dict[str, Any]]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "070에서 발견한 page-size 의존 font_size clamp 문제를 "
            "insertion.py에서 page 세로 길이 비례 clamp로 고친 뒤(cache-policy "
            "only로 API 재호출 없이 재생성), clamp_share가 정상화됐는지 확인하고 "
            "069의 stack hierarchy 알고리즘을 실제 OCR overlay 산출물 2권에 다시 "
            "적용해 사람이 육안 검토할 inferred_bookmark_tree를 만든다."
        ),
        "inputs": [str(book["pdf"].relative_to(ROOT_DIR)) for book in BOOKS],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": [
            "069_page_order_stack_hierarchy",
            "070_ocr_overlay_font_size_clamp_check",
        ],
        "min_tier_count": MIN_TIER_COUNT,
        "finding": finding,
        "books": book_summaries,
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

    book_summaries = [run_book(config) for config in BOOKS]

    finding = " | ".join(
        f"{s['book_id']}: page_rect={s['page_width_pt']}x{s['page_height_pt']}pt "
        f"clamp_18_share={s['clamp']['clamp_18_share']:.2%}(070 이전 대비) "
        f"candidates={s['candidate_count']} tree_nodes={s['inferred_bookmark_tree_nodes']} "
        f"level_jumps={s['level_jumps']} monotonic={s['monotonicity']['is_monotonic']}"
        for s in book_summaries
    )

    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps({"experiment_id": EXPERIMENT_ID, "books": book_summaries, "finding": finding}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_experiment(finding, book_summaries)

    print("\n=== exp 071: relative clamp fix + stack hierarchy verification ===")
    print(finding)
    for s in book_summaries:
        print(f"  -> {s['inferred_bookmark_tree_path']}")
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
