from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.preprocessing import StandardScaler


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "009_unsupervised_page_shape_classification"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DATA_DIR = ROOT_DIR / "data"

GRID_SIZE = 4
TOP_CANDIDATE_COUNT = 30
TOP_CROP_COUNT = 20


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def slugify(value: str, limit: int = 80) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value).strip("_")
    return (slug or "pdf")[:limit]


def percentile(values: list[float], q: float, default: float = 0.0) -> float:
    if not values:
        return default
    return float(np.percentile(np.array(values, dtype=float), q))


def mean(values: list[float], default: float = 0.0) -> float:
    if not values:
        return default
    return float(statistics.fmean(values))


def median(values: list[float], default: float = 0.0) -> float:
    if not values:
        return default
    return float(statistics.median(values))


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def minmax_scale(values: list[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if math.isclose(low, high):
        return [0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def robust_z(value: float, values: list[float]) -> float:
    if not values:
        return 0.0
    center = median(values)
    deviations = [abs(item - center) for item in values]
    mad = median(deviations)
    if mad <= 1e-9:
        return 0.0
    return (value - center) / (1.4826 * mad)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def find_input_pdfs(data_dir: Path) -> list[Path]:
    return sorted(data_dir.rglob("*.pdf"), key=lambda path: str(path).lower())


def extract_bookmarks(document: fitz.Document) -> list[dict[str, Any]]:
    bookmarks = []
    for order, item in enumerate(document.get_toc(simple=False), start=1):
        level, title, pdf_page = item[:3]
        bookmarks.append(
            {
                "order": order,
                "level": int(level),
                "title": normalize_text(title),
                "pdf_page": int(pdf_page) if pdf_page and pdf_page > 0 else None,
            }
        )
    return bookmarks


def extract_page_boxes(page: fitz.Page, page_number: int) -> list[dict[str, Any]]:
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    extracted = page.get_text("dict")
    boxes = []
    sequence = 0

    for block_index, block in enumerate(extracted.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for line_index, line in enumerate(block.get("lines", [])):
            spans = line.get("spans", [])
            text = normalize_text(" ".join(span.get("text", "") for span in spans))
            if not text:
                continue

            x0, y0, x1, y1 = [float(value) for value in line["bbox"]]
            width = max(0.0, x1 - x0)
            height = max(0.0, y1 - y0)
            if width <= 0 or height <= 0:
                continue

            font_sizes = [
                float(span.get("size", 0.0))
                for span in spans
                if float(span.get("size", 0.0)) > 0
            ]
            sequence += 1
            boxes.append(
                {
                    "page_number": page_number,
                    "sequence": sequence,
                    "block_index": block_index,
                    "line_index": line_index,
                    "text": text,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "width": width,
                    "height": height,
                    "area": width * height,
                    "rel_x0": safe_divide(x0, page_width),
                    "rel_y0": safe_divide(y0, page_height),
                    "rel_x1": safe_divide(x1, page_width),
                    "rel_y1": safe_divide(y1, page_height),
                    "rel_width": safe_divide(width, page_width),
                    "rel_height": safe_divide(height, page_height),
                    "rel_area": safe_divide(width * height, page_width * page_height),
                    "font_size_max": max(font_sizes) if font_sizes else height,
                    "font_size_mean": mean(font_sizes, default=height),
                    "char_count": len(text),
                    "word_count": len(text.split()),
                }
            )

    if boxes:
        return boxes

    # 일부 OCR PDF는 dict line 추출이 약할 수 있어 word box를 fallback으로 쓴다.
    for sequence, word in enumerate(page.get_text("words"), start=1):
        x0, y0, x1, y1, text = word[:5]
        text = normalize_text(str(text))
        if not text:
            continue
        x0 = float(x0)
        y0 = float(y0)
        x1 = float(x1)
        y1 = float(y1)
        width = max(0.0, x1 - x0)
        height = max(0.0, y1 - y0)
        if width <= 0 or height <= 0:
            continue
        boxes.append(
            {
                "page_number": page_number,
                "sequence": sequence,
                "block_index": int(word[5]) if len(word) > 5 else 0,
                "line_index": int(word[6]) if len(word) > 6 else sequence,
                "text": text,
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "width": width,
                "height": height,
                "area": width * height,
                "rel_x0": safe_divide(x0, page_width),
                "rel_y0": safe_divide(y0, page_height),
                "rel_x1": safe_divide(x1, page_width),
                "rel_y1": safe_divide(y1, page_height),
                "rel_width": safe_divide(width, page_width),
                "rel_height": safe_divide(height, page_height),
                "rel_area": safe_divide(width * height, page_width * page_height),
                "font_size_max": height,
                "font_size_mean": height,
                "char_count": len(text),
                "word_count": 1,
            }
        )
    return boxes


def geometry_signature(box: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        round(float(box["rel_x0"]) / 0.03),
        round(float(box["rel_y0"]) / 0.025),
        round(float(box["rel_width"]) / 0.03),
        round(float(box["rel_height"]) / 0.015),
    )


def mark_furniture(page_boxes: list[list[dict[str, Any]]]) -> dict[tuple[int, int], float]:
    page_count = len(page_boxes)
    signature_pages: dict[tuple[int, int, int, int], set[int]] = {}
    signature_boxes: dict[tuple[int, int, int, int], list[dict[str, Any]]] = {}

    for page_index, boxes in enumerate(page_boxes):
        seen_on_page = set()
        for box in boxes:
            signature = geometry_signature(box)
            seen_on_page.add(signature)
            signature_boxes.setdefault(signature, []).append(box)
        for signature in seen_on_page:
            signature_pages.setdefault(signature, set()).add(page_index)

    min_repeat = max(5, math.ceil(page_count * 0.18))
    furniture_scores: dict[tuple[int, int], float] = {}
    for page_index, boxes in enumerate(page_boxes):
        for box in boxes:
            signature = geometry_signature(box)
            repeat_count = len(signature_pages.get(signature, set()))
            repeat_ratio = safe_divide(repeat_count, page_count)
            in_edge_band = box["rel_y0"] <= 0.12 or box["rel_y1"] >= 0.88
            small_box = box["rel_area"] <= 0.02 or box["char_count"] <= 12
            score = 0.0
            if repeat_count >= min_repeat:
                score += repeat_ratio
            if in_edge_band and repeat_count >= max(3, math.ceil(page_count * 0.08)):
                score += repeat_ratio * 0.8
            if small_box and repeat_count >= min_repeat:
                score += 0.2
            furniture_scores[(page_index + 1, box["sequence"])] = clamp(score)
    return furniture_scores


def sorted_vertical_gaps(boxes: list[dict[str, Any]]) -> list[float]:
    if len(boxes) < 2:
        return []
    sorted_boxes = sorted(boxes, key=lambda box: (box["rel_y0"], box["rel_x0"]))
    gaps = []
    previous_y1 = sorted_boxes[0]["rel_y1"]
    for box in sorted_boxes[1:]:
        gaps.append(max(0.0, box["rel_y0"] - previous_y1))
        previous_y1 = max(previous_y1, box["rel_y1"])
    return gaps


def occupancy_grid(boxes: list[dict[str, Any]], grid_size: int) -> dict[str, float]:
    cells = {f"grid_{row}_{col}": 0.0 for row in range(grid_size) for col in range(grid_size)}
    for box in boxes:
        col0 = max(0, min(grid_size - 1, int(box["rel_x0"] * grid_size)))
        col1 = max(0, min(grid_size - 1, int(box["rel_x1"] * grid_size)))
        row0 = max(0, min(grid_size - 1, int(box["rel_y0"] * grid_size)))
        row1 = max(0, min(grid_size - 1, int(box["rel_y1"] * grid_size)))
        share = safe_divide(float(box["rel_area"]), (row1 - row0 + 1) * (col1 - col0 + 1))
        for row in range(row0, row1 + 1):
            for col in range(col0, col1 + 1):
                cells[f"grid_{row}_{col}"] += share
    return cells


def entropy(values: list[float]) -> float:
    if not values:
        return 0.0
    counts = Counter(round(value / 0.05) for value in values)
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return float(
        -sum((count / total) * math.log(count / total) for count in counts.values())
    )


def calculate_page_shape(
    pdf_name: str,
    page_number: int,
    page_count: int,
    page_width: float,
    page_height: float,
    boxes: list[dict[str, Any]],
    furniture_scores: dict[tuple[int, int], float],
) -> dict[str, Any]:
    filtered = [
        box
        for box in boxes
        if furniture_scores.get((page_number, box["sequence"]), 0.0) < 0.75
    ]
    source_boxes = filtered or boxes
    widths = [float(box["rel_width"]) for box in source_boxes]
    heights = [float(box["rel_height"]) for box in source_boxes]
    areas = [float(box["rel_area"]) for box in source_boxes]
    y0s = [float(box["rel_y0"]) for box in source_boxes]
    x0s = [float(box["rel_x0"]) for box in source_boxes]
    gaps = sorted_vertical_gaps(source_boxes)

    if source_boxes:
        content_x0 = min(float(box["rel_x0"]) for box in source_boxes)
        content_y0 = min(float(box["rel_y0"]) for box in source_boxes)
        content_x1 = max(float(box["rel_x1"]) for box in source_boxes)
        content_y1 = max(float(box["rel_y1"]) for box in source_boxes)
    else:
        content_x0 = content_y0 = content_x1 = content_y1 = 0.0

    content_width = max(0.0, content_x1 - content_x0)
    content_height = max(0.0, content_y1 - content_y0)
    feature = {
        "pdf": pdf_name,
        "page_number": page_number,
        "page_count": page_count,
        "page_position": safe_divide(page_number, page_count),
        "page_width": page_width,
        "page_height": page_height,
        "raw_box_count": len(boxes),
        "box_count": len(source_boxes),
        "removed_furniture_box_count": len(boxes) - len(filtered),
        "word_count": sum(int(box["word_count"]) for box in source_boxes),
        "char_count": sum(int(box["char_count"]) for box in source_boxes),
        "content_bbox_x0": content_x0,
        "content_bbox_y0": content_y0,
        "content_bbox_x1": content_x1,
        "content_bbox_y1": content_y1,
        "content_bbox_width": content_width,
        "content_bbox_height": content_height,
        "content_area_ratio": content_width * content_height,
        "top_whitespace_ratio": content_y0,
        "bottom_whitespace_ratio": max(0.0, 1.0 - content_y1),
        "left_whitespace_ratio": content_x0,
        "right_whitespace_ratio": max(0.0, 1.0 - content_x1),
        "box_area_sum_ratio": sum(areas),
        "box_area_mean": mean(areas),
        "box_area_median": median(areas),
        "box_area_p90": percentile(areas, 90),
        "box_height_mean": mean(heights),
        "box_height_median": median(heights),
        "box_height_p90": percentile(heights, 90),
        "box_width_mean": mean(widths),
        "box_width_median": median(widths),
        "box_width_p90": percentile(widths, 90),
        "vertical_gap_mean": mean(gaps),
        "vertical_gap_median": median(gaps),
        "vertical_gap_p90": percentile(gaps, 90),
        "horizontal_alignment_entropy": entropy(x0s),
        "vertical_position_entropy": entropy(y0s),
        "large_box_count": sum(1 for area in areas if area >= percentile(areas, 85)),
        "sparse_region_score": max(content_y0, max(0.0, 1.0 - content_y1), percentile(gaps, 90)),
    }
    feature.update(occupancy_grid(source_boxes, GRID_SIZE))
    return feature


def feature_columns() -> list[str]:
    columns = [
        "raw_box_count",
        "box_count",
        "removed_furniture_box_count",
        "word_count",
        "char_count",
        "content_bbox_x0",
        "content_bbox_y0",
        "content_bbox_width",
        "content_bbox_height",
        "content_area_ratio",
        "top_whitespace_ratio",
        "bottom_whitespace_ratio",
        "left_whitespace_ratio",
        "right_whitespace_ratio",
        "box_area_sum_ratio",
        "box_area_mean",
        "box_area_median",
        "box_area_p90",
        "box_height_mean",
        "box_height_median",
        "box_height_p90",
        "box_width_mean",
        "box_width_median",
        "box_width_p90",
        "vertical_gap_mean",
        "vertical_gap_median",
        "vertical_gap_p90",
        "horizontal_alignment_entropy",
        "vertical_position_entropy",
        "large_box_count",
        "sparse_region_score",
    ]
    columns.extend(f"grid_{row}_{col}" for row in range(GRID_SIZE) for col in range(GRID_SIZE))
    return columns


def cluster_page_shapes(rows: list[dict[str, Any]]) -> tuple[list[int], dict[str, Any]]:
    if len(rows) < 3:
        return [0 for _ in rows], {"method": "single_cluster", "cluster_count": 1}

    columns = feature_columns()
    matrix = np.array([[float(row[column]) for column in columns] for row in rows], dtype=float)
    scaled = StandardScaler().fit_transform(matrix)
    cluster_count = min(8, max(3, round(math.sqrt(len(rows)))))
    if len(rows) <= cluster_count:
        labels = list(range(len(rows)))
        return labels, {"method": "identity_small_pdf", "cluster_count": len(rows)}

    kmeans = KMeans(n_clusters=cluster_count, random_state=42, n_init=20)
    labels = kmeans.fit_predict(scaled).astype(int).tolist()

    # 비교용으로 계층 clustering label도 summary에만 남긴다.
    agglomerative = AgglomerativeClustering(n_clusters=cluster_count)
    agglomerative_labels = agglomerative.fit_predict(scaled).astype(int).tolist()
    return labels, {
        "method": "kmeans",
        "cluster_count": cluster_count,
        "feature_columns": columns,
        "agglomerative_labels": agglomerative_labels,
    }


def infer_body_cluster(rows: list[dict[str, Any]]) -> int:
    by_cluster: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_cluster.setdefault(int(row["layout_cluster_id"]), []).append(row)

    scored = []
    for cluster_id, items in by_cluster.items():
        count_score = safe_divide(len(items), len(rows))
        density_score = mean([float(item["box_area_sum_ratio"]) for item in items])
        box_score = mean([float(item["box_count"]) for item in items])
        whitespace_penalty = mean(
            [
                float(item["top_whitespace_ratio"]) + float(item["bottom_whitespace_ratio"])
                for item in items
            ]
        )
        score = count_score * 2.0 + density_score + box_score * 0.002 - whitespace_penalty * 0.5
        scored.append((score, cluster_id))
    return max(scored)[1] if scored else 0


def page_distance(left: dict[str, Any], right: dict[str, Any], columns: list[str]) -> float:
    return float(
        math.sqrt(
            sum((float(left[column]) - float(right[column])) ** 2 for column in columns)
        )
    )


def calculate_salient_boxes(
    page_number: int,
    boxes: list[dict[str, Any]],
    furniture_scores: dict[tuple[int, int], float],
    crop_dir: Path,
    pdf_slug: str,
) -> list[dict[str, Any]]:
    filtered = [
        box
        for box in boxes
        if furniture_scores.get((page_number, box["sequence"]), 0.0) < 0.75
    ]
    source_boxes = filtered or boxes
    heights = [float(box["rel_height"]) for box in source_boxes]
    areas = [float(box["rel_area"]) for box in source_boxes]
    gaps_above: dict[int, float] = {}
    gaps_below: dict[int, float] = {}
    sorted_boxes = sorted(source_boxes, key=lambda box: (box["rel_y0"], box["rel_x0"]))
    for index, box in enumerate(sorted_boxes):
        previous_y1 = sorted_boxes[index - 1]["rel_y1"] if index > 0 else 0.0
        next_y0 = sorted_boxes[index + 1]["rel_y0"] if index < len(sorted_boxes) - 1 else 1.0
        gaps_above[int(box["sequence"])] = max(0.0, float(box["rel_y0"]) - float(previous_y1))
        gaps_below[int(box["sequence"])] = max(0.0, float(next_y0) - float(box["rel_y1"]))

    candidates = []
    for box in source_boxes:
        height_z = robust_z(float(box["rel_height"]), heights)
        area_z = robust_z(float(box["rel_area"]), areas)
        whitespace = gaps_above[int(box["sequence"])] + gaps_below[int(box["sequence"])]
        salience = (
            clamp((height_z + 2.0) / 5.0) * 0.35
            + clamp((area_z + 2.0) / 5.0) * 0.25
            + clamp(whitespace / 0.25) * 0.30
            + clamp(float(box["rel_width"]) / 0.8) * 0.10
        )
        candidates.append(
            {
                "page_number": page_number,
                "candidate_rank": 0,
                "text": box["text"],
                "bbox": [
                    round(float(box["x0"]), 2),
                    round(float(box["y0"]), 2),
                    round(float(box["x1"]), 2),
                    round(float(box["y1"]), 2),
                ],
                "rel_bbox": [
                    round(float(box["rel_x0"]), 5),
                    round(float(box["rel_y0"]), 5),
                    round(float(box["rel_x1"]), 5),
                    round(float(box["rel_y1"]), 5),
                ],
                "salience_score": float(salience),
                "height_z": float(height_z),
                "area_z": float(area_z),
                "surrounding_whitespace": float(whitespace),
                "furniture_score": furniture_scores.get((page_number, box["sequence"]), 0.0),
                "crop_path": str((crop_dir / pdf_slug / f"p{page_number:04}_title_{box['sequence']:03}.png").relative_to(ROOT_DIR)),
            }
        )
    candidates.sort(key=lambda item: item["salience_score"], reverse=True)
    for rank, candidate in enumerate(candidates, start=1):
        candidate["candidate_rank"] = rank
    return candidates


def render_crop(document: fitz.Document, page_number: int, bbox: list[float], path: Path) -> None:
    page = document.load_page(page_number - 1)
    x0, y0, x1, y1 = bbox
    margin = 18.0
    clip = fitz.Rect(
        max(0.0, x0 - margin),
        max(0.0, y0 - margin),
        min(float(page.rect.width), x1 + margin),
        min(float(page.rect.height), y1 + margin),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False)
    pixmap.save(path)


def score_chapter_candidates(
    rows: list[dict[str, Any]],
    page_boxes: list[list[dict[str, Any]]],
    furniture_scores: dict[tuple[int, int], float],
    pdf_slug: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not rows:
        return [], []

    columns = feature_columns()
    body_cluster = infer_body_cluster(rows)
    body_rows = [row for row in rows if int(row["layout_cluster_id"]) == body_cluster]
    body_center = {
        column: mean([float(row[column]) for row in body_rows])
        for column in columns
    }
    body_distances = [page_distance(row, body_center, columns) for row in rows]
    body_outliers = minmax_scale(body_distances)

    transition_raw = [0.0]
    for index in range(1, len(rows)):
        transition_raw.append(page_distance(rows[index - 1], rows[index], columns))
    transition_scores = minmax_scale(transition_raw)

    cluster_sequence = [int(row["layout_cluster_id"]) for row in rows]
    motifs = Counter()
    for index, cluster_id in enumerate(cluster_sequence):
        prev_cluster = cluster_sequence[index - 1] if index > 0 else -1
        next_cluster = cluster_sequence[index + 1] if index < len(cluster_sequence) - 1 else -1
        motifs[(prev_cluster, cluster_id, next_cluster)] += 1
    max_motif_count = max(motifs.values()) if motifs else 1

    sparse_values = [float(row["sparse_region_score"]) for row in rows]
    area_values = [float(row["box_area_sum_ratio"]) for row in rows]

    all_title_candidates = []
    candidates = []
    crop_dir = OUTPUT_DIR / "crops"
    for index, row in enumerate(rows):
        page_number = int(row["page_number"])
        future = rows[index + 1 : index + 4]
        future_body_ratio = safe_divide(
            sum(1 for item in future if int(item["layout_cluster_id"]) == body_cluster),
            len(future),
        )
        sparse_score = clamp((robust_z(float(row["sparse_region_score"]), sparse_values) + 2.0) / 5.0)
        low_area_score = clamp((-robust_z(float(row["box_area_sum_ratio"]), area_values) + 2.0) / 5.0)
        opener_shape_score = sparse_score * 0.55 + low_area_score * 0.45
        prev_cluster = cluster_sequence[index - 1] if index > 0 else -1
        next_cluster = cluster_sequence[index + 1] if index < len(cluster_sequence) - 1 else -1
        motif_score = safe_divide(motifs[(prev_cluster, cluster_sequence[index], next_cluster)], max_motif_count)
        title_candidates = calculate_salient_boxes(
            page_number=page_number,
            boxes=page_boxes[index],
            furniture_scores=furniture_scores,
            crop_dir=crop_dir,
            pdf_slug=pdf_slug,
        )
        for title_candidate in title_candidates[:5]:
            title_candidate["pdf"] = row["pdf"]
            title_candidate["layout_cluster_id"] = row["layout_cluster_id"]
            all_title_candidates.append(title_candidate)
        salient_box_score = title_candidates[0]["salience_score"] if title_candidates else 0.0

        score = (
            body_outliers[index] * 0.25
            + transition_scores[index] * 0.20
            + future_body_ratio * 0.20
            + opener_shape_score * 0.18
            + motif_score * 0.07
            + salient_box_score * 0.10
        )
        selected_title = title_candidates[0] if title_candidates else None
        candidates.append(
            {
                "pdf": row["pdf"],
                "page_number": page_number,
                "rank": 0,
                "score": float(score),
                "layout_cluster_id": int(row["layout_cluster_id"]),
                "prev_cluster_id": int(prev_cluster),
                "next_cluster_id": int(next_cluster),
                "body_cluster_id": int(body_cluster),
                "layout_outlier_score": float(body_outliers[index]),
                "transition_from_previous_score": float(transition_scores[index]),
                "following_body_convergence_score": float(future_body_ratio),
                "opener_shape_score": float(opener_shape_score),
                "recurring_motif_score": float(motif_score),
                "salient_box_score": float(salient_box_score),
                "selected_title_text": selected_title["text"] if selected_title else "",
                "selected_title_bbox": selected_title["bbox"] if selected_title else [],
                "crop_path": selected_title["crop_path"] if selected_title else "",
                "evidence": (
                    f"cluster={row['layout_cluster_id']}, body={body_cluster}, "
                    f"outlier={body_outliers[index]:.3f}, transition={transition_scores[index]:.3f}, "
                    f"future_body={future_body_ratio:.3f}, opener={opener_shape_score:.3f}"
                ),
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
    return candidates, all_title_candidates


def nearest_bookmark(page_number: int, bookmarks: list[dict[str, Any]]) -> dict[str, Any] | None:
    page_bookmarks = [
        bookmark
        for bookmark in bookmarks
        if isinstance(bookmark.get("pdf_page"), int)
    ]
    if not page_bookmarks:
        return None
    return min(page_bookmarks, key=lambda bookmark: abs(int(bookmark["pdf_page"]) - page_number))


def analyze_bookmark_reference(
    rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    bookmarks: list[dict[str, Any]],
) -> dict[str, Any]:
    page_by_number = {int(row["page_number"]): row for row in rows}
    rank_by_page = {int(candidate["page_number"]): int(candidate["rank"]) for candidate in candidates}
    score_by_page = {int(candidate["page_number"]): float(candidate["score"]) for candidate in candidates}
    level_one_pages = [
        int(bookmark["pdf_page"])
        for bookmark in bookmarks
        if bookmark.get("level") == 1 and isinstance(bookmark.get("pdf_page"), int)
    ]
    level_one_pages = sorted(dict.fromkeys(level_one_pages))
    matched_rows = [
        page_by_number[page]
        for page in level_one_pages
        if page in page_by_number
    ]
    cluster_counts = Counter(int(row["layout_cluster_id"]) for row in matched_rows)
    ranks = [rank_by_page[page] for page in level_one_pages if page in rank_by_page]
    scores = [score_by_page[page] for page in level_one_pages if page in score_by_page]
    return {
        "level_one_bookmark_count": len(level_one_pages),
        "level_one_pages": level_one_pages[:80],
        "matched_level_one_page_count": len(matched_rows),
        "level_one_layout_cluster_counts": dict(cluster_counts),
        "level_one_rank_median": median([float(rank) for rank in ranks], default=None),
        "level_one_rank_p25": percentile([float(rank) for rank in ranks], 25, default=None),
        "level_one_rank_p75": percentile([float(rank) for rank in ranks], 75, default=None),
        "level_one_score_mean": mean(scores, default=None),
        "level_one_feature_means": {
            key: mean([float(row[key]) for row in matched_rows], default=None)
            for key in [
                "box_count",
                "box_area_sum_ratio",
                "content_area_ratio",
                "top_whitespace_ratio",
                "bottom_whitespace_ratio",
                "vertical_gap_p90",
                "sparse_region_score",
            ]
        },
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def analyze_pdf(pdf_path: Path, max_pages: int = 0) -> dict[str, Any]:
    pdf_name = str(pdf_path.relative_to(ROOT_DIR))
    pdf_slug = slugify(pdf_path.stem)
    with fitz.open(pdf_path) as document:
        page_count = document.page_count if max_pages <= 0 else min(document.page_count, max_pages)
        bookmarks = extract_bookmarks(document)
        page_boxes = []
        page_sizes = []
        for page_index in range(page_count):
            page = document.load_page(page_index)
            page_boxes.append(extract_page_boxes(page, page_index + 1))
            page_sizes.append((float(page.rect.width), float(page.rect.height)))

        furniture_scores = mark_furniture(page_boxes)
        page_shape_rows = [
            calculate_page_shape(
                pdf_name=pdf_name,
                page_number=index + 1,
                page_count=page_count,
                page_width=page_sizes[index][0],
                page_height=page_sizes[index][1],
                boxes=page_boxes[index],
                furniture_scores=furniture_scores,
            )
            for index in range(page_count)
        ]
        cluster_labels, cluster_summary = cluster_page_shapes(page_shape_rows)
        for row, label in zip(page_shape_rows, cluster_labels, strict=True):
            row["layout_cluster_id"] = int(label)

        candidates, title_candidates = score_chapter_candidates(
            rows=page_shape_rows,
            page_boxes=page_boxes,
            furniture_scores=furniture_scores,
            pdf_slug=pdf_slug,
        )

        for candidate in candidates:
            bookmark = nearest_bookmark(int(candidate["page_number"]), bookmarks)
            candidate["nearest_bookmark_title"] = bookmark["title"] if bookmark else ""
            candidate["nearest_bookmark_page"] = bookmark["pdf_page"] if bookmark else ""
            candidate["nearest_bookmark_level"] = bookmark["level"] if bookmark else ""
            candidate["nearest_bookmark_page_delta"] = (
                int(candidate["page_number"]) - int(bookmark["pdf_page"])
                if bookmark and bookmark.get("pdf_page")
                else ""
            )

        for candidate in candidates[:TOP_CROP_COUNT]:
            if not candidate["selected_title_bbox"]:
                continue
            crop_path = ROOT_DIR / candidate["crop_path"]
            render_crop(
                document=document,
                page_number=int(candidate["page_number"]),
                bbox=[float(value) for value in candidate["selected_title_bbox"]],
                path=crop_path,
            )

    reference = analyze_bookmark_reference(page_shape_rows, candidates, bookmarks)
    return {
        "pdf": pdf_name,
        "pdf_slug": pdf_slug,
        "page_count": page_count,
        "bookmark_count": len(bookmarks),
        "cluster_summary": cluster_summary,
        "bookmark_reference": reference,
        "page_shapes": page_shape_rows,
        "chapter_candidates": candidates[:TOP_CANDIDATE_COUNT],
        "all_chapter_candidates": candidates,
        "title_candidates": title_candidates,
        "bookmarks": bookmarks,
    }


def build_cluster_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    by_cluster: dict[int, list[dict[str, Any]]] = {}
    for row in result["page_shapes"]:
        by_cluster.setdefault(int(row["layout_cluster_id"]), []).append(row)
    for cluster_id, items in sorted(by_cluster.items()):
        rows.append(
            {
                "pdf": result["pdf"],
                "layout_cluster_id": cluster_id,
                "page_count": len(items),
                "pages": " ".join(str(item["page_number"]) for item in items[:80]),
                "box_count_mean": mean([float(item["box_count"]) for item in items]),
                "box_area_sum_ratio_mean": mean([float(item["box_area_sum_ratio"]) for item in items]),
                "content_area_ratio_mean": mean([float(item["content_area_ratio"]) for item in items]),
                "top_whitespace_ratio_mean": mean([float(item["top_whitespace_ratio"]) for item in items]),
                "bottom_whitespace_ratio_mean": mean([float(item["bottom_whitespace_ratio"]) for item in items]),
                "vertical_gap_p90_mean": mean([float(item["vertical_gap_p90"]) for item in items]),
                "sparse_region_score_mean": mean([float(item["sparse_region_score"]) for item in items]),
            }
        )
    return rows


def build_finding(results: list[dict[str, Any]]) -> str:
    parts = []
    for result in results:
        top_pages = [candidate["page_number"] for candidate in result["chapter_candidates"][:10]]
        reference = result["bookmark_reference"]
        cluster_counts = reference["level_one_layout_cluster_counts"]
        rank_median = reference["level_one_rank_median"]
        rank_text = f"{rank_median:.1f}" if isinstance(rank_median, float) else "없음"
        parts.append(
            f"{Path(result['pdf']).name}는 page shape 기반 chapter start 후보 상위 page가 "
            f"{top_pages}이다. 기존 level 1 bookmark {reference['level_one_bookmark_count']}개 중 "
            f"{reference['matched_level_one_page_count']}개 page를 feature와 비교했고, "
            f"level 1 bookmark page의 cluster 분포는 {cluster_counts}, 후보 rank median은 {rank_text}이다."
        )
    return " ".join(parts)


def load_experiment_registry() -> dict[str, Any]:
    if not EXPERIMENTS_JSON.exists():
        return {"experiments": []}
    text = EXPERIMENTS_JSON.read_text(encoding="utf-8").strip()
    if not text:
        return {"experiments": []}
    loaded = json.loads(text)
    if isinstance(loaded, list):
        return {"experiments": loaded}
    loaded.setdefault("experiments", [])
    return loaded


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def update_experiment_registry(results: list[dict[str, Any]], input_pdfs: list[Path]) -> None:
    registry = load_experiment_registry()
    experiments = [
        experiment
        for experiment in registry["experiments"]
        if experiment.get("id") != EXPERIMENT_ID
    ]
    experiments.append(
        {
            "id": EXPERIMENT_ID,
            "purpose": (
                "data/ 아래 PDF를 대상으로 text keyword나 TOC label 없이 page box의 "
                "공간 패턴, 크기 분포, page shape cluster, layout transition motif만으로 "
                "chapter start page 후보와 bookmark item 후보를 생성하고, 기존 bookmark가 "
                "있는 PDF에서는 level 1 bookmark page의 shape 특성을 참고 분석한다."
            ),
            "inputs": [str(path.relative_to(ROOT_DIR)) for path in input_pdfs],
            "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
            "finding": build_finding(results),
            "ran_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    registry["experiments"] = experiments
    write_json(EXPERIMENTS_JSON, registry)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="page box geometry만으로 chapter start 후보를 찾는 비지도 실험이다.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help="분석할 PDF가 들어 있는 data directory다.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="PDF별로 분석할 최대 page 수다. 0이면 전체 page를 분석한다.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="결과 파일만 쓰고 콘솔 JSON 출력은 생략한다.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    data_dir = args.data_dir if args.data_dir.is_absolute() else ROOT_DIR / args.data_dir
    input_pdfs = find_input_pdfs(data_dir)
    if not input_pdfs:
        raise FileNotFoundError(f"PDF 파일을 찾지 못했습니다: {data_dir}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = [analyze_pdf(pdf_path, max_pages=args.max_pages) for pdf_path in input_pdfs]

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "pdf_count": len(results),
        "results": [
            {
                "pdf": result["pdf"],
                "page_count": result["page_count"],
                "bookmark_count": result["bookmark_count"],
                "cluster_summary": result["cluster_summary"],
                "bookmark_reference": result["bookmark_reference"],
                "top_chapter_candidate_pages": [
                    candidate["page_number"]
                    for candidate in result["chapter_candidates"][:10]
                ],
                "top_chapter_candidates": result["chapter_candidates"][:10],
            }
            for result in results
        ],
        "finding": build_finding(results),
    }

    page_shape_rows = [row for result in results for row in result["page_shapes"]]
    cluster_rows = [row for result in results for row in build_cluster_rows(result)]
    chapter_rows = [row for result in results for row in result["chapter_candidates"]]
    all_chapter_rows = [row for result in results for row in result["all_chapter_candidates"]]
    title_rows = [row for result in results for row in result["title_candidates"]]
    bookmark_rows = [
        bookmark | {"pdf": result["pdf"]}
        for result in results
        for bookmark in result["bookmarks"]
    ]

    write_csv(OUTPUT_DIR / "page_shapes.csv", page_shape_rows, list(page_shape_rows[0].keys()))
    write_csv(
        OUTPUT_DIR / "page_shape_clusters.csv",
        cluster_rows,
        list(cluster_rows[0].keys()) if cluster_rows else ["pdf"],
    )
    write_csv(
        OUTPUT_DIR / "chapter_start_candidates.csv",
        chapter_rows,
        list(chapter_rows[0].keys()) if chapter_rows else ["pdf"],
    )
    write_csv(
        OUTPUT_DIR / "all_chapter_start_candidates.csv",
        all_chapter_rows,
        list(all_chapter_rows[0].keys()) if all_chapter_rows else ["pdf"],
    )
    write_csv(
        OUTPUT_DIR / "title_box_candidates.csv",
        title_rows,
        list(title_rows[0].keys()) if title_rows else ["pdf"],
    )
    write_csv(
        OUTPUT_DIR / "existing_bookmarks_reference.csv",
        bookmark_rows,
        list(bookmark_rows[0].keys()) if bookmark_rows else ["pdf"],
    )
    write_json(OUTPUT_DIR / "summary.json", summary)
    update_experiment_registry(results, input_pdfs)

    if not args.quiet:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
