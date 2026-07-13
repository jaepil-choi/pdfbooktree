"""bookmark tree의 통계적 특성을 300study 전체에서 계산하고 시각화하는 실험.

배경:
- 010 실험에서 "최소 1 depth tree" 필터와 max_children 임계값을 검토했지만,
  임계값을 정하기 전에 bookmark tree 지표가 데이터 전체에서 어떤 분포를 갖는지
  먼저 눈으로 봐야 한다.
- pseudo label 소스로 쓸 PDF를 거를 때 어떤 지표가 정상 책과 비정상(덤프/문제집)을
  실제로 분리하는지 확인하는 것이 목적이다.

입력은 outputs/300study_detection.json의 결과 목록에 들어 있는 PDF 경로다.
각 PDF의 기존 bookmark를 읽어 tree 지표를 계산하고, 분포를 multi-panel figure로 그린다.

monolithic script로 작성했고, bookmark 추출만 패키지 함수를 재사용한다.
plot label은 matplotlib 기본 폰트의 한글 미지원(두부 현상)을 피하려고 영어로 둔다.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "011_bookmark_tree_statistics_viz"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DETECTION_JSON = ROOT_DIR / "outputs" / "300study_detection.json"

# 010 실험에서 검토한 후보 임계값.
MIN_TREE_DEPTH = 1
MAX_CHILDREN_THRESHOLD = 50


def analyze_bookmark_tree(bookmarks: list[dict[str, Any]]) -> dict[str, Any]:
    """bookmark level 시퀀스로 tree 모양 지표를 계산한다(010과 동일 정의)."""

    levels = [bookmark["level"] for bookmark in bookmarks]
    level_counts = Counter(levels)

    if not levels:
        return {
            "bookmark_count": 0,
            "level_counts": {},
            "distinct_levels": 0,
            "max_level": 0,
            "tree_depth": 0,
            "parent_child_pairs": 0,
            "level_jumps": 0,
            "max_children": 0,
            "mean_children": 0.0,
            "is_min_depth_tree": False,
        }

    min_level = min(levels)
    max_level = max(levels)
    tree_depth = max_level - min_level

    stack: list[list[int]] = []
    parent_child_pairs = 0
    level_jumps = 0
    children_counter: list[int] = []

    for level in levels:
        while stack and stack[-1][0] >= level:
            children_counter.append(stack.pop()[1])
        if stack:
            if level - stack[-1][0] > 1:
                level_jumps += 1
            stack[-1][1] += 1
            parent_child_pairs += 1
        stack.append([level, 0])
    while stack:
        children_counter.append(stack.pop()[1])

    # 부모 노드(자식이 1개 이상인 노드)의 자식 수만 평균에 반영한다.
    parents = [c for c in children_counter if c > 0]
    mean_children = sum(parents) / len(parents) if parents else 0.0
    max_children = max(children_counter) if children_counter else 0

    return {
        "bookmark_count": len(bookmarks),
        "level_counts": {str(k): v for k, v in sorted(level_counts.items())},
        "distinct_levels": len(level_counts),
        "max_level": max_level,
        "tree_depth": tree_depth,
        "parent_child_pairs": parent_child_pairs,
        "level_jumps": level_jumps,
        "max_children": max_children,
        "mean_children": mean_children,
        "is_min_depth_tree": tree_depth >= MIN_TREE_DEPTH and parent_child_pairs > 0,
    }


def collect_metrics() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """detection.json의 PDF를 순회하며 tree 지표를 모은다."""

    detection = json.loads(DETECTION_JSON.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for result in detection["results"]:
        pdf_path = Path(result["input_pdf"])
        rel = result.get("root_relative_pdf") or result["input_pdf"]
        if not pdf_path.exists():
            errors.append({"pdf": rel, "error": "missing_file"})
            continue
        try:
            bookmarks = extract_existing_bookmarks(pdf_path)
        except Exception as exc:  # noqa: BLE001 - 실험에서는 모든 실패를 기록만 한다.
            errors.append({"pdf": rel, "error": str(exc)[:80]})
            continue
        metrics = analyze_bookmark_tree(bookmarks)
        if metrics["bookmark_count"] == 0:
            continue
        rows.append({"pdf": rel, **metrics})
    return rows, errors


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q / 100 * (len(ordered) - 1))))
    return float(ordered[idx])


def build_figure(rows: list[dict[str, Any]]) -> Path:
    """6-panel 통계 figure를 그려 PNG로 저장한다."""

    counts = [r["bookmark_count"] for r in rows]
    depths = [r["tree_depth"] for r in rows]
    max_children = [r["max_children"] for r in rows]
    distinct_levels = [r["distinct_levels"] for r in rows]
    mean_children = [r["mean_children"] for r in rows]

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle(
        f"Bookmark tree statistics over 300study ({len(rows)} bookmarked PDFs)",
        fontsize=15,
        fontweight="bold",
    )

    # 1) bookmark count 분포 (log-binned)
    ax = axes[0][0]
    ax.hist(counts, bins=40, color="#4C72B0", edgecolor="white")
    for thr, color in [(50, "#999999"), (500, "#DD8452"), (1000, "#C44E52")]:
        ax.axvline(thr, color=color, linestyle="--", linewidth=1.2, label=f"{thr}")
    ax.set_yscale("log")
    ax.set_title("Bookmark count per PDF")
    ax.set_xlabel("bookmark_count")
    ax.set_ylabel("PDF count (log)")
    ax.legend(title="threshold", fontsize=8)

    # 2) tree depth 분포
    ax = axes[0][1]
    depth_counts = Counter(depths)
    xs = sorted(depth_counts)
    bars = ax.bar(
        xs, [depth_counts[x] for x in xs], color="#55A868", edgecolor="white"
    )
    if 0 in depth_counts:
        bars[xs.index(0)].set_color("#C44E52")  # flat 덤프 강조
    for x in xs:
        ax.text(x, depth_counts[x], str(depth_counts[x]), ha="center", va="bottom", fontsize=9)
    ax.set_title("Tree depth (max_level - min_level)\nred = depth 0 (flat list)")
    ax.set_xlabel("tree_depth")
    ax.set_ylabel("PDF count")

    # 3) distinct levels 분포
    ax = axes[0][2]
    lvl_counts = Counter(distinct_levels)
    xs = sorted(lvl_counts)
    ax.bar(xs, [lvl_counts[x] for x in xs], color="#8172B3", edgecolor="white")
    for x in xs:
        ax.text(x, lvl_counts[x], str(lvl_counts[x]), ha="center", va="bottom", fontsize=9)
    ax.set_title("Distinct bookmark levels")
    ax.set_xlabel("distinct_levels")
    ax.set_ylabel("PDF count")

    # 4) max_children 분포
    ax = axes[1][0]
    ax.hist(max_children, bins=40, color="#937860", edgecolor="white")
    ax.axvline(
        MAX_CHILDREN_THRESHOLD,
        color="#C44E52",
        linestyle="--",
        linewidth=1.4,
        label=f"threshold {MAX_CHILDREN_THRESHOLD}",
    )
    ax.set_yscale("log")
    ax.set_title("Max children of a single node")
    ax.set_xlabel("max_children")
    ax.set_ylabel("PDF count (log)")
    ax.legend(fontsize=8)

    # 5) bookmark count vs tree depth, max_children로 색칠
    ax = axes[1][1]
    scatter = ax.scatter(
        counts,
        depths,
        c=max_children,
        cmap="viridis",
        s=28,
        alpha=0.75,
        edgecolor="white",
        linewidth=0.3,
    )
    ax.set_xscale("symlog")
    ax.set_title("count vs depth (color = max_children)")
    ax.set_xlabel("bookmark_count (symlog)")
    ax.set_ylabel("tree_depth")
    fig.colorbar(scatter, ax=ax, label="max_children")

    # 6) 필터 통과/탈락 요약
    ax = axes[1][2]
    flat = sum(1 for r in rows if not r["is_min_depth_tree"])
    big_children = sum(
        1
        for r in rows
        if r["is_min_depth_tree"] and r["max_children"] >= MAX_CHILDREN_THRESHOLD
    )
    passed = len(rows) - flat - big_children
    labels = ["pass", "drop:\nflat depth0", f"drop:\nmaxchild>={MAX_CHILDREN_THRESHOLD}"]
    vals = [passed, flat, big_children]
    colors = ["#55A868", "#C44E52", "#DD8452"]
    bars = ax.bar(labels, vals, color=colors, edgecolor="white")
    for bar, v in zip(bars, vals, strict=False):
        ax.text(bar.get_x() + bar.get_width() / 2, v, str(v), ha="center", va="bottom", fontsize=11)
    ax.set_title("Filter outcome (depth>=1 AND max_children<50)")
    ax.set_ylabel("PDF count")

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    figure_path = OUTPUT_DIR / "bookmark_tree_statistics.png"
    fig.savefig(figure_path, dpi=130)
    plt.close(fig)
    return figure_path


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "pdf",
        "bookmark_count",
        "distinct_levels",
        "max_level",
        "tree_depth",
        "parent_child_pairs",
        "level_jumps",
        "max_children",
        "mean_children",
        "is_min_depth_tree",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_summary(rows: list[dict[str, Any]], errors: list[dict[str, str]]) -> dict[str, Any]:
    counts = [r["bookmark_count"] for r in rows]
    depths = [r["tree_depth"] for r in rows]
    max_children = [r["max_children"] for r in rows]
    flat = sum(1 for r in rows if not r["is_min_depth_tree"])
    big_children = sum(
        1
        for r in rows
        if r["is_min_depth_tree"] and r["max_children"] >= MAX_CHILDREN_THRESHOLD
    )
    return {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "bookmarked_pdf_count": len(rows),
        "error_count": len(errors),
        "bookmark_count": {
            "median": percentile(counts, 50),
            "p90": percentile(counts, 90),
            "p99": percentile(counts, 99),
            "max": max(counts) if counts else 0,
        },
        "tree_depth_distribution": dict(sorted(Counter(depths).items())),
        "max_children": {
            "median": percentile(max_children, 50),
            "p90": percentile(max_children, 90),
            "p99": percentile(max_children, 99),
            "max": max(max_children) if max_children else 0,
        },
        "filter_outcome": {
            "pass": len(rows) - flat - big_children,
            "drop_flat_depth0": flat,
            "drop_max_children_ge_threshold": big_children,
        },
        "errors": errors,
    }


def update_experiment_registry(summary: dict[str, Any]) -> None:
    if not EXPERIMENTS_JSON.exists():
        return
    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    fo = summary["filter_outcome"]
    finding = (
        f"300study bookmark 보유 PDF {summary['bookmarked_pdf_count']}개의 tree 지표를 "
        f"6-panel figure로 시각화했다. bookmark_count median "
        f"{summary['bookmark_count']['median']:.0f}, p99 {summary['bookmark_count']['p99']:.0f}, "
        f"max {summary['bookmark_count']['max']}이다. tree_depth 분포는 "
        f"{summary['tree_depth_distribution']}이고, max_children p99는 "
        f"{summary['max_children']['p99']:.0f}, max {summary['max_children']['max']}이다. "
        f"depth>=1 AND max_children<{MAX_CHILDREN_THRESHOLD} 필터 기준 pass {fo['pass']}, "
        f"flat depth0 탈락 {fo['drop_flat_depth0']}, max_children 초과 탈락 "
        f"{fo['drop_max_children_ge_threshold']}개다."
    )
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "300study bookmark 보유 PDF의 tree 지표(bookmark count, tree depth, "
            "distinct levels, max_children) 분포를 시각화해 pseudo label 필터 임계값을 "
            "정하기 위한 통계적 근거를 확인한다."
        ),
        "inputs": ["outputs\\300study_detection.json"],
        "outputs": "experiments\\outputs\\011_bookmark_tree_statistics_viz",
        "finding": finding,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    registry["experiments"] = [
        e for e in registry["experiments"] if e.get("id") != EXPERIMENT_ID
    ]
    registry["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    rows, errors = collect_metrics()
    figure_path = build_figure(rows)
    summary = build_summary(rows, errors)

    write_csv(OUTPUT_DIR / "bookmark_tree_metrics.csv", rows)
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    update_experiment_registry(summary)

    if not args.quiet:
        print(f"figure: {figure_path}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
