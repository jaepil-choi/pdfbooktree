"""experiment 055: 페이지를 tier 분포 벡터로 표현해 clustering하면 chapter-start가 묶이는가.

052~054에서 KDE valley cut(+2px 거리 병합)으로 book 전체 line의 font_size tier를
만들었다. 이 실험은 그 tier를 이용해 "페이지"를 단위로 다시 본다.

애초 아이디어는 페이지 안에서 top line -> bottom line의 tier 순서(sequence)를 그대로
보존해 페이지끼리 비교하는 것이었다. 하지만 순서를 강제하면 chapter-start처럼 아주
뚜렷한 모양(큰 tier 한두 줄 + 본문 tier 나머지)만 잡힐 뿐, 그보다 작은 단위(예: 본문
중간에 절 제목이 섞인 페이지)는 순서 제약 때문에 오히려 못 묶일 수 있다는 지적을
받아, 순서를 버리고 "이 페이지에 어떤 tier가 얼마나 있는가"라는 tier 분포만 벡터로
만들어 clustering한다. 벡터는 두 가지로 다 만든다: (1) tier별 절대 줄 수(count),
(2) 페이지 길이로 나눈 tier별 비율(normalized). 페이지 길이 편향이 있는지 두 버전을
비교해서 확인한다.

tier 자체도 두 단계로 정제한다: KDE 봉우리/골짜기 -> 2px 미만 거리 병합(052/054) ->
최소 5회 미만 등장하는 tier는 노이즈로 보고 가장 가까운 이웃 tier로 흡수하는 병합을
새로 추가한다(min-count 병합).

검증: John Hull bookmark의 level 1 'Chapter N. ...' page(진짜 장 시작 page, 37개)로
count/normalized/presence 세 벡터를 비교했더니 count/normalized는 제목이 짧은 챕터를
누락시켰고, presence(tier별 존재 여부 0/1, 제목 줄 수에 영향받지 않음)를 추가하니
recall 1.0(37/37)을 달성했다. 이 방법을 data/ 아래 나머지 5권(Shreve, Luenberger,
algorithm 두 권, 수리통계학 scanned)에도 그대로 적용해 일반화되는지 확인한다.
bookmark가 없거나('scanned-pdf-not-indexed') 신뢰할 chapter 패턴이 없는 책은 F1
검증 없이 presence_vector clustering 결과만으로 tree를 만든다.

[재작업] line 병합 단계에서 height를 계산만 하고 버리고 있었다(y_gate 임계값에만
쓰고 최종 line에는 font_size만 남김). height를 median으로 살려 line에 남기고,
font_size/height 두 신호로 tiering->vectorize->clustering->tree 전체 파이프라인을
각각 따로 돌려(052 방식) 책마다 두 신호 결과를 나란히 비교한다(run_signal).

실행:
    uv run python experiments/055_page_tier_distribution_clustering.py
출력:
    experiments/outputs/055_page_tier_distribution_clustering/
        - summary.json                                        : 책 전체 결과 요약
        - <book_id>/<font_size|height>/page_tier_vectors.csv  : 페이지별 tier count/normalized/presence 벡터 + 클러스터 결과
        - <book_id>/<font_size|height>/clusters_<tag>_silhouette.txt : vector별 silhouette 최적 k 클러스터(최대 50개/cluster)
        - <book_id>/<font_size|height>/clusters_<tag>_bestf1.txt     : vector별 chapter-start 적중 F1 최적 k(truth 있는 책만)
        - <book_id>/<font_size|height>/inferred_bookmark_tree.txt    : quality-pass cluster page 번호로 만든 human-readable flat tree
        - <book_id>/<font_size|height>/inferred_bookmark_tree.json   : 위와 동일한 내용의 구조화 버전
        - <book_id>/summary.json                    : 책별 요약
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
import numpy as np
from scipy.signal import argrelextrema
from scipy.stats import gaussian_kde
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "055_page_tier_distribution_clustering"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

# 책마다 bookmark 계층에서 '진짜 chapter 시작'이 어느 level/제목 패턴으로 나오는지
# 다르다(John Hull은 level 1 'Chapter N.', Shreve는 level 1 'N Title', Luenberger는
# Part 아래 level 2 'Chapter NN Title'). bookmark가 없는 책(algorithm 시리즈, 수리통계학
# scanned-not-indexed)은 truth_level=None으로 두면 F1 검증 없이 clustering 결과만 본다.
BOOKS = [
    {
        "id": "john_hull",
        "pdf": ROOT_DIR / "data" / "native-pdf-indexed" / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf",
        "truth_level": 1,
        "truth_pattern": re.compile(r"^Chapter\s+\d+\.", re.IGNORECASE),
    },
    {
        "id": "shreve_binomial",
        "pdf": ROOT_DIR / "data" / "scanned-pdf-indexed" / "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf",
        "truth_level": 1,
        "truth_pattern": re.compile(r"^\d+\s+[A-Z]"),
    },
    {
        "id": "luenberger_investment_science",
        "pdf": ROOT_DIR / "data" / "scanned-pdf-indexed" / "David G. Luenberger, Investment Science 2nd - adobeOCR - indexed.pdf",
        "truth_level": 2,
        "truth_pattern": re.compile(r"^Chapter\s+\d+\s", re.IGNORECASE),
    },
    {
        "id": "algorithm_nine",
        "pdf": ROOT_DIR / "data" / "scanned-pdf-not-indexed" / "미래를_바꾼_아홉가지_알고리즘_-_존_맥코믹-compressed[algorithm cs book].pdf",
        "truth_level": None,
        "truth_pattern": None,
    },
    {
        "id": "algorithms_to_live_by",
        "pdf": ROOT_DIR / "data" / "scanned-pdf-not-indexed" / "알고리즘_인생을계산하다_The_computer_science_of_human_decisions_-_BrianChristian.pdf",
        "truth_level": None,
        "truth_pattern": None,
    },
    {
        "id": "suri_tonggyehak_scanned",
        "pdf": ROOT_DIR / "data" / "scanned-pdf-not-indexed" / "수리통계학(개정판)-김우철_upocr_merged.pdf",
        "truth_level": None,
        "truth_pattern": None,
    },
]

MIN_GAP = 2.0
MIN_TIER_COUNT = 5
MAX_SAMPLES_PER_CLUSTER = 50
K_RANGE = range(2, 16)
CANDIDATE_K = [2, 3, 4, 5, 6, 8, 10, 15, 20, 30, 39, 50]
RANDOM_SEED = 20260705

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def extract_page_content_spans(page: fitz.Page) -> list[dict[str, Any]]:
    """page의 모든 content span을 fitz block/line 경계와 무관하게 평평하게 뽑는다(054와 동일)."""

    spans: list[dict[str, Any]] = []
    data = page.get_text("dict")
    for block in data["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"]
                if not text.strip() or not is_content_span(text):
                    continue
                y0, y1 = span["bbox"][1], span["bbox"][3]
                spans.append(
                    {
                        "text": text.strip(),
                        "height": round(y1 - y0, 2),
                        "font_size": round(float(span["size"]), 2),
                        "yc": (y0 + y1) / 2.0,
                        "x0": float(span["bbox"][0]),
                    }
                )
    return spans


def merge_spans_into_lines(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 시각적 줄에 있는 text box(span)들을 y좌표로 다시 묶고 median height/size를 낸다(054와 동일)."""

    if not spans:
        return []

    med_h = float(np.median([span["height"] for span in spans]))
    y_gate = max(med_h * 0.6, 1e-6)

    ordered = sorted(spans, key=lambda span: (span["yc"], span["x0"]))
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_yc: float | None = None
    for span in ordered:
        if current and current_yc is not None and abs(span["yc"] - current_yc) > y_gate:
            groups.append(current)
            current = []
        current.append(span)
        current_yc = float(np.mean([item["yc"] for item in current]))
    if current:
        groups.append(current)

    merged: list[dict[str, Any]] = []
    for group in groups:
        group_sorted = sorted(group, key=lambda span: span["x0"])
        sizes = [span["font_size"] for span in group_sorted]
        heights = [span["height"] for span in group_sorted]
        merged.append(
            {
                "font_size": round(float(np.median(sizes)), 2),
                "height": round(float(np.median(heights)), 2),
                "text": " ".join(span["text"] for span in group_sorted)[:120],
            }
        )
    return merged


def extract_book_pages(pdf_path: Path) -> dict[int, list[dict[str, Any]]]:
    """page_no -> [line(top~bottom 순서), ...] 사전을 만든다."""

    pages: dict[int, list[dict[str, Any]]] = {}
    with fitz.open(pdf_path) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            spans = extract_page_content_spans(page)
            merged_lines = merge_spans_into_lines(spans)
            if merged_lines:
                pages[page_index + 1] = merged_lines
    return pages


def cluster_by_density(values: list[float]) -> dict[str, Any]:
    """1D 값을 KDE 밀도의 봉우리/골짜기로 클러스터링한다(k 미고정, 052~054와 동일)."""

    arr = np.asarray(values, dtype=float)
    uniq = np.unique(arr)
    if uniq.size == 1:
        return {"tier_count": 1, "cut_points": [], "peaks": [float(uniq[0])]}
    if uniq.size < 3:
        return {
            "tier_count": int(uniq.size),
            "cut_points": [float((uniq[i] + uniq[i + 1]) / 2.0) for i in range(uniq.size - 1)],
            "peaks": sorted((float(v) for v in uniq), reverse=True),
        }

    kde = gaussian_kde(arr)
    grid = np.linspace(arr.min() - 1.0, arr.max() + 1.0, 4096)
    density = kde(grid)

    peak_idx = argrelextrema(density, np.greater)[0]
    valley_idx = argrelextrema(density, np.less)[0]
    if peak_idx.size == 0:
        return {"tier_count": 1, "cut_points": [], "peaks": [float(np.median(arr))]}

    peaks = [float(grid[i]) for i in peak_idx]
    cut_points = [float(grid[vi]) for vi in valley_idx if peaks[0] < grid[vi] < peaks[-1]]
    cut_points = sorted(cut_points)[: max(len(peaks) - 1, 0)]

    return {"tier_count": len(peaks), "cut_points": cut_points, "peaks": sorted(peaks, reverse=True)}


def merge_close_tiers(peaks: list[float], cut_points: list[float], min_gap: float) -> tuple[list[float], list[float]]:
    """인접 tier의 peak 차이가 min_gap 미만이면 사슬식으로 병합한다(052/054와 동일)."""

    peaks_asc = sorted(peaks)
    cuts_asc = sorted(cut_points)
    if len(peaks_asc) <= 1:
        return sorted(peaks, reverse=True), []

    merged_peaks = [peaks_asc[0]]
    merged_cuts: list[float] = []
    for i in range(1, len(peaks_asc)):
        gap = peaks_asc[i] - merged_peaks[-1]
        if gap < min_gap:
            merged_peaks[-1] = (merged_peaks[-1] + peaks_asc[i]) / 2.0
        else:
            cut = cuts_asc[i - 1] if i - 1 < len(cuts_asc) else (peaks_asc[i - 1] + peaks_asc[i]) / 2.0
            merged_cuts.append(cut)
            merged_peaks.append(peaks_asc[i])

    return sorted(merged_peaks, reverse=True), sorted(merged_cuts)


def assign_tier(value: float, cut_points: list[float]) -> int:
    tier = 1
    for cut in sorted(cut_points, reverse=True):
        if value >= cut:
            return tier
        tier += 1
    return tier


def merge_tiers_by_min_count(
    values: list[float], peaks: list[float], cut_points: list[float], min_count: int
) -> tuple[list[float], list[float]]:
    """책 전체에서 min_count번 미만 등장하는 tier를, 값이 더 가까운 이웃 tier로 흡수한다.

    2px 거리 병합(merge_close_tiers)과는 독립적인 후처리다 — 거리는 멀어도 등장
    빈도가 너무 낮은 tier(수식/장식 폰트 파편)를 노이즈로 보고 없앤다.
    """

    peaks_desc = sorted(peaks, reverse=True)
    cuts_desc = sorted(cut_points, reverse=True)

    while len(peaks_desc) > 1:
        counts = Counter(assign_tier(value, cuts_desc) for value in values)
        tier_counts = [counts.get(i + 1, 0) for i in range(len(peaks_desc))]
        min_idx = min(range(len(tier_counts)), key=lambda i: tier_counts[i])
        if tier_counts[min_idx] >= min_count:
            break

        if min_idx == 0:
            merge_with = 1
        elif min_idx == len(peaks_desc) - 1:
            merge_with = min_idx - 1
        else:
            left_gap = peaks_desc[min_idx - 1] - peaks_desc[min_idx]
            right_gap = peaks_desc[min_idx] - peaks_desc[min_idx + 1]
            merge_with = min_idx - 1 if left_gap <= right_gap else min_idx + 1

        lo_idx, hi_idx = sorted([min_idx, merge_with])
        del cuts_desc[lo_idx]
        peaks_desc[lo_idx] = (peaks_desc[lo_idx] + peaks_desc[hi_idx]) / 2.0
        del peaks_desc[hi_idx]

    return peaks_desc, cuts_desc


def compute_tiers(values: list[float], min_gap: float, min_count: int) -> dict[str, Any]:
    """KDE 봉우리/골짜기 -> 2px 거리 병합 -> 최소 등장 횟수 병합, 3단계를 한 번에 묶는다.

    font_size와 height 어느 신호든 같은 방식으로 tier를 만들 수 있게 값 리스트만
    받는다(052/054/055가 공유하는 순서).
    """

    raw = cluster_by_density(values)
    gap_peaks, gap_cuts = merge_close_tiers(raw["peaks"], raw["cut_points"], min_gap)
    final_peaks, final_cuts = merge_tiers_by_min_count(values, gap_peaks, gap_cuts, min_count)
    return {
        "raw_tier_count": raw["tier_count"],
        "gap_merged_peaks": gap_peaks,
        "gap_merged_cuts": gap_cuts,
        "gap_merged_tier_count": len(gap_peaks),
        "final_peaks": final_peaks,
        "final_cuts": final_cuts,
        "final_tier_count": len(final_peaks),
    }


def build_page_vectors(
    pages: dict[int, list[dict[str, Any]]],
    cut_points: list[float],
    tier_count: int,
    value_key: str = "font_size",
) -> dict[int, dict[str, Any]]:
    """page_no -> {count_vector, normalized_vector, top_tier_text, line_count}.

    value_key로 font_size/height 어느 신호를 tiering에 쓸지 고른다.
    """

    out: dict[int, dict[str, Any]] = {}
    for page_no, lines in pages.items():
        tiers = [assign_tier(line[value_key], cut_points) for line in lines]
        counts = Counter(tiers)
        count_vec = [counts.get(t, 0) for t in range(1, tier_count + 1)]
        total = sum(count_vec)
        norm_vec = [c / total for c in count_vec] if total else [0.0] * tier_count
        # presence_vector: 제목이 1줄이든 3줄이든 '그 tier가 있냐 없냐'만 본다.
        # normalized_vector는 count_T1을 전체 줄 수로 나눠 제목 줄 수(구조와 무관)에
        # 따라 값이 흔들리는데, presence는 그 흔들림을 아예 없앤다.
        presence_vec = [1.0 if c > 0 else 0.0 for c in count_vec]
        top_tier_idx = min(tiers)
        top_line_text = next(
            line["text"] for line, tier in zip(lines, tiers) if tier == top_tier_idx
        )
        # tree 제목용: top tier에 속하는 line을 전부(순서대로) 이어붙인다. 장 표제가
        # 'Determination of' / 'Forward and' / 'Futures Prices'처럼 여러 줄로 나뉘는
        # 경우 top_line_text 한 줄만으로는 제목이 잘리기 때문이다.
        top_tier_full_text = " ".join(
            line["text"] for line, tier in zip(lines, tiers) if tier == top_tier_idx
        )
        out[page_no] = {
            "count_vector": count_vec,
            "normalized_vector": norm_vec,
            "presence_vector": presence_vec,
            "line_count": total,
            "top_tier": top_tier_idx,
            "top_tier_full_text": top_tier_full_text,
            "top_tier_text": top_line_text,
        }
    return out


def choose_best_k(features: np.ndarray, k_range: range) -> tuple[int, dict[int, float]]:
    scores: dict[int, float] = {}
    for k in k_range:
        if k >= len(features):
            break
        model = KMeans(n_clusters=k, random_state=RANDOM_SEED, n_init=10)
        labels = model.fit_predict(features)
        if len(set(labels)) < 2:
            continue
        scores[k] = float(silhouette_score(features, labels))
    best_k = max(scores, key=scores.get) if scores else 2
    return best_k, scores


def sweep_k_for_f1(
    features: np.ndarray, page_ids: list[int], truth_pages: set[int], k_list: list[int]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """silhouette는 최대 분산 기준이라 body-tier 줄 수 편차 같은 구조 무관 축에 끌려갈 수 있다.

    그래서 여러 k를 직접 돌려보고, dominant cluster가 실제 chapter-start와 얼마나
    맞는지(precision/recall/F1)로도 별도로 골라본다.
    """

    results: list[dict[str, Any]] = []
    for k in k_list:
        if k >= len(features):
            continue
        model = KMeans(n_clusters=k, random_state=RANDOM_SEED, n_init=10)
        cluster_labels = model.fit_predict(features)
        labels = {page: int(label) for page, label in zip(page_ids, cluster_labels)}
        stat = evaluate_against_truth(labels, truth_pages)
        precision = stat["dominant_cluster_precision"]
        recall = stat["dominant_cluster_recall"]
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        results.append({"k": k, "precision": precision, "recall": recall, "f1": round(f1, 4), "labels": labels, "stat": stat})
    best = max(results, key=lambda r: r["f1"]) if results else None
    return best, results


def chapter_start_pages(pdf_path: Path, truth_level: int | None, truth_pattern: re.Pattern | None) -> list[int]:
    """bookmark에서 truth_level/truth_pattern에 맞는 '진짜 chapter 시작' page를 뽑는다.

    책마다 chapter가 bookmark의 어느 level, 어떤 제목 패턴으로 나오는지 다르다.
    truth_level이 None이면(bookmark 자체가 없거나 신뢰할 패턴이 없는 책) 빈 목록을
    반환해 F1 검증 없이 clustering 결과만 보게 한다.
    """

    if truth_level is None or truth_pattern is None:
        return []
    with fitz.open(pdf_path) as document:
        toc = document.get_toc(simple=False)
    return sorted(
        page_no for level, title, page_no, _dest in toc if level == truth_level and truth_pattern.match(title)
    )


def pick_top_tier_cluster(
    labels: dict[int, int], vectors: dict[int, dict[str, Any]], vector_key: str, tier_index: int = 0
) -> list[int]:
    """bookmark 정답이 없는 책에서 쓰는 대안 선택 규칙.

    presence_vector의 T1(tier_index=0, 가장 큰 tier)이 있는 page 비중이 가장 높은
    cluster를 'quality-pass cluster'로 채택한다. ground truth F1이 없을 때도 같은
    clustering 파이프라인으로 chapter-like page를 골라낼 수 있는지 확인하는 용도다.
    """

    by_cluster: dict[int, list[int]] = {}
    for page, label in labels.items():
        by_cluster.setdefault(label, []).append(page)
    cluster_means = {
        label: float(np.mean([vectors[page][vector_key][tier_index] for page in members]))
        for label, members in by_cluster.items()
    }
    best_label = max(cluster_means, key=cluster_means.get)
    return by_cluster[best_label]


def evaluate_against_truth(labels: dict[int, int], truth_pages: set[int]) -> dict[str, Any]:
    truth_labels = Counter(labels[page] for page in truth_pages if page in labels)
    dominant_cluster, dominant_hits = truth_labels.most_common(1)[0] if truth_labels else (None, 0)
    cluster_sizes = Counter(labels.values())
    dominant_size = cluster_sizes.get(dominant_cluster, 0)
    return {
        "truth_page_count": len(truth_pages),
        "truth_pages_found": sum(truth_labels.values()),
        "distinct_clusters_hit": len(truth_labels),
        "dominant_cluster": dominant_cluster,
        "dominant_cluster_size": dominant_size,
        "dominant_cluster_recall": round(dominant_hits / max(len(truth_pages), 1), 4),
        "dominant_cluster_precision": round(dominant_hits / max(dominant_size, 1), 4),
        "cluster_hit_breakdown": dict(truth_labels),
    }


def dump_clusters(
    path: Path,
    labels: dict[int, int],
    vectors: dict[int, dict[str, Any]],
    truth_pages: set[int],
    vector_key: str,
) -> None:
    by_cluster: dict[int, list[int]] = {}
    for page_no, label in labels.items():
        by_cluster.setdefault(label, []).append(page_no)

    out: list[str] = []
    for cluster_id in sorted(by_cluster):
        member_pages = sorted(by_cluster[cluster_id])
        truth_hits = sum(1 for page in member_pages if page in truth_pages)
        out.append(
            f"===== cluster {cluster_id} n={len(member_pages)} "
            f"chapter_start_hits={truth_hits} (표시 최대 {MAX_SAMPLES_PER_CLUSTER}) ====="
        )
        for page_no in member_pages[:MAX_SAMPLES_PER_CLUSTER]:
            info = vectors[page_no]
            mark = " [CHAPTER-START]" if page_no in truth_pages else ""
            out.append(
                f"  p{page_no:>4} {vector_key}={info[vector_key]} "
                f"top_tier=T{info['top_tier']} text={info['top_tier_text']!r}{mark}"
            )
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


def write_csv(path: Path, pages: dict[int, dict[str, Any]], tier_count: int) -> None:
    keys = (
        ["pdf_page", "line_count", "top_tier", "top_tier_text"]
        + [f"count_T{t}" for t in range(1, tier_count + 1)]
        + [f"norm_T{t}" for t in range(1, tier_count + 1)]
        + [f"presence_T{t}" for t in range(1, tier_count + 1)]
        + ["cluster_count_vec", "cluster_normalized_vec", "cluster_presence_vec"]
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for page_no in sorted(pages):
            info = pages[page_no]
            row = {
                "pdf_page": page_no,
                "line_count": info["line_count"],
                "top_tier": info["top_tier"],
                "top_tier_text": info["top_tier_text"],
                "cluster_count_vec": info.get("cluster_count_vec"),
                "cluster_normalized_vec": info.get("cluster_normalized_vec"),
                "cluster_presence_vec": info.get("cluster_presence_vec"),
            }
            for t in range(1, tier_count + 1):
                row[f"count_T{t}"] = info["count_vector"][t - 1]
                row[f"norm_T{t}"] = round(info["normalized_vector"][t - 1], 4)
                row[f"presence_T{t}"] = info["presence_vector"][t - 1]
            writer.writerow(row)


def build_inferred_bookmark_tree(
    quality_pass_pages: list[int], vectors: dict[int, dict[str, Any]], total_pages: int
) -> list[dict[str, Any]]:
    """quality pass한 cluster의 page 번호만 보고 flat chapter tree를 만든다.

    시퀀스/순서 정보 없이, 정렬된 page 번호를 그대로 chapter 경계로 쓴다: 이 page부터
    다음 quality-pass page 바로 앞까지가 한 chapter다. 제목은 그 page에서 top tier에
    속한 줄을 전부 이어붙인 텍스트를 쓴다.
    """

    ordered = sorted(quality_pass_pages)
    tree: list[dict[str, Any]] = []
    for index, page_no in enumerate(ordered):
        start = page_no
        end = (ordered[index + 1] - 1) if index + 1 < len(ordered) else total_pages
        title = re.sub(r"\s+", " ", vectors[page_no]["top_tier_full_text"]).strip()
        tree.append({"index": index + 1, "title": title, "start_page": start, "end_page": end})
    return tree


def render_tree_text(tree: list[dict[str, Any]], truth_pages: set[int]) -> list[str]:
    out = [f"총 {len(tree)}개 chapter 노드 (quality-pass cluster의 page 번호로만 구성한 flat tree)", ""]
    for node in tree:
        mark = " [bookmark 'Chapter N.'와 일치]" if node["start_page"] in truth_pages else " [비교 대상 밖 또는 새로 발견]"
        out.append(
            f"{node['index']:02d}. p.{node['start_page']}-{node['end_page']}  {node['title']}{mark}"
        )
    return out


def record_experiment(finding: str, extra: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "052~054의 font_size/height tier(KDE valley cut + 2px 거리 병합 + 최소 5회 "
            "등장 빈도 병합)에서 만든 tier로, 페이지의 top~bottom 순서를 버리고 페이지별 "
            "tier 분포(count/normalized/presence 세 벡터)로 KMeans clustering해 "
            "chapter-start page가 뭉치는지 본다. line 병합 단계에서 버려지고 있던 "
            "height를 median으로 되살려 font_size와 나란히 두 신호로 전체 파이프라인을 "
            "각각 돌린다(run_signal). John Hull에서 검증한 방법을 data/ 아래 나머지 "
            "5권(Shreve, Luenberger, algorithm 두 권, 수리통계학)에도 그대로 적용해 "
            "일반화되는지 확인하고, 책·신호마다 quality-pass cluster로 human-readable "
            "flat bookmark tree를 inferred_bookmark_tree.txt로 남긴다."
        ),
        "inputs": [str(book["pdf"].relative_to(ROOT_DIR)) for book in BOOKS],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": [
            "052_whole_book_line_font_height_kde",
            "053_bookmark_depth_font_size_kde",
            "054_tier_merge_and_scanned_font_check",
        ],
        "min_gap": MIN_GAP,
        "min_tier_count": MIN_TIER_COUNT,
        "finding": finding,
        **extra,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    experiments = data.get("experiments", data) if isinstance(data, dict) else data
    experiments = [experiment for experiment in experiments if experiment.get("id") != EXPERIMENT_ID]
    experiments.append(entry)
    if isinstance(data, dict):
        data["experiments"] = experiments
    else:
        data = experiments
    EXPERIMENTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


VECTOR_TAGS = {
    "count_vector": "count",
    "normalized_vector": "normalized",
    "presence_vector": "presence",
}


def run_signal(
    pages: dict[int, list[dict[str, Any]]],
    value_key: str,
    book_id: str,
    truth_pages: set[int],
    signal_output_dir: Path,
) -> dict[str, Any]:
    """font_size든 height든, 같은 tiering->vectorize->clustering->tree 파이프라인을 돌린다.

    052에서 font_size/height를 나란히 비교했던 것처럼, 055도 신호 하나에 얽매이지
    않고 두 신호 결과를 나란히 비교할 수 있게 이 로직을 분리했다.
    """

    signal_output_dir.mkdir(parents=True, exist_ok=True)
    has_truth = bool(truth_pages)

    all_values = [line[value_key] for lines in pages.values() for line in lines]
    tiers = compute_tiers(all_values, MIN_GAP, MIN_TIER_COUNT)
    tier_count = tiers["final_tier_count"]
    print(
        f"    [{value_key}] tiers: raw={tiers['raw_tier_count']} -> gap_merged={tiers['gap_merged_tier_count']} "
        f"-> min_count_merged={tier_count}",
        flush=True,
    )

    vectors = build_page_vectors(pages, tiers["final_cuts"], tier_count, value_key=value_key)

    results: dict[str, Any] = {}
    all_labels: dict[str, dict[int, int]] = {}
    for vector_key, tag in VECTOR_TAGS.items():
        page_ids = sorted(vectors)
        features = np.asarray([vectors[p][vector_key] for p in page_ids], dtype=float)
        best_k, k_scores = choose_best_k(features, K_RANGE)
        model = KMeans(n_clusters=best_k, random_state=RANDOM_SEED, n_init=10)
        cluster_labels = model.fit_predict(features)
        labels = {page: int(label) for page, label in zip(page_ids, cluster_labels)}
        all_labels[vector_key] = labels

        cluster_field = f"cluster_{tag}_vec"
        for page, label in labels.items():
            vectors[page][cluster_field] = label

        eval_stat = evaluate_against_truth(labels, truth_pages)
        dump_clusters(signal_output_dir / f"clusters_{tag}_silhouette.txt", labels, vectors, truth_pages, vector_key)

        stat: dict[str, Any] = {
            "best_k": best_k,
            "silhouette_scores": {str(k): round(v, 4) for k, v in k_scores.items()},
            "silhouette_best": round(k_scores.get(best_k, 0.0), 4),
            "eval_vs_chapter_start": eval_stat,
        }

        if has_truth:
            # silhouette는 body-tier 줄 수 편차처럼 구조와 무관한 축에 끌려가 chapter-start를
            # 놓칠 수 있어(k=2에서 실제로 그랬다), chapter-start 적중 F1이 가장 좋은 k도 따로 찾는다.
            best_f1, f1_sweep = sweep_k_for_f1(features, page_ids, truth_pages, CANDIDATE_K)
            if best_f1 is not None:
                dump_clusters(
                    signal_output_dir / f"clusters_{tag}_bestf1.txt", best_f1["labels"], vectors, truth_pages, vector_key
                )
            stat.update(
                {
                    "f1_sweep": [
                        {"k": r["k"], "precision": r["precision"], "recall": r["recall"], "f1": r["f1"]}
                        for r in f1_sweep
                    ],
                    "best_f1_k": best_f1["k"] if best_f1 else None,
                    "best_f1_score": best_f1["f1"] if best_f1 else 0.0,
                    "best_f1_eval": best_f1["stat"] if best_f1 else None,
                    "best_f1_labels": best_f1["labels"] if best_f1 else None,
                }
            )
        results[vector_key] = stat

    write_csv(signal_output_dir / "page_tier_vectors.csv", vectors, tier_count)

    quality_pass_pages: list[int] = []
    quality_pass_source = ""
    if has_truth:
        best_vector_key = max(results, key=lambda key: results[key].get("best_f1_score", 0.0))
        best_result = results[best_vector_key]
        if best_result.get("best_f1_labels") and best_result.get("best_f1_eval"):
            dominant_cluster = best_result["best_f1_eval"]["dominant_cluster"]
            quality_pass_pages = [
                page for page, label in best_result["best_f1_labels"].items() if label == dominant_cluster
            ]
        quality_pass_source = f"{best_vector_key} F1-best dominant cluster"
    else:
        quality_pass_pages = pick_top_tier_cluster(all_labels["presence_vector"], vectors, "presence_vector", 0)
        quality_pass_source = "presence_vector silhouette-best, T1 비중 최고 cluster(ground truth 없음)"

    inferred_tree = build_inferred_bookmark_tree(quality_pass_pages, vectors, max(pages))
    tree_text = render_tree_text(inferred_tree, truth_pages)
    if not has_truth:
        tree_text.insert(1, "(이 책은 bookmark 정답이 없어 precision/recall 검증 없이 clustering 결과만 표시한다)")
    (signal_output_dir / "inferred_bookmark_tree.txt").write_text("\n".join(tree_text), encoding="utf-8")
    (signal_output_dir / "inferred_bookmark_tree.json").write_text(
        json.dumps(inferred_tree, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    finding = (
        f"[{value_key}] tier {tiers['raw_tier_count']}(raw)->{tiers['gap_merged_tier_count']}(2px 병합)"
        f"->{tier_count}(min_count={MIN_TIER_COUNT} 병합, peaks={[round(p, 2) for p in tiers['final_peaks']]}). "
    )
    if has_truth:
        for vector_key, stat in results.items():
            if stat.get("best_f1_eval"):
                fev = stat["best_f1_eval"]
                finding += (
                    f"{vector_key} F1-best k={stat['best_f1_k']}: dominant cluster "
                    f"size={fev['dominant_cluster_size']} recall={fev['dominant_cluster_recall']} "
                    f"precision={fev['dominant_cluster_precision']}. "
                )
    finding += (
        f"quality-pass({quality_pass_source}) {len(quality_pass_pages)}개 page로 flat tree "
        f"{len(inferred_tree)}개 노드를 {book_id}/{value_key}/inferred_bookmark_tree.txt에 남겼다."
    )

    results_light = {
        vector_key: {key: value for key, value in stat.items() if key != "best_f1_labels"}
        for vector_key, stat in results.items()
    }

    return {
        "value_key": value_key,
        "tiers": {
            "raw_tier_count": tiers["raw_tier_count"],
            "gap_merged_tier_count": tiers["gap_merged_tier_count"],
            "final_tier_count": tier_count,
            "final_peaks": [round(p, 2) for p in tiers["final_peaks"]],
            "final_cuts": [round(c, 2) for c in tiers["final_cuts"]],
        },
        "quality_pass_source": quality_pass_source,
        "quality_pass_page_count": len(quality_pass_pages),
        "results": results_light,
        "inferred_bookmark_tree_nodes": len(inferred_tree),
        "finding": finding,
    }


def run_book(config: dict[str, Any]) -> dict[str, Any]:
    book_id = config["id"]
    pdf_path: Path = config["pdf"]
    truth_level = config["truth_level"]
    truth_pattern = config["truth_pattern"]
    book_output_dir = OUTPUT_DIR / book_id
    book_output_dir.mkdir(parents=True, exist_ok=True)

    print(f"... {book_id} 전체 page 훑는 중: {pdf_path.name}", flush=True)
    pages = extract_book_pages(pdf_path)
    total_lines = sum(len(lines) for lines in pages.values())
    print(f"    pages_with_content={len(pages)} total_lines={total_lines}", flush=True)

    truth_pages = set(chapter_start_pages(pdf_path, truth_level, truth_pattern))
    has_truth = bool(truth_pages)
    print(f"    chapter_start_truth_pages={len(truth_pages)} (has_truth={has_truth})", flush=True)

    # font_size와 height 둘 다로 같은 파이프라인을 돌려 나란히 비교한다(052 방식).
    signal_summaries = {
        value_key: run_signal(pages, value_key, book_id, truth_pages, book_output_dir / value_key)
        for value_key in ["font_size", "height"]
    }

    finding = f"{book_id}(truth={'있음 ' + str(len(truth_pages)) + '개' if has_truth else '없음'}, page_with_content={len(pages)}): "
    finding += " / ".join(signal_summaries[key]["finding"] for key in ["font_size", "height"])

    book_summary = {
        "book_id": book_id,
        "has_truth": has_truth,
        "page_with_content": len(pages),
        "chapter_start_truth_pages": sorted(truth_pages),
        "signals": signal_summaries,
        "finding": finding,
    }
    (book_output_dir / "summary.json").write_text(json.dumps(book_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    for value_key, signal_summary in signal_summaries.items():
        print(
            f"    [{value_key}] quality_pass={signal_summary['quality_pass_page_count']} "
            f"tree_nodes={signal_summary['inferred_bookmark_tree_nodes']}",
            flush=True,
        )
    return book_summary


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    book_summaries: list[dict[str, Any]] = []
    for config in BOOKS:
        book_summaries.append(run_book(config))

    combined_finding = " | ".join(summary["finding"] for summary in book_summaries)
    combined = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "books": {summary["book_id"]: summary for summary in book_summaries},
        "finding": combined_finding,
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    record_experiment(
        combined_finding,
        {
            "books": {
                summary["book_id"]: {
                    value_key: {"tiers": sig["tiers"], "results": sig["results"]}
                    for value_key, sig in summary["signals"].items()
                }
                for summary in book_summaries
            }
        },
    )

    print("\n=== exp 055: page tier distribution clustering (multi-book, font_size vs height) ===")
    for summary in book_summaries:
        fs = summary["signals"]["font_size"]
        ht = summary["signals"]["height"]
        print(
            f"- {summary['book_id']} (has_truth={summary['has_truth']}): "
            f"font_size tree_nodes={fs['inferred_bookmark_tree_nodes']} / height tree_nodes={ht['inferred_bookmark_tree_nodes']}"
        )
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
