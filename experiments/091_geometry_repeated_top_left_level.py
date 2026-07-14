"""experiment 091: 여러 페이지에 반복되는 top-left geometry만 level로 인정한다.

090까지 font tier만으로 heading 후보를 고르면 수식과 figure 조각도 우연히 큰
font size를 가져 level을 오염시켰다. 이번 실험은 body와 다른 font tier라는 기존
조건에 더해, 같은 tier의 BPE heading이 여러 페이지에서 같은 top-left 위치에
반복될 때만 level 후보로 인정한다.

BPE 병합 결과의 대표 위치는 첫 조각의 top-left다. 현재 ``BpeHeading``은 y0만
보존하므로, (pdf_page, y0)로 원본 visual line을 역참조해 첫 조각의 x0를 복원한다.
실제 OCR 좌표 흔들림의 영향을 보기 위해 0/1/2/4/8pt 허용오차를 비교한다.

실행:
    uv run python experiments/091_geometry_repeated_top_left_level.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree.config import TypographyConfig
from pdfbooktree.typography.bpe import BpeHeading, extract_bpe_headings
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts
from pdfbooktree.typography.tiers import compute_tier_set

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "091_geometry_repeated_top_left_level"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
INPUT_PDF = (
    ROOT_DIR
    / "showcase"
    / "outputs"
    / "011_heading_line_merge_live"
    / "Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance]_bookmarked.pdf"
)

POSITION_TOLERANCES = [0.0, 1.0, 2.0, 4.0, 8.0]
MIN_DISTINCT_PAGES = 2
KNOWN_REAL_HEADINGS = [
    "The Investment Environment",
    "1.1 Real Assets versus Financial Assets",
    "1.2 Financial Assets",
    "1.3 Financial Markets and the Economy",
    "1.4 The Investment Process",
]


@dataclass(frozen=True)
class PositionedHeading:
    """BPE heading에 첫 조각의 top-left 좌표를 붙인 실험용 레코드다."""

    heading: BpeHeading
    x0: float
    y0: float


def attach_first_top_left(
    headings: list[BpeHeading], lines: list[Any]
) -> tuple[list[PositionedHeading], list[dict[str, Any]]]:
    """BPE가 보존한 첫 y0로 원본 첫 line의 x0를 복원한다."""

    by_page_y: dict[tuple[int, float], list[Any]] = defaultdict(list)
    for line in lines:
        by_page_y[(line.pdf_page, line.y0)].append(line)

    positioned: list[PositionedHeading] = []
    misses: list[dict[str, Any]] = []
    for heading in headings:
        matches = by_page_y.get((heading.pdf_page, heading.y0), [])
        if not matches:
            misses.append(
                {"pdf_page": heading.pdf_page, "y0": heading.y0, "title": heading.title}
            )
            continue
        first = min(matches, key=lambda line: line.x0)
        positioned.append(PositionedHeading(heading=heading, x0=first.x0, y0=first.y0))
    return positioned, misses


def position_clusters(
    items: list[PositionedHeading], tolerance: float
) -> list[list[PositionedHeading]]:
    """같은 tier에서 고정 대표 top-left와 허용오차 이내인 묶음을 만든다.

    연결 성분을 쓰면 작은 좌표 차이가 사슬처럼 이어져 서로 멀리 떨어진 위치까지
    같은 cluster가 될 수 있다. 각 cluster의 첫 좌표를 대표점으로 고정해 이 전이를
    금지한다.
    """

    clusters: list[list[PositionedHeading]] = []
    by_tier: dict[int, list[PositionedHeading]] = defaultdict(list)
    for item in items:
        by_tier[item.heading.tier].append(item)

    for tier_items in by_tier.values():
        tier_clusters: list[list[PositionedHeading]] = []
        ordered = sorted(
            tier_items, key=lambda item: (item.x0, item.y0, item.heading.pdf_page)
        )
        for item in ordered:
            target = next(
                (
                    cluster
                    for cluster in tier_clusters
                    if max(member.x0 for member in cluster + [item])
                    - min(member.x0 for member in cluster + [item])
                    <= tolerance
                    and max(member.y0 for member in cluster + [item])
                    - min(member.y0 for member in cluster + [item])
                    <= tolerance
                ),
                None,
            )
            if target is None:
                tier_clusters.append([item])
            else:
                target.append(item)
        clusters.extend(tier_clusters)
    return clusters


def select_repeated_positions(
    items: list[PositionedHeading], tolerance: float
) -> tuple[list[PositionedHeading], list[dict[str, Any]]]:
    """두 페이지 이상에서 반복되는 위치 cluster에 속한 후보만 남긴다."""

    accepted: list[PositionedHeading] = []
    reports: list[dict[str, Any]] = []
    for cluster_id, cluster in enumerate(position_clusters(items, tolerance), start=1):
        pages = sorted({item.heading.pdf_page for item in cluster})
        keep = len(pages) >= MIN_DISTINCT_PAGES
        if keep:
            accepted.extend(cluster)
        xs = [item.x0 for item in cluster]
        ys = [item.y0 for item in cluster]
        reports.append(
            {
                "cluster_id": cluster_id,
                "tier": cluster[0].heading.tier,
                "count": len(cluster),
                "distinct_pages": len(pages),
                "pages_preview": pages[:20],
                "x0_range": [round(min(xs), 2), round(max(xs), 2)],
                "y0_range": [round(min(ys), 2), round(max(ys), 2)],
                "accepted": keep,
                "title_preview": [item.heading.title for item in cluster[:8]],
            }
        )
    accepted.sort(key=lambda item: (item.heading.pdf_page, item.y0, item.x0))
    reports.sort(
        key=lambda item: (
            not item["accepted"],
            -item["distinct_pages"],
            item["tier"],
            item["cluster_id"],
        )
    )
    return accepted, reports


def run_stack(items: list[PositionedHeading]) -> list[tuple[PositionedHeading, int]]:
    """geometry filter 뒤 기존 tier stack으로 level을 부여한다."""

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


def anchor_hits(items: list[PositionedHeading]) -> list[dict[str, Any]]:
    """기존 실험에서 확인한 실제 제목 anchor가 남는지 본다."""

    result = []
    for anchor in KNOWN_REAL_HEADINGS:
        matches = [item for item in items if anchor in item.heading.title]
        result.append(
            {
                "anchor": anchor,
                "match_count": len(matches),
                "matches": [
                    {
                        "pdf_page": item.heading.pdf_page,
                        "tier": item.heading.tier,
                        "x0": item.x0,
                        "y0": item.y0,
                        "title": item.heading.title,
                    }
                    for item in matches[:5]
                ],
            }
        )
    return result


def evaluate(items: list[PositionedHeading], tolerance: float) -> dict[str, Any]:
    selected, clusters = select_repeated_positions(items, tolerance)
    stack = run_stack(selected)
    level_counts = Counter(level for _, level in stack)
    page_counts = Counter(item.heading.pdf_page for item in selected)
    return {
        "position_tolerance_pt": tolerance,
        "candidate_count": len(selected),
        "retention_ratio": round(len(selected) / len(items), 4) if items else 0.0,
        "distinct_pages": len(page_counts),
        "max_candidates_on_one_page": max(page_counts.values(), default=0),
        "tier_counts": dict(
            sorted(Counter(item.heading.tier for item in selected).items())
        ),
        "level_counts": dict(sorted(level_counts.items())),
        "anchor_hits": anchor_hits(selected),
        "accepted_cluster_count": sum(cluster["accepted"] for cluster in clusters),
        "accepted_clusters": [cluster for cluster in clusters if cluster["accepted"]],
        "tree_preview": [
            {
                "level": level,
                "pdf_page": item.heading.pdf_page,
                "tier": item.heading.tier,
                "x0": item.x0,
                "y0": item.y0,
                "merged_line_count": item.heading.merged_line_count,
                "title": item.heading.title,
            }
            for item, level in stack[:80]
        ],
    }


def record_experiment(summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    record_summary = {
        "initial_bpe_heading_count": summary["initial_bpe_heading_count"],
        "positioned_heading_count": summary["positioned_heading_count"],
        "coordinate_lookup_miss_count": summary["coordinate_lookup_miss_count"],
        "minimum_distinct_pages": summary["minimum_distinct_pages"],
        "comparison": summary["comparison"],
        "recommended_tolerance_pt": summary["recommended_tolerance_pt"],
        "finding": summary["finding"],
    }
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "font tier만으로 level 후보를 고를 때 equation/figure의 무작위 큰 글씨가 "
            "섞이는 문제를 줄이기 위해, 여러 페이지에서 같은 top-left 위치가 반복되는 "
            "font tier만 level로 인정하는 geometry rule을 검증한다."
        ),
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "showcase 011의 실제 Zvi Bodie 교재 PDF에서 기존 typography line, margin "
            "제거, font tier, BPE "
            "추출을 그대로 수행했다. BPE 결과는 병합 첫 조각의 y0를 보존하므로 원본 "
            "line을 (page,y0)로 역참조해 첫 조각 x0를 복원했다. 같은 font tier이면서 "
            "top-left의 x0/y0 차이가 각각 tolerance 이내인 cluster가 최소 2개 서로 다른 "
            "page에 등장할 때만 level 후보로 인정했다. tolerance 0/1/2/4/8pt를 비교했다."
        ),
        "summary": record_summary,
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
    if not INPUT_PDF.exists():
        raise FileNotFoundError(f"실제 showcase 입력이 없다: {INPUT_PDF}")

    config = TypographyConfig()
    raw_lines = extract_typography_lines(INPUT_PDF, config)
    lines = exclude_margin_artifacts(raw_lines, config)
    font_tiers = compute_tier_set(lines, "font_size", config)
    headings = extract_bpe_headings(lines, font_tiers, config)
    positioned, misses = attach_first_top_left(headings, lines)
    results = [evaluate(positioned, tolerance) for tolerance in POSITION_TOLERANCES]

    compact = [
        {
            "tolerance": result["position_tolerance_pt"],
            "candidates": result["candidate_count"],
            "pages": result["distinct_pages"],
            "tiers": result["tier_counts"],
            "levels": result["level_counts"],
            "clusters": result["accepted_cluster_count"],
            "anchor_hit_count": sum(
                hit["match_count"] > 0 for hit in result["anchor_hits"]
            ),
        }
        for result in results
    ]
    best = max(
        results,
        key=lambda result: (
            sum(hit["match_count"] > 0 for hit in result["anchor_hits"]),
            -result["candidate_count"],
        ),
    )
    finding = (
        f"초기 BPE font-tier 후보 {len(positioned)}개 중 top-left 반복 조건 결과는 "
        f"{compact}이다. 알려진 실제 제목 anchor 보존을 우선하고 후보 수를 최소화하면 "
        f"{best['position_tolerance_pt']}pt가 이 입력에서 가장 유리했다. "
        f"대표 결과는 {best['candidate_count']}개 후보, {best['distinct_pages']}개 page, "
        f"tier={best['tier_counts']}, level={best['level_counts']}이다."
    )
    summary = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "raw_line_count": len(raw_lines),
        "margin_filtered_line_count": len(lines),
        "font_tier_count": len(font_tiers.tiers),
        "initial_bpe_heading_count": len(headings),
        "positioned_heading_count": len(positioned),
        "coordinate_lookup_miss_count": len(misses),
        "coordinate_lookup_misses_preview": misses[:20],
        "minimum_distinct_pages": MIN_DISTINCT_PAGES,
        "comparison": compact,
        "recommended_tolerance_pt": best["position_tolerance_pt"],
        "results": results,
        "finding": finding,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_experiment(summary)
    print(
        json.dumps(
            {"comparison": compact, "finding": finding}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
