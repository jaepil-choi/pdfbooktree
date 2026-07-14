"""experiment 094: font size와 normalized position을 joint style로 묶는다.

092는 global font tier에서 body tier를 먼저 제거해 실제 제목 57개 중 51개를
geometry 검사 전에 잃었다. 이번 실험은 모든 visual line에서 body font와 상대적으로
다른 font size를 가진 line을 고른 뒤, font-size ratio와 page-normalized top-left를
동시에 style로 clustering한다. 여러 page에 반복되는 style만 level 후보로 인정하고
style 대표 font size를 비교하는 stack으로 hierarchy를 만든다. PDF bookmark는 오류가
섞인 near-answer weak reference로만 사용하고, 최종 판단은 bookmark_tree.txt를 직접
읽어 수행한다.

실행:
    uv run python experiments/094_interest_economics_joint_style.py
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
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts
from pdfbooktree.typography.tiers import assign_tier, compute_tier_set

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "094_interest_economics_joint_style"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
INPUT_PDF = (
    ROOT_DIR
    / "showcase"
    / "outputs"
    / "017_interest_economics_ocr_overlay"
    / "interest_economics_ocr.pdf"
)
POSITION_HEIGHT_RATIOS = [0.25, 0.5, 1.0]
FONT_RELATIVE_TOLERANCES = [0.05, 0.1]
MIN_DISTINCT_PAGES = 2
MARGIN_MIN_CONSECUTIVE_PAGES = 3
TITLE_MATCH_THRESHOLD = 70.0


@dataclass(frozen=True)
class StyleLine:
    line: Any
    x_unit: float
    y_unit: float
    font_ratio_to_body: float


@dataclass
class StyleCluster:
    cluster_id: int
    items: list[StyleLine]

    @property
    def font_size(self) -> float:
        return float(median(item.line.font_size for item in self.items))

    @property
    def pages(self) -> set[int]:
        return {item.line.pdf_page for item in self.items}


def normalize_title(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", " ", text.casefold()).strip()


def title_score(left: str, right: str) -> float:
    left_norm = normalize_title(left)
    right_norm = normalize_title(right)
    if left_norm and (left_norm in right_norm or right_norm in left_norm):
        return 100.0
    return 100.0 * SequenceMatcher(None, left_norm, right_norm).ratio()


def load_truth() -> list[dict[str, Any]]:
    with fitz.open(INPUT_PDF) as document:
        return [
            {"level": level, "title": title, "pdf_page": page}
            for level, title, page in document.get_toc()
            if page > 0
        ]


def estimate_body_font_size(lines: list[Any], tiers: Any) -> tuple[int, float]:
    tier_numbers = [assign_tier(line.font_size, tiers.cut_points) for line in lines]
    body_tier = max(
        Counter(tier_numbers), key=lambda tier: (Counter(tier_numbers)[tier], tier)
    )
    body_sizes = [
        line.font_size
        for line, tier in zip(lines, tier_numbers, strict=True)
        if tier == body_tier
    ]
    return body_tier, float(median(body_sizes))


def build_style_lines(
    lines: list[Any], body_font_size: float
) -> tuple[list[StyleLine], dict[str, float]]:
    median_x_height = median(line.height / line.page_width for line in lines)
    median_y_height = median(line.height / line.page_height for line in lines)
    result = [
        StyleLine(
            line=line,
            x_unit=(line.x0 / line.page_width) / median_x_height,
            y_unit=(line.y0 / line.page_height) / median_y_height,
            font_ratio_to_body=line.font_size / body_font_size,
        )
        for line in lines
    ]
    return result, {
        "body_font_size": round(body_font_size, 4),
        "median_height_over_page_width": median_x_height,
        "median_height_over_page_height": median_y_height,
    }


def cluster_joint_styles(
    items: list[StyleLine], position_tolerance: float, font_tolerance: float
) -> list[StyleCluster]:
    clusters: list[list[StyleLine]] = []
    ordered = sorted(
        items,
        key=lambda item: (
            item.font_ratio_to_body,
            item.x_unit,
            item.y_unit,
            item.line.pdf_page,
        ),
    )
    for item in ordered:
        target = next(
            (
                cluster
                for cluster in clusters
                if max(row.x_unit for row in cluster + [item])
                - min(row.x_unit for row in cluster + [item])
                <= position_tolerance
                and max(row.y_unit for row in cluster + [item])
                - min(row.y_unit for row in cluster + [item])
                <= position_tolerance
                and max(row.font_ratio_to_body for row in cluster + [item])
                / min(row.font_ratio_to_body for row in cluster + [item])
                - 1.0
                <= font_tolerance
            ),
            None,
        )
        if target is None:
            clusters.append([item])
        else:
            target.append(item)
    return [
        StyleCluster(index, cluster) for index, cluster in enumerate(clusters, start=1)
    ]


def select_repeated_styles(
    style_lines: list[StyleLine], position_tolerance: float, font_tolerance: float
) -> tuple[list[tuple[StyleLine, StyleCluster]], list[dict[str, Any]]]:
    # 사용자 결정대로 본문 font와 다른 line만 level 후보로 허용한다.
    non_body = [
        item
        for item in style_lines
        if abs(item.font_ratio_to_body - 1.0) > font_tolerance
    ]
    clusters = cluster_joint_styles(non_body, position_tolerance, font_tolerance)
    accepted = [
        cluster for cluster in clusters if len(cluster.pages) >= MIN_DISTINCT_PAGES
    ]
    memberships = [(item, cluster) for cluster in accepted for item in cluster.items]
    memberships.sort(
        key=lambda row: (row[0].line.pdf_page, row[0].line.y0, row[0].line.x0)
    )
    reports = [
        {
            "cluster_id": cluster.cluster_id,
            "count": len(cluster.items),
            "distinct_pages": len(cluster.pages),
            "font_size_median": round(cluster.font_size, 4),
            "font_ratio_median": round(
                median(item.font_ratio_to_body for item in cluster.items), 4
            ),
            "x_unit_range": [
                round(min(item.x_unit for item in cluster.items), 4),
                round(max(item.x_unit for item in cluster.items), 4),
            ],
            "y_unit_range": [
                round(min(item.y_unit for item in cluster.items), 4),
                round(max(item.y_unit for item in cluster.items), 4),
            ],
            "titles": [item.line.text for item in cluster.items[:8]],
        }
        for cluster in accepted
    ]
    return memberships, reports


def run_style_stack(
    memberships: list[tuple[StyleLine, StyleCluster]], font_tolerance: float
) -> list[tuple[StyleLine, StyleCluster, int]]:
    stack: list[tuple[StyleCluster, float]] = []
    result: list[tuple[StyleLine, StyleCluster, int]] = []
    for item, cluster in memberships:
        size = cluster.font_size
        while stack and size > stack[-1][1] * (1.0 + font_tolerance):
            stack.pop()
        if stack and abs(size / stack[-1][1] - 1.0) <= font_tolerance:
            level = len(stack)
            stack[-1] = (cluster, size)
        else:
            stack.append((cluster, size))
            level = len(stack)
        result.append((item, cluster, level))
    return result


def evaluate_truth(
    inferred: list[tuple[StyleLine, StyleCluster, int]], truth: list[dict[str, Any]]
) -> dict[str, Any]:
    by_page: dict[int, list[tuple[StyleLine, StyleCluster, int]]] = defaultdict(list)
    for row in inferred:
        by_page[row[0].line.pdf_page].append(row)
    matches = []
    unmatched = []
    for entry in truth:
        page_rows = by_page.get(entry["pdf_page"], [])
        best = max(
            page_rows,
            key=lambda row: title_score(entry["title"], row[0].line.text),
            default=None,
        )
        score = title_score(entry["title"], best[0].line.text) if best else 0.0
        if best is None or score < TITLE_MATCH_THRESHOLD:
            unmatched.append(entry)
            continue
        item, cluster, level = best
        matches.append(
            {
                "truth_title": entry["title"],
                "truth_page": entry["pdf_page"],
                "truth_level": entry["level"],
                "candidate_title": item.line.text,
                "candidate_level": level,
                "style_cluster": cluster.cluster_id,
                "style_font_size": round(cluster.font_size, 4),
                "score": round(score, 1),
                "level_correct": level == entry["level"],
            }
        )
    return {
        "truth_count": len(truth),
        "label_quality": "no embedded labels; human review required",
        "bookmark_tree_txt": str(
            (OUTPUT_DIR / "bookmark_tree.txt").relative_to(ROOT_DIR)
        ),
        "matched": len(matches),
        "recall": round(len(matches) / len(truth), 4) if truth else 0.0,
        "level_correct": sum(row["level_correct"] for row in matches),
        "level_accuracy": round(
            sum(row["level_correct"] for row in matches) / len(matches), 4
        )
        if matches
        else 0.0,
        "matches": matches,
        "unmatched": unmatched,
    }


def evaluate(
    style_lines: list[StyleLine],
    truth: list[dict[str, Any]],
    position_tolerance: float,
    font_tolerance: float,
) -> dict[str, Any]:
    memberships, clusters = select_repeated_styles(
        style_lines, position_tolerance, font_tolerance
    )
    inferred = run_style_stack(memberships, font_tolerance)
    truth_eval = evaluate_truth(inferred, truth)
    return {
        "position_tolerance_line_heights": position_tolerance,
        "font_relative_tolerance": font_tolerance,
        "candidate_count": len(memberships),
        "accepted_style_count": len(clusters),
        "level_counts": dict(
            sorted(Counter(level for _, _, level in inferred).items())
        ),
        "truth_evaluation": truth_eval,
        "accepted_styles": clusters,
        "tree_preview": [
            {
                "page": item.line.pdf_page,
                "level": level,
                "style": cluster.cluster_id,
                "font_size": round(cluster.font_size, 2),
                "title": item.line.text,
            }
            for item, cluster, level in inferred[:100]
        ],
    }


def record_experiment(summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    compact = {
        key: summary[key]
        for key in (
            "margin_min_consecutive_pages",
            "body_tier",
            "normalization",
            "truth_count",
            "label_quality",
            "bookmark_tree_txt",
            "comparison",
            "best_config",
            "finding",
        )
    }
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": "global body tier 제거 전에 font-size ratio와 normalized top-left를 joint style로 만들고, 여러 page에 반복되는 style만 level 후보로 인정해 bookmark hierarchy를 복원할 수 있는지 검증한다. 기존 PDF bookmark는 near-answer weak reference로만 사용한다.",
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": "production exclude_margin_artifacts를 연속 page-number run 3페이지로 적용한 뒤, 모든 visual line의 top-left를 page-relative 좌표로 바꾸고 문서 median line-height를 단위로 환산했다. body font median과 font-size가 상대적으로 다른 line만 대상으로, font ratio와 x/y가 각각 dimensionless tolerance 안에 드는 joint style을 만들었다. 2개 이상 page에 반복되는 style만 남기고 style median font-size stack으로 level을 부여했다.",
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
    config = TypographyConfig(margin_min_consecutive_pages=MARGIN_MIN_CONSECUTIVE_PAGES)
    raw_lines = extract_typography_lines(INPUT_PDF, config)
    lines = exclude_margin_artifacts(raw_lines, config)
    tiers = compute_tier_set(lines, "font_size", config)
    body_tier, body_font_size = estimate_body_font_size(lines, tiers)
    style_lines, normalization = build_style_lines(lines, body_font_size)
    truth = load_truth()
    results = [
        evaluate(style_lines, truth, position_tolerance, font_tolerance)
        for position_tolerance in POSITION_HEIGHT_RATIOS
        for font_tolerance in FONT_RELATIVE_TOLERANCES
    ]
    tree_files: list[dict[str, Any]] = []
    for result in results:
        position_ratio = result["position_tolerance_line_heights"]
        font_ratio = result["font_relative_tolerance"]
        memberships, _styles = select_repeated_styles(
            style_lines, position_ratio, font_ratio
        )
        inferred = run_style_stack(memberships, font_ratio)
        tree_path = OUTPUT_DIR / (
            f"bookmark_tree_position_{position_ratio:g}_font_{font_ratio:g}.txt"
        )
        tree_lines = [
            f"{'  ' * (level - 1)}[L{level}] [p.{item.line.pdf_page}] "
            f"[style={cluster.cluster_id}] [font={cluster.font_size:.2f}] "
            f"{item.line.text}"
            for item, cluster, level in inferred
        ]
        tree_path.write_text(
            "\n".join(tree_lines) + ("\n" if tree_lines else ""), encoding="utf-8"
        )
        tree_files.append(
            {
                "position_ratio": position_ratio,
                "font_ratio": font_ratio,
                "path": str(tree_path.relative_to(ROOT_DIR)),
                "line_count": len(tree_lines),
            }
        )
    comparison = [
        {
            "position_ratio": result["position_tolerance_line_heights"],
            "font_ratio": result["font_relative_tolerance"],
            "candidates": result["candidate_count"],
            "styles": result["accepted_style_count"],
            "levels": result["level_counts"],
            "recall": result["truth_evaluation"]["recall"],
            "level_accuracy": result["truth_evaluation"]["level_accuracy"],
            "level_correct": result["truth_evaluation"]["level_correct"],
        }
        for result in results
    ]
    best = min(results, key=lambda result: result["candidate_count"])
    best_config = {
        "position_ratio": best["position_tolerance_line_heights"],
        "font_ratio": best["font_relative_tolerance"],
    }
    best_memberships, _best_styles = select_repeated_styles(
        style_lines,
        best["position_tolerance_line_heights"],
        best["font_relative_tolerance"],
    )
    best_tree = run_style_stack(best_memberships, best["font_relative_tolerance"])
    tree_lines = [
        f"{'  ' * (level - 1)}[L{level}] [p.{item.line.pdf_page}] "
        f"[style={cluster.cluster_id}] [font={cluster.font_size:.2f}] "
        f"{item.line.text}"
        for item, cluster, level in best_tree
    ]
    (OUTPUT_DIR / "bookmark_tree.txt").write_text(
        "\n".join(tree_lines) + ("\n" if tree_lines else ""), encoding="utf-8"
    )
    finding = (
        f"body tier={body_tier}, body font median={body_font_size:.4f}, "
        f"visual lines={len(lines)}, embedded bookmark=0. joint style 비교={comparison}. "
        f"label이 없으므로 자동 정답 설정은 선택하지 않았다. 사람이 먼저 읽을 "
        f"conservative preview는 config={best_config}, candidates={best['candidate_count']}, "
        f"levels={best['level_counts']}이다. 모든 config의 tree txt를 별도 저장했다."
    )
    summary = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "raw_line_count": len(raw_lines),
        "line_count": len(lines),
        "margin_min_consecutive_pages": MARGIN_MIN_CONSECUTIVE_PAGES,
        "body_tier": body_tier,
        "normalization": normalization,
        "truth_count": len(truth),
        "label_quality": "no embedded labels; human review required",
        "bookmark_tree_txt": str(
            (OUTPUT_DIR / "bookmark_tree.txt").relative_to(ROOT_DIR)
        ),
        "comparison": comparison,
        "best_config": best_config,
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
