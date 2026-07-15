"""experiment 099: 상세 bookmark 책에서 position 후보의 precision을 검증한다.

퀀트의 세계 embedded outline을 정답으로 사용해 position-only 후보가 실제
bookmark인지, 그중에서도 목표인 level 1~2 coarse bookmark인지 분리 평가한다.
recall이나 같은 책에서 고른 최적 임계값은 평가하지 않는다.

실행:
    uv run python experiments/099_quant_position_precision.py
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
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
EXPERIMENT_ID = "099_quant_position_precision"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
INPUT_PDF = ROOT_DIR / "data" / "native-pdf-indexed" / "퀀트의 세계 - 홍창수.pdf"

BODY_TEXT_COVERAGE = 0.95
TITLE_MATCH_THRESHOLD = 0.55


@dataclass(frozen=True)
class CurrentAnchor:
    """following chunk의 배치를 제외한 현재 chunk 위치다."""

    current: Any
    values: tuple[float, float]


def normalize_title(text: str) -> str:
    """한글과 영숫자를 보존하면서 bookmark 제목을 비교 가능하게 만든다."""

    return re.sub(r"[^\w]+", " ", text.casefold(), flags=re.UNICODE).strip()


def title_score(left: str, right: str) -> float:
    """포함 관계, 문자 순서, token 중복 중 가장 강한 제목 일치도를 반환한다."""

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
        if left_tokens and right_tokens
        else 0.0
    )
    return max(sequence, token_overlap)


def load_bookmarks() -> list[dict[str, Any]]:
    """PDF embedded outline의 level, 제목, 1-based page를 읽는다."""

    with fitz.open(INPUT_PDF) as document:
        return [
            {"level": level, "title": title.replace("\n", " "), "pdf_page": page}
            for level, title, page in document.get_toc()
            if page > 0
        ]


def cluster_statistics(clusters: list[list[Any]]) -> list[dict[str, Any]]:
    """반복 위치 cluster의 support, 내부 지름, 최근접 cluster 고립도를 계산한다."""

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
        distances = np.max(np.abs(centers - centers[index]), axis=1)
        distances[index] = math.inf
        nearest_index = int(np.argmin(distances)) if len(stats) > 1 else None
        nearest_distance = (
            float(distances[nearest_index]) if nearest_index is not None else 0.0
        )
        margin = (
            nearest_distance - radii[index] - radii[nearest_index]
            if nearest_index is not None
            else 0.0
        )
        stat["nearest_center_distance"] = nearest_distance
        stat["separation_margin"] = float(margin)
        stat["isolation_ratio"] = (
            nearest_distance / max(float(stat["diameter"]), 0.05)
            if nearest_index is not None
            else 0.0
        )
    return stats


def bookmark_matches(
    chunk: Any, bookmarks_by_page: dict[int, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """같은 page에서 제목 유사도 기준을 넘는 bookmark를 찾는다."""

    matches = []
    for bookmark in bookmarks_by_page.get(chunk.pdf_page, []):
        score = title_score(bookmark["title"], chunk.text)
        if score >= TITLE_MATCH_THRESHOLD:
            matches.append({**bookmark, "score": score})
    return sorted(matches, key=lambda row: (row["score"], -row["level"]), reverse=True)


def build_rows(
    chunks: list[Any],
    font_tiers: Any,
    profile: Any,
    stats: list[dict[str, Any]],
    bookmarks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """각 chunk에 position feature와 detailed/coarse bookmark 정답을 붙인다."""

    stat_by_chunk = {
        pattern.current.chunk_id: stat for stat in stats for pattern in stat["cluster"]
    }
    bookmarks_by_page: dict[int, list[dict[str, Any]]] = {}
    for bookmark in bookmarks:
        bookmarks_by_page.setdefault(bookmark["pdf_page"], []).append(bookmark)

    rows = []
    for chunk in chunks:
        stat = stat_by_chunk.get(chunk.chunk_id)
        matches = bookmark_matches(chunk, bookmarks_by_page)
        coarse_matches = [row for row in matches if row["level"] <= 2]
        best = matches[0] if matches else None
        rows.append(
            {
                "chunk_id": chunk.chunk_id,
                "pdf_page": chunk.pdf_page,
                "text": chunk.text,
                "font_size": round(float(chunk.font_size), 4),
                "font_ratio": round(
                    float(chunk.font_size) / profile.representative_body_font_size, 4
                ),
                "font_tier": _tier_for_size(chunk.font_size, font_tiers),
                "font_candidate": (
                    _tier_for_size(chunk.font_size, font_tiers)
                    in profile.candidate_tiers
                ),
                "cluster_id": stat["cluster_id"] if stat else None,
                "support_pages": int(stat["support_pages"]) if stat else 0,
                "pattern_count": int(stat["pattern_count"]) if stat else 0,
                "intra_diameter": round(float(stat["diameter"]), 4) if stat else 0.0,
                "isolation_ratio": (
                    round(float(stat["isolation_ratio"]), 4) if stat else 0.0
                ),
                "is_any_bookmark": bool(matches),
                "is_coarse_bookmark": bool(coarse_matches),
                "is_detail_only_bookmark": bool(matches) and not coarse_matches,
                "matched_level": best["level"] if best else None,
                "matched_title": best["title"] if best else None,
                "title_score": round(float(best["score"]), 4) if best else 0.0,
            }
        )
    return rows


def evaluate(name: str, selected: list[dict[str, Any]]) -> dict[str, Any]:
    """선택 후보의 detailed/coarse precision만 계산한다."""

    count = len(selected)
    any_hits = sum(bool(row["is_any_bookmark"]) for row in selected)
    coarse_hits = sum(bool(row["is_coarse_bookmark"]) for row in selected)
    detail_only_hits = sum(bool(row["is_detail_only_bookmark"]) for row in selected)
    return {
        "name": name,
        "candidate_count": count,
        "any_bookmark_hits": any_hits,
        "any_bookmark_precision": round(any_hits / count, 4) if count else 0.0,
        "coarse_bookmark_hits": coarse_hits,
        "coarse_bookmark_precision": round(coarse_hits / count, 4) if count else 0.0,
        "detail_only_hits": detail_only_hits,
        "false_positive_count": count - any_hits,
        "candidate_preview": [
            {
                "pdf_page": row["pdf_page"],
                "text": row["text"][:100],
                "matched_level": row["matched_level"],
                "matched_title": row["matched_title"],
            }
            for row in selected[:20]
        ],
    }


def analyze_mode(
    name: str,
    patterns: list[Any],
    tolerance: float,
    chunks: list[Any],
    font_tiers: Any,
    profile: Any,
    bookmarks: list[dict[str, Any]],
) -> dict[str, Any]:
    """고정 position 조건과 font 교집합의 precision을 계산한다."""

    clusters = _cluster_patterns(patterns, tolerance=tolerance)
    stats = cluster_statistics(clusters)
    rows = build_rows(chunks, font_tiers, profile, stats, bookmarks)
    repeated = [row for row in rows if row["support_pages"] >= 3]
    top_cluster_id = max(
        {int(row["cluster_id"]) for row in repeated if row["cluster_id"] is not None},
        key=lambda cluster_id: max(
            row["isolation_ratio"]
            for row in repeated
            if row["cluster_id"] == cluster_id
        ),
    )
    selections = {
        "position_support_3": repeated,
        "position_support_5": [row for row in rows if row["support_pages"] >= 5],
        "position_support_3_isolation_1": [
            row
            for row in rows
            if row["support_pages"] >= 3 and row["isolation_ratio"] >= 1.0
        ],
        "position_support_5_isolation_1": [
            row
            for row in rows
            if row["support_pages"] >= 5 and row["isolation_ratio"] >= 1.0
        ],
        "top_isolated_repeated_cluster": [
            row for row in rows if row["cluster_id"] == top_cluster_id
        ],
    }
    metrics = []
    for selection_name, selected in selections.items():
        metrics.append(evaluate(f"{name}_{selection_name}", selected))
        metrics.append(
            evaluate(
                f"{name}_font_and_{selection_name}",
                [row for row in selected if row["font_candidate"]],
            )
        )

    cluster_audits = []
    for stat in stats:
        if stat["support_pages"] < 3:
            continue
        cluster_rows = [row for row in rows if row["cluster_id"] == stat["cluster_id"]]
        metric = evaluate(f"cluster_{stat['cluster_id']}", cluster_rows)
        cluster_audits.append(
            {
                "cluster_id": stat["cluster_id"],
                "support_pages": stat["support_pages"],
                "isolation_ratio": round(float(stat["isolation_ratio"]), 4),
                **metric,
            }
        )
    cluster_audits.sort(
        key=lambda row: (row["isolation_ratio"], row["support_pages"]), reverse=True
    )
    return {
        "name": name,
        "tolerance": tolerance,
        "cluster_count": len(clusters),
        "rows": rows,
        "metrics": metrics,
        "cluster_audits": cluster_audits,
        "top_cluster_id": top_cluster_id,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """사람이 오탐을 감사할 수 있도록 CSV를 저장한다."""

    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def compact_metric(metric: dict[str, Any]) -> dict[str, Any]:
    """registry에는 preview를 제외한 precision 수치만 남긴다."""

    return {key: value for key, value in metric.items() if key != "candidate_preview"}


def record_experiment(summary: dict[str, Any]) -> None:
    """experiments registry에 precision 중심 결과를 기록한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "상세 embedded bookmark가 있는 퀀트의 세계에서 position-only 후보가 "
            "실제 bookmark인지와 목표인 level 1~2 coarse bookmark인지를 precision으로 "
            "분리 검증한다."
        ),
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "production geometry chunk에 production 4D anchor와 current-anchor 2D를 "
            "각각 적용했다. 같은 page의 embedded outline 제목과 한글 보존 유사도로 "
            "정답을 연결하고, 고정 support/isolation 조건의 all-level bookmark precision과 "
            "level 1~2 coarse bookmark precision만 비교했다. recall과 같은 책에서 고른 "
            "최적 threshold는 사용하지 않았다."
        ),
        "summary": {
            "page_count": summary["page_count"],
            "bookmark_level_counts": summary["bookmark_level_counts"],
            "body_font_size": summary["body_font_size"],
            "body_line_spacing": summary["body_line_spacing"],
            "modes": [
                {
                    "name": mode["name"],
                    "tolerance": mode["tolerance"],
                    "cluster_count": mode["cluster_count"],
                    "metrics": [compact_metric(row) for row in mode["metrics"]],
                    "top_isolation_clusters": [
                        compact_metric(row) for row in mode["cluster_audits"][:10]
                    ],
                }
                for mode in summary["modes"]
            ],
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
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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
    chunks = _merge_adjacent_non_body_chunks(
        _build_chunks(restored, continuation_upper),
        font_tiers,
        profile,
        body_spacing,
    )
    production_patterns = _build_anchor_patterns(chunks, body_spacing)
    current_patterns = [
        CurrentAnchor(pattern.current, pattern.values[:2])
        for pattern in production_patterns
    ]
    bookmarks = load_bookmarks()
    modes = [
        analyze_mode(
            "production_4d",
            production_patterns,
            1.0,
            chunks,
            font_tiers,
            profile,
            bookmarks,
        ),
        analyze_mode(
            "current_anchor_2d",
            current_patterns,
            2.0,
            chunks,
            font_tiers,
            profile,
            bookmarks,
        ),
    ]
    two_dimensional = modes[1]
    top_cluster = two_dimensional["cluster_audits"][0]
    fixed_position = next(
        row
        for row in two_dimensional["metrics"]
        if row["name"] == "current_anchor_2d_position_support_3_isolation_1"
    )
    fixed_and_font = next(
        row
        for row in two_dimensional["metrics"]
        if row["name"] == "current_anchor_2d_font_and_position_support_3_isolation_1"
    )
    finding = (
        f"embedded bookmarks={len(bookmarks)}. current-anchor 2D의 가장 isolated된 "
        f"반복 cluster는 candidates={top_cluster['candidate_count']}, all-level "
        f"bookmark precision={top_cluster['any_bookmark_precision']}이지만 coarse "
        f"level 1~2 precision={top_cluster['coarse_bookmark_precision']}이다. "
        f"고정 support>=3, isolation>=1 position-only는 candidates="
        f"{fixed_position['candidate_count']}, all-level precision="
        f"{fixed_position['any_bookmark_precision']}, coarse precision="
        f"{fixed_position['coarse_bookmark_precision']}; font 교집합도 candidates="
        f"{fixed_and_font['candidate_count']}, all-level precision="
        f"{fixed_and_font['any_bookmark_precision']}, coarse precision="
        f"{fixed_and_font['coarse_bookmark_precision']}이다. 따라서 isolation이 높은 "
        f"반복 위치는 실제 bookmark 확신은 높일 수 있어도 chapter급 level 확신은 "
        f"보장하지 않는다."
    )
    with fitz.open(INPUT_PDF) as document:
        page_count = document.page_count
    summary = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "page_count": page_count,
        "raw_line_count": len(raw_lines),
        "line_count": len(lines),
        "chunk_count": len(chunks),
        "bookmark_count": len(bookmarks),
        "bookmark_level_counts": {
            str(level): sum(row["level"] == level for row in bookmarks)
            for level in sorted({row["level"] for row in bookmarks})
        },
        "body_font_size": round(profile.representative_body_font_size, 4),
        "body_line_spacing": round(body_spacing, 4),
        "modes": modes,
        "finding": finding,
    }
    serializable_summary = {
        **summary,
        "modes": [
            {key: value for key, value in mode.items() if key != "rows"}
            for mode in modes
        ],
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(serializable_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv(OUTPUT_DIR / "candidate_features_2d.csv", two_dimensional["rows"])
    write_csv(
        OUTPUT_DIR / "cluster_precision_2d.csv", two_dimensional["cluster_audits"]
    )
    record_experiment(summary)
    print(json.dumps({"finding": finding}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
