"""experiment 033: vertical half pane별 indent KDE valley cut 비교.

목적:
- 032에서 vertical half 여부를 count balance/median/gap 같은 여러 조건으로 판정했다.
- 더 단순하고 설명 가능한 신호로, page를 좌우 half로 나눈 뒤 각 pane 내부에서 y-KDE로
  line을 먼저 만들고 line indent x의 KDE와 valley cut이 서로 비슷한지 확인한다.
- 우선 Zvi Bodie Investments 목차 page에서 left/right pane의 pane-local line indent KDE를
  겹쳐 plot으로 확인한다.

실행:
    uv run python experiments/033_half_pane_indent_kde.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pdfbooktree.utils.text_normalize import normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "033_half_pane_indent_kde"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"

TARGET = {
    "id": "zvi_bodie_investments_page10",
    "pdf": "data/native-pdf-indexed/Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf",
    "toc_pages": [10],
}

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")


def is_content_text(text: str) -> bool:
    """계층 판단에 쓸 수 있는 글자 span인지 판정한다."""

    stripped = text.strip()
    return bool(stripped and (_HANGUL.search(stripped) or _LATIN2.search(stripped)))


def extract_content_boxes(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """TOC page의 content span bbox를 추출한다."""

    boxes: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pdf_page in toc_pages:
            page = document.load_page(pdf_page - 1)
            page_width = float(page.rect.width)
            for block_index, block in enumerate(page.get_text("dict")["blocks"]):
                for line_index, line in enumerate(block.get("lines", [])):
                    for span_index, span in enumerate(line.get("spans", [])):
                        text = normalize_text(span["text"])
                        if not is_content_text(text):
                            continue
                        x0, y0, x1, y1 = [float(value) for value in span["bbox"]]
                        pane = "left" if x0 < page_width / 2 else "right"
                        pane_origin = 0.0 if pane == "left" else page_width / 2
                        pane_width = page_width / 2
                        boxes.append(
                            {
                                "pdf_page": pdf_page,
                                "block_index": block_index,
                                "line_index": line_index,
                                "span_index": span_index,
                                "text": text,
                                "pane": pane,
                                "page_width": round(page_width, 2),
                                "x0": round(x0, 2),
                                "y0": round(y0, 2),
                                "x1": round(x1, 2),
                                "y1": round(y1, 2),
                                "pane_x": round((x0 - pane_origin) / pane_width, 4),
                            }
                        )
    return boxes


def kde_density(
    values: list[float],
    *,
    bandwidth: float | None = None,
    grid_size: int = 2048,
    unit_range: bool = False,
) -> tuple[np.ndarray, np.ndarray, float]:
    """1D Gaussian KDE density를 계산한다."""

    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return np.asarray([]), np.asarray([]), 0.0
    std = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    if bandwidth is None:
        bandwidth = 1.06 * std * (arr.size ** -0.2) if std > 0.0 else 0.02
    bandwidth = max(float(bandwidth), 0.01)
    if unit_range:
        grid_min, grid_max = -0.02, 1.02
    else:
        value_min = float(np.min(arr))
        value_max = float(np.max(arr))
        padding = max(bandwidth * 3.0, (value_max - value_min) * 0.05, 1e-6)
        grid_min = value_min - padding
        grid_max = value_max + padding
    grid = np.linspace(grid_min, grid_max, grid_size)
    z = (grid[:, None] - arr[None, :]) / bandwidth
    density = np.exp(-0.5 * z * z).sum(axis=1)
    area = np.trapezoid(density, grid)
    if area > 0:
        density = density / area
    return grid, density, bandwidth


def valley_cuts(grid: np.ndarray, density: np.ndarray) -> list[float]:
    """KDE peak 사이 valley를 cut 후보로 반환한다."""

    if len(grid) < 3:
        return []
    peak_idx = [
        index
        for index in range(1, len(density) - 1)
        if density[index - 1] < density[index] > density[index + 1]
    ]
    if not peak_idx:
        return []
    valley_idx = [
        index
        for index in range(1, len(density) - 1)
        if density[index - 1] > density[index] < density[index + 1]
    ]
    peaks = [float(grid[index]) for index in peak_idx]
    return [
        float(grid[index])
        for index in valley_idx
        if min(peaks) < float(grid[index]) < max(peaks)
    ]



def cluster_cut_points(
    values: list[float],
    *,
    bandwidth: float | None = None,
    grid_size: int = 8192,
) -> list[float]:
    """1D 값 분포의 KDE valley cut을 계산한다."""

    if not values:
        return []
    grid, density, _ = kde_density(values, bandwidth=bandwidth, grid_size=grid_size)
    return valley_cuts(grid, density)


def band_low_first(value: float, cuts: list[float]) -> int:
    """작은 값이 1번이 되도록 band를 부여한다."""

    band = 1
    for cut in sorted(cuts):
        if value < cut:
            return band
        band += 1
    return band


def reconstruct_half_lines(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """vertical half 안에서 y-KDE로 line을 재구성하고 line indent를 계산한다."""

    partitions = {"left": [], "right": []}
    for box in boxes:
        partitions[box["pane"]].append(box)

    tier_by_box_id: dict[int, int] = {}
    for pane_boxes in partitions.values():
        heights = [box["y1"] - box["y0"] for box in pane_boxes]
        median_height = float(np.median(heights)) if heights else 4.0
        bandwidth = max(1.0, median_height * 0.3)
        y_cuts = cluster_cut_points(
            [box["y0"] for box in pane_boxes],
            bandwidth=bandwidth,
            grid_size=8192,
        )
        for box in pane_boxes:
            tier_by_box_id[id(box)] = band_low_first(box["y0"], y_cuts)

    grouped: dict[tuple[int, str, int], list[dict[str, Any]]] = {}
    for box in boxes:
        key = (int(box["pdf_page"]), str(box["pane"]), tier_by_box_id[id(box)])
        grouped.setdefault(key, []).append(box)

    lines: list[dict[str, Any]] = []
    for (pdf_page, pane, y_tier), members in sorted(grouped.items()):
        ordered = sorted(members, key=lambda value: (value["x0"], value["span_index"]))
        page_width = float(ordered[0]["page_width"])
        pane_origin = 0.0 if pane == "left" else page_width / 2
        pane_width = page_width / 2
        content_min_x = min(member["x0"] for member in ordered)
        pane_indent_x = (content_min_x - pane_origin) / pane_width
        lines.append(
            {
                "pdf_page": pdf_page,
                "pane": pane,
                "y_tier": y_tier,
                "content_text": normalize_text(" ".join(member["text"] for member in ordered)),
                "content_min_x": round(content_min_x, 2),
                "pane_indent_x": round(pane_indent_x, 4),
                "box_count": len(ordered),
            }
        )
    return lines
def pane_stats(values: list[float]) -> dict[str, Any]:
    """pane별 x 분포와 valley cut 요약을 만든다."""

    grid, density, bandwidth = kde_density(values, unit_range=True)
    cuts = valley_cuts(grid, density)
    return {
        "count": len(values),
        "bandwidth": round(bandwidth, 4),
        "q10": round(float(np.quantile(values, 0.1)), 4),
        "q50": round(float(np.quantile(values, 0.5)), 4),
        "q90": round(float(np.quantile(values, 0.9)), 4),
        "valley_cuts": [round(value, 4) for value in cuts],
        "grid": grid,
        "density": density,
    }


def plot_overlay(stats: dict[str, dict[str, Any]], output_path: Path) -> None:
    """left/right pane KDE와 valley cut을 한 그림에 그린다."""

    width, height = 1400, 820
    margin_left, margin_right = 110, 40
    margin_top, margin_bottom = 70, 115
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    colors = {"left": "#246BFE", "right": "#E4572E"}
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    all_density = np.concatenate([stats[pane]["density"] for pane in ["left", "right"]])
    y_max = float(np.max(all_density)) * 1.08 if all_density.size else 1.0

    def px(x_value: float) -> float:
        return margin_left + x_value * plot_width

    def py(y_value: float) -> float:
        return margin_top + plot_height - (y_value / y_max) * plot_height

    draw.rectangle(
        [margin_left, margin_top, margin_left + plot_width, margin_top + plot_height],
        outline="#222222",
        width=1,
    )
    for tick in np.linspace(0.0, 1.0, 6):
        x = px(float(tick))
        draw.line([x, margin_top, x, margin_top + plot_height], fill="#E5E5E5")
        draw.text((x - 10, margin_top + plot_height + 12), f"{tick:.1f}", fill="#222222", font=font)
    for tick in np.linspace(0.0, y_max, 5):
        y = py(float(tick))
        draw.line([margin_left, y, margin_left + plot_width, y], fill="#EDEDED")
        draw.text((18, y - 6), f"{tick:.1f}", fill="#222222", font=font)

    draw.text((margin_left, 25), "Zvi Bodie TOC: pane-local line indent KDE", fill="#111111", font=font)
    draw.text((margin_left + plot_width / 2 - 95, height - 45), "line min x / half-page width", fill="#111111", font=font)
    draw.text((20, margin_top - 28), "density", fill="#111111", font=font)

    for pane in ["left", "right"]:
        pane_stat = stats[pane]
        points = [
            (px(float(x_value)), py(float(y_value)))
            for x_value, y_value in zip(pane_stat["grid"], pane_stat["density"], strict=True)
        ]
        if len(points) > 1:
            draw.line(points, fill=colors[pane], width=4)
        for cut in pane_stat["valley_cuts"]:
            x = px(cut)
            draw.line([x, margin_top, x, margin_top + plot_height], fill=colors[pane], width=2)

    legend_x = width - 360
    legend_y = 35
    for offset, pane in enumerate(["left", "right"]):
        y = legend_y + offset * 26
        draw.line([legend_x, y + 7, legend_x + 48, y + 7], fill=colors[pane], width=4)
        draw.text(
            (legend_x + 58, y),
            f"{pane} pane KDE (n={stats[pane]['count']})",
            fill="#111111",
            font=font,
        )
    image.save(output_path)


def cut_similarity(left_cuts: list[float], right_cuts: list[float]) -> dict[str, Any]:
    """좌우 valley cut 위치가 얼마나 비슷한지 간단히 요약한다."""

    if not left_cuts or not right_cuts:
        return {"matched_count": 0, "mean_abs_diff": None, "max_abs_diff": None}
    diffs = [min(abs(left - right) for right in right_cuts) for left in left_cuts]
    return {
        "matched_count": len(diffs),
        "mean_abs_diff": round(float(np.mean(diffs)), 4),
        "max_abs_diff": round(float(np.max(diffs)), 4),
    }


def build_finding(summary: dict[str, Any]) -> str:
    """experiments.json에 남길 finding 문자열을 만든다."""

    left = summary["pane_stats"]["left"]
    right = summary["pane_stats"]["right"]
    similarity = summary["cut_similarity"]
    return (
        "Zvi Bodie TOC를 vertical half로 나눈 뒤 y-KDE로 line을 재구성하고 pane-local line indent x를 KDE로 "
        f"겹쳐 그렸다. left/right count={left['count']}/{right['count']}, "
        f"left cuts={left['valley_cuts']}, right cuts={right['valley_cuts']}, "
        f"cut mean_abs_diff={similarity['mean_abs_diff']}, "
        f"max_abs_diff={similarity['max_abs_diff']}이다. "
        "좌우 pane의 KDE peak/valley 위치가 유사하면 half split이 단순 count/gap "
        "휴리스틱보다 강한 2단 목차 증거로 쓸 수 있다."
    )


def record_experiment(summary: dict[str, Any]) -> None:
    """실험 registry에 이번 결과를 기록한다."""

    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "Zvi Bodie Investments TOC page를 좌우 vertical half로 나누고, 각 pane 내부 "
            "y-KDE로 line을 만든 뒤 line indent x 분포의 KDE와 valley cut을 같은 축에 "
            "겹쳐 그려 half split 여부를 판정할 더 단순한 신호가 되는지 확인한다."
        ),
        "inputs": [TARGET["pdf"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "model": "none(deterministic)",
        "finding": summary["finding"],
        "ran_at": summary["ran_at"],
    }
    registry["experiments"] = [
        experiment
        for experiment in registry["experiments"]
        if experiment.get("id") != EXPERIMENT_ID
    ]
    registry["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """실험 entrypoint."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = ROOT_DIR / TARGET["pdf"]
    boxes = extract_content_boxes(pdf_path, TARGET["toc_pages"])
    lines = reconstruct_half_lines(boxes)
    values_by_pane = {
        "left": [line["pane_indent_x"] for line in lines if line["pane"] == "left"],
        "right": [line["pane_indent_x"] for line in lines if line["pane"] == "right"],
    }
    stats = {pane: pane_stats(values) for pane, values in values_by_pane.items()}
    plot_path = OUTPUT_DIR / "zvi_bodie_page10_half_pane_indent_kde.png"
    plot_overlay(stats, plot_path)

    serializable_stats = {
        pane: {
            key: value
            for key, value in pane_stat.items()
            if key not in {"grid", "density"}
        }
        for pane, pane_stat in stats.items()
    }
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "target": TARGET,
        "plot": str(plot_path.relative_to(ROOT_DIR)),
        "content_box_count": len(boxes),
        "line_count": len(lines),
        "pane_stats": serializable_stats,
        "cut_similarity": cut_similarity(
            stats["left"]["valley_cuts"], stats["right"]["valley_cuts"]
        ),
    }
    summary["finding"] = build_finding(summary)

    (OUTPUT_DIR / "content_boxes.json").write_text(
        json.dumps(boxes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "half_lines.json").write_text(
        json.dumps(lines, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_experiment(summary)

    print("=== exp 033: half pane indent KDE ===")
    print(summary["finding"])
    print(f"plot: {plot_path}")


if __name__ == "__main__":
    main()











