"""experiment 092: 정규화된 top-left geometry와 font tier로 level을 추출한다.

절대 pt tolerance는 책의 판형과 OCR overlay scale에 종속된다. 이 실험은 BPE
heading 첫 조각의 top-left를 page width/height로 정규화하고, 문서 내 heading
후보의 중앙 line height를 좌표 거리 단위로 삼는다. 같은 font tier이면서 여러
페이지에서 같은 정규화 위치에 반복되는 후보만 남긴 뒤 기존 tier stack으로
level을 부여하고 PDF bookmark 정답과 비교한다.

실행:
    uv run python experiments/092_normalized_geometry_font_level.py
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Any

import fitz

from pdfbooktree.config import TypographyConfig
from pdfbooktree.typography.bpe import BpeHeading, extract_bpe_headings
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts
from pdfbooktree.typography.tiers import assign_tier, compute_tier_set

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "092_normalized_geometry_font_level"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
INPUT_PDF = (
    ROOT_DIR
    / "showcase"
    / "outputs"
    / "016_econometrics_note1_ocr_overlay"
    / "kim_econometrics_note1_ocr.pdf"
)
POSITION_HEIGHT_RATIOS = [0.25, 0.5, 1.0]
MIN_DISTINCT_PAGES = 2
TITLE_MATCH_THRESHOLD = 70.0


@dataclass(frozen=True)
class PositionedHeading:
    heading: BpeHeading
    x_unit: float
    y_unit: float
    raw_x0: float
    raw_y0: float


def attach_normalized_top_left(
    headings: list[BpeHeading], lines: list[Any]
) -> tuple[list[PositionedHeading], int, dict[str, float]]:
    by_page_y: dict[tuple[int, float], list[Any]] = defaultdict(list)
    for line in lines:
        by_page_y[(line.pdf_page, line.y0)].append(line)

    matched: list[tuple[BpeHeading, Any]] = []
    for heading in headings:
        source = by_page_y.get((heading.pdf_page, heading.y0), [])
        if source:
            matched.append((heading, min(source, key=lambda line: line.x0)))

    x_height_unit = median(line.height / line.page_width for _, line in matched)
    y_height_unit = median(line.height / line.page_height for _, line in matched)
    positioned = [
        PositionedHeading(
            heading=heading,
            x_unit=(line.x0 / line.page_width) / x_height_unit,
            y_unit=(line.y0 / line.page_height) / y_height_unit,
            raw_x0=line.x0,
            raw_y0=line.y0,
        )
        for heading, line in matched
    ]
    return (
        positioned,
        len(headings) - len(matched),
        {
            "median_height_over_page_width": x_height_unit,
            "median_height_over_page_height": y_height_unit,
        },
    )


def cluster_positions(
    items: list[PositionedHeading], tolerance: float
) -> list[list[PositionedHeading]]:
    by_tier: dict[int, list[PositionedHeading]] = defaultdict(list)
    for item in items:
        by_tier[item.heading.tier].append(item)

    result: list[list[PositionedHeading]] = []
    for tier_items in by_tier.values():
        clusters: list[list[PositionedHeading]] = []
        for item in sorted(tier_items, key=lambda row: (row.x_unit, row.y_unit)):
            target = next(
                (
                    cluster
                    for cluster in clusters
                    if max(row.x_unit for row in cluster + [item])
                    - min(row.x_unit for row in cluster + [item])
                    <= tolerance
                    and max(row.y_unit for row in cluster + [item])
                    - min(row.y_unit for row in cluster + [item])
                    <= tolerance
                ),
                None,
            )
            if target is None:
                clusters.append([item])
            else:
                target.append(item)
        result.extend(clusters)
    return result


def select_repeated(
    items: list[PositionedHeading], tolerance: float
) -> tuple[list[PositionedHeading], list[dict[str, Any]]]:
    selected: list[PositionedHeading] = []
    reports: list[dict[str, Any]] = []
    for cluster in cluster_positions(items, tolerance):
        pages = {item.heading.pdf_page for item in cluster}
        accepted = len(pages) >= MIN_DISTINCT_PAGES
        if accepted:
            selected.extend(cluster)
        reports.append(
            {
                "tier": cluster[0].heading.tier,
                "count": len(cluster),
                "distinct_pages": len(pages),
                "accepted": accepted,
                "x_unit_range": [
                    round(min(item.x_unit for item in cluster), 4),
                    round(max(item.x_unit for item in cluster), 4),
                ],
                "y_unit_range": [
                    round(min(item.y_unit for item in cluster), 4),
                    round(max(item.y_unit for item in cluster), 4),
                ],
                "title_preview": [item.heading.title for item in cluster[:5]],
            }
        )
    selected.sort(key=lambda item: (item.heading.pdf_page, item.raw_y0, item.raw_x0))
    return selected, reports


def run_stack(items: list[PositionedHeading]) -> list[tuple[PositionedHeading, int]]:
    stack: list[PositionedHeading] = []
    result: list[tuple[PositionedHeading, int]] = []
    for item in items:
        while stack and stack[-1].heading.tier > item.heading.tier:
            stack.pop()
        if stack and stack[-1].heading.tier == item.heading.tier:
            level = len(stack)
            stack[-1] = item
        else:
            stack.append(item)
            level = len(stack)
        result.append((item, level))
    return result


def normalize_title(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", " ", text.casefold()).strip()


def load_truth() -> list[dict[str, Any]]:
    with fitz.open(INPUT_PDF) as document:
        return [
            {"level": level, "title": title, "pdf_page": page}
            for level, title, page in document.get_toc()
            if page > 0
        ]


def evaluate_truth(
    pairs: list[tuple[PositionedHeading, int]], truth: list[dict[str, Any]]
) -> dict[str, Any]:
    by_page: dict[int, list[tuple[PositionedHeading, int]]] = defaultdict(list)
    for item, level in pairs:
        by_page[item.heading.pdf_page].append((item, level))

    matches: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    matched_candidate_keys: set[tuple[int, float, str]] = set()
    for entry in truth:
        best = None
        best_score = -1.0
        for item, level in by_page.get(entry["pdf_page"], []):
            truth_title = normalize_title(entry["title"])
            candidate_title = normalize_title(item.heading.title)
            if truth_title and (
                truth_title in candidate_title or candidate_title in truth_title
            ):
                score = 100.0
            else:
                score = (
                    100.0 * SequenceMatcher(None, truth_title, candidate_title).ratio()
                )
            if score > best_score:
                best = (item, level)
                best_score = score
        if best is None or best_score < TITLE_MATCH_THRESHOLD:
            unmatched.append(entry)
            continue
        item, level = best
        matched_candidate_keys.add(
            (item.heading.pdf_page, item.raw_y0, item.heading.title)
        )
        matches.append(
            {
                "truth_title": entry["title"],
                "truth_page": entry["pdf_page"],
                "truth_level": entry["level"],
                "candidate_title": item.heading.title,
                "candidate_tier": item.heading.tier,
                "candidate_level": level,
                "score": round(best_score, 1),
                "level_correct": level == entry["level"],
            }
        )
    matched = len(matches)
    return {
        "truth_count": len(truth),
        "matched_truth_count": matched,
        "recall": round(matched / len(truth), 4) if truth else 0.0,
        "level_correct_count": sum(row["level_correct"] for row in matches),
        "level_accuracy_on_matched": round(
            sum(row["level_correct"] for row in matches) / matched, 4
        )
        if matched
        else 0.0,
        "matched_candidate_count": len(matched_candidate_keys),
        "matches": matches,
        "unmatched_truth": unmatched,
    }


def evaluate_truth_in_all_lines(
    lines: list[Any], truth: list[dict[str, Any]], tiers: Any
) -> dict[str, Any]:
    """geometry/BPE 전에 정답 제목이 어느 global font tier에 있는지 확인한다."""

    by_page: dict[int, list[Any]] = defaultdict(list)
    for line in lines:
        by_page[line.pdf_page].append(line)
    matched_tiers: Counter[int] = Counter()
    matched = 0
    for entry in truth:
        best_line = None
        best_score = -1.0
        for line in by_page.get(entry["pdf_page"], []):
            truth_title = normalize_title(entry["title"])
            line_title = normalize_title(line.text)
            if truth_title and (truth_title in line_title or line_title in truth_title):
                score = 100.0
            else:
                score = 100.0 * SequenceMatcher(None, truth_title, line_title).ratio()
            if score > best_score:
                best_line = line
                best_score = score
        if best_line is not None and best_score >= TITLE_MATCH_THRESHOLD:
            matched += 1
            matched_tiers[assign_tier(best_line.font_size, tiers.cut_points)] += 1
    return {
        "truth_count": len(truth),
        "matched_line_count": matched,
        "line_recall": round(matched / len(truth), 4) if truth else 0.0,
        "matched_font_tier_counts": dict(sorted(matched_tiers.items())),
    }


def evaluate(
    items: list[PositionedHeading], truth: list[dict[str, Any]], tolerance: float
) -> dict[str, Any]:
    selected, clusters = select_repeated(items, tolerance)
    pairs = run_stack(selected)
    truth_eval = evaluate_truth(pairs, truth)
    return {
        "position_tolerance_line_heights": tolerance,
        "candidate_count": len(selected),
        "retention_ratio": round(len(selected) / len(items), 4) if items else 0.0,
        "tier_counts": dict(
            sorted(Counter(item.heading.tier for item in selected).items())
        ),
        "level_counts": dict(sorted(Counter(level for _, level in pairs).items())),
        "accepted_cluster_count": sum(report["accepted"] for report in clusters),
        "truth_evaluation": truth_eval,
        "accepted_clusters": [report for report in clusters if report["accepted"]],
        "tree_preview": [
            {
                "level": level,
                "page": item.heading.pdf_page,
                "tier": item.heading.tier,
                "title": item.heading.title,
            }
            for item, level in pairs[:80]
        ],
    }


def record_experiment(summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    compact = {
        "initial_candidate_count": summary["initial_candidate_count"],
        "coordinate_lookup_miss_count": summary["coordinate_lookup_miss_count"],
        "normalization": summary["normalization"],
        "all_line_truth_evaluation": summary["all_line_truth_evaluation"],
        "comparison": summary["comparison"],
        "best_ratio": summary["best_ratio"],
        "finding": summary["finding"],
    }
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": "절대 pt 없이 page-relative top-left와 문서 중앙 line-height 단위로 geometry 반복 조건을 만들고 font tier stack bookmark의 recall과 level 정확도를 실제 bookmark 57개에 대해 검증한다.",
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": "BPE merge 첫 line의 top-left를 page width/height로 정규화한 뒤, 전체 heading 후보의 median line-height를 1 geometry unit으로 정의했다. 같은 font tier에서 cluster 전체 x/y 폭이 0.25/0.5/1.0 line-height 이내이고 2개 이상 page에 반복되는 후보만 tier stack에 넣었다.",
        "summary": compact,
        "finding": summary["finding"],
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"] = [
        item for item in data["experiments"] if item.get("id") != EXPERIMENT_ID
    ] + [entry]
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = TypographyConfig()
    raw_lines = extract_typography_lines(INPUT_PDF, config)
    lines = exclude_margin_artifacts(raw_lines, config)
    tiers = compute_tier_set(lines, "font_size", config)
    headings = extract_bpe_headings(lines, tiers, config)
    positioned, misses, normalization = attach_normalized_top_left(headings, lines)
    truth = load_truth()
    all_line_truth = evaluate_truth_in_all_lines(lines, truth, tiers)
    results = [evaluate(positioned, truth, ratio) for ratio in POSITION_HEIGHT_RATIOS]
    comparison = [
        {
            "ratio": result["position_tolerance_line_heights"],
            "candidates": result["candidate_count"],
            "retention": result["retention_ratio"],
            "levels": result["level_counts"],
            "recall": result["truth_evaluation"]["recall"],
            "level_accuracy": result["truth_evaluation"]["level_accuracy_on_matched"],
        }
        for result in results
    ]
    best = max(
        results,
        key=lambda result: (
            result["truth_evaluation"]["level_correct_count"],
            result["truth_evaluation"]["matched_truth_count"],
            -result["candidate_count"],
        ),
    )
    finding = (
        f"초기 BPE 후보 {len(positioned)}개와 bookmark 정답 {len(truth)}개를 비교했다. "
        f"전체 visual line에서는 {all_line_truth['matched_line_count']}/{len(truth)}개 제목을 찾았고 "
        f"그 font tier 분포는 {all_line_truth['matched_font_tier_counts']}이다. "
        f"정규화 geometry 결과는 {comparison}이다. 정답 level을 가장 많이 맞힌 설정은 "
        f"{best['position_tolerance_line_heights']} line-height이며 candidate={best['candidate_count']}, "
        f"recall={best['truth_evaluation']['recall']}, matched-level-accuracy={best['truth_evaluation']['level_accuracy_on_matched']}이다."
    )
    summary = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "raw_line_count": len(raw_lines),
        "filtered_line_count": len(lines),
        "font_tier_count": len(tiers.tiers),
        "initial_candidate_count": len(positioned),
        "coordinate_lookup_miss_count": misses,
        "truth_bookmark_count": len(truth),
        "all_line_truth_evaluation": all_line_truth,
        "normalization": normalization,
        "comparison": comparison,
        "best_ratio": best["position_tolerance_line_heights"],
        "results": results,
        "finding": finding,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_experiment(summary)
    print(
        json.dumps(
            {"comparison": comparison, "finding": finding}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
