"""experiment 032: y KDE 줄 재구성 후 x KDE indentation tier 확인.

목적:
- 기존 indentation 실험들은 PyMuPDF가 반환한 line을 그대로 쓰고, 줄의 첫 content span
  x 또는 gap 기반 binning으로 indentation column을 만들었다.
- 이번 실험은 span/textbox의 y 좌표를 먼저 KDE valley cut으로 tier화해 줄을 재구성한다.
- 같은 page의 같은 y tier에 있는 textbox를 x 방향으로 이어 붙인 뒤, 재구성 line들의
  min x를 다시 KDE valley cut으로 tier화해 indentation tier를 만든다.

실행:
    uv run python experiments/032_y_kde_line_indent.py
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import numpy as np

from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "032_y_kde_line_indent"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "032_y_kde_line_indent"

TARGETS = [
    {
        "id": "zvi_bodie_investments",
        "pdf": "data/native-pdf-indexed/Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf",
        "toc_pages": list(range(7, 17)),
    },
    {
        "id": "kim_econometrics_note1",
        "pdf": "data/scanned-pdf-indexed/고려대_계량경제학노트1_김창진-compressed-indexed[econ stats book].pdf",
        "toc_pages": [3],
    },
    {
        "id": "kim_econometrics_note2",
        "pdf": "data/scanned-pdf-indexed/고려대_계량경제학노트2_김창진-compressed-indexed[econ stats book].pdf",
        "toc_pages": list(range(21, 41)),
    },
    {
        "id": "quant_world",
        "pdf": "data/scanned-pdf-not-indexed/퀀트의 세계 - 홍창수.pdf",
        "toc_pages": list(range(17, 21)),
    },
    {
        "id": "hankyung_reader",
        "pdf": "data/scanned-pdf-not-indexed/한경_읽는법_-_한국경제신문-compressed[econ macro book].pdf",
        "toc_pages": [7],
    },
]

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_SUBSET = re.compile(r"^[A-Z]{6}\+")
_TITLE_WORDS = {
    "목차",
    "목 차",
    "차례",
    "contents",
    "contents in brief",
    "brief contents",
    "table of contents",
}


def is_content_text(text: str) -> bool:
    """계층 판단에 쓸 수 있는 글자 span인지 판정한다."""

    stripped = text.strip()
    return bool(stripped and (_HANGUL.search(stripped) or _LATIN2.search(stripped)))


def is_title_word(text: str) -> bool:
    """목차 머리말 단독 줄인지 판정한다."""

    return normalize_for_match(text) in _TITLE_WORDS


def base_font(name: str) -> str:
    """PDF subset prefix와 style suffix를 줄인 font family 문자열을 만든다."""

    return _SUBSET.sub("", name).split("-")[0].split(",")[0].lower()


def span_is_bold(span: dict[str, Any]) -> bool:
    """PyMuPDF flags/font 이름에서 bold 여부를 보수적으로 읽는다."""

    return bool(span["flags"] & 2**4) or ("bold" in span["font"].lower())


def cluster_cut_points(
    values: list[float],
    *,
    bandwidth: float | None = None,
    grid_size: int = 2048,
) -> list[float]:
    """1D 값 분포의 KDE valley를 cut point로 반환한다."""

    if not values:
        return []
    arr = np.asarray(values, dtype=float)
    if np.unique(arr).size <= 1:
        return []
    std = float(np.std(arr, ddof=1))
    if std <= 0.0:
        return []
    bandwidth = bandwidth or 1.06 * std * (len(arr) ** -0.2)
    if bandwidth <= 0.0 or not math.isfinite(bandwidth):
        return []
    grid = np.linspace(float(arr.min()) - 1.0, float(arr.max()) + 1.0, grid_size)
    z = (grid[:, None] - arr[None, :]) / bandwidth
    density = np.exp(-0.5 * z * z).sum(axis=1)
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
    return sorted(
        float(grid[index])
        for index in valley_idx
        if min(peaks) < float(grid[index]) < max(peaks)
    )


def band_low_first(value: float, cuts: list[float]) -> int:
    """작은 값이 1번이 되도록 1D band를 부여한다."""

    band = 1
    for cut in sorted(cuts):
        if value < cut:
            return band
        band += 1
    return band


def extract_textboxes(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """TOC page의 span/textbox들을 좌표와 함께 추출한다."""

    boxes: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pdf_page in toc_pages:
            if pdf_page < 1 or pdf_page > document.page_count:
                continue
            page = document.load_page(pdf_page - 1)
            width = float(page.rect.width)
            height = float(page.rect.height)
            for block_index, block in enumerate(page.get_text("dict")["blocks"]):
                for line_index, line in enumerate(block.get("lines", [])):
                    for span_index, span in enumerate(line.get("spans", [])):
                        text = normalize_text(span["text"])
                        if not text.strip():
                            continue
                        x0, y0, x1, y1 = [float(value) for value in span["bbox"]]
                        boxes.append(
                            {
                                "pdf_page": pdf_page,
                                "page_width": round(width, 2),
                                "page_height": round(height, 2),
                                "block_index": block_index,
                                "pymupdf_line_index": line_index,
                                "span_index": span_index,
                                "text": text,
                                "x0": round(x0, 2),
                                "y0": round(y0, 2),
                                "x1": round(x1, 2),
                                "y1": round(y1, 2),
                                "span_height": round(y1 - y0, 2),
                                "is_content": is_content_text(text),
                                "font_family": base_font(span["font"]),
                                "is_bold": span_is_bold(span),
                            }
                        )
    return boxes


def reconstruct_lines_from_y_kde(
    boxes: list[dict[str, Any]],
    *,
    split_vertical_halves: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """y KDE tier로 같은 row의 textbox를 이어 붙여 line을 만든다."""

    content_boxes = [box for box in boxes if box["is_content"]]
    y_values = [box["y0"] for box in content_boxes]
    # 줄 재구성은 page 전체 y 분포용 Scott bandwidth보다 훨씬 작은 대역폭이 필요하다.
    # span 높이의 일부를 bandwidth로 쓰면 줄 사이 valley를 보존하면서 같은 줄의 미세 y jitter만 묶는다.
    median_span_height = (
        float(np.median([box["span_height"] for box in content_boxes]))
        if content_boxes
        else 4.0
    )
    y_bandwidth = max(1.0, median_span_height * 0.3)
    y_cuts = cluster_cut_points(y_values, bandwidth=y_bandwidth, grid_size=8192)
    for box in boxes:
        box["y_tier"] = band_low_first(box["y0"], y_cuts)

    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for box in boxes:
        if not box["is_content"] and not re.search(r"\d", box["text"]):
            continue
        half = 1
        if split_vertical_halves:
            half = 1 if float(box["x0"]) < float(box["page_width"]) / 2 else 2
        key = (int(box["pdf_page"]), half, int(box["y_tier"]))
        grouped.setdefault(key, []).append(box)

    lines: list[dict[str, Any]] = []
    for (pdf_page, half, y_tier), members in sorted(grouped.items()):
        ordered = sorted(members, key=lambda value: (value["x0"], value["span_index"]))
        content_members = [member for member in ordered if member["is_content"]]
        if not content_members:
            continue
        text = normalize_text(" ".join(member["text"] for member in ordered))
        content_text = normalize_text(" ".join(member["text"] for member in content_members))
        min_x = min(member["x0"] for member in ordered)
        content_min_x = min(member["x0"] for member in content_members)
        lines.append(
            {
                "pdf_page": pdf_page,
                "vertical_half": half,
                "y_tier": y_tier,
                "text": text,
                "content_text": content_text,
                "min_x": round(min_x, 2),
                "content_min_x": round(content_min_x, 2),
                "y0_min": round(min(member["y0"] for member in ordered), 2),
                "y0_mean": round(float(np.mean([member["y0"] for member in ordered])), 2),
                "box_count": len(ordered),
                "content_box_count": len(content_members),
                "height_max": round(max(member["span_height"] for member in content_members), 2),
                "font_families": sorted({member["font_family"] for member in content_members}),
                "bold_count": sum(1 for member in content_members if member["is_bold"]),
                "source_boxes": [
                    {
                        "text": member["text"],
                        "x0": member["x0"],
                        "y0": member["y0"],
                        "is_content": member["is_content"],
                    }
                    for member in ordered
                ],
            }
        )

    x_cuts_all = cluster_cut_points([line["min_x"] for line in lines if not is_title_word(line["content_text"])])
    x_cuts_content = cluster_cut_points(
        [line["content_min_x"] for line in lines if not is_title_word(line["content_text"])]
    )
    for line in lines:
        line["indent_tier_min_x"] = band_low_first(line["min_x"], x_cuts_all)
        line["indent_tier_content_min_x"] = band_low_first(
            line["content_min_x"], x_cuts_content
        )

    debug = {
        "box_count": len(boxes),
        "content_box_count": len(content_boxes),
        "split_vertical_halves": split_vertical_halves,
        "y_bandwidth": round(y_bandwidth, 3),
        "median_span_height": round(median_span_height, 3),
        "y_cut_count": len(y_cuts),
        "y_cuts_preview": [round(value, 2) for value in y_cuts[:30]],
        "x_cut_count_min_x": len(x_cuts_all),
        "x_cuts_min_x": [round(value, 2) for value in x_cuts_all],
        "x_cut_count_content_min_x": len(x_cuts_content),
        "x_cuts_content_min_x": [round(value, 2) for value in x_cuts_content],
    }
    return lines, debug



def quantile(values: list[float], q: float) -> float | None:
    """정렬된 분위값을 간단히 계산한다."""

    if not values:
        return None
    ordered = sorted(values)
    index = int((len(ordered) - 1) * q)
    return ordered[index]


def analyze_vertical_half_need(boxes: list[dict[str, Any]]) -> dict[str, Any]:
    """content x 분포가 좌우 2단 목차처럼 크게 갈리는지 판정한다."""

    xs = [box["x0"] / box["page_width"] for box in boxes if box["is_content"]]
    ordered = sorted(xs)
    gaps = [
        (ordered[index + 1] - ordered[index], ordered[index], ordered[index + 1])
        for index in range(len(ordered) - 1)
    ]
    largest_gap = max(gaps, default=(0.0, None, None), key=lambda row: row[0])
    left_count = sum(1 for value in xs if value < 0.5)
    right_count = len(xs) - left_count
    balance = (
        min(left_count, right_count) / max(left_count, right_count)
        if left_count and right_count
        else 0.0
    )
    median_x = quantile(ordered, 0.5) or 0.0
    gap_width, gap_left, gap_right = largest_gap
    should_split = (
        len(xs) >= 40
        and balance >= 0.7
        and median_x >= 0.42
        and gap_width >= 0.06
        and gap_left is not None
        and gap_right is not None
        and 0.25 <= gap_left <= 0.5
        and 0.35 <= gap_right <= 0.65
    )
    return {
        "content_box_count": len(xs),
        "left_count": left_count,
        "right_count": right_count,
        "half_balance": round(balance, 4),
        "q10": round(quantile(ordered, 0.1) or 0.0, 4),
        "q50": round(median_x, 4),
        "q90": round(quantile(ordered, 0.9) or 0.0, 4),
        "largest_gap_width": round(gap_width, 4),
        "largest_gap_left": round(gap_left, 4) if gap_left is not None else None,
        "largest_gap_right": round(gap_right, 4) if gap_right is not None else None,
        "should_split_vertical_halves": should_split,
    }


def reconstruct_lines_after_partition_decision(
    boxes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """content x 분포로 vertical-half 여부를 먼저 정한 뒤 partition별 y-KDE를 수행한다."""

    decision = analyze_vertical_half_need(boxes)
    split_vertical_halves = bool(decision["should_split_vertical_halves"])
    partitions: dict[int, list[dict[str, Any]]] = {1: []}
    if split_vertical_halves:
        partitions = {1: [], 2: []}
    for box in boxes:
        half = 1
        if split_vertical_halves:
            half = 1 if float(box["x0"]) < float(box["page_width"]) / 2 else 2
        partitions.setdefault(half, []).append(box)

    tier_by_box_id: dict[int, int] = {}
    partition_debug: dict[str, Any] = {}
    for half, part_boxes in sorted(partitions.items()):
        content_boxes = [box for box in part_boxes if box["is_content"]]
        median_span_height = (
            float(np.median([box["span_height"] for box in content_boxes]))
            if content_boxes
            else 4.0
        )
        y_bandwidth = max(1.0, median_span_height * 0.3)
        y_cuts = cluster_cut_points(
            [box["y0"] for box in content_boxes],
            bandwidth=y_bandwidth,
            grid_size=8192,
        )
        for box in part_boxes:
            tier_by_box_id[id(box)] = band_low_first(box["y0"], y_cuts)
        partition_debug[str(half)] = {
            "box_count": len(part_boxes),
            "content_box_count": len(content_boxes),
            "median_span_height": round(median_span_height, 3),
            "y_bandwidth": round(y_bandwidth, 3),
            "y_cut_count": len(y_cuts),
            "y_cuts_preview": [round(value, 2) for value in y_cuts[:30]],
        }

    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for box in boxes:
        if not box["is_content"] and not re.search(r"\d", box["text"]):
            continue
        half = 1
        if split_vertical_halves:
            half = 1 if float(box["x0"]) < float(box["page_width"]) / 2 else 2
        key = (int(box["pdf_page"]), half, tier_by_box_id.get(id(box), 1))
        grouped.setdefault(key, []).append(box)

    lines: list[dict[str, Any]] = []
    for (pdf_page, half, y_tier), members in sorted(grouped.items()):
        ordered = sorted(members, key=lambda value: (value["x0"], value["span_index"]))
        content_members = [member for member in ordered if member["is_content"]]
        if not content_members:
            continue
        text = normalize_text(" ".join(member["text"] for member in ordered))
        content_text = normalize_text(" ".join(member["text"] for member in content_members))
        min_x = min(member["x0"] for member in ordered)
        content_min_x = min(member["x0"] for member in content_members)
        lines.append(
            {
                "pdf_page": pdf_page,
                "vertical_half": half,
                "y_tier": y_tier,
                "text": text,
                "content_text": content_text,
                "min_x": round(min_x, 2),
                "content_min_x": round(content_min_x, 2),
                "y0_min": round(min(member["y0"] for member in ordered), 2),
                "y0_mean": round(float(np.mean([member["y0"] for member in ordered])), 2),
                "box_count": len(ordered),
                "content_box_count": len(content_members),
                "height_max": round(max(member["span_height"] for member in content_members), 2),
                "font_families": sorted({member["font_family"] for member in content_members}),
                "bold_count": sum(1 for member in content_members if member["is_bold"]),
                "source_boxes": [
                    {
                        "text": member["text"],
                        "x0": member["x0"],
                        "y0": member["y0"],
                        "is_content": member["is_content"],
                    }
                    for member in ordered
                ],
            }
        )

    x_cuts_all = cluster_cut_points(
        [line["min_x"] for line in lines if not is_title_word(line["content_text"])]
    )
    x_cuts_content = cluster_cut_points(
        [
            line["content_min_x"]
            for line in lines
            if not is_title_word(line["content_text"])
        ]
    )
    for line in lines:
        line["indent_tier_min_x"] = band_low_first(line["min_x"], x_cuts_all)
        line["indent_tier_content_min_x"] = band_low_first(
            line["content_min_x"], x_cuts_content
        )

    debug = {
        "vertical_half_decision": decision,
        "split_vertical_halves": split_vertical_halves,
        "partition_y_kde": partition_debug,
        "x_cut_count_min_x": len(x_cuts_all),
        "x_cuts_min_x": [round(value, 2) for value in x_cuts_all],
        "x_cut_count_content_min_x": len(x_cuts_content),
        "x_cuts_content_min_x": [round(value, 2) for value in x_cuts_content],
    }
    return lines, debug
def extract_pymupdf_lines_old(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """기존 실험 계열처럼 PyMuPDF line과 첫 content span x를 그대로 사용한다."""

    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pdf_page in toc_pages:
            if pdf_page < 1 or pdf_page > document.page_count:
                continue
            page = document.load_page(pdf_page - 1)
            for block in page.get_text("dict")["blocks"]:
                for raw_line in block.get("lines", []):
                    spans = [span for span in raw_line.get("spans", []) if span["text"].strip()]
                    content_spans = [
                        span for span in spans if is_content_text(str(span["text"]))
                    ]
                    if not content_spans:
                        continue
                    content_spans.sort(key=lambda span: span["bbox"][0])
                    lines.append(
                        {
                            "pdf_page": pdf_page,
                            "text": normalize_text(" ".join(span["text"].strip() for span in spans)),
                            "title_x": round(float(content_spans[0]["bbox"][0]), 2),
                            "height_max": round(
                                max(
                                    float(span["bbox"][3] - span["bbox"][1])
                                    for span in content_spans
                                ),
                                2,
                            ),
                        }
                    )
    return lines


def summarize_indent(lines: list[dict[str, Any]], key: str) -> dict[str, int]:
    """indent tier 분포를 문자열 key dict로 만든다."""

    return {
        str(tier): count
        for tier, count in sorted(Counter(line[key] for line in lines).items())
    }


def preview_by_indent(lines: list[dict[str, Any]], key: str) -> dict[str, list[str]]:
    """indent tier별 대표 line을 몇 개만 뽑는다."""

    out: dict[str, list[str]] = {}
    for line in lines:
        if is_title_word(line["content_text"]):
            continue
        tier = str(line[key])
        out.setdefault(tier, [])
        if len(out[tier]) < 5:
            out[tier].append(line["content_text"][:120])
    return out


def run_one(target: dict[str, Any]) -> dict[str, Any]:
    """단일 PDF의 기존 line 방식과 y-KDE 재구성 방식을 비교한다."""

    pdf_path = ROOT_DIR / target["pdf"]
    record: dict[str, Any] = {
        "id": target["id"],
        "input_pdf": target["pdf"],
        "toc_pages": target["toc_pages"],
    }
    if not pdf_path.exists():
        record["status"] = "missing_pdf"
        return record

    boxes = extract_textboxes(pdf_path, target["toc_pages"])
    auto_lines, auto_debug = reconstruct_lines_after_partition_decision(boxes)
    new_lines, debug = reconstruct_lines_from_y_kde(boxes)
    half_lines, half_debug = reconstruct_lines_from_y_kde(
        boxes, split_vertical_halves=True
    )
    old_lines = extract_pymupdf_lines_old(pdf_path, target["toc_pages"])

    cid = target["id"]
    (OUTPUT_DIR / f"{cid}_boxes.json").write_text(
        json.dumps(boxes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / f"{cid}_lines_y_kde_auto.json").write_text(
        json.dumps(auto_lines, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / f"{cid}_lines_y_kde.json").write_text(
        json.dumps(new_lines, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / f"{cid}_lines_y_kde_vertical_halves.json").write_text(
        json.dumps(half_lines, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / f"{cid}_lines_pymupdf_old.json").write_text(
        json.dumps(old_lines, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    record.update(
        {
            "status": "ok",
            "old_pymupdf_line_count": len(old_lines),
            "auto_y_kde_line_count": len(auto_lines),
            "auto_line_count_delta": len(auto_lines) - len(old_lines),
            "auto_vertical_half": auto_debug["split_vertical_halves"],
            "auto_debug": auto_debug,
            "new_y_kde_line_count": len(new_lines),
            "line_count_delta": len(new_lines) - len(old_lines),
            "half_y_kde_line_count": len(half_lines),
            "half_line_count_delta": len(half_lines) - len(old_lines),
            "debug": debug,
            "half_debug": half_debug,
            "auto_indent_distribution_min_x": summarize_indent(
                auto_lines, "indent_tier_min_x"
            ),
            "auto_indent_distribution_content_min_x": summarize_indent(
                auto_lines, "indent_tier_content_min_x"
            ),
            "auto_preview_content_min_x": preview_by_indent(
                auto_lines, "indent_tier_content_min_x"
            ),
            "indent_distribution_min_x": summarize_indent(
                new_lines, "indent_tier_min_x"
            ),
            "indent_distribution_content_min_x": summarize_indent(
                new_lines, "indent_tier_content_min_x"
            ),
            "preview_min_x": preview_by_indent(new_lines, "indent_tier_min_x"),
            "preview_content_min_x": preview_by_indent(
                new_lines, "indent_tier_content_min_x"
            ),
            "half_indent_distribution_min_x": summarize_indent(
                half_lines, "indent_tier_min_x"
            ),
            "half_indent_distribution_content_min_x": summarize_indent(
                half_lines, "indent_tier_content_min_x"
            ),
            "half_preview_content_min_x": preview_by_indent(
                half_lines, "indent_tier_content_min_x"
            ),
        }
    )
    return record


def build_finding(results: list[dict[str, Any]]) -> str:
    """experiments.json에 남길 finding 문자열을 만든다."""

    parts: list[str] = []
    for result in results:
        if result.get("status") != "ok":
            parts.append(f"{result['id']}: {result.get('status')}")
            continue
        debug = result["debug"]
        parts.append(
            f"{result['id']}: old_lines={result['old_pymupdf_line_count']}, "
            f"auto_lines={result['auto_y_kde_line_count']} "
            f"(auto_delta={result['auto_line_count_delta']}, "
            f"auto_half={result['auto_vertical_half']}), "
            f"y_kde_lines={result['new_y_kde_line_count']} "
            f"(delta={result['line_count_delta']}), "
            f"half_lines={result['half_y_kde_line_count']} "
            f"(half_delta={result['half_line_count_delta']}), "
            f"y_cuts={debug['y_cut_count']}, "
            f"x_cuts_all={debug['x_cut_count_min_x']}, "
            f"x_cuts_content={debug['x_cut_count_content_min_x']}, "
            f"auto_indent_content={result['auto_indent_distribution_content_min_x']}, "
            f"indent_all={result['indent_distribution_min_x']}, "
            f"indent_content={result['indent_distribution_content_min_x']}, "
            f"half_indent_content={result['half_indent_distribution_content_min_x']}"
        )
    return " | ".join(parts)


def record_experiment(summary: dict[str, Any]) -> None:
    """실험 registry에 이번 결과를 기록한다."""

    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "data/ 아래 실제 PDF에서 TOC page의 span/textbox y 좌표를 KDE valley cut으로 "
            "줄 tier로 나누고, 같은 page와 y tier의 textbox를 x 방향으로 이어 붙여 line을 "
            "재구성한 뒤, line min x를 다시 KDE valley cut으로 indentation tier화한다. "
            "2단 목차에서 좌우 column이 같은 y tier로 합쳐지는 문제를 보기 위해 page를 "
            "세로 절반으로 나눈 vertical-half arm도 함께 비교한다. 실제 처리 후보는 "
            "content x 분포의 좌우 balance와 중앙 gap을 먼저 보고 vertical-half 여부를 "
            "결정한 뒤 y-KDE를 수행하는 auto arm이다."
        ),
        "inputs": [target["pdf"] for target in TARGETS],
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
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    """실험 entrypoint."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = [run_one(target) for target in TARGETS]
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "finding": build_finding(results),
        "results": results,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record_experiment(summary)

    print("=== exp 032: y KDE line reconstruction + x KDE indentation ===")
    for result in results:
        if result.get("status") != "ok":
            print(f"- {result['id']}: {result.get('status')}")
            continue
        debug = result["debug"]
        print(
            f"- {result['id']}: old={result['old_pymupdf_line_count']} "
            f"auto={result['auto_y_kde_line_count']} auto_delta={result['auto_line_count_delta']} "
            f"auto_half={result['auto_vertical_half']} "
            f"new={result['new_y_kde_line_count']} delta={result['line_count_delta']} "
            f"half={result['half_y_kde_line_count']} half_delta={result['half_line_count_delta']} "
            f"y_cuts={debug['y_cut_count']} x_all={debug['x_cut_count_min_x']} "
            f"x_content={debug['x_cut_count_content_min_x']}"
        )
        decision = result["auto_debug"]["vertical_half_decision"]
        print(f"  decision={decision}")
        print(f"  auto_indent_content={result['auto_indent_distribution_content_min_x']}")
        print(f"  indent_all={result['indent_distribution_min_x']}")
        print(f"  indent_content={result['indent_distribution_content_min_x']}")
        print(f"  half_indent_content={result['half_indent_distribution_content_min_x']}")
    print(summary["finding"])


if __name__ == "__main__":
    main()







