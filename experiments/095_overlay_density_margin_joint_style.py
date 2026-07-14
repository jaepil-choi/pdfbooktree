"""experiment 095: chunk anchor pattern과 font size 후보를 독립적으로 비교한다.

개별 OCR line의 좌표를 곧바로 position으로 사용하지 않는다. 먼저 같은 페이지에서
문서의 median line spacing 안에 이어지는 line을 하나의 chunk로 묶고, chunk의 첫
line top-left를 anchor로 사용한다. 현재 chunk와 다음 chunk의 anchor 쌍이 여러 page에
반복되는 경우 현재 chunk를 position 후보로 인정한다.

position 후보와 body font-size가 다른 후보는 독립적으로 만들며 position, font,
position AND font 세 tree를 모두 저장한다. 기본 bookmark_tree.txt는 AND 결과다.

실행:
    uv run python experiments/095_overlay_density_margin_joint_style.py
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from math import ceil, sqrt
from pathlib import Path
from statistics import median
from typing import Any

import fitz
import numpy as np

from pdfbooktree.config import TypographyConfig
from pdfbooktree.typography.lines import extract_typography_lines

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "095_overlay_density_margin_joint_style"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
INPUT_PDF = (
    ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf"
)
POSITION_TOLERANCES = [0.25, 0.5, 1.0]
FONT_RELATIVE_TOLERANCES = [0.05, 0.1]
CHUNK_CONTINUATION_RATIO = 1.35
MIN_PATTERN_PAGES = 3


@dataclass(frozen=True)
class VisualRow:
    pdf_page: int
    lines: tuple[Any, ...]
    x0: float
    y0: float
    x1: float
    y1: float
    page_width: float
    page_height: float
    font_size: float
    text: str


@dataclass(frozen=True)
class TextChunk:
    chunk_id: int
    pdf_page: int
    rows: tuple[VisualRow, ...]
    x0: float
    y0: float
    page_width: float
    page_height: float
    font_size: float
    text: str

    @property
    def line_count(self) -> int:
        return len(self.rows)

    @property
    def y1(self) -> float:
        return max(row.y1 for row in self.rows)


@dataclass(frozen=True)
class AnchorPattern:
    current: TextChunk
    following: TextChunk
    values: tuple[float, float, float, float]


def exclude_overlay_density_margins(
    lines: list[Any],
) -> tuple[list[Any], dict[str, Any]]:
    """여러 page의 y 좌표를 겹쳐 좁고 고립된 양끝 반복 band를 제거한다."""

    if not lines:
        return [], {"status": "empty"}
    page_count = max(line.pdf_page for line in lines)
    median_height_ratio = median(line.height / line.page_height for line in lines)
    bin_width = median_height_ratio / 4.0
    pages_by_bin: dict[int, set[int]] = defaultdict(set)
    for line in lines:
        pages_by_bin[round(line.y_center_ratio / bin_width)].add(line.pdf_page)

    minimum_page_support = max(3, ceil(sqrt(page_count)))
    occupied = sorted(
        index
        for index, pages in pages_by_bin.items()
        if len(pages) >= minimum_page_support
    )
    components: list[list[int]] = []
    for index in occupied:
        if not components or index - components[-1][-1] > 2:
            components.append([index])
        else:
            components[-1].append(index)
    if not components:
        return list(lines), {
            "status": "no_repeated_components",
            "bin_width_ratio": bin_width,
            "minimum_page_support": minimum_page_support,
        }

    widths = [component[-1] - component[0] + 1 for component in components]
    minimum_content_width = median(widths)
    first_content_index = int(widths[0] < minimum_content_width)
    last_content_index = len(components) - int(widths[-1] < minimum_content_width)
    content_components = components[first_content_index:last_content_index]
    lower_bin = content_components[0][0]
    upper_bin = content_components[-1][-1]
    lower_ratio = lower_bin * bin_width
    upper_ratio = upper_bin * bin_width
    kept = [line for line in lines if lower_ratio <= line.y_center_ratio <= upper_ratio]
    report = {
        "status": "filtered",
        "page_count": page_count,
        "median_line_height_ratio": median_height_ratio,
        "bin_width_ratio": bin_width,
        "minimum_page_support": minimum_page_support,
        "components": [
            {
                "lower_y_ratio": round(component[0] * bin_width, 4),
                "upper_y_ratio": round(component[-1] * bin_width, 4),
                "width_bins": width,
                "content": first_content_index <= index < last_content_index,
            }
            for index, (component, width) in enumerate(
                zip(components, widths, strict=True)
            )
        ],
        "inferred_content_y_ratio": [round(lower_ratio, 4), round(upper_ratio, 4)],
        "input_line_count": len(lines),
        "kept_line_count": len(kept),
        "removed_line_count": len(lines) - len(kept),
    }
    return kept, report


def infer_density_bands(values: list[float]) -> dict[str, Any]:
    """강건한 Silverman bandwidth와 density valley로 1차원 band를 찾는다."""

    array = np.asarray(values, dtype=float)
    q1, q3 = np.percentile(array, [25, 75])
    robust_scale = min(float(np.std(array, ddof=1)), float((q3 - q1) / 1.34))
    bandwidth = 0.9 * robust_scale * (len(array) ** -0.2)
    grid = np.linspace(float(array.min()), float(array.max()), 2048)
    density = np.zeros_like(grid)
    for batch in np.array_split(array, max(1, ceil(len(array) / 4096))):
        z = (grid[:, None] - batch[None, :]) / bandwidth
        density += np.exp(-0.5 * z * z).sum(axis=1)
    valley_indices = [
        index
        for index in range(1, len(density) - 1)
        if density[index - 1] > density[index] < density[index + 1]
    ]
    cuts = [float(grid[index]) for index in valley_indices]
    return {"bandwidth": bandwidth, "cuts": cuts}


def band_index(value: float, cuts: list[float]) -> int:
    return int(np.searchsorted(np.asarray(cuts), value, side="right"))


def infer_body_font_band(lines: list[Any]) -> dict[str, Any]:
    """font-size density에서 문서 median이 속한 band를 본문 font band로 삼는다."""

    values = [float(line.font_size) for line in lines]
    density = infer_density_bands(values)
    cuts = density["cuts"]
    document_median = float(median(values))
    body_band = band_index(document_median, cuts)
    lower = cuts[body_band - 1] if body_band > 0 else float("-inf")
    upper = cuts[body_band] if body_band < len(cuts) else float("inf")
    body_values = [value for value in values if band_index(value, cuts) == body_band]
    return {
        "font_size": float(median(body_values)),
        "band_index": body_band,
        "lower": lower,
        "upper": upper,
        "bandwidth": density["bandwidth"],
        "cuts": cuts,
        "line_count": len(body_values),
    }


def build_visual_rows(lines: list[Any]) -> tuple[list[VisualRow], float]:
    """세로 bbox가 겹치고 가로 영역이 분리된 OCR 조각만 같은 인쇄 line으로 합친다."""

    median_height = float(median(line.height for line in lines))
    rows: list[VisualRow] = []
    by_page: dict[int, list[Any]] = defaultdict(list)
    for line in lines:
        by_page[line.pdf_page].append(line)
    for page, page_lines in sorted(by_page.items()):
        groups: list[list[Any]] = []
        for line in sorted(page_lines, key=lambda item: (item.y0, item.x0)):
            target = next(
                (
                    group
                    for group in reversed(groups)
                    if min(line.y1, max(item.y1 for item in group))
                    > max(line.y0, min(item.y0 for item in group))
                    and all(line.x1 <= item.x0 or line.x0 >= item.x1 for item in group)
                ),
                None,
            )
            if target is None:
                groups.append([line])
            else:
                target.append(line)
        for group in groups:
            ordered = sorted(group, key=lambda item: item.x0)
            rows.append(
                VisualRow(
                    pdf_page=page,
                    lines=tuple(ordered),
                    x0=min(item.x0 for item in ordered),
                    y0=min(item.y0 for item in ordered),
                    x1=max(item.x1 for item in ordered),
                    y1=max(item.y1 for item in ordered),
                    page_width=ordered[0].page_width,
                    page_height=ordered[0].page_height,
                    font_size=float(median(item.font_size for item in ordered)),
                    text=" ".join(
                        item.text.strip() for item in ordered if item.text.strip()
                    ),
                )
            )
    return rows, median_height


def estimate_line_spacing(
    rows: list[VisualRow], body_font_band: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    """복원된 본문 line의 top-to-top 분포와 paragraph 내부 band를 구한다."""

    body_rows = [
        row
        for row in rows
        if body_font_band["lower"] <= row.font_size < body_font_band["upper"]
    ]
    by_page: dict[int, list[VisualRow]] = defaultdict(list)
    for row in body_rows:
        by_page[row.pdf_page].append(row)
    gaps = []
    bbox_gaps = []
    for page_rows in by_page.values():
        ordered = sorted(page_rows, key=lambda row: (row.y0, row.x0))
        for left, right in zip(ordered, ordered[1:]):
            if right.y0 <= left.y0:
                continue
            if max(left.x0, right.x0) >= min(left.x1, right.x1):
                continue
            gaps.append(right.y0 - left.y0)
            bbox_gaps.append(right.y0 - left.y1)

    top_step = float(median(gaps))
    q1, q3 = np.percentile(gaps, [25, 75])
    upper_fence = float(q3 + 1.5 * (q3 - q1))
    core_gaps = [gap for gap in gaps if gap <= upper_fence]
    gap_density = infer_density_bands(core_gaps)
    upper_valleys = [cut for cut in gap_density["cuts"] if cut >= top_step]
    continuation_upper = upper_valleys[0] if upper_valleys else float(max(core_gaps))
    return top_step, {
        "body_row_count": len(body_rows),
        "adjacent_pair_count": len(gaps),
        "top_to_top_median": top_step,
        "font_excess_y_distance": top_step - body_font_band["font_size"],
        "bbox_gap_median": float(median(bbox_gaps)),
        "density_bandwidth": gap_density["bandwidth"],
        "density_valleys": gap_density["cuts"],
        "continuation_upper": continuation_upper,
    }


def build_chunks(rows: list[VisualRow], line_spacing: float) -> list[TextChunk]:
    """median line spacing으로 이어지는 row들을 한 덩어리로 묶는다."""

    by_page: dict[int, list[VisualRow]] = defaultdict(list)
    for row in rows:
        by_page[row.pdf_page].append(row)
    chunks: list[TextChunk] = []
    chunk_id = 1
    for page, page_rows in sorted(by_page.items()):
        groups: list[list[VisualRow]] = []
        for row in sorted(page_rows, key=lambda item: (item.y0, item.x0)):
            if groups and row.y0 - groups[-1][-1].y0 <= line_spacing:
                groups[-1].append(row)
            else:
                groups.append([row])
        for group in groups:
            first = group[0]
            chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    pdf_page=page,
                    rows=tuple(group),
                    x0=first.x0,
                    y0=first.y0,
                    page_width=first.page_width,
                    page_height=first.page_height,
                    font_size=float(median(row.font_size for row in group)),
                    text=" ".join(row.text for row in group),
                )
            )
            chunk_id += 1
    return chunks


def merge_adjacent_non_body_chunks(
    chunks: list[TextChunk],
    body_font_band: dict[str, Any],
    body_line_spacing: float,
) -> tuple[list[TextChunk], dict[str, Any]]:
    """같은 page의 연속된 non-body chunk를 bbox gap과 font 방향으로 병합한다."""

    def font_side(chunk: TextChunk) -> int:
        if chunk.font_size < body_font_band["lower"]:
            return -1
        if chunk.font_size >= body_font_band["upper"]:
            return 1
        return 0

    merged: list[TextChunk] = []
    merge_pairs = []
    for chunk in sorted(chunks, key=lambda item: (item.pdf_page, item.y0, item.x0)):
        if not merged:
            merged.append(chunk)
            continue
        previous = merged[-1]
        vertical_gap = chunk.y0 - previous.y1
        previous_side = font_side(previous)
        should_merge = (
            previous.pdf_page == chunk.pdf_page
            and chunk.y0 > previous.y0
            and vertical_gap <= body_line_spacing
            and previous_side != 0
            and previous_side == font_side(chunk)
        )
        if not should_merge:
            merged.append(chunk)
            continue
        rows = tuple(
            sorted(previous.rows + chunk.rows, key=lambda row: (row.y0, row.x0))
        )
        combined = TextChunk(
            chunk_id=previous.chunk_id,
            pdf_page=previous.pdf_page,
            rows=rows,
            x0=previous.x0,
            y0=previous.y0,
            page_width=previous.page_width,
            page_height=previous.page_height,
            font_size=float(median(row.font_size for row in rows)),
            text=f"{previous.text} {chunk.text}".strip(),
        )
        merged[-1] = combined
        merge_pairs.append(
            {
                "page": chunk.pdf_page,
                "first_chunk_id": previous.chunk_id,
                "second_chunk_id": chunk.chunk_id,
                "vertical_gap": round(vertical_gap, 3),
                "merged_text": combined.text[:160],
            }
        )
    return merged, {
        "input_chunk_count": len(chunks),
        "output_chunk_count": len(merged),
        "merge_count": len(merge_pairs),
        "merges": merge_pairs,
    }


def build_anchor_patterns(
    chunks: list[TextChunk], line_spacing: float
) -> list[AnchorPattern]:
    """현재 chunk와 바로 다음 chunk의 top-left anchor 쌍을 만든다."""

    by_page: dict[int, list[TextChunk]] = defaultdict(list)
    for chunk in chunks:
        by_page[chunk.pdf_page].append(chunk)
    patterns = []
    for page_chunks in by_page.values():
        ordered = sorted(page_chunks, key=lambda chunk: (chunk.y0, chunk.x0))
        for current, following in zip(ordered, ordered[1:]):
            patterns.append(
                AnchorPattern(
                    current=current,
                    following=following,
                    values=(
                        (current.x0 / current.page_width)
                        / (line_spacing / current.page_width),
                        (current.y0 / current.page_height)
                        / (line_spacing / current.page_height),
                        (following.x0 / following.page_width)
                        / (line_spacing / following.page_width),
                        (following.y0 / following.page_height)
                        / (line_spacing / following.page_height),
                    ),
                )
            )
    return patterns


def cluster_patterns(
    patterns: list[AnchorPattern], tolerance: float
) -> list[list[AnchorPattern]]:
    """anchor 네 좌표가 모두 tolerance 안에 드는 위치 패턴을 군집화한다."""

    clusters: list[list[AnchorPattern]] = []
    for pattern in sorted(patterns, key=lambda item: item.values):
        target = next(
            (
                cluster
                for cluster in clusters
                if all(
                    max(values) - min(values) <= tolerance
                    for values in zip(
                        *(item.values for item in cluster + [pattern]), strict=True
                    )
                )
            ),
            None,
        )
        if target is None:
            clusters.append([pattern])
        else:
            target.append(pattern)
    return clusters


def infer_position_tolerance(patterns: list[AnchorPattern]) -> dict[str, Any]:
    """다른 page에서 가장 가까운 pattern까지의 거리 중앙값으로 jitter를 추론한다."""

    values = np.asarray([pattern.values for pattern in patterns], dtype=float)
    pages = np.asarray([pattern.current.pdf_page for pattern in patterns], dtype=int)
    nearest = []
    for index, value in enumerate(values):
        distances = np.max(np.abs(values - value), axis=1)
        nearest.append(float(np.min(distances[pages != pages[index]])))
    return {
        "tolerance_line_spacings": float(median(nearest)),
        "nearest_distance_median": float(median(nearest)),
        "nearest_distance_q1": float(np.percentile(nearest, 25)),
        "nearest_distance_q3": float(np.percentile(nearest, 75)),
    }


def infer_minimum_pattern_pages(
    clusters: list[list[AnchorPattern]],
) -> tuple[int, dict[int, int]]:
    """page support histogram의 가장 큰 감소 지점 다음을 반복 경계로 삼는다."""

    histogram = Counter(
        len({item.current.pdf_page for item in cluster}) for cluster in clusters
    )
    consecutive = [
        support
        for support in sorted(histogram)
        if support + 1 in histogram and histogram[support + 1] > 0
    ]
    if not consecutive:
        return 2, dict(sorted(histogram.items()))
    boundary = max(
        consecutive,
        key=lambda support: histogram[support] / histogram[support + 1],
    )
    return boundary + 1, dict(sorted(histogram.items()))


def select_position_candidates(
    patterns: list[AnchorPattern], tolerance: float
) -> tuple[set[int], list[dict[str, Any]], dict[str, Any]]:
    clusters = cluster_patterns(patterns, tolerance)
    minimum_pages, support_histogram = infer_minimum_pattern_pages(clusters)
    accepted = [
        cluster
        for cluster in clusters
        if len({item.current.pdf_page for item in cluster}) >= minimum_pages
    ]
    candidate_ids = {item.current.chunk_id for cluster in accepted for item in cluster}
    reports = [
        {
            "distinct_pages": len({item.current.pdf_page for item in cluster}),
            "count": len(cluster),
            "anchor_ranges": [
                [round(min(values), 3), round(max(values), 3)]
                for values in zip(*(item.values for item in cluster), strict=True)
            ],
            "examples": [item.current.text[:120] for item in cluster[:5]],
        }
        for cluster in accepted
    ]
    return (
        candidate_ids,
        reports,
        {
            "minimum_pages": minimum_pages,
            "support_histogram": support_histogram,
            "accepted_pattern_count": len(accepted),
        },
    )


def select_font_candidates(
    chunks: list[TextChunk], body_font_band: dict[str, Any]
) -> set[int]:
    """본문 density band 밖에 있는 chunk를 font 후보로 삼는다."""

    return {
        chunk.chunk_id
        for chunk in chunks
        if not (body_font_band["lower"] <= chunk.font_size < body_font_band["upper"])
    }


def assign_levels(
    chunks: list[TextChunk], font_tolerance: float
) -> list[tuple[TextChunk, int]]:
    """선택과 독립적으로 대표 font size stack을 사용해 임시 level을 부여한다."""

    stack: list[float] = []
    result = []
    for chunk in sorted(chunks, key=lambda item: (item.pdf_page, item.y0, item.x0)):
        size = chunk.font_size
        while stack and size > stack[-1] * (1.0 + font_tolerance):
            stack.pop()
        if stack and abs(size / stack[-1] - 1.0) <= font_tolerance:
            level = len(stack)
            stack[-1] = size
        else:
            stack.append(size)
            level = len(stack)
        result.append((chunk, level))
    return result


def write_tree(path: Path, chunks: list[TextChunk], font_tolerance: float) -> int:
    inferred = assign_levels(chunks, font_tolerance)
    lines = [
        f"{'  ' * (level - 1)}[L{level}] [p.{chunk.pdf_page}] "
        f"[anchor=({chunk.x0:.1f},{chunk.y0:.1f})] [rows={chunk.line_count}] "
        f"[font={chunk.font_size:.2f}] {chunk.text}"
        for chunk, level in inferred
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


def load_truth() -> list[dict[str, Any]]:
    """embedded bookmark를 이번 clean PDF의 정답으로 읽는다."""

    with fitz.open(INPUT_PDF) as document:
        return [
            {"level": level, "title": title, "pdf_page": page}
            for level, title, page in document.get_toc()
            if page > 0
        ]


def normalize_title(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", text.casefold()).strip()


def title_score(left: str, right: str) -> float:
    """문자열 순서와 token 겹침을 함께 사용하는 제목 유사도다."""

    left_norm = normalize_title(left)
    right_norm = normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if min(len(left_norm), len(right_norm)) >= 4 and (
        left_norm in right_norm or right_norm in left_norm
    ):
        return 1.0
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    token_score = (
        2.0 * len(left_tokens & right_tokens) / (len(left_tokens) + len(right_tokens))
    )
    return max(sequence, token_score)


def infer_match_threshold(best_scores: list[float]) -> float:
    """Otsu between-class variance로 공통 title-match threshold를 추론한다."""

    scores = np.asarray(best_scores, dtype=float)
    histogram, edges = np.histogram(scores, bins=256, range=(0.0, 1.0))
    probability = histogram / max(histogram.sum(), 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    cumulative_weight = np.cumsum(probability)
    cumulative_mean = np.cumsum(probability * centers)
    total_mean = cumulative_mean[-1]
    denominator = cumulative_weight * (1.0 - cumulative_weight)
    variance = np.zeros_like(denominator)
    valid = denominator > 0
    variance[valid] = (
        total_mean * cumulative_weight[valid] - cumulative_mean[valid]
    ) ** 2 / denominator[valid]
    return float(centers[int(np.argmax(variance))])


def evaluate_mode(
    truth: list[dict[str, Any]],
    inferred: list[tuple[TextChunk, int]],
    match_threshold: float,
) -> dict[str, Any]:
    """동일 page에서 truth와 candidate를 one-to-one greedy matching한다."""

    pairs = []
    for truth_index, entry in enumerate(truth):
        for candidate_index, (chunk, level) in enumerate(inferred):
            if chunk.pdf_page != entry["pdf_page"]:
                continue
            pairs.append(
                (
                    title_score(entry["title"], chunk.text),
                    truth_index,
                    candidate_index,
                    level,
                )
            )
    used_truth: set[int] = set()
    used_candidates: set[int] = set()
    matches = []
    for score, truth_index, candidate_index, level in sorted(pairs, reverse=True):
        if score < match_threshold:
            break
        if truth_index in used_truth or candidate_index in used_candidates:
            continue
        used_truth.add(truth_index)
        used_candidates.add(candidate_index)
        entry = truth[truth_index]
        chunk = inferred[candidate_index][0]
        matches.append(
            {
                "truth_title": entry["title"],
                "truth_page": entry["pdf_page"],
                "truth_level": entry["level"],
                "candidate_title": chunk.text,
                "candidate_level": level,
                "candidate_chunk_id": chunk.chunk_id,
                "score": round(score, 4),
                "level_correct": level == entry["level"],
            }
        )
    true_positive = len(matches)
    precision = true_positive / len(inferred) if inferred else 0.0
    recall = true_positive / len(truth) if truth else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "truth_count": len(truth),
        "candidate_count": len(inferred),
        "matched": true_positive,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "level_accuracy": round(
            sum(match["level_correct"] for match in matches) / true_positive, 4
        )
        if true_positive
        else 0.0,
        "matches": matches,
        "unmatched_truth": [
            entry for index, entry in enumerate(truth) if index not in used_truth
        ],
        "unmatched_candidate_count": len(inferred) - true_positive,
    }


def record_experiment(summary: dict[str, Any]) -> None:
    compact_summary = {
        key: summary[key]
        for key in (
            "margin_report",
            "font_density",
            "body_spacing",
            "visual_row_count",
            "chunk_count",
            "position_inference",
            "pattern_support",
            "candidate_counts",
            "truth_count",
            "match_threshold",
            "default_mode",
            "bookmark_tree_txt",
            "finding",
        )
    }
    compact_summary["adjacent_non_body_merge"] = {
        key: value
        for key, value in summary["adjacent_non_body_merge"].items()
        if key != "merges"
    }
    compact_summary["evaluation"] = {
        mode: {
            key: value
            for key, value in result.items()
            if key not in ("matches", "unmatched_truth")
        }
        for mode, result in summary["evaluation"].items()
    }
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "본문 font density band에서 line spacing을 추론해 OCR line을 chunk화하고, "
            "연속 chunk anchor pattern과 font 후보를 독립적으로 비교한다."
        ),
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "font-size 분포는 강건한 Silverman bandwidth KDE의 valley로 band를 "
            "나누고 문서 median이 속한 band를 본문으로 정했다. 본문 line spacing "
            "중앙값이 속한 density band의 상한으로 chunk를 만들었다. 같은 page에서 "
            "연속되고 같은 non-body font 방향이며 bbox gap이 본문 spacing 이내인 "
            "chunk는 첫 anchor를 보존해 병합했다. position tolerance는 다른 page의 "
            "최근접 anchor pattern 거리 중앙값으로, 최소 반복 page 수는 support "
            "histogram의 최대 감소 지점으로 추론했다."
        ),
        "summary": compact_summary,
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
    config = TypographyConfig()
    raw_lines = extract_typography_lines(INPUT_PDF, config)
    lines, margin_report = exclude_overlay_density_margins(raw_lines)
    body_font_band = infer_body_font_band(lines)
    rows, median_line_height = build_visual_rows(lines)
    line_spacing, spacing_report = estimate_line_spacing(rows, body_font_band)
    initial_chunks = build_chunks(rows, spacing_report["continuation_upper"])
    chunks, adjacent_merge_report = merge_adjacent_non_body_chunks(
        initial_chunks, body_font_band, line_spacing
    )
    patterns = build_anchor_patterns(chunks, line_spacing)

    position_inference = infer_position_tolerance(patterns)
    position_ids, pattern_reports, pattern_support = select_position_candidates(
        patterns, position_inference["tolerance_line_spacings"]
    )
    font_ids = select_font_candidates(chunks, body_font_band)
    mode_ids = {
        "position": position_ids,
        "font": font_ids,
        "and": position_ids & font_ids,
    }
    level_tolerance = body_font_band["bandwidth"] / body_font_band["font_size"]
    truth = load_truth()
    files = {}
    for mode, candidate_ids in mode_ids.items():
        selected = [chunk for chunk in chunks if chunk.chunk_id in candidate_ids]
        path = OUTPUT_DIR / f"bookmark_tree_{mode}.txt"
        files[mode] = {
            "path": str(path.relative_to(ROOT_DIR)),
            "count": write_tree(path, selected, level_tolerance),
        }
    inferred_by_mode = {
        mode: assign_levels(
            [chunk for chunk in chunks if chunk.chunk_id in candidate_ids],
            level_tolerance,
        )
        for mode, candidate_ids in mode_ids.items()
    }
    union_chunks = [
        chunk for chunk in chunks if chunk.chunk_id in (position_ids | font_ids)
    ]
    best_scores = [
        max(
            (
                title_score(entry["title"], chunk.text)
                for chunk in union_chunks
                if chunk.pdf_page == entry["pdf_page"]
            ),
            default=0.0,
        )
        for entry in truth
    ]
    match_threshold = infer_match_threshold(best_scores)
    evaluation = {
        mode: evaluate_mode(truth, inferred, match_threshold)
        for mode, inferred in inferred_by_mode.items()
    }
    (OUTPUT_DIR / "evaluation.json").write_text(
        json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    default_chunks = [chunk for chunk in chunks if chunk.chunk_id in mode_ids["and"]]
    write_tree(OUTPUT_DIR / "bookmark_tree.txt", default_chunks, level_tolerance)

    candidate_counts = {
        mode: len(candidate_ids) for mode, candidate_ids in mode_ids.items()
    }
    finding = (
        f"visual lines={len(lines)}, visual rows={len(rows)}, chunks={len(chunks)}, "
        f"adjacent non-body merges={adjacent_merge_report['merge_count']}, "
        f"body-only top-to-top median={line_spacing:.3f}, "
        f"body font={body_font_band['font_size']:.3f}, "
        f"inferred position tolerance="
        f"{position_inference['tolerance_line_spacings']:.3f} line spacings, "
        f"inferred minimum pages={pattern_support['minimum_pages']}, "
        f"position AND font candidates={candidate_counts['and']}, "
        f"truth={len(truth)}, match threshold={match_threshold:.3f}. "
        "수동 position/font tolerance는 사용하지 않았다."
    )
    summary = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "margin_report": margin_report,
        "raw_line_count": len(raw_lines),
        "line_count": len(lines),
        "visual_row_count": len(rows),
        "chunk_count": len(chunks),
        "adjacent_non_body_merge": adjacent_merge_report,
        "median_line_height": median_line_height,
        "font_density": body_font_band,
        "body_spacing": spacing_report,
        "position_inference": position_inference,
        "pattern_support": pattern_support,
        "candidate_counts": candidate_counts,
        "truth_count": len(truth),
        "match_threshold": match_threshold,
        "evaluation": evaluation,
        "accepted_position_patterns": pattern_reports,
        "files": files,
        "default_mode": "position AND font",
        "bookmark_tree_txt": str(
            (OUTPUT_DIR / "bookmark_tree.txt").relative_to(ROOT_DIR)
        ),
        "finding": finding,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_experiment(summary)
    compact_evaluation = {
        mode: {
            key: value
            for key, value in result.items()
            if key not in ("matches", "unmatched_truth")
        }
        for mode, result in evaluation.items()
    }
    print(
        json.dumps(
            {
                "body_font_band": body_font_band,
                "body_spacing": spacing_report,
                "position_inference": position_inference,
                "pattern_support": pattern_support,
                "candidate_counts": candidate_counts,
                "truth_count": len(truth),
                "match_threshold": match_threshold,
                "evaluation": compact_evaluation,
                "finding": finding,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
