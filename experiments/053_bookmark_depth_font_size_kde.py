"""experiment 053: bookmark tree depth별로 실제 장/절 시작 heading의 font size KDE를 본다.

052는 책 전체 line의 font size를 depth 구분 없이 몰아서 KDE를 그렸더니, 각 tier가
실제로 무슨 역할(본문/절 제목/장 표제)을 하는지는 페이지를 직접 대조해야만 알 수 있었다.
이번에는 발상을 바꿔, 이미 PDF에 들어있는 bookmark(outline) 트리를 정답으로 써서
"진짜 장/절이 시작되는 page의 heading 줄"만 골라내고, 그 heading을 bookmark
depth(level)별로 나눠 KDE를 그린다. level 1 depth의 KDE, level 2 depth의 KDE를
따로 그려서 depth마다 font size가 서로 다른 좁은 tier로 갈리는지 확인한다.

heading 매칭 방법: bookmark title과 정확히 같은 텍스트가 페이지에 그대로 있으리라는
보장이 없다(장식 글자 간격, 번호 위치가 분리된 span 등). 그래서 매칭은
1) 대상 page의 line을 뽑고, 2) 연속으로 같은 font size(허용오차 0.5pt)인 line을
하나의 heading 후보 run으로 묶고(단, 4줄/90자 이하만 후보로 인정해 본문 문단이
후보에 섞이지 않게 한다), 3) rapidfuzz token_set_ratio로 bookmark title과 가장
비슷한 run을 찾는다. score < MATCH_THRESHOLD면 매칭 실패로 버린다.

이 실험은 John Hull(bookmark 트리가 level 1/2 두 단계뿐)만 대상으로 한다. LLM은
호출하지 않는다.

실행:
    uv run python experiments/053_bookmark_depth_font_size_kde.py
출력:
    experiments/outputs/053_bookmark_depth_font_size_kde/
        - bookmark_heading_matches.csv : bookmark별 매칭된 heading run과 font size/height
        - kde_by_level.png             : level별 KDE(행)와 font size/height(열) 그리드
        - kde_overlay.png              : 모든 level KDE를 한 그래프에 겹쳐 비교
        - tier_texts.txt                : level별 font size tier에 실제 어떤 bookmark title이 들어갔는지 텍스트 덤프
        - summary.json
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from rapidfuzz import fuzz
from scipy.signal import argrelextrema
from scipy.stats import gaussian_kde

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "053_bookmark_depth_font_size_kde"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

TARGET_PDF = (
    ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf"
)
TARGET_ID = "john_hull"

RUN_FONT_SIZE_TOLERANCE = 0.5
MAX_CANDIDATE_LINES = 4
MAX_CANDIDATE_CHARS = 90
MATCH_THRESHOLD = 70.0

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_NORM_STRIP = re.compile(r"[^a-z0-9가-힣 ]")
_MULTI_SPACE = re.compile(r"\s+")


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def normalize_for_match(text: str) -> str:
    text = text.lower()
    text = _NORM_STRIP.sub(" ", text)
    return _MULTI_SPACE.sub(" ", text).strip()


def page_lines(page: fitz.Page) -> list[dict[str, Any]]:
    """page의 line 단위 대표 height/font_size/text를 뽑는다(내용 span 기준)."""

    data = page.get_text("dict")
    lines: list[dict[str, Any]] = []
    for block in data["blocks"]:
        for line in block.get("lines", []):
            heights: list[float] = []
            sizes: list[float] = []
            parts: list[str] = []
            for span in line["spans"]:
                text = span["text"]
                if not text.strip():
                    continue
                parts.append(text.strip())
                if is_content_span(text):
                    y0, y1 = span["bbox"][1], span["bbox"][3]
                    heights.append(round(y1 - y0, 2))
                    sizes.append(round(float(span["size"]), 2))
            if not heights:
                continue
            lines.append(
                {
                    "text": " ".join(parts),
                    "height": max(heights),
                    "font_size": max(sizes),
                }
            )
    return lines


def build_heading_candidates(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """연속으로 같은 font size인 line을 묶어 heading 후보 run을 만든다.

    본문 문단은 대개 수십 줄이 이어지므로, 줄 수/글자 수 상한을 둬 후보에서 뺀다.
    """

    runs: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_size: float | None = None
    for line in lines:
        if current and current_size is not None and abs(line["font_size"] - current_size) <= RUN_FONT_SIZE_TOLERANCE:
            current.append(line)
        else:
            if current:
                runs.append(current)
            current = [line]
        current_size = line["font_size"]
    if current:
        runs.append(current)

    candidates: list[dict[str, Any]] = []
    for run in runs:
        text = " ".join(item["text"] for item in run)
        if len(run) > MAX_CANDIDATE_LINES or len(text) > MAX_CANDIDATE_CHARS:
            continue
        candidates.append(
            {
                "text": text,
                "font_size": max(item["font_size"] for item in run),
                "height": max(item["height"] for item in run),
                "n_lines": len(run),
            }
        )
    return candidates


def match_bookmark_heading(title: str, candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    title_n = normalize_for_match(title)
    if not title_n or not candidates:
        return None, 0.0
    scored = [
        (candidate, fuzz.token_set_ratio(title_n, normalize_for_match(candidate["text"])))
        for candidate in candidates
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    best, score = scored[0]
    return best, score


def cluster_by_density(values: list[float]) -> dict[str, Any]:
    """1D 값을 KDE 밀도의 봉우리/골짜기로 클러스터링한다(k 미고정)."""

    arr = np.asarray(values, dtype=float)
    uniq = np.unique(arr)
    if uniq.size == 1:
        return {"tier_count": 1, "cut_points": [], "peaks": [float(uniq[0])], "bandwidth": None}
    if uniq.size < 3:
        return {
            "tier_count": int(uniq.size),
            "cut_points": [float((uniq[i] + uniq[i + 1]) / 2.0) for i in range(uniq.size - 1)],
            "peaks": sorted((float(v) for v in uniq), reverse=True),
            "bandwidth": None,
        }

    kde = gaussian_kde(arr)
    grid = np.linspace(arr.min() - 1.0, arr.max() + 1.0, 2048)
    density = kde(grid)

    peak_idx = argrelextrema(density, np.greater)[0]
    valley_idx = argrelextrema(density, np.less)[0]
    if peak_idx.size == 0:
        return {
            "tier_count": 1,
            "cut_points": [],
            "peaks": [float(np.median(arr))],
            "bandwidth": float(kde.factor),
            "grid": grid,
            "density": density,
        }

    peaks = [float(grid[i]) for i in peak_idx]
    cut_points = [float(grid[vi]) for vi in valley_idx if peaks[0] < grid[vi] < peaks[-1]]
    cut_points = sorted(cut_points)[: max(len(peaks) - 1, 0)]

    return {
        "tier_count": len(peaks),
        "cut_points": cut_points,
        "peaks": sorted(peaks, reverse=True),
        "bandwidth": float(kde.factor),
        "grid": grid,
        "density": density,
    }


def collect_bookmark_headings(pdf_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        toc = document.get_toc(simple=False)
        page_cache: dict[int, list[dict[str, Any]]] = {}
        for level, title, page_no, _dest in toc:
            if page_no < 1 or page_no > document.page_count:
                unmatched.append({"level": level, "title": title, "page": page_no, "reason": "page_out_of_range"})
                continue
            if page_no not in page_cache:
                page = document.load_page(page_no - 1)
                page_cache[page_no] = build_heading_candidates(page_lines(page))
            candidates = page_cache[page_no]
            best, score = match_bookmark_heading(title, candidates)
            if best is None or score < MATCH_THRESHOLD:
                unmatched.append(
                    {"level": level, "title": title, "page": page_no, "reason": "low_score", "score": round(score, 2)}
                )
                continue
            matched.append(
                {
                    "level": level,
                    "title": title,
                    "page": page_no,
                    "matched_text": best["text"],
                    "font_size": best["font_size"],
                    "height": best["height"],
                    "match_score": round(score, 2),
                }
            )
    return matched, unmatched


def save_kde_grid(rows: list[dict[str, Any]], clusters: dict[int, dict[str, Any]], path: Path) -> None:
    levels = sorted(clusters)
    fig, axes = plt.subplots(len(levels), 2, figsize=(14, 4 * len(levels)), squeeze=False)
    for row_idx, level in enumerate(levels):
        level_rows = [row for row in rows if row["level"] == level]
        for col_idx, key in enumerate(["font_size", "height"]):
            ax = axes[row_idx][col_idx]
            values = np.asarray([row[key] for row in level_rows], dtype=float)
            cluster = clusters[level][key]
            ax.hist(values, bins=30, density=True, color="#b0c4de", alpha=0.7, label="hist")
            if "grid" in cluster:
                ax.plot(cluster["grid"], cluster["density"], color="#1f4e79", lw=2, label="KDE")
            for peak in cluster["peaks"]:
                ax.axvline(peak, color="#2e7d32", ls="--", lw=1)
            for cut in cluster["cut_points"]:
                ax.axvline(cut, color="#c62828", ls=":", lw=1.5)
            ax.set_title(f"level {level} - {key} (n={len(level_rows)}, tiers={cluster['tier_count']})")
            ax.set_xlabel(key)
            ax.set_ylabel("density")
            ax.legend(loc="upper right", fontsize=8)
    fig.suptitle(f"{TARGET_ID}: bookmark depth별 heading font size/height KDE")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def save_kde_overlay(rows: list[dict[str, Any]], path: Path) -> None:
    levels = sorted({row["level"] for row in rows})
    colors = plt.get_cmap("tab10").colors
    fig, axes = plt.subplots(1, 2, figsize=(16, 5))
    for key, ax in zip(["font_size", "height"], axes):
        for idx, level in enumerate(levels):
            values = np.asarray(
                [row[key] for row in rows if row["level"] == level], dtype=float
            )
            if values.size == 0:
                continue
            ax.hist(
                values,
                bins=30,
                density=True,
                alpha=0.35,
                color=colors[idx % len(colors)],
                label=f"level {level} hist (n={values.size})",
            )
            if np.unique(values).size > 1:
                kde = gaussian_kde(values)
                grid = np.linspace(values.min() - 1.0, values.max() + 1.0, 512)
                ax.plot(grid, kde(grid), color=colors[idx % len(colors)], lw=2, label=f"level {level} KDE")
        ax.set_xlabel(key)
        ax.set_ylabel("density")
        ax.set_title(f"{key}: level별 overlay")
        ax.legend(loc="upper right", fontsize=8)
    fig.suptitle(f"{TARGET_ID}: bookmark depth 겹쳐 비교")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def assign_tier(value: float, cut_points: list[float]) -> int:
    """value를 cut_points로 나눈 tier로 매핑한다(T1 = 가장 큰 값)."""

    tier = 1
    for cut in sorted(cut_points, reverse=True):
        if value >= cut:
            return tier
        tier += 1
    return tier


def render_tier_dump(rows: list[dict[str, Any]], clusters: dict[int, dict[str, Any]]) -> list[str]:
    """level별로 font_size tier에 실제 어떤 bookmark title이 들어갔는지 텍스트로 남긴다."""

    out: list[str] = []
    for level in sorted(clusters):
        cut_points = clusters[level]["font_size"]["cut_points"]
        level_rows = [row for row in rows if row["level"] == level]
        buckets: dict[int, list[dict[str, Any]]] = {}
        for row in level_rows:
            tier = assign_tier(row["font_size"], cut_points)
            buckets.setdefault(tier, []).append(row)
        out.append(f"===== level {level} (n={len(level_rows)}, tiers={len(buckets)}) =====")
        for tier in sorted(buckets):
            tier_rows = sorted(buckets[tier], key=lambda row: row["page"])
            sizes = sorted({row["font_size"] for row in tier_rows}, reverse=True)
            out.append(f"--- T{tier} font_size={sizes} n={len(tier_rows)} ---")
            for row in tier_rows:
                out.append(
                    f"  p{row['page']:>4} fs={row['font_size']:>5} "
                    f"title={row['title']!r} matched={row['matched_text']!r} "
                    f"score={row['match_score']}"
                )
        out.append("")
    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def build_finding(summary: dict[str, Any]) -> str:
    parts = [
        f"{TARGET_ID} bookmark {summary['total_bookmarks']}개 중 {summary['matched_count']}개"
        f"({summary['match_rate']:.3f})를 heading run에 매칭했다(미매칭 {summary['unmatched_count']}개)."
    ]
    for level in sorted(summary["level_stats"]):
        stat = summary["level_stats"][level]
        fs = stat["font_size"]
        ht = stat["height"]
        parts.append(
            f"level {level}(n={stat['count']}): font_size median={fs['median']} "
            f"(peaks={fs['peaks']}, tiers={fs['tier_count']}), "
            f"height median={ht['median']} (peaks={ht['peaks']}, tiers={ht['tier_count']})."
        )
    return " ".join(parts)


def record_experiment(summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "052가 책 전체 line을 depth 구분 없이 KDE로 봤다면, 이번에는 PDF에 이미 "
            "있는 bookmark(outline) 트리를 정답 삼아 실제 장/절이 시작되는 page의 "
            "heading 줄만 골라 bookmark depth(level 1, level 2, ...)별로 나눠 font "
            "size/height KDE를 그린다. bookmark title과 page heading은 rapidfuzz "
            "token_set_ratio로 매칭한다."
        ),
        "inputs": [str(TARGET_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiment": "052_whole_book_line_font_height_kde",
        "match_threshold": MATCH_THRESHOLD,
        "clustering": "1D gaussian_kde(Scott bandwidth) 봉우리/골짜기, k 미고정, level별 분리",
        "finding": summary["finding"],
        "ran_at": summary["ran_at"],
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

    print(f"... {TARGET_ID} bookmark 트리에서 heading 매칭 중: {TARGET_PDF.name}", flush=True)
    matched, unmatched = collect_bookmark_headings(TARGET_PDF)
    print(f"    matched={len(matched)} unmatched={len(unmatched)}", flush=True)

    levels = sorted({row["level"] for row in matched})
    clusters: dict[int, dict[str, Any]] = {}
    level_stats: dict[int, dict[str, Any]] = {}
    for level in levels:
        level_rows = [row for row in matched if row["level"] == level]
        font_sizes = [row["font_size"] for row in level_rows]
        heights = [row["height"] for row in level_rows]
        font_cluster = cluster_by_density(font_sizes)
        height_cluster = cluster_by_density(heights)
        clusters[level] = {"font_size": font_cluster, "height": height_cluster}
        level_stats[level] = {
            "count": len(level_rows),
            "font_size": {
                "median": round(float(np.median(font_sizes)), 2),
                "mean": round(float(np.mean(font_sizes)), 2),
                "std": round(float(np.std(font_sizes)), 2),
                "tier_count": font_cluster["tier_count"],
                "peaks": [round(p, 2) for p in font_cluster["peaks"]],
                "cut_points": [round(c, 2) for c in font_cluster["cut_points"]],
            },
            "height": {
                "median": round(float(np.median(heights)), 2),
                "mean": round(float(np.mean(heights)), 2),
                "std": round(float(np.std(heights)), 2),
                "tier_count": height_cluster["tier_count"],
                "peaks": [round(p, 2) for p in height_cluster["peaks"]],
                "cut_points": [round(c, 2) for c in height_cluster["cut_points"]],
            },
        }

    save_kde_grid(matched, clusters, OUTPUT_DIR / "kde_by_level.png")
    save_kde_overlay(matched, OUTPUT_DIR / "kde_overlay.png")

    tier_dump = render_tier_dump(matched, clusters)
    (OUTPUT_DIR / "tier_texts.txt").write_text("\n".join(tier_dump), encoding="utf-8")

    write_csv(OUTPUT_DIR / "bookmark_heading_matches.csv", matched)
    write_csv(OUTPUT_DIR / "bookmark_heading_unmatched.csv", unmatched)

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "target_id": TARGET_ID,
        "total_bookmarks": len(matched) + len(unmatched),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "match_rate": round(len(matched) / max(len(matched) + len(unmatched), 1), 4),
        "match_threshold": MATCH_THRESHOLD,
        "level_counts": dict(Counter(row["level"] for row in matched)),
        "level_stats": level_stats,
    }
    summary["finding"] = build_finding(summary)

    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    record_experiment(summary)

    print("\n=== exp 053: bookmark depth heading font size KDE ===")
    print(f"matched={len(matched)} unmatched={len(unmatched)} rate={summary['match_rate']}")
    for level in levels:
        stat = level_stats[level]
        print(
            f"- level {level}: n={stat['count']} font_size median={stat['font_size']['median']} "
            f"peaks={stat['font_size']['peaks']} tiers={stat['font_size']['tier_count']}"
        )
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
