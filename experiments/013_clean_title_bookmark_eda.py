"""글자 포함 bookmark만 남긴 뒤(깨진 제목 제외) 다시 EDA를 하는 실험.

배경:
- 012에서 frac_no_letter > 0.5 인 PDF 10개를 깨진 bookmark(숫자/OCR 아티팩트 제목)로
  분리했다. 이 10개는 011의 전체 분포(특히 tree_depth 0, 대량 bookmark)를 오염시켰다.
- 깨진 것을 제거한 '글자 포함' 402개만 다시 보면, 다음 필터 후보 신호가 더 선명하게
  보일 수 있다.

이 실험은 011(tree 지표)과 012(title 지표) 산출 CSV, detection.json(total_pages)을
조인한 뒤 frac_no_letter <= 0.5 인 PDF만 남겨 EDA figure를 그린다.
PDF를 다시 열지 않으므로 빠르다.

새 파생 지표:
- bookmarks_per_page: bookmark_count / total_pages. 페이지당 bookmark가 비정상적으로
  많으면 문제집/용어집 덤프일 수 있다.

plot label은 한글 폰트 두부 현상을 피해 영어로 둔다.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "013_clean_title_bookmark_eda"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"

TREE_CSV = (
    ROOT_DIR
    / "experiments/outputs/011_bookmark_tree_statistics_viz/bookmark_tree_metrics.csv"
)
TITLE_CSV = (
    ROOT_DIR
    / "experiments/outputs/012_bookmark_title_length_filter/bookmark_title_metrics.csv"
)
DETECTION_JSON = ROOT_DIR / "outputs" / "300study_detection.json"

NO_LETTER_THRESHOLD = 0.5


def load_clean_rows() -> list[dict[str, Any]]:
    """세 소스를 조인하고 글자 포함 bookmark PDF만 남긴다."""

    tree = {
        r["pdf"]: r
        for r in csv.DictReader(open(TREE_CSV, encoding="utf-8-sig"))
    }
    title = {
        r["pdf"]: r
        for r in csv.DictReader(open(TITLE_CSV, encoding="utf-8-sig"))
    }
    detection = json.loads(DETECTION_JSON.read_text(encoding="utf-8"))
    pages = {
        (r.get("root_relative_pdf") or r["input_pdf"]): r.get("total_pages")
        for r in detection["results"]
    }

    rows: list[dict[str, Any]] = []
    for pdf, tr in tree.items():
        ti = title.get(pdf)
        if ti is None:
            continue
        frac_no_letter = float(ti["frac_no_letter"])
        if frac_no_letter > NO_LETTER_THRESHOLD:
            continue  # 깨진 제목 PDF 제외
        total_pages = pages.get(pdf) or 0
        bookmark_count = int(tr["bookmark_count"])
        rows.append(
            {
                "pdf": pdf,
                "bookmark_count": bookmark_count,
                "total_pages": int(total_pages),
                "tree_depth": int(tr["tree_depth"]),
                "distinct_levels": int(tr["distinct_levels"]),
                "max_children": int(tr["max_children"]),
                "mean_children": float(tr["mean_children"]),
                "median_char": float(ti["median_char"]),
                "mean_char": float(ti["mean_char"]),
                "frac_no_letter": frac_no_letter,
                "bookmarks_per_page": (
                    bookmark_count / total_pages if total_pages else 0.0
                ),
            }
        )
    return rows


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[min(len(ordered) - 1, int(round(q / 100 * (len(ordered) - 1))))])


def build_figure(rows: list[dict[str, Any]]) -> Path:
    counts = [r["bookmark_count"] for r in rows]
    depths = [r["tree_depth"] for r in rows]
    max_children = [r["max_children"] for r in rows]
    med_char = [r["median_char"] for r in rows]
    bpp = [r["bookmarks_per_page"] for r in rows]
    pages = [r["total_pages"] for r in rows]

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle(
        f"EDA on letter-containing bookmark PDFs ({len(rows)} PDFs, broken titles removed)",
        fontsize=15,
        fontweight="bold",
    )

    # 1) bookmark count
    ax = axes[0][0]
    ax.hist(counts, bins=40, color="#4C72B0", edgecolor="white")
    ax.set_yscale("log")
    ax.set_title("Bookmark count per PDF")
    ax.set_xlabel("bookmark_count")
    ax.set_ylabel("PDF count (log)")

    # 2) tree depth (OCR 덤프 제거 후 변화 확인)
    ax = axes[0][1]
    from collections import Counter

    dc = Counter(depths)
    xs = sorted(dc)
    bars = ax.bar(xs, [dc[x] for x in xs], color="#55A868", edgecolor="white")
    if 0 in dc:
        bars[xs.index(0)].set_color("#C44E52")
    for x in xs:
        ax.text(x, dc[x], str(dc[x]), ha="center", va="bottom", fontsize=9)
    ax.set_title("Tree depth (clean)\nred = depth 0 (flat)")
    ax.set_xlabel("tree_depth")
    ax.set_ylabel("PDF count")

    # 3) median title length
    ax = axes[0][2]
    ax.hist([min(m, 60) for m in med_char], bins=40, color="#8172B3", edgecolor="white")
    ax.axvline(pct(med_char, 50), color="#333333", linestyle=":", linewidth=1.0, label="median")
    ax.set_title("Per-PDF median title length (clean)")
    ax.set_xlabel("median title char length")
    ax.set_ylabel("PDF count")
    ax.legend(fontsize=8)

    # 4) bookmarks_per_page (새 신호)
    ax = axes[1][0]
    ax.hist([min(b, 3.0) for b in bpp], bins=40, color="#DD8452", edgecolor="white")
    p99 = pct(bpp, 99)
    ax.axvline(p99, color="#C44E52", linestyle="--", linewidth=1.2, label=f"p99={p99:.2f}")
    ax.set_yscale("log")
    ax.set_title("Bookmarks per page (clipped at 3.0)")
    ax.set_xlabel("bookmark_count / total_pages")
    ax.set_ylabel("PDF count (log)")
    ax.legend(fontsize=8)

    # 5) bookmark count vs total pages (색 = bookmarks_per_page)
    ax = axes[1][1]
    sc = ax.scatter(
        pages,
        counts,
        c=[min(b, 2.0) for b in bpp],
        cmap="plasma",
        s=26,
        alpha=0.75,
        edgecolor="white",
        linewidth=0.3,
    )
    ax.set_title("bookmark_count vs total_pages\n(color = bookmarks/page)")
    ax.set_xlabel("total_pages")
    ax.set_ylabel("bookmark_count")
    fig.colorbar(sc, ax=ax, label="bookmarks/page")

    # 6) max_children (clean)
    ax = axes[1][2]
    ax.hist(max_children, bins=40, color="#937860", edgecolor="white")
    ax.set_yscale("log")
    ax.set_title("Max children of a single node (clean)")
    ax.set_xlabel("max_children")
    ax.set_ylabel("PDF count (log)")

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    figure_path = OUTPUT_DIR / "clean_title_bookmark_eda.png"
    fig.savefig(figure_path, dpi=130)
    plt.close(fig)
    return figure_path


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = [r["bookmark_count"] for r in rows]
    bpp = [r["bookmarks_per_page"] for r in rows]
    med_char = [r["median_char"] for r in rows]
    from collections import Counter

    top_bpp = sorted(rows, key=lambda r: -r["bookmarks_per_page"])[:10]
    return {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "clean_pdf_count": len(rows),
        "bookmark_count": {
            "median": pct(counts, 50),
            "p90": pct(counts, 90),
            "p99": pct(counts, 99),
            "max": max(counts),
        },
        "tree_depth_distribution": dict(sorted(Counter(r["tree_depth"] for r in rows).items())),
        "median_title_char": {
            "p10": pct(med_char, 10),
            "median": pct(med_char, 50),
            "p90": pct(med_char, 90),
        },
        "bookmarks_per_page": {
            "median": round(pct(bpp, 50), 3),
            "p90": round(pct(bpp, 90), 3),
            "p99": round(pct(bpp, 99), 3),
            "max": round(max(bpp), 3),
        },
        "top_bookmarks_per_page": [
            {
                "pdf": r["pdf"],
                "bookmarks_per_page": round(r["bookmarks_per_page"], 3),
                "bookmark_count": r["bookmark_count"],
                "total_pages": r["total_pages"],
                "tree_depth": r["tree_depth"],
            }
            for r in top_bpp
        ],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def update_experiment_registry(summary: dict[str, Any]) -> None:
    if not EXPERIMENTS_JSON.exists():
        return
    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    finding = (
        f"깨진 제목 PDF를 제외한 글자 포함 bookmark PDF {summary['clean_pdf_count']}개로 "
        f"다시 EDA했다. bookmark_count median {summary['bookmark_count']['median']:.0f}, "
        f"p99 {summary['bookmark_count']['p99']:.0f}, max {summary['bookmark_count']['max']}이다. "
        f"tree_depth 분포는 {summary['tree_depth_distribution']}로, OCR 덤프 제거 후 depth 0 "
        f"그룹이 줄었다. median title 글자수는 p10 {summary['median_title_char']['p10']:.0f}, "
        f"median {summary['median_title_char']['median']:.0f}이다. 새 지표 bookmarks_per_page는 "
        f"median {summary['bookmarks_per_page']['median']}, p99 "
        f"{summary['bookmarks_per_page']['p99']}, max {summary['bookmarks_per_page']['max']}로 "
        f"상위는 페이지당 bookmark가 과도한 문제집/용어집 후보다."
    )
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "글자 포함 bookmark만 남긴 깨끗한 402개 PDF에서 bookmark count, tree depth, "
            "title 길이, bookmarks_per_page 분포를 다시 EDA해 다음 필터 후보 신호를 찾는다."
        ),
        "inputs": [
            "experiments\\outputs\\011_bookmark_tree_statistics_viz\\bookmark_tree_metrics.csv",
            "experiments\\outputs\\012_bookmark_title_length_filter\\bookmark_title_metrics.csv",
            "outputs\\300study_detection.json",
        ],
        "outputs": "experiments\\outputs\\013_clean_title_bookmark_eda",
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

    rows = load_clean_rows()
    figure_path = build_figure(rows)
    summary = build_summary(rows)

    write_csv(OUTPUT_DIR / "clean_title_bookmark_metrics.csv", rows)
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    update_experiment_registry(summary)

    if not args.quiet:
        print(f"figure: {figure_path}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
