"""experiment 097: 반복 강도와 위치 고립도로 chapter 확신을 측정한다.

clean text가 있는 Zvi Bodie Investments PDF의 ``Chapter N:`` bookmark 28개만
정답으로 사용한다. position 신호로 모든 subchapter를 찾으려 하지 않고, font
후보가 chapter급 최상위 제목이라는 확신을 강화할 수 있는지만 평가한다.

실행:
    uv run python experiments/097_position_chapter_confidence.py
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import fitz
import numpy as np

from pdfbooktree.config import TypographyConfig
from pdfbooktree.typography.geometry import (
    _body_spacing_band,
    _build_anchor_patterns,
    _build_chunks,
    _cluster_patterns,
    _merge_adjacent_non_body_chunks,
    _merge_printed_line_fragments,
    _tier_for_size,
    classify_font_tiers_by_text_coverage,
    compute_geometry_font_tier_set,
)
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "097_position_chapter_confidence"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
INPUT_PDF = (
    ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf"
)

BODY_TEXT_COVERAGE = 0.95
POSITION_TOLERANCE = 1.0
MATCH_THRESHOLD = 0.60
SUPPORT_THRESHOLDS = [2, 3, 5, 8, 13, 21]
ISOLATION_QUANTILES = [0.0, 0.25, 0.5, 0.75, 0.9]
CHAPTER_PATTERN = re.compile(r"^Chapter\s+\d+:", re.IGNORECASE)


def normalize_title(text: str) -> str:
    """영문 chapter 제목 비교용으로 구두점과 공백을 정규화한다."""

    return re.sub(r"[^0-9a-z]+", " ", text.casefold()).strip()


def title_score(left: str, right: str) -> float:
    """문자 순서와 token 중복 중 더 강한 제목 일치도를 반환한다."""

    left_norm = normalize_title(left)
    right_norm = normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if min(len(left_norm), len(right_norm)) >= 4 and (
        left_norm in right_norm or right_norm in left_norm
    ):
        return 1.0
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    token_overlap = (
        2.0 * len(left_tokens & right_tokens) / (len(left_tokens) + len(right_tokens))
    )
    return max(sequence, token_overlap)


def load_chapter_truth() -> list[dict[str, Any]]:
    """embedded outline에서 Chapter N 형식의 28개 chapter만 읽는다."""

    with fitz.open(INPUT_PDF) as document:
        return [
            {"level": level, "title": title, "pdf_page": page}
            for level, title, page in document.get_toc()
            if page > 0 and CHAPTER_PATTERN.match(title.strip())
        ]


def match_truth_to_chunks(
    truth: list[dict[str, Any]], chunks: list[Any]
) -> tuple[set[int], list[dict[str, Any]], list[dict[str, Any]]]:
    """같은 page의 제목 일치 chunk 중 chapter급 큰 font를 정답으로 지정한다.

    PDF text reading order가 뒤섞이면 chapter 제목 token이 재배열될 수 있고, 이때
    문자열 유사도만으로는 같은 page의 9.1 같은 subchapter를 더 높게 고를 수 있다.
    먼저 제목 일치 threshold를 통과시킨 뒤 font size와 일치도 순으로 선택한다.
    """

    chunks_by_page: dict[int, list[Any]] = {}
    for chunk in chunks:
        chunks_by_page.setdefault(chunk.pdf_page, []).append(chunk)

    positive_ids: set[int] = set()
    matches: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []
    for entry in truth:
        candidates = chunks_by_page.get(entry["pdf_page"], [])
        scored = [
            (title_score(entry["title"], chunk.text), chunk) for chunk in candidates
        ]
        eligible = [row for row in scored if row[0] >= MATCH_THRESHOLD]
        ranked = sorted(
            eligible,
            key=lambda row: (row[1].font_size, row[0]),
            reverse=True,
        )
        if not ranked:
            best = max(scored, key=lambda row: row[0], default=None)
            misses.append(
                {
                    **entry,
                    "best_score": round(best[0], 4) if best else 0.0,
                    "best_text": best[1].text if best else None,
                }
            )
            continue
        score, chunk = ranked[0]
        positive_ids.add(chunk.chunk_id)
        matches.append(
            {
                **entry,
                "chunk_id": chunk.chunk_id,
                "chunk_text": chunk.text,
                "font_size": round(float(chunk.font_size), 4),
                "score": round(score, 4),
            }
        )
    return positive_ids, matches, misses


def cluster_statistics(clusters: list[list[Any]]) -> list[dict[str, Any]]:
    """반복 support와 다른 position cluster로부터의 고립도를 계산한다."""

    geometries: list[dict[str, Any]] = []
    for cluster_id, cluster in enumerate(clusters, start=1):
        values = np.asarray([pattern.values for pattern in cluster], dtype=float)
        center = np.median(values, axis=0)
        radius = float(np.max(np.abs(values - center)))
        diameter = float(np.max(np.ptp(values, axis=0)))
        geometries.append(
            {
                "cluster_id": cluster_id,
                "cluster": cluster,
                "center": center,
                "radius": radius,
                "diameter": diameter,
                "support_pages": len({pattern.current.pdf_page for pattern in cluster}),
                "pattern_count": len(cluster),
            }
        )

    for geometry in geometries:
        neighbors = []
        for other in geometries:
            if other is geometry:
                continue
            center_distance = float(
                np.max(np.abs(geometry["center"] - other["center"]))
            )
            separation_margin = center_distance - geometry["radius"] - other["radius"]
            neighbors.append((center_distance, separation_margin, other["cluster_id"]))
        nearest = min(neighbors, default=(math.inf, math.inf, None))
        geometry["nearest_center_distance"] = nearest[0]
        geometry["separation_margin"] = nearest[1]
        geometry["nearest_cluster_id"] = nearest[2]
        geometry["isolation_ratio"] = (
            nearest[0] / max(geometry["diameter"], 0.05)
            if math.isfinite(nearest[0])
            else 0.0
        )
    return geometries


def candidate_rows(
    chunks: list[Any],
    font_ids: set[int],
    positive_ids: set[int],
    cluster_stats: list[dict[str, Any]],
    body_font_size: float,
    page_count: int,
) -> list[dict[str, Any]]:
    """font 후보별 반복 강도와 position isolation feature를 만든다."""

    stats_by_chunk: dict[int, dict[str, Any]] = {}
    for stat in cluster_stats:
        for pattern in stat["cluster"]:
            stats_by_chunk[pattern.current.chunk_id] = stat

    rows = []
    for chunk in chunks:
        if chunk.chunk_id not in font_ids:
            continue
        stat = stats_by_chunk.get(chunk.chunk_id)
        support_pages = int(stat["support_pages"]) if stat else 0
        repeated_isolation = (
            float(stat["isolation_ratio"]) if stat and support_pages >= 2 else 0.0
        )
        rows.append(
            {
                "chunk_id": chunk.chunk_id,
                "pdf_page": chunk.pdf_page,
                "text": chunk.text,
                "font_size": float(chunk.font_size),
                "font_ratio": (
                    float(chunk.font_size) / body_font_size if body_font_size else 0.0
                ),
                "is_larger_than_body": float(chunk.font_size) > body_font_size,
                "is_chapter": chunk.chunk_id in positive_ids,
                "cluster_id": stat["cluster_id"] if stat else None,
                "support_pages": support_pages,
                "support_ratio": support_pages / page_count if page_count else 0.0,
                "pattern_count": int(stat["pattern_count"]) if stat else 0,
                "intra_diameter": float(stat["diameter"]) if stat else 0.0,
                "nearest_center_distance": (
                    float(stat["nearest_center_distance"]) if stat else 0.0
                ),
                "separation_margin": (
                    float(stat["separation_margin"]) if stat else 0.0
                ),
                "isolation_ratio": repeated_isolation,
            }
        )
    return rows


def evaluate_selected(
    name: str,
    rows: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    truth_count: int,
) -> dict[str, Any]:
    """chapter만 양성으로 본 precision/recall/F1을 계산한다."""

    true_positive = sum(bool(row["is_chapter"]) for row in selected)
    precision = true_positive / len(selected) if selected else 0.0
    recall = true_positive / truth_count if truth_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "name": name,
        "candidate_count": len(selected),
        "matched_chapters": true_positive,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "chapter_pages": [row["pdf_page"] for row in selected if row["is_chapter"]],
        "false_positive_preview": [
            {"pdf_page": row["pdf_page"], "text": row["text"][:120]}
            for row in selected
            if not row["is_chapter"]
        ][:20],
        "font_candidate_count": len(rows),
    }


def rank_percentiles(rows: list[dict[str, Any]], key: str) -> dict[int, float]:
    """동점에 같은 값을 주는 0~1 percentile rank를 만든다."""

    unique = sorted({float(row[key]) for row in rows})
    if len(unique) <= 1:
        return {row["chunk_id"]: 0.0 for row in rows}
    rank_by_value = {
        value: index / (len(unique) - 1) for index, value in enumerate(unique)
    }
    return {row["chunk_id"]: rank_by_value[float(row[key])] for row in rows}


def ranking_metrics(
    name: str,
    rows: list[dict[str, Any]],
    scores: dict[int, float],
    truth_count: int,
) -> dict[str, Any]:
    """AUC, average precision, precision@chapter-count를 계산한다."""

    ordered = sorted(
        rows,
        key=lambda row: (scores[row["chunk_id"]], row["font_size"]),
        reverse=True,
    )
    positives = [row for row in rows if row["is_chapter"]]
    negatives = [row for row in rows if not row["is_chapter"]]
    pair_score = 0.0
    for positive in positives:
        for negative in negatives:
            left = scores[positive["chunk_id"]]
            right = scores[negative["chunk_id"]]
            pair_score += 1.0 if left > right else 0.5 if left == right else 0.0
    auc = (
        pair_score / (len(positives) * len(negatives))
        if positives and negatives
        else 0.0
    )

    hits = 0
    precisions = []
    for index, row in enumerate(ordered, start=1):
        if row["is_chapter"]:
            hits += 1
            precisions.append(hits / index)
    top = ordered[:truth_count]
    top_hits = sum(bool(row["is_chapter"]) for row in top)
    return {
        "name": name,
        "auc": round(auc, 4),
        "average_precision": round(
            sum(precisions) / truth_count if truth_count else 0.0, 4
        ),
        "precision_at_chapter_count": round(top_hits / len(top), 4) if top else 0.0,
        "recall_at_chapter_count": round(top_hits / truth_count, 4)
        if truth_count
        else 0.0,
        "top_chapter_count": top_hits,
        "top_preview": [
            {
                "pdf_page": row["pdf_page"],
                "text": row["text"][:120],
                "is_chapter": row["is_chapter"],
                "score": round(scores[row["chunk_id"]], 4),
            }
            for row in top[:40]
        ],
    }


def build_rankings(
    rows: list[dict[str, Any]], truth_count: int
) -> list[dict[str, Any]]:
    """font, support, isolation과 결합 순위의 chapter 분리력을 비교한다."""

    font = rank_percentiles(rows, "font_ratio")
    support = rank_percentiles(rows, "support_pages")
    isolation = rank_percentiles(rows, "isolation_ratio")
    score_sets = {
        "font_size": font,
        "repeat_support": support,
        "position_isolation": isolation,
        "font_plus_support": {
            row["chunk_id"]: font[row["chunk_id"]] + support[row["chunk_id"]]
            for row in rows
        },
        "font_plus_isolation": {
            row["chunk_id"]: font[row["chunk_id"]] + isolation[row["chunk_id"]]
            for row in rows
        },
        "font_support_isolation": {
            row["chunk_id"]: font[row["chunk_id"]]
            + support[row["chunk_id"]]
            + isolation[row["chunk_id"]]
            for row in rows
        },
    }
    return [
        ranking_metrics(name, rows, scores, truth_count)
        for name, scores in score_sets.items()
    ]


def build_filter_sweep(
    rows: list[dict[str, Any]], truth_count: int
) -> list[dict[str, Any]]:
    """support 임계값과 isolation 분위수의 hard-filter 결과를 모두 기록한다."""

    results = []
    for support in SUPPORT_THRESHOLDS:
        supported = [
            row
            for row in rows
            if row["is_larger_than_body"] and row["support_pages"] >= support
        ]
        isolation_values = [row["isolation_ratio"] for row in supported]
        for quantile in ISOLATION_QUANTILES:
            threshold = (
                float(np.quantile(isolation_values, quantile))
                if isolation_values
                else 0.0
            )
            selected = [row for row in supported if row["isolation_ratio"] >= threshold]
            metric = evaluate_selected(
                f"large_font_support_{support}_isolation_q{quantile:g}",
                rows,
                selected,
                truth_count,
            )
            metric.update(
                {
                    "minimum_support_pages": support,
                    "isolation_quantile": quantile,
                    "isolation_threshold": round(threshold, 4),
                }
            )
            results.append(metric)
    return results


def write_candidate_csv(rows: list[dict[str, Any]]) -> None:
    """사람이 chapter와 오탐의 feature를 직접 비교할 CSV를 저장한다."""

    fieldnames = list(rows[0]) if rows else []
    with (OUTPUT_DIR / "candidate_features.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def record_experiment(summary: dict[str, Any]) -> None:
    """실험 registry에는 판단에 필요한 압축 결과만 기록한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    compact = {
        "chapter_truth_count": summary["chapter_truth_count"],
        "chapter_match_count": summary["chapter_match_count"],
        "font_candidate_count": summary["font_candidate_count"],
        "body_font_size": summary["body_font_size"],
        "body_line_spacing": summary["body_line_spacing"],
        "cluster_count": summary["cluster_count"],
        "support_histogram": summary["support_histogram"],
        "baselines": [
            {
                key: value
                for key, value in row.items()
                if key not in ("false_positive_preview", "chapter_pages")
            }
            for row in summary["baselines"]
        ],
        "rankings": [
            {key: value for key, value in row.items() if key != "top_preview"}
            for row in summary["rankings"]
        ],
        "best_filter": {
            key: value
            for key, value in summary["best_filter"].items()
            if key not in ("false_positive_preview", "chapter_pages")
        },
        "best_filter_selection_scope": "same_book_exploratory",
        "finding": summary["finding"],
    }
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "clean text Investments의 Chapter N bookmark 28개를 대상으로, font size "
            "후보에 position 반복 강도와 다른 anchor cluster로부터의 isolation을 "
            "추가하면 chapter급 최상위 제목의 확신이 높아지는지 검증한다."
        ),
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "production과 동일한 margin 제거, 95% text coverage font tier, 본문 "
            "line-spacing chunk/anchor를 사용했다. 정답은 embedded outline의 "
            "Chapter N: 형식 28개로 제한했다. cluster별 distinct page support, "
            "L-inf 내부 diameter, 최근접 cluster 중심 거리와 isolation ratio를 "
            "계산해 font-only, support, isolation, 결합 ranking과 hard-filter sweep을 "
            "비교했다. subchapter는 의도적으로 정답에서 제외했다."
        ),
        "summary": compact,
        "finding": summary["finding"],
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    experiments = data["experiments"]
    for index, existing in enumerate(experiments):
        if existing.get("id") == EXPERIMENT_ID:
            experiments[index] = entry
            break
    else:
        experiments.append(entry)
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = TypographyConfig(
        body_font_text_coverage=BODY_TEXT_COVERAGE,
        position_min_repeated_pages=5,
    )
    raw_lines = extract_typography_lines(INPUT_PDF, config)
    lines = exclude_margin_artifacts(raw_lines, config)
    font_tiers = compute_geometry_font_tier_set(lines)
    profile = classify_font_tiers_by_text_coverage(
        lines, font_tiers, BODY_TEXT_COVERAGE
    )
    restored = _merge_printed_line_fragments(lines)
    body_spacing, continuation_upper = _body_spacing_band(restored, font_tiers, profile)
    initial_chunks = _build_chunks(restored, continuation_upper)
    chunks = _merge_adjacent_non_body_chunks(
        initial_chunks, font_tiers, profile, body_spacing
    )
    patterns = _build_anchor_patterns(chunks, body_spacing)
    clusters = _cluster_patterns(patterns, tolerance=POSITION_TOLERANCE)
    cluster_stats = cluster_statistics(clusters)

    font_ids = {
        chunk.chunk_id
        for chunk in chunks
        if _tier_for_size(chunk.font_size, font_tiers) in profile.candidate_tiers
    }
    truth = load_chapter_truth()
    positive_ids, truth_matches, truth_misses = match_truth_to_chunks(truth, chunks)
    with fitz.open(INPUT_PDF) as document:
        page_count = document.page_count
    rows = candidate_rows(
        chunks,
        font_ids,
        positive_ids,
        cluster_stats,
        profile.representative_body_font_size,
        page_count,
    )

    font_only = evaluate_selected("font_only", rows, rows, len(truth))
    large_font = [row for row in rows if row["is_larger_than_body"]]
    large_font_only = evaluate_selected("large_font_only", rows, large_font, len(truth))
    current_min5 = [row for row in rows if row["support_pages"] >= 5]
    current_filter = evaluate_selected(
        "font_and_position_min5", rows, current_min5, len(truth)
    )
    large_min5 = [
        row for row in rows if row["is_larger_than_body"] and row["support_pages"] >= 5
    ]
    chapter_filter = evaluate_selected(
        "large_font_and_position_min5", rows, large_min5, len(truth)
    )
    baselines = [font_only, large_font_only, current_filter, chapter_filter]
    rankings = build_rankings(rows, len(truth))
    filter_sweep = build_filter_sweep(rows, len(truth))
    best_filter = max(
        filter_sweep,
        key=lambda row: (row["f1"], row["precision"], row["recall"]),
    )

    support_histogram = dict(
        sorted(Counter(int(stat["support_pages"]) for stat in cluster_stats).items())
    )
    best_ranking = max(
        rankings,
        key=lambda row: (
            row["average_precision"],
            row["precision_at_chapter_count"],
        ),
    )
    finding = (
        f"chapter truth={len(truth)}, matched chunks={len(positive_ids)}, "
        f"font candidates={len(rows)}. 현재 font+position min5는 "
        f"precision={current_filter['precision']}, recall={current_filter['recall']}, "
        f"F1={current_filter['f1']}; 큰 font로 제한하면 "
        f"precision={chapter_filter['precision']}, recall={chapter_filter['recall']}, "
        f"F1={chapter_filter['f1']}. 최적 ranking={best_ranking['name']}, "
        f"AP={best_ranking['average_precision']}, "
        f"P@28={best_ranking['precision_at_chapter_count']}. 최적 hard filter는 "
        f"support>={best_filter['minimum_support_pages']}, "
        f"isolation q={best_filter['isolation_quantile']}로 "
        f"precision={best_filter['precision']}, recall={best_filter['recall']}, "
        f"F1={best_filter['f1']}이다. 이 hard filter는 같은 책에서 고른 탐색적 "
        f"최적값이며, subchapter는 의도적으로 정답에서 제외했다."
    )
    summary = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "page_count": page_count,
        "raw_line_count": len(raw_lines),
        "line_count": len(lines),
        "chunk_count": len(chunks),
        "cluster_count": len(clusters),
        "body_font_size": round(profile.representative_body_font_size, 4),
        "body_line_spacing": round(body_spacing, 4),
        "position_tolerance_line_spacings": POSITION_TOLERANCE,
        "chapter_truth_count": len(truth),
        "chapter_match_count": len(positive_ids),
        "chapter_matches": truth_matches,
        "chapter_misses": truth_misses,
        "font_candidate_count": len(rows),
        "font_chapter_count": sum(row["is_chapter"] for row in rows),
        "support_histogram": support_histogram,
        "baselines": baselines,
        "rankings": rankings,
        "filter_sweep": filter_sweep,
        "best_filter": best_filter,
        "best_filter_selection_scope": "same_book_exploratory",
        "finding": finding,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_candidate_csv(rows)
    record_experiment(summary)
    print(json.dumps({"finding": finding}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
