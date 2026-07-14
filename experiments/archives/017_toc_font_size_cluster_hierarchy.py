"""experiment 017: TOC 줄의 글씨 height만으로 계층 tier를 클러스터링한다.

문제: scanned OCR 책(예: '알고리즘 인생을 계산하다')의 목차는 장/절/소절을
번호 없이 '글씨 크기'로만 구분한다. 그런데 현재 파이프라인은 get_text("text")로
크기를 버린 평탄한 줄만 LLM에 넘겨 계층이 무너진다(showcase 006에서 확인).

가설: 목차 page의 textbox height 하나만 가지고 클러스터링하면, 사람이 보는
'큰 글씨/작은 글씨' tier가 그대로 복원된다. tier 개수는 책마다 다르므로
KMeans처럼 k를 고정하지 않고, 1D 밀도(KDE)의 봉우리 개수로 데이터가 정하게 한다.

이 실험은 LLM을 호출하지 않는다. height-only 클러스터링이 tier를 깨끗이
가르는지부터 결정론적으로 검증한다. 신호가 좋으면 다음 실험에서 이 tier를
enriched prompt로 LLM에 먹인다.

입력: experiments/labels/answer_toc_ranges_manual.json 의 GT TOC page range.
출력: experiments/outputs/017_toc_font_size_cluster_hierarchy/
    - <id>_tier_tree.txt : tier를 들여쓰기로 입힌 목차 전체 덤프(눈으로 검증)
    - <id>_height_kde.png : height 분포 + KDE + 봉우리/골짜기 cut
    - summary.json
실행:
    uv run python experiments/017_toc_font_size_cluster_hierarchy.py
"""

from __future__ import annotations

import json
import re
import sys
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
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = (
    ROOT_DIR / "experiments" / "outputs" / "017_toc_font_size_cluster_hierarchy"
)

# height 클러스터링에서 제외할 노이즈 span 판정용. 글자(한글/라틴 2자 이상)를
# 가진 span만 '내용 span'으로 본다. 불릿(•), 구분자(|, I), 페이지 번호(24)는 뺀다.
_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")


def _case_id(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_")[:80]


def is_content_span(text: str) -> bool:
    """글자를 담은 내용 span인지(불릿/구분자/순수 숫자 제외)."""

    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def extract_toc_lines(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """TOC page들에서 줄 단위 (대표 height, 텍스트)를 뽑는다.

    줄 대표 height = 그 줄의 내용 span bbox height 중 최댓값. 내용 span이 없는
    줄(순수 숫자/불릿 줄)은 목차 항목이 아니라 보고 버린다.
    """

    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pno in toc_pages:
            page = document.load_page(pno - 1)
            data = page.get_text("dict")
            for block in data["blocks"]:
                for line in block.get("lines", []):
                    content_heights: list[float] = []
                    parts: list[str] = []
                    for span in line["spans"]:
                        text = span["text"]
                        if not text.strip():
                            continue
                        parts.append(text.strip())
                        if is_content_span(text):
                            y0, y1 = span["bbox"][1], span["bbox"][3]
                            content_heights.append(round(y1 - y0, 2))
                    if not content_heights:
                        continue  # 내용 없는 줄(페이지 번호/장식)은 제외
                    lines.append(
                        {
                            "pdf_page": pno,
                            "height": max(content_heights),
                            "text": " ".join(parts),
                        }
                    )
    return lines


def cluster_heights_by_density(heights: list[float]) -> dict[str, Any]:
    """height 1D를 KDE 밀도의 봉우리/골짜기로 클러스터링한다(k 미고정).

    tier 개수 = KDE 봉우리(local maxima) 개수. 봉우리 사이 골짜기(local minima)를
    경계로 삼는다. 데이터가 거의 한 값이면 tier 1개로 본다.
    """

    arr = np.asarray(heights, dtype=float)
    uniq = np.unique(arr)
    if uniq.size == 1:
        return {
            "tier_count": 1,
            "cut_points": [],
            "peaks": [float(uniq[0])],
            "bandwidth": None,
        }

    # Scott 규칙(gaussian_kde 기본)으로 자동 bandwidth. k도 봉우리도 손으로 안 정한다.
    kde = gaussian_kde(arr)
    grid = np.linspace(arr.min() - 1.0, arr.max() + 1.0, 1024)
    density = kde(grid)

    peak_idx = argrelextrema(density, np.greater)[0]
    valley_idx = argrelextrema(density, np.less)[0]
    if peak_idx.size == 0:  # 안전장치: 봉우리를 못 찾으면 단일 tier
        return {
            "tier_count": 1,
            "cut_points": [],
            "peaks": [float(np.median(arr))],
            "bandwidth": float(kde.factor),
        }

    peaks = [float(grid[i]) for i in peak_idx]
    # 봉우리 사이에 있는 골짜기만 경계로 채택한다.
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
    }


def assign_tier(height: float, cut_points: list[float]) -> int:
    """height를 cut_points로 나눈 tier로 매핑한다(T1 = 가장 큰 글씨)."""

    # 큰 height일수록 작은 tier 번호. cut을 큰 값부터 비교한다.
    tier = 1
    for cut in sorted(cut_points, reverse=True):
        if height >= cut:
            return tier
        tier += 1
    return tier


def render_tier_tree(lines: list[dict[str, Any]], cut_points: list[float]) -> list[str]:
    """tier를 들여쓰기로 입힌 목차 전체 덤프를 만든다(자르지 않는다)."""

    out: list[str] = []
    for line in lines:
        tier = assign_tier(line["height"], cut_points)
        indent = "    " * (tier - 1)
        out.append(f"{indent}[T{tier} h={line['height']:.1f}] {line['text']}")
    return out


def save_kde_plot(
    heights: list[float], cluster: dict[str, Any], path: Path, title: str
) -> None:
    arr = np.asarray(heights, dtype=float)
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.hist(arr, bins=40, density=True, color="#b0c4de", alpha=0.7, label="height hist")
    if np.unique(arr).size > 1:
        kde = gaussian_kde(arr)
        grid = np.linspace(arr.min() - 1.0, arr.max() + 1.0, 512)
        ax.plot(grid, kde(grid), color="#1f4e79", lw=2, label="KDE")
    for peak in cluster["peaks"]:
        ax.axvline(peak, color="#2e7d32", ls="--", lw=1)
    for cut in cluster["cut_points"]:
        ax.axvline(cut, color="#c62828", ls=":", lw=1.5)
    ax.set_title(f"{title}  (tiers={cluster['tier_count']})")
    ax.set_xlabel("textbox height")
    ax.set_ylabel("density")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run_book(label: dict[str, Any]) -> dict[str, Any]:
    pdf_path = ROOT_DIR / label["input_pdf"]
    case_id = label["id"]
    record: dict[str, Any] = {
        "id": case_id,
        "input_pdf": label["input_pdf"],
        "toc_pages": label["toc_pages"],
    }
    if not pdf_path.exists():
        record["status"] = "missing_pdf"
        return record

    lines = extract_toc_lines(pdf_path, label["toc_pages"])
    if not lines:
        record["status"] = "no_lines"
        return record

    heights = [line["height"] for line in lines]
    cluster = cluster_heights_by_density(heights)

    tier_tree = render_tier_tree(lines, cluster["cut_points"])
    tree_path = OUTPUT_DIR / f"{_case_id(case_id)}_tier_tree.txt"
    tree_path.write_text("\n".join(tier_tree) + "\n", encoding="utf-8")

    plot_path = OUTPUT_DIR / f"{_case_id(case_id)}_height_kde.png"
    save_kde_plot(heights, cluster, plot_path, case_id)

    # tier별 줄 수와 height 범위.
    tier_stats: dict[int, dict[str, Any]] = {}
    for line in lines:
        tier = assign_tier(line["height"], cluster["cut_points"])
        bucket = tier_stats.setdefault(
            tier, {"count": 0, "min_h": line["height"], "max_h": line["height"]}
        )
        bucket["count"] += 1
        bucket["min_h"] = min(bucket["min_h"], line["height"])
        bucket["max_h"] = max(bucket["max_h"], line["height"])

    record.update(
        {
            "status": "ok",
            "line_count": len(lines),
            "tier_count": cluster["tier_count"],
            "peaks": [round(p, 2) for p in cluster["peaks"]],
            "cut_points": [round(c, 2) for c in cluster["cut_points"]],
            "bandwidth_factor": cluster["bandwidth"],
            "tier_stats": {
                str(t): {
                    "count": s["count"],
                    "height_range": [round(s["min_h"], 1), round(s["max_h"], 1)],
                }
                for t, s in sorted(tier_stats.items())
            },
            "tier_tree_file": str(tree_path.relative_to(ROOT_DIR)),
            "kde_plot_file": str(plot_path.relative_to(ROOT_DIR)),
            "tier_tree_preview": tier_tree[:18],
        }
    )
    return record


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]
    results = [run_book(label) for label in labels]

    summary = {
        "purpose": (
            "TOC 줄의 textbox height만으로 계층 tier를 클러스터링한다. tier 개수는 "
            "KMeans처럼 고정하지 않고 1D KDE 밀도의 봉우리 개수로 데이터가 정한다. "
            "LLM은 호출하지 않는다."
        ),
        "clustering": "1D gaussian_kde(Scott bandwidth) 봉우리/골짜기, k 미고정",
        "labels_source": str(LABELS_PATH.relative_to(ROOT_DIR)),
        "results": results,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=== TOC height-only 밀도 클러스터링 (k 미고정) ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']}: {r.get('status')}")
            continue
        print(
            f"\n- {r['id']}: tiers={r['tier_count']} "
            f"peaks={r['peaks']} cuts={r['cut_points']} lines={r['line_count']}"
        )
        for tier, stat in r["tier_stats"].items():
            print(
                f"    T{tier}: {stat['count']}줄 height {stat['height_range']}"
            )
        print("    tier tree preview:")
        for line in r["tier_tree_preview"][:12]:
            print(f"      {line}")


if __name__ == "__main__":
    main()
