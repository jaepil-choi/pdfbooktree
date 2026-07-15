"""experiment 098: OCR chapter를 position support와 isolation으로 복구한다.

통계학원론 OCR overlay에서 chapter 제목 font가 본문 font profile에 흡수될 때,
font 조건 없이 position 반복 강도와 cluster isolation으로 chapter를 복구할 수
있는지 검증한다.

실행:
    uv run python experiments/098_ocr_position_chapter_rescue.py
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
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
EXPERIMENT_ID = "098_ocr_position_chapter_rescue"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
OCR_DIR = ROOT_DIR / "showcase" / "outputs" / "018_statistics_principles_ocr_overlay"
INPUT_PDF = OCR_DIR / "statistics_principles_ocr.pdf"
OCR_LINE_STATS = OCR_DIR / "ocr_line_stats.jsonl"

BODY_TEXT_COVERAGE = 0.95
POSITION_TOLERANCE = 1.0
TOC_END_PAGE = 11
CHAPTER_COUNT = 11
SUPPORT_THRESHOLDS = [2, 3, 5, 8, 10, 11]
ISOLATION_QUANTILES = [0.0, 0.5, 0.75, 0.9, 0.95, 0.99]
CURRENT_ANCHOR_TOLERANCES = [0.5, 1.0, 1.5, 2.0]
CHAPTER_PATTERN = re.compile(r"^\s*제\s*(\d+)\s*장\b")
CHAPTER_ANYWHERE_PATTERN = re.compile(r"제\s*(\d+)\s*장\b")


@dataclass(frozen=True)
class CurrentAnchor:
    """다음 chunk layout을 제외한 현재 chapter anchor 좌표다."""

    current: Any
    values: tuple[float, float]


def display_text(text: str) -> str:
    """PDF overlay의 CP949 mojibake를 가능할 때 복원한다."""

    try:
        return text.encode("latin1").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def load_chapter_truth() -> list[dict[str, Any]]:
    """OCR line stats에서 목차 이후 각 제N장의 최초 출현을 정답으로 읽는다."""

    first: dict[int, dict[str, Any]] = {}
    with OCR_LINE_STATS.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            normalized = row["text"].replace("|", " ").replace("I", " ")
            match = CHAPTER_PATTERN.search(normalized)
            if match is None:
                continue
            chapter = int(match.group(1))
            if not 1 <= chapter <= CHAPTER_COUNT or row["pdf_page"] <= TOC_END_PAGE:
                continue
            candidate = {
                "chapter": chapter,
                "pdf_page": int(row["pdf_page"]),
                "text": row["text"],
                "category": row["category"],
                "source_font_size": row["inserted_font_size_median_pt"],
                "x0": float(row["x0_pt"]),
                "y0": float(row["y0_pt"]),
                "x1": float(row["x1_pt"]),
                "y1": float(row["y1_pt"]),
            }
            current = first.get(chapter)
            if current is None or (candidate["pdf_page"], candidate["y0"]) < (
                current["pdf_page"],
                current["y0"],
            ):
                first[chapter] = candidate
    missing = sorted(set(range(1, CHAPTER_COUNT + 1)) - set(first))
    if missing:
        raise RuntimeError(f"OCR chapter 정답을 찾지 못했다: {missing}")
    return [first[number] for number in sorted(first)]


def cluster_statistics(clusters: list[list[Any]]) -> list[dict[str, Any]]:
    """cluster별 page support, 내부 지름, 최근접 cluster 고립도를 계산한다."""

    stats = []
    for cluster_id, cluster in enumerate(clusters, start=1):
        values = np.asarray([pattern.values for pattern in cluster], dtype=float)
        center = np.median(values, axis=0)
        radius = float(np.max(np.abs(values - center)))
        stats.append(
            {
                "cluster_id": cluster_id,
                "cluster": cluster,
                "center": center,
                "radius": radius,
                "diameter": float(np.max(np.ptp(values, axis=0))),
                "support_pages": len({pattern.current.pdf_page for pattern in cluster}),
                "pattern_count": len(cluster),
            }
        )

    centers = np.asarray([stat["center"] for stat in stats], dtype=float)
    radii = np.asarray([stat["radius"] for stat in stats], dtype=float)
    for index, stat in enumerate(stats):
        if len(stats) <= 1:
            nearest_index = None
            nearest_distance = 0.0
            margin = 0.0
        else:
            distances = np.max(np.abs(centers - centers[index]), axis=1)
            distances[index] = math.inf
            nearest_index = int(np.argmin(distances))
            nearest_distance = float(distances[nearest_index])
            margin = nearest_distance - radii[index] - radii[nearest_index]
        stat["nearest_cluster_id"] = (
            stats[nearest_index]["cluster_id"] if nearest_index is not None else None
        )
        stat["nearest_center_distance"] = nearest_distance
        stat["separation_margin"] = float(margin)
        stat["isolation_ratio"] = (
            nearest_distance / max(float(stat["diameter"]), 0.05)
            if nearest_index is not None
            else 0.0
        )
    return stats


def map_truth_to_chunks(
    truth: list[dict[str, Any]], chunks: list[Any], body_spacing: float
) -> tuple[set[int], list[dict[str, Any]]]:
    """OCR 원본 anchor와 같은 page에서 가장 가까운 production chunk를 연결한다."""

    by_page: dict[int, list[Any]] = {}
    for chunk in chunks:
        by_page.setdefault(chunk.pdf_page, []).append(chunk)

    positive_ids: set[int] = set()
    matches = []
    for entry in truth:
        page_chunks = by_page.get(entry["pdf_page"], [])
        if not page_chunks:
            raise RuntimeError(f"chapter page에 production chunk가 없다: {entry}")
        chunk = min(
            page_chunks,
            key=lambda item: max(
                abs(item.x0 - entry["x0"]), abs(item.y0 - entry["y0"])
            ),
        )
        distance = max(abs(chunk.x0 - entry["x0"]), abs(chunk.y0 - entry["y0"]))
        positive_ids.add(chunk.chunk_id)
        matches.append(
            {
                **entry,
                "chunk_id": chunk.chunk_id,
                "chunk_text": display_text(chunk.text),
                "chunk_font_size": round(float(chunk.font_size), 4),
                "anchor_distance_points": round(distance, 4),
                "anchor_distance_line_spacings": round(
                    distance / body_spacing if body_spacing else 0.0, 4
                ),
            }
        )
    if len(positive_ids) != len(truth):
        raise RuntimeError("서로 다른 chapter가 같은 production chunk에 연결됐다.")
    return positive_ids, matches


def build_rows(
    chunks: list[Any],
    font_tiers: Any,
    profile: Any,
    positive_ids: set[int],
    cluster_stats: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """모든 chunk에 font membership과 position confidence를 붙인다."""

    stats_by_chunk = {
        pattern.current.chunk_id: stat
        for stat in cluster_stats
        for pattern in stat["cluster"]
    }
    rows = []
    for chunk in chunks:
        tier = _tier_for_size(chunk.font_size, font_tiers)
        stat = stats_by_chunk.get(chunk.chunk_id)
        support = int(stat["support_pages"]) if stat else 0
        isolation = (
            float(stat["isolation_ratio"]) if stat is not None and support >= 2 else 0.0
        )
        rows.append(
            {
                "chunk_id": chunk.chunk_id,
                "pdf_page": chunk.pdf_page,
                "text": display_text(chunk.text),
                "font_size": float(chunk.font_size),
                "font_ratio": (
                    float(chunk.font_size) / profile.representative_body_font_size
                    if profile.representative_body_font_size
                    else 0.0
                ),
                "font_tier": tier,
                "font_candidate": tier in profile.candidate_tiers,
                "body_font_tier": tier in profile.body_tiers,
                "is_chapter": chunk.chunk_id in positive_ids,
                "cluster_id": stat["cluster_id"] if stat else None,
                "support_pages": support,
                "pattern_count": int(stat["pattern_count"]) if stat else 0,
                "intra_diameter": float(stat["diameter"]) if stat else 0.0,
                "nearest_center_distance": (
                    float(stat["nearest_center_distance"]) if stat else 0.0
                ),
                "separation_margin": (
                    float(stat["separation_margin"]) if stat else 0.0
                ),
                "isolation_ratio": isolation,
            }
        )
    return rows


def evaluate_ids(
    name: str,
    rows: list[dict[str, Any]],
    selected_ids: set[int],
    truth_count: int,
) -> dict[str, Any]:
    """chapter만 양성으로 본 후보 집합의 precision/recall을 계산한다."""

    selected = [row for row in rows if row["chunk_id"] in selected_ids]
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
            {
                "pdf_page": row["pdf_page"],
                "text": row["text"][:120],
                "support_pages": row["support_pages"],
                "isolation_ratio": round(row["isolation_ratio"], 4),
            }
            for row in selected
            if not row["is_chapter"]
        ][:20],
    }


def rank_percentiles(rows: list[dict[str, Any]], key: str) -> dict[int, float]:
    """동점에 같은 점수를 주는 0~1 percentile rank를 만든다."""

    unique = sorted({float(row[key]) for row in rows})
    if len(unique) <= 1:
        return {row["chunk_id"]: 0.0 for row in rows}
    by_value = {value: index / (len(unique) - 1) for index, value in enumerate(unique)}
    return {row["chunk_id"]: by_value[float(row[key])] for row in rows}


def ranking_metrics(
    name: str,
    rows: list[dict[str, Any]],
    scores: dict[int, float],
    truth_count: int,
) -> dict[str, Any]:
    """AUC, average precision, precision@chapter-count를 계산한다."""

    ordered = sorted(
        rows,
        key=lambda row: (scores[row["chunk_id"]], -row["pdf_page"]),
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
                "text": row["text"][:100],
                "is_chapter": row["is_chapter"],
                "score": round(scores[row["chunk_id"]], 4),
            }
            for row in top
        ],
    }


def build_rankings(
    rows: list[dict[str, Any]], truth_count: int
) -> list[dict[str, Any]]:
    """font와 position 신호의 chapter ranking 성능을 비교한다."""

    font = rank_percentiles(rows, "font_ratio")
    support = rank_percentiles(rows, "support_pages")
    isolation = rank_percentiles(rows, "isolation_ratio")
    scores = {
        "font_size": font,
        "repeat_support": support,
        "position_isolation": isolation,
        "support_plus_isolation": {
            row["chunk_id"]: support[row["chunk_id"]] + isolation[row["chunk_id"]]
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
        ranking_metrics(name, rows, score, truth_count)
        for name, score in scores.items()
    ]


def build_filter_sweep(
    rows: list[dict[str, Any]], truth_count: int
) -> list[dict[str, Any]]:
    """font 조건 없이 support와 isolation만으로 chapter 후보를 거른다."""

    results = []
    for support in SUPPORT_THRESHOLDS:
        supported = [row for row in rows if row["support_pages"] >= support]
        isolation_values = [row["isolation_ratio"] for row in supported]
        for quantile in ISOLATION_QUANTILES:
            threshold = (
                float(np.quantile(isolation_values, quantile))
                if isolation_values
                else 0.0
            )
            selected_ids = {
                row["chunk_id"]
                for row in supported
                if row["isolation_ratio"] >= threshold
            }
            metric = evaluate_ids(
                f"position_support_{support}_isolation_q{quantile:g}",
                rows,
                selected_ids,
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


def analyze_position_mode(
    mode: str,
    tolerance: float,
    clusters: list[list[Any]],
    chunks: list[Any],
    font_tiers: Any,
    profile: Any,
    positive_ids: set[int],
    truth_count: int,
) -> dict[str, Any]:
    """한 position representation의 min5, ranking, hard-filter를 평가한다."""

    stats = cluster_statistics(clusters)
    rows = build_rows(chunks, font_tiers, profile, positive_ids, stats)
    min5_ids = {row["chunk_id"] for row in rows if row["support_pages"] >= 5}
    min5 = evaluate_ids(f"{mode}_min5", rows, min5_ids, truth_count)
    min5.update({"pattern_mode": mode, "position_tolerance": tolerance})
    rankings = build_rankings(rows, truth_count)
    for ranking in rankings:
        ranking["name"] = f"{mode}_{ranking['name']}"
        ranking["pattern_mode"] = mode
        ranking["position_tolerance"] = tolerance
    filters = build_filter_sweep(rows, truth_count)
    for metric in filters:
        metric["pattern_mode"] = mode
        metric["position_tolerance"] = tolerance
        metric["name"] = f"{mode}_{metric['name']}"
    best_filter = max(
        filters,
        key=lambda row: (row["f1"], row["precision"], row["recall"]),
    )
    return {
        "pattern_mode": mode,
        "position_tolerance": tolerance,
        "cluster_count": len(clusters),
        "rows": rows,
        "stats": stats,
        "min5": min5,
        "rankings": rankings,
        "filters": filters,
        "best_filter": best_filter,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """검토 가능한 UTF-8 BOM CSV를 저장한다."""

    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def compact_metric(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in ("false_positive_preview", "chapter_pages", "top_preview")
    }


def record_experiment(summary: dict[str, Any]) -> None:
    """실험 registry에 판단에 필요한 압축 결과만 기록한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "통계학원론 OCR overlay에서 chapter font가 본문 font tier에 흡수될 때, "
            "font 조건 없이 position 반복 강도와 cluster isolation으로 chapter를 "
            "복구할 수 있는지 검증한다."
        ),
        "inputs": [
            str(INPUT_PDF.relative_to(ROOT_DIR)),
            str(OCR_LINE_STATS.relative_to(ROOT_DIR)),
        ],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "OCR 원본 line stats에서 목차 이후 제1장~제11장의 최초 출현 좌표를 "
            "독립 정답으로 만들고 production geometry chunk에 같은-page anchor "
            "거리로 연결했다. 모든 chunk의 font tier membership, distinct-page "
            "support, L-inf cluster diameter, 최근접 cluster isolation을 계산했다. "
            "font-only, position min5, 기존 position AND font, position-only "
            "ranking과 support/isolation hard-filter sweep을 비교했다."
        ),
        "summary": {
            "chapter_truth_count": summary["chapter_truth_count"],
            "chapter_pages": summary["chapter_pages"],
            "body_font_size": summary["body_font_size"],
            "body_line_spacing": summary["body_line_spacing"],
            "chapter_font_candidate_count": summary["chapter_font_candidate_count"],
            "font_missed_chapter_count": summary["font_missed_chapter_count"],
            "position_min5_rescued_count": summary["position_min5_rescued_count"],
            "current_4d_position_min5_rescued_count": summary[
                "current_4d_position_min5_rescued_count"
            ],
            "best_position_mode": summary["best_position_mode"],
            "position_mode_comparison": summary["position_mode_comparison"],
            "primary_cluster_audit": summary["primary_cluster_audit"],
            "chapter_profiles": summary["chapter_profiles"],
            "baselines": [compact_metric(row) for row in summary["baselines"]],
            "rankings": [compact_metric(row) for row in summary["rankings"]],
            "best_position_filter": compact_metric(summary["best_position_filter"]),
            "best_filter_selection_scope": "same_book_exploratory",
            "finding": summary["finding"],
        },
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

    truth = load_chapter_truth()
    positive_ids, truth_matches = map_truth_to_chunks(truth, chunks, body_spacing)
    current_clusters = _cluster_patterns(patterns, tolerance=POSITION_TOLERANCE)
    modes = [
        analyze_position_mode(
            "current_following_anchor_4d",
            POSITION_TOLERANCE,
            current_clusters,
            chunks,
            font_tiers,
            profile,
            positive_ids,
            len(truth),
        )
    ]
    current_anchors = [
        CurrentAnchor(current=pattern.current, values=pattern.values[:2])
        for pattern in patterns
    ]
    for tolerance in CURRENT_ANCHOR_TOLERANCES:
        modes.append(
            analyze_position_mode(
                "current_anchor_2d",
                tolerance,
                _cluster_patterns(current_anchors, tolerance=tolerance),
                chunks,
                font_tiers,
                profile,
                positive_ids,
                len(truth),
            )
        )

    current_mode = modes[0]
    best_mode = max(
        modes,
        key=lambda mode: (
            mode["best_filter"]["f1"],
            mode["best_filter"]["precision"],
            mode["min5"]["recall"],
        ),
    )
    current_rows = current_mode["rows"]
    best_rows = best_mode["rows"]
    current_by_id = {row["chunk_id"]: row for row in current_rows}
    best_by_id = {row["chunk_id"]: row for row in best_rows}
    font_ids = {row["chunk_id"] for row in current_rows if row["font_candidate"]}
    current_min5_ids = {
        row["chunk_id"] for row in current_rows if row["support_pages"] >= 5
    }
    best_min5_ids = {row["chunk_id"] for row in best_rows if row["support_pages"] >= 5}
    current_and_ids = font_ids & current_min5_ids

    baselines = [
        evaluate_ids("font_only", current_rows, font_ids, len(truth)),
        current_mode["min5"],
        evaluate_ids(
            "position_and_font_min5",
            current_rows,
            current_and_ids,
            len(truth),
        ),
        best_mode["min5"],
    ]
    rankings = [ranking for mode in modes for ranking in mode["rankings"]]
    filter_sweep = [metric for mode in modes for metric in mode["filters"]]
    best_position_filter = max(
        filter_sweep,
        key=lambda row: (row["f1"], row["precision"], row["recall"]),
    )
    best_ranking = max(
        rankings,
        key=lambda row: (
            row["average_precision"],
            row["precision_at_chapter_count"],
        ),
    )

    chapter_profiles = []
    for match in truth_matches:
        current = current_by_id[match["chunk_id"]]
        best = best_by_id[match["chunk_id"]]
        chapter_profiles.append(
            {
                "chapter": match["chapter"],
                "pdf_page": match["pdf_page"],
                "source_text": match["text"],
                "chunk_text": match["chunk_text"],
                "source_font_size": round(float(match["source_font_size"]), 4),
                "chunk_font_size": current["font_size"],
                "font_ratio": round(current["font_ratio"], 4),
                "font_tier": current["font_tier"],
                "font_candidate": current["font_candidate"],
                "body_font_tier": current["body_font_tier"],
                "current_4d_cluster_id": current["cluster_id"],
                "current_4d_support_pages": current["support_pages"],
                "current_4d_isolation_ratio": round(current["isolation_ratio"], 4),
                "best_pattern_mode": best_mode["pattern_mode"],
                "best_position_tolerance": best_mode["position_tolerance"],
                "best_cluster_id": best["cluster_id"],
                "best_support_pages": best["support_pages"],
                "best_intra_diameter": round(best["intra_diameter"], 4),
                "best_nearest_center_distance": round(
                    best["nearest_center_distance"], 4
                ),
                "best_isolation_ratio": round(best["isolation_ratio"], 4),
                "anchor_distance_line_spacings": match["anchor_distance_line_spacings"],
            }
        )

    font_missed = positive_ids - font_ids
    current_rescued = font_missed & current_min5_ids
    best_rescued = font_missed & best_min5_ids
    mode_comparison = [
        {
            "pattern_mode": mode["pattern_mode"],
            "position_tolerance": mode["position_tolerance"],
            "cluster_count": mode["cluster_count"],
            "min5": compact_metric(mode["min5"]),
            "best_filter": compact_metric(mode["best_filter"]),
        }
        for mode in modes
    ]
    cluster_ids = {
        int(row["cluster_id"]) for row in best_rows if row["cluster_id"] is not None
    }
    primary_cluster_id = max(
        cluster_ids,
        key=lambda cluster_id: sum(
            bool(row["is_chapter"])
            for row in best_rows
            if row["cluster_id"] is not None and int(row["cluster_id"]) == cluster_id
        ),
    )
    primary_cluster_rows = [
        row
        for row in best_rows
        if row["cluster_id"] is not None
        and int(row["cluster_id"]) == primary_cluster_id
    ]
    audited_chapters = sorted(
        {
            int(match.group(1))
            for row in primary_cluster_rows
            if (match := CHAPTER_ANYWHERE_PATTERN.search(str(row["text"])))
            and 1 <= int(match.group(1)) <= CHAPTER_COUNT
        }
    )
    primary_cluster_audit = {
        "cluster_id": primary_cluster_id,
        "chunk_count": len(primary_cluster_rows),
        "support_pages": int(primary_cluster_rows[0]["support_pages"]),
        "isolation_ratio": round(float(primary_cluster_rows[0]["isolation_ratio"]), 4),
        "independent_truth_match_count": sum(
            bool(row["is_chapter"]) for row in primary_cluster_rows
        ),
        "readable_chapter_marker_count": len(audited_chapters),
        "readable_chapter_numbers": audited_chapters,
        "semantic_precision": round(
            len(audited_chapters) / len(primary_cluster_rows), 4
        ),
        "semantic_recall": round(len(audited_chapters) / CHAPTER_COUNT, 4),
        "false_positive_count": len(primary_cluster_rows) - len(audited_chapters),
        "audit_note": (
            "독립 OCR line stats는 제9장 본문 시작(311쪽)을 정답으로 잡았지만, "
            "production clean chunk에는 직전 310쪽의 복합 줄 "
            "'제 9 장 구간추정'이 실제 chapter marker로 존재한다. 따라서 독립 "
            "정답 일치는 10개지만 readable marker 수동 감사 결과는 11개다."
        ),
    }
    finding = (
        f"chapter truth={len(truth)}, font candidates가 보존한 chapter="
        f"{len(positive_ids & font_ids)}, 놓친 chapter={len(font_missed)}. "
        f"production 4D position min5는 {len(current_rescued)}/"
        f"{len(font_missed)}개를 복구했고, current-anchor 2D "
        f"tolerance={best_mode['position_tolerance']} min5는 "
        f"{len(best_rescued)}/{len(font_missed)}개를 복구했다. "
        f"기존 position AND font min5는 chapter "
        f"{len(positive_ids & current_and_ids)}/{len(truth)}개를 보존했다. "
        f"최적 ranking={best_ranking['name']}, "
        f"AP={best_ranking['average_precision']}, "
        f"P@11={best_ranking['precision_at_chapter_count']}. "
        f"같은 책에서 고른 탐색적 position-only hard filter는 "
        f"mode={best_position_filter['pattern_mode']}, tolerance="
        f"{best_position_filter['position_tolerance']}, support>="
        f"{best_position_filter['minimum_support_pages']}, isolation q="
        f"{best_position_filter['isolation_quantile']}로 precision="
        f"{best_position_filter['precision']}, recall="
        f"{best_position_filter['recall']}, "
        f"F1={best_position_filter['f1']}이다."
        f" 다만 반복 위치 클러스터 자체를 감사하면 {len(primary_cluster_rows)}개 중 "
        f"chapter marker가 {len(audited_chapters)}개로 precision="
        f"{primary_cluster_audit['semantic_precision']}, recall="
        f"{primary_cluster_audit['semantic_recall']}이며 실제 오탐은 1개다."
    )
    with fitz.open(INPUT_PDF) as document:
        page_count = document.page_count
    summary = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "ocr_line_stats": str(OCR_LINE_STATS.relative_to(ROOT_DIR)),
        "page_count": page_count,
        "raw_line_count": len(raw_lines),
        "line_count": len(lines),
        "chunk_count": len(chunks),
        "body_font_size": round(profile.representative_body_font_size, 4),
        "body_line_spacing": round(body_spacing, 4),
        "chapter_truth_count": len(truth),
        "chapter_pages": [entry["pdf_page"] for entry in truth],
        "chapter_matches": truth_matches,
        "chapter_profiles": chapter_profiles,
        "chapter_font_candidate_count": len(positive_ids & font_ids),
        "font_missed_chapter_count": len(font_missed),
        "position_min5_rescued_count": len(best_rescued),
        "current_4d_position_min5_rescued_count": len(current_rescued),
        "best_position_mode": {
            "pattern_mode": best_mode["pattern_mode"],
            "position_tolerance": best_mode["position_tolerance"],
        },
        "position_mode_comparison": mode_comparison,
        "primary_cluster_audit": primary_cluster_audit,
        "support_histogram": dict(
            sorted(
                Counter(
                    int(stat["support_pages"]) for stat in best_mode["stats"]
                ).items()
            )
        ),
        "baselines": baselines,
        "rankings": rankings,
        "position_filter_sweep": filter_sweep,
        "best_position_filter": best_position_filter,
        "best_filter_selection_scope": "same_book_exploratory",
        "finding": finding,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv(
        OUTPUT_DIR / "candidate_features_current_4d.csv",
        current_rows,
    )
    write_csv(
        OUTPUT_DIR / "candidate_features_best_mode.csv",
        best_rows,
    )
    write_csv(
        OUTPUT_DIR / "chapter_profiles.csv",
        chapter_profiles,
    )
    record_experiment(summary)
    print(json.dumps({"finding": finding}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
