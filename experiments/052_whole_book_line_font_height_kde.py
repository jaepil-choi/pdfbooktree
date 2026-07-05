"""experiment 052: 책 전체 line의 font height/size 분포로 valley cut이 되는지 본다.

발상 전환: 지금까지는 TOC page 안에서만 글씨 크기 tier를 클러스터링했다(017, 018).
이번에는 관점을 바꿔서 "책 한 권 전체"에 쓰인 폰트가 실제로 몇 종류(title/chapter/
section/body)로 제한돼 있다는 가설을 검증한다. Document Parse(외부 API)는 쓰지 않고
로컬 fitz(PyMuPDF)만으로 John Hull 책 881페이지 전부를 line 단위로 훑어, line마다
대표 font height(내용 span bbox 높이)와 font size(PDF 폰트 크기 속성)를 뽑는다.

가설: 책 전체 line의 font height/size를 모아 KDE를 그리면, body 본문 폰트가 압도적으로
큰 단일 봉우리를 이루고, 그보다 드물고 큰 폰트(장 제목, 절 제목, 책 제목)가 별도의
작은 봉우리로 나뉘어, 봉우리 사이 골짜기(valley)로 자동 cut할 수 있을 것이다.

이 실험은 TOC page range와 무관하게 책 "본문 전체"를 대상으로 한다. LLM은 호출하지
않는다. bbox height와 PDF font size 속성 두 신호를 나란히 비교해 어느 쪽이 더 깨끗한
valley를 주는지도 본다.

실행:
    uv run python experiments/052_whole_book_line_font_height_kde.py
출력:
    experiments/outputs/052_whole_book_line_font_height_kde/
        - line_font_data.csv   : 전체 book의 line별 (page, height, font_size, text 일부)
        - kde_height.png       : bbox height KDE(선형/로그 y축)
        - kde_font_size.png    : font size KDE(선형/로그 y축)
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
from scipy.signal import argrelextrema
from scipy.stats import gaussian_kde

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "052_whole_book_line_font_height_kde"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

TARGET_PDF = (
    ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf"
)
TARGET_ID = "john_hull"

# 내용 span 판정: 불릿/구분자/순수 숫자(page number) 줄은 폰트 tier 신호로 안 쓴다.
_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def extract_book_lines(pdf_path: Path) -> list[dict[str, Any]]:
    """책 전체 page를 훑어 line 단위 대표 height/font_size/text를 뽑는다."""

    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            data = page.get_text("dict")
            for block in data["blocks"]:
                for line in block.get("lines", []):
                    content_heights: list[float] = []
                    content_sizes: list[float] = []
                    is_bold = False
                    parts: list[str] = []
                    for span in line["spans"]:
                        text = span["text"]
                        if not text.strip():
                            continue
                        parts.append(text.strip())
                        if is_content_span(text):
                            y0, y1 = span["bbox"][1], span["bbox"][3]
                            content_heights.append(round(y1 - y0, 2))
                            content_sizes.append(round(float(span["size"]), 2))
                            if span.get("flags", 0) & (1 << 4):
                                is_bold = True
                    if not content_heights:
                        continue  # 페이지 번호/장식 줄 등 내용 없는 줄은 제외
                    lines.append(
                        {
                            "pdf_page": page_index + 1,
                            "height": max(content_heights),
                            "font_size": max(content_sizes),
                            "is_bold": int(is_bold),
                            "text": " ".join(parts)[:120],
                        }
                    )
    return lines


def cluster_by_density(values: list[float]) -> dict[str, Any]:
    """1D 값을 KDE 밀도의 봉우리/골짜기로 클러스터링한다(k 미고정)."""

    arr = np.asarray(values, dtype=float)
    uniq = np.unique(arr)
    if uniq.size == 1:
        return {
            "tier_count": 1,
            "cut_points": [],
            "peaks": [float(uniq[0])],
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
        }

    peaks = [float(grid[i]) for i in peak_idx]
    cut_points: list[float] = []
    for vi in valley_idx:
        v = grid[vi]
        if peaks[0] < v < peaks[-1]:
            cut_points.append(float(v))
    cut_points = sorted(cut_points)[: max(len(peaks) - 1, 0)]

    return {
        "tier_count": len(peaks),
        "cut_points": cut_points,
        "peaks": sorted(peaks, reverse=True),
        "bandwidth": float(kde.factor),
        "grid": grid,
        "density": density,
    }


def assign_tier(value: float, cut_points: list[float]) -> int:
    """value를 cut_points로 나눈 tier로 매핑한다(T1 = 가장 큰 값)."""

    tier = 1
    for cut in sorted(cut_points, reverse=True):
        if value >= cut:
            return tier
        tier += 1
    return tier


def tier_samples(
    lines: list[dict[str, Any]], key: str, cut_points: list[float], top_n: int = 6
) -> dict[str, Any]:
    """tier별 line 개수와 대표 text 샘플(빈도 상위)을 모은다."""

    buckets: dict[int, Counter[str]] = {}
    counts: Counter[int] = Counter()
    for line in lines:
        tier = assign_tier(line[key], cut_points)
        counts[tier] += 1
        buckets.setdefault(tier, Counter())[line["text"].strip()] += 1
    out: dict[str, Any] = {}
    for tier in sorted(counts):
        samples = [text for text, _ in buckets[tier].most_common(top_n)]
        out[f"T{tier}"] = {"line_count": counts[tier], "sample_texts": samples}
    return out


def save_kde_figure(
    values: list[float], cluster: dict[str, Any], path: Path, label: str
) -> None:
    arr = np.asarray(values, dtype=float)
    fig, axes = plt.subplots(1, 2, figsize=(16, 5))
    for ax, yscale in zip(axes, ["linear", "log"]):
        ax.hist(arr, bins=80, density=True, color="#b0c4de", alpha=0.7, label="hist")
        if "grid" in cluster:
            ax.plot(cluster["grid"], cluster["density"], color="#1f4e79", lw=2, label="KDE")
        for peak in cluster["peaks"]:
            ax.axvline(peak, color="#2e7d32", ls="--", lw=1)
        for cut in cluster["cut_points"]:
            ax.axvline(cut, color="#c62828", ls=":", lw=1.5)
        ax.set_yscale(yscale)
        ax.set_xlabel(label)
        ax.set_ylabel(f"density ({yscale})")
        ax.legend(loc="upper right", fontsize=8)
    fig.suptitle(f"{TARGET_ID}: {label} 전체 book KDE (tiers={cluster['tier_count']})")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


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
    h = summary["height_cluster"]
    s = summary["font_size_cluster"]
    h_top = summary["height_tier_samples"]["T1"]
    s_top = summary["font_size_tier_samples"]["T1"]
    return (
        f"{TARGET_ID} 책 전체 {summary['total_pages']}페이지, {summary['line_count']}줄에서 "
        f"bbox height KDE는 tiers={h['tier_count']}(peaks={[round(p, 2) for p in h['peaks']]}, "
        f"cuts={[round(c, 2) for c in h['cut_points']]}), "
        f"font size KDE는 tiers={s['tier_count']}(peaks={[round(p, 2) for p in s['peaks']]}, "
        f"cuts={[round(c, 2) for c in s['cut_points']]})로 나뉘었다. "
        f"height 최상위 tier(T1)는 {h_top['line_count']}줄, 샘플={h_top['sample_texts'][:3]}. "
        f"font_size 최상위 tier(T1)는 {s_top['line_count']}줄, 샘플={s_top['sample_texts'][:3]}."
    )


def record_experiment(summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "TOC page 안이 아니라 책 전체 본문에서, 책에 쓰이는 font가 title/chapter/"
            "section/body 소수의 tier로 제한되어 있다는 가설을 검증한다. Document Parse "
            "없이 로컬 fitz만으로 John Hull 881페이지 전체 line의 bbox height와 PDF "
            "font size 속성을 모아 KDE 봉우리/골짜기로 valley cut이 되는지 본다."
        ),
        "inputs": [str(TARGET_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "clustering": "1D gaussian_kde(Scott bandwidth) 봉우리/골짜기, k 미고정, 책 전체 line 대상",
        "finding": summary["finding"],
        "ran_at": summary["ran_at"],
    }
    experiments = data.get("experiments", data) if isinstance(data, dict) else data
    experiments = [
        experiment for experiment in experiments if experiment.get("id") != EXPERIMENT_ID
    ]
    experiments.append(entry)
    if isinstance(data, dict):
        data["experiments"] = experiments
    else:
        data = experiments
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"... {TARGET_ID} 전체 page 훑는 중: {TARGET_PDF.name}", flush=True)
    lines = extract_book_lines(TARGET_PDF)
    with fitz.open(TARGET_PDF) as document:
        total_pages = document.page_count
    print(f"    total_pages={total_pages}, extracted_lines={len(lines)}", flush=True)

    heights = [line["height"] for line in lines]
    font_sizes = [line["font_size"] for line in lines]

    height_cluster = cluster_by_density(heights)
    font_size_cluster = cluster_by_density(font_sizes)

    height_samples = tier_samples(lines, "height", height_cluster["cut_points"])
    font_size_samples = tier_samples(lines, "font_size", font_size_cluster["cut_points"])

    save_kde_figure(heights, height_cluster, OUTPUT_DIR / "kde_height.png", "bbox height")
    save_kde_figure(
        font_sizes, font_size_cluster, OUTPUT_DIR / "kde_font_size.png", "pdf font size"
    )

    csv_rows = [
        {
            "pdf_page": line["pdf_page"],
            "height": line["height"],
            "font_size": line["font_size"],
            "is_bold": line["is_bold"],
            "text": line["text"],
        }
        for line in lines
    ]
    write_csv(OUTPUT_DIR / "line_font_data.csv", csv_rows)

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "target_id": TARGET_ID,
        "total_pages": total_pages,
        "line_count": len(lines),
        "height_cluster": {
            key: value for key, value in height_cluster.items() if key not in ("grid", "density")
        },
        "font_size_cluster": {
            key: value
            for key, value in font_size_cluster.items()
            if key not in ("grid", "density")
        },
        "height_tier_samples": height_samples,
        "font_size_tier_samples": font_size_samples,
    }
    summary["finding"] = build_finding(summary)

    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record_experiment(summary)

    print("\n=== exp 052: whole-book line font height KDE ===")
    print(
        f"height: tiers={height_cluster['tier_count']} "
        f"peaks={[round(p, 2) for p in height_cluster['peaks']]} "
        f"cuts={[round(c, 2) for c in height_cluster['cut_points']]}"
    )
    print(
        f"font_size: tiers={font_size_cluster['tier_count']} "
        f"peaks={[round(p, 2) for p in font_size_cluster['peaks']]} "
        f"cuts={[round(c, 2) for c in font_size_cluster['cut_points']]}"
    )
    print("\nheight tier samples:")
    for tier, info in height_samples.items():
        print(f"  {tier}: n={info['line_count']} {info['sample_texts'][:3]}")
    print("\nfont_size tier samples:")
    for tier, info in font_size_samples.items():
        print(f"  {tier}: n={info['line_count']} {info['sample_texts'][:3]}")
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
