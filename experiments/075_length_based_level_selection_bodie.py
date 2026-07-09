"""experiment 075: 본문 길이 기반 level cutoff 선택.

배경 (사용자 지적):
    074의 BPE 병합(bpe_min15)으로 Zvi Bodie의 candidate tree를 만들면 L1~L4까지
    나온다. 그런데 L4는 실제로 의미 있는 구조(예: "WORDS FROM THE STREET BOXES"
    사이드바 제목)일 때도 있지만, 상당수는 L4 폰트 tier가 본문 글씨 크기와 비슷해서
    본문 문단이 그대로 heading candidate로 잘못 잡힌 것이다("No risk, no reward.
    Most people intuitively understand..." 같은 문단 전체가 L4로 잡히는 사례).

    사용자 제안: "이 책은 L3까지만 잡아도 충분하다"는 판단을 tier 정확도를 하나하나
    고치는 방식이 아니라, **level 아래 들어가는 본문 길이**로 하자. 어떤 level 값을
    heading으로 쓸지는, 그 level의 연속된 두 heading 사이(현재 heading의 시작 page
    ~ 같은 level의 다음 heading이 시작하는 page 직전)에 들어가는 단어 수의 최댓값을
    구해서, 사용자가 지정한 목표 단어 수(예: 1000 단어)를 여전히 넘지 않는 선에서
    가장 깊은(세분화된) level을 고른다.

    예시(사용자 제공): level 1 아래 전체 책 100000 단어, level 2 아래 max 10000,
    level 3 아래 max 2000, level 4 아래 max 300 이고 목표가 1000이면 -> level 3을
    고른다("목표의 upper를 쓴다" - level 3 max(2000)는 아직 목표(1000) 이상이고,
    level 4 max(300)는 이미 목표 밑으로 떨어졌으므로 떨어지기 직전인 level 3에서
    멈춘다).

    이 기준은 부수적으로 노이즈 필터 역할도 한다: 본문 문단이 잘못 heading으로
    잡힌 tier는 그 tier의 후보가 책 전체에 너무 촘촘하게(문단마다) 나타나므로,
    같은 level 연속 heading 사이 간격(단어 수)이 극단적으로 작아진다. 그 결과 목표
    단어 수 기준을 적용하면 이런 tier는 애초에 selection 대상에서 자연히 제외된다
    - tier별 정확도를 직접 고치지 않아도 된다.

    이 실험은 074(bpe_min15, mode_and_smaller - 지금까지 최고 결과)로 만든 Zvi
    Bodie candidate tree에 이 길이 기반 selection을 적용해, 목표 1000단어일 때
    실제로 level 몇이 선택되는지 확인한다.

실행:
    uv run python experiments/075_length_based_level_selection_bodie.py
출력:
    experiments/outputs/075_length_based_level_selection_bodie/
        - candidate_tree.json (074와 동일 파이프라인으로 재생성한 flat tree)
        - level_length_stats.json (level별 단어 수 통계 + 목표별 선택 결과)
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

import fitz
import numpy as np
from scipy.signal import argrelextrema
from scipy.stats import gaussian_kde

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "075_length_based_level_selection_bodie"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

MIN_TIER_COUNT = 5
BODY_MODE = "mode_and_smaller"  # 074에서 가장 결과가 좋았던 body_mode
MERGE_GAP_RATIO = 1.5
MIN_PAIR_COUNT = 15  # 074 스윕에서 parent_accuracy/level_accuracy 동시 개선된 sweet spot
MAX_BPE_ITERATIONS = 50
TARGET_WORD_COUNTS = [500, 1000, 2000, 3000]  # 1000이 이번 실험의 핵심 질문, 나머지는 참고용

BOOK_PDF = (
    ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf"
)

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_DIGIT = re.compile(r"\d")
_WORD_SPLIT = re.compile(r"\S+")


# ---------------------------------------------------------------------------
# 074와 동일한 파이프라인 (line 추출 -> tier -> body 제외 -> bpe 병합 -> stack level)
# 074 script를 import하지 않고 그대로 복사한다(AGENTS.md 3절 monolithic 원칙).
# ---------------------------------------------------------------------------


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped) or _DIGIT.search(stripped))


def extract_page_content_spans(page: fitz.Page) -> list[dict[str, Any]]:
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
                "text": " ".join(span["text"] for span in group_sorted)[:160],
                "y0": min(item["yc"] for item in group_sorted),
            }
        )
    return merged


def extract_book_lines_and_page_word_counts(
    pdf_path: Path,
) -> tuple[list[dict[str, Any]], dict[int, int], int]:
    lines: list[dict[str, Any]] = []
    page_word_counts: dict[int, int] = {}
    with fitz.open(pdf_path) as document:
        page_count = document.page_count
        for page_index in range(page_count):
            page = document.load_page(page_index)
            pdf_page = page_index + 1
            spans = extract_page_content_spans(page)
            for merged_line in merge_spans_into_lines(spans):
                lines.append({"pdf_page": pdf_page, **merged_line})
            # [075 신규] level별 본문 길이 계산을 위해 page 전체 raw text의 단어 수를
            # 미리 세어 둔다(공백 기준 split, heading/본문 구분 없이 그 page에 있는
            # 모든 텍스트를 센다 - markdown export가 page range를 그대로 붙이는 방식과
            # 동일한 근사치).
            page_text = page.get_text("text")
            page_word_counts[pdf_page] = len(_WORD_SPLIT.findall(page_text))
    return lines, page_word_counts, page_count


def cluster_by_density(values: list[float]) -> dict[str, Any]:
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

    cut_points: list[float] = []
    for lo_peak_idx, hi_peak_idx in zip(peak_idx[:-1], peak_idx[1:]):
        between = [vi for vi in valley_idx if lo_peak_idx < vi < hi_peak_idx]
        best_idx = min(between, key=lambda vi: density[vi]) if between else (lo_peak_idx + hi_peak_idx) // 2
        cut_points.append(float(grid[best_idx]))

    return {"tier_count": len(peaks), "cut_points": cut_points, "peaks": sorted(peaks, reverse=True)}


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


def compute_tiers(values: list[float], min_count: int) -> dict[str, Any]:
    raw = cluster_by_density(values)
    final_peaks, final_cuts = merge_tiers_by_min_count(values, raw["peaks"], raw["cut_points"], min_count)
    return {
        "raw_tier_count": raw["tier_count"],
        "final_peaks": final_peaks,
        "final_cuts": final_cuts,
        "final_tier_count": len(final_peaks),
    }


def exclude_body_tiers(tier_of_line: list[int], tier_count: int, mode: str) -> set[int]:
    counts = Counter(tier_of_line)
    if mode == "mode_only":
        mode_tier = max(counts, key=counts.get)
        return {mode_tier}
    if mode == "mode_and_smaller":
        mode_tier = max(counts, key=counts.get)
        return set(range(mode_tier, tier_count + 1))
    raise ValueError(f"unknown body exclusion mode: {mode}")


def bpe_merge_page_local(
    filtered_lines: list[tuple[dict[str, Any], int]],
    gap_ratio: float,
    min_pair_count: int,
    max_iterations: int = MAX_BPE_ITERATIONS,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = [
        {
            "pdf_page": line["pdf_page"],
            "text": line["text"],
            "font_size": line["font_size"],
            "y0": line["y0"],
            "y1": line["y0"] + line["height"],
            "height": line["height"],
            "tier_seq": (tier,),
            "merged_line_count": 1,
        }
        for line, tier in filtered_lines
    ]

    for _iteration in range(max_iterations):
        pair_counter: Counter[tuple[tuple[int, ...], tuple[int, ...]]] = Counter()
        pair_positions: dict[tuple[tuple[int, ...], tuple[int, ...]], list[int]] = defaultdict(list)

        for i in range(len(nodes) - 1):
            a, b = nodes[i], nodes[i + 1]
            if a["pdf_page"] != b["pdf_page"]:
                continue
            gap = b["y0"] - a["y1"]
            gate = max(a["height"], b["height"]) * gap_ratio
            if gap > gate:
                continue
            pair = (a["tier_seq"], b["tier_seq"])
            pair_counter[pair] += 1
            pair_positions[pair].append(i)

        if not pair_counter:
            break
        best_pair, best_count = pair_counter.most_common(1)[0]
        if best_count < min_pair_count:
            break

        merge_at = set(pair_positions[best_pair])
        new_nodes: list[dict[str, Any]] = []
        skip_next = False
        i = 0
        while i < len(nodes):
            if skip_next:
                skip_next = False
                i += 1
                continue
            if i in merge_at and i + 1 < len(nodes):
                a, b = nodes[i], nodes[i + 1]
                new_nodes.append(
                    {
                        "pdf_page": a["pdf_page"],
                        "text": f"{a['text']} {b['text']}".strip(),
                        "font_size": float(median([a["font_size"], b["font_size"]])),
                        "y0": a["y0"],
                        "y1": b["y1"],
                        "height": b["y1"] - a["y0"],
                        "tier_seq": a["tier_seq"] + b["tier_seq"],
                        "merged_line_count": a["merged_line_count"] + b["merged_line_count"],
                    }
                )
                skip_next = True
            else:
                new_nodes.append(nodes[i])
            i += 1
        nodes = new_nodes

    return nodes


@dataclass
class HeadingCandidate:
    idx: int
    pdf_page: int
    text: str
    font_size: float
    tier_value: float
    tier: int
    level: int = 0
    parent_idx: int | None = None


def assign_levels_by_stack(candidates: list[HeadingCandidate]) -> None:
    stack: list[dict[str, Any]] = []
    for candidate in candidates:
        size = candidate.tier_value
        while stack and stack[-1]["value"] < size:
            stack.pop()
        if stack and stack[-1]["value"] == size:
            candidate.level = len(stack)
            candidate.parent_idx = stack[-2]["idx"] if len(stack) >= 2 else None
            stack[-1] = {"value": size, "idx": candidate.idx}
        else:
            candidate.parent_idx = stack[-1]["idx"] if stack else None
            stack.append({"value": size, "idx": candidate.idx})
            candidate.level = len(stack)


def build_candidate_tree(
    pdf_path: Path, max_title_words: int = 20
) -> tuple[list[HeadingCandidate], dict[int, int], int, list[dict[str, Any]]]:
    lines, page_word_counts, page_count = extract_book_lines_and_page_word_counts(pdf_path)

    font_sizes = [line["font_size"] for line in lines]
    tiers = compute_tiers(font_sizes, MIN_TIER_COUNT)
    print(
        f"font_size tiers: raw={tiers['raw_tier_count']} -> final={tiers['final_tier_count']} "
        f"peaks={[round(p, 2) for p in tiers['final_peaks']]}"
    )

    tier_of_line = [assign_tier(line["font_size"], tiers["final_cuts"]) for line in lines]
    body_tiers = exclude_body_tiers(tier_of_line, tiers["final_tier_count"], BODY_MODE)
    filtered_lines = [(line, tier) for line, tier in zip(lines, tier_of_line) if tier not in body_tiers]

    bpe_nodes = bpe_merge_page_local(filtered_lines, gap_ratio=MERGE_GAP_RATIO, min_pair_count=MIN_PAIR_COUNT)

    # [075 신규, 사용자 규칙] title 텍스트가 max_title_words(기본 20단어)를 넘는
    # 개별 후보만 걷어낸다 - 그 후보가 속한 level 전체를 버리지 않는다. 반드시
    # stack 알고리즘(assign_levels_by_stack)을 돌리기 **전에** 걷어내야 한다.
    # stack은 순차적으로 push/pop을 누적하는 greedy 알고리즘이라, 노이즈 후보 하나가
    # 중간에 끼어 엉뚱한 tier_value로 pop/push를 일으키면 그 뒤로 이어지는 모든
    # level/parent_idx가 연쇄로 틀어진다. 먼저 걸러내면 stack이 애초에 노이즈를
    # 보지 않으므로 이 문제가 구조적으로 발생하지 않는다.
    kept_nodes: list[dict[str, Any]] = []
    removed_nodes: list[dict[str, Any]] = []
    for node in bpe_nodes:
        word_count = len(_WORD_SPLIT.findall(node["text"]))
        if word_count > max_title_words:
            removed_nodes.append(
                {"pdf_page": node["pdf_page"], "title": node["text"][:120], "title_word_count": word_count}
            )
        else:
            kept_nodes.append(node)

    candidates = [
        HeadingCandidate(
            idx=idx,
            pdf_page=node["pdf_page"],
            text=node["text"],
            font_size=node["font_size"],
            tier_value=tiers["final_peaks"][min(node["tier_seq"]) - 1],
            tier=min(node["tier_seq"]),
        )
        for idx, node in enumerate(kept_nodes)
    ]
    assign_levels_by_stack(candidates)
    return candidates, page_word_counts, page_count, removed_nodes


# ---------------------------------------------------------------------------
# [075 신규] cutoff depth D별 본문 길이 통계 + 목표 기반 depth 선택
# ---------------------------------------------------------------------------


def compute_level_length_stats(
    candidates: list[HeadingCandidate], page_word_counts: dict[int, int], page_count: int
) -> dict[int, dict[str, Any]]:
    """cutoff depth D를 늘려가며(1..max_level), "level <= D인 모든 heading을 파일
    경계로 쓴다"고 가정했을 때 파일 하나의 단어 수 분포를 구한다.

    [075 버그 수정] 처음 구현은 "정확히 level == D인 candidate끼리의 간격"만 쟀다.
    이러면 L4 자식이 없는 terminal L3 node(예: "Section B") 다음에 다른 L3/L1/L2
    heading이 나와도 무시하고, 그보다 훨씬 뒤에 나오는 다음 L4 candidate까지의
    거리를 그 앞의 L4 후보 구간으로 잘못 계산했다 - L3 관할 구간을 앞선 L4에
    통째로 얹어버리는 것과 같다. 그 결과 depth를 늘렸는데(L3 -> L4) 오히려
    mean/median이 커지는, 구조적으로 불가능한 결과가 나왔다(더 세분화하면 파일은
    같거나 작아져야지 커질 수 없다).

    올바른 정의는 "depth D까지 자른다"는 건 level 1..D에 속하는 **모든** heading이
    파일 경계가 된다는 뜻이다(D 자신의 level만이 아니라 그보다 얕은 level도 전부
    경계). 이렇게 하면 D가 커질수록 경계 집합이 항상 상위집합(superset)이 되므로,
    구간은 더 잘게 쪼개지기만 하고 절대 합쳐지지 않는다 - max/mean/median이 D
    증가에 따라 항상 감소하거나 같아야 한다는 불변식이 자동으로 성립한다.
    """

    # [075 추가] "자식이 있는 컨테이너 노드는 자기 텍스트가 거의 0단어인 게 정상"
    # (예: "Chapter 1" 바로 다음 줄이 "1.1 ..."이면 "Chapter 1 자신의 몫"은 원래
    # 없다시피 하다) - min_words 조건은 그 depth에서 더 이상 안 쪼개지는 leaf
    # 노드에만 적용해야 의미가 있다(사용자 확인). max_words는 컨테이너 포함 모든
    # 노드에 그대로 적용한다(컨테이너의 자기 preamble이 과도하게 길어지는 것도
    # 막아야 하므로).
    children_of: dict[int, list[HeadingCandidate]] = defaultdict(list)
    for c in candidates:
        if c.parent_idx is not None:
            children_of[c.parent_idx].append(c)

    max_level = max((c.level for c in candidates), default=0)
    stats: dict[int, dict[str, Any]] = {}

    for depth in range(1, max_level + 1):
        # depth 이하 모든 level을 경계로 쓴다(candidates는 이미 page-order로 정렬돼 있다).
        boundaries = [c for c in candidates if c.level <= depth]
        if not boundaries:
            continue

        segment_lengths: list[int] = []
        leaf_segment_lengths: list[int] = []
        segment_details: list[dict[str, Any]] = []
        for i, node in enumerate(boundaries):
            start_page = node.pdf_page
            end_page_exclusive = (
                boundaries[i + 1].pdf_page if i + 1 < len(boundaries) else page_count + 1
            )
            length = sum(
                page_word_counts.get(p, 0) for p in range(start_page, max(start_page, end_page_exclusive))
            )
            segment_lengths.append(length)
            is_leaf_at_depth = not any(child.level <= depth for child in children_of.get(node.idx, []))
            if is_leaf_at_depth:
                leaf_segment_lengths.append(length)
            segment_details.append(
                {
                    "title": node.text[:80],
                    "level": node.level,
                    "start_page": start_page,
                    "end_page_exclusive": end_page_exclusive,
                    "word_count": length,
                    "is_leaf_at_depth": is_leaf_at_depth,
                }
            )

        segment_lengths_sorted = sorted(segment_lengths, reverse=True)
        stats[depth] = {
            "node_count": len(boundaries),
            "leaf_node_count": len(leaf_segment_lengths),
            "max_words": max(segment_lengths),
            "p95_words": int(np.percentile(segment_lengths, 95)),
            "p90_words": int(np.percentile(segment_lengths, 90)),
            "median_words": int(median(segment_lengths)),
            "mean_words": round(sum(segment_lengths) / len(segment_lengths), 1),
            "leaf_median_words": int(median(leaf_segment_lengths)) if leaf_segment_lengths else None,
            "leaf_mean_words": round(sum(leaf_segment_lengths) / len(leaf_segment_lengths), 1)
            if leaf_segment_lengths
            else None,
            "top5_longest": segment_lengths_sorted[:5],
            "longest_segment_sample": max(segment_details, key=lambda d: d["word_count"]),
            "segment_word_counts": segment_lengths,  # max_words 조건용(전체 노드)
            "leaf_segment_word_counts": leaf_segment_lengths,  # min_words 조건용(leaf 노드만)
        }
    return stats


# ---------------------------------------------------------------------------
# [075 신규] level별 title 오염(pollution) 검사
# ---------------------------------------------------------------------------


def check_level_pollution(
    candidates: list[HeadingCandidate], max_title_words: int = 10
) -> dict[int, dict[str, Any]]:
    """레벨별 heading 후보의 title 텍스트 자체 길이로 "이 레벨이 본문 오염됐는지"를 본다.

    [075 신규, 사용자 규칙] 진짜 heading(챕터/섹션 제목)은 보통 10단어 이하의 짧은
    문구다. "No risk, no reward. Most people intuitively understand..."처럼 본문
    문단 전체가 heading 후보로 잘못 잡히면 title 텍스트 자체가 수십~수백 단어로
    길어진다. 어떤 level에 이런 후보가 하나라도 있으면 그 level 전체를 "오염됨
    (polluted)"으로 보고, 본문 길이 기반 depth 선택 대상에서 통째로 제외한다 -
    본문 길이(segment 통계)가 아니라 title 텍스트 길이 자체로 판단하는 별도 필터다.
    """

    by_level: dict[int, list[HeadingCandidate]] = defaultdict(list)
    for c in candidates:
        by_level[c.level].append(c)

    result: dict[int, dict[str, Any]] = {}
    for level, nodes in sorted(by_level.items()):
        word_counts = [len(_WORD_SPLIT.findall(n.text)) for n in nodes]
        polluted_items = [
            {"title": n.text[:100], "title_word_count": wc, "pdf_page": n.pdf_page}
            for n, wc in zip(nodes, word_counts)
            if wc > max_title_words
        ]
        result[level] = {
            "node_count": len(nodes),
            "max_title_word_count": max(word_counts),
            "polluted_item_count": len(polluted_items),
            "is_polluted": len(polluted_items) > 0,
            "polluted_samples": sorted(polluted_items, key=lambda d: -d["title_word_count"])[:5],
        }
    return result


def select_level_for_target(
    level_stats: dict[int, dict[str, Any]], target_words: int, stat_key: str = "max_words"
) -> dict[str, Any]:
    """stat_key(기본 max_words)가 target_words 이상으로 유지되는 가장 깊은 level을 고른다.

    [075 신규] 사용자 규칙: "사용자가 지정한 것의 upper를 쓴다" - level을 점점
    깊게(숫자를 키워) 볼 때 통계값이 target 밑으로 처음 떨어지기 직전, 즉 여전히
    target 이상인 마지막 level을 선택한다. 모든 level이 이미 target 밑이면 level
    1을 쓴다. 가장 깊은 level도 target 이상이면 가장 깊은 level을 쓴다.

    stat_key로 "max_words" 대신 "p95_words" 등을 넘기면, book 구조상 후보가 아예
    안 나오는 넓은 대역 하나 때문에 순수 max가 왜곡되는 문제를 피해 더 안정적인
    선택을 볼 수 있다(대신 "어떤 파일도 target을 절대 넘지 않는다"는 엄격한 보장은
    포기하는 것이다).
    """

    levels_sorted = sorted(level_stats)
    chosen = levels_sorted[0] if levels_sorted else None
    for level in levels_sorted:
        if level_stats[level][stat_key] >= target_words:
            chosen = level
        else:
            break
    return {
        "target_words": target_words,
        "stat_key": stat_key,
        "chosen_level": chosen,
        "chosen_level_stat_value": level_stats[chosen][stat_key] if chosen is not None else None,
    }


def select_level_by_conditions(
    level_stats: dict[int, dict[str, Any]],
    cum_percentile: float = 0.9,
    min_words: int | None = 1000,
    max_words: int | None = None,
) -> dict[str, Any]:
    """cumulative percentile 기반 두 조건(min_words/max_words)으로 cutoff depth를 고른다.

    [075 신규, 사용자 규칙]
    - min_words 조건: "md 파일의 cum_percentile 비율 이상이 min_words 이상이어야
      한다." depth가 깊어질수록 파일이 잘게 쪼개져 이 비율은 단조 비증가한다. 이
      조건만 있으면 비율 >= cum_percentile을 만족하는 **가장 깊은(최대) depth**를
      고른다("to have maximum levels" - 더 깊이 쪼개고 싶은데, 너무 잘게 쪼개서
      작은 파일이 cum_percentile 넘게 생기는 지점 직전까지 허용).
    - max_words 조건: "md 파일의 cum_percentile 비율 이상이 max_words 이하여야
      한다." depth가 깊어질수록 이 비율은 단조 비감소한다. 이 조건만 있으면 비율
      >= cum_percentile을 만족하는 **가장 얕은(최소) depth**를 고른다("to have
      minimum levels" - 필요한 만큼만 쪼개고, 그 이상은 낭비이므로 조건을 만족하는
      순간 멈춘다).
    - 둘 다 주어지면 두 조건을 모두 만족하는 depth 집합(교집합)을 구한다. 교집합이
      비어 있으면 "만족하는 level이 없다"로 명시적으로 fail한다(임의로 아무 depth나
      골라 반환하지 않는다).
    - 기본값은 cum_percentile=0.9, min_words=1000, max_words=None이다.
    """

    if min_words is None and max_words is None:
        raise ValueError("min_words와 max_words 중 최소 하나는 지정해야 한다")

    per_depth: dict[int, dict[str, Any]] = {}
    for depth, stat in sorted(level_stats.items()):
        all_counts = stat["segment_word_counts"]
        leaf_counts = stat["leaf_segment_word_counts"]
        entry: dict[str, Any] = {"node_count": len(all_counts), "leaf_node_count": len(leaf_counts)}
        if min_words is not None:
            # [075 추가, 사용자 확인] min_words는 leaf 노드(그 depth에서 더 이상
            # 안 쪼개지는 노드)에만 적용한다. 자식이 있는 컨테이너 노드는 자기
            # 텍스트가 짧은 게 정상이라 검사 대상에서 뺀다.
            if leaf_counts:
                frac = sum(1 for w in leaf_counts if w >= min_words) / len(leaf_counts)
            else:
                frac = 1.0  # leaf가 하나도 없으면(전부 컨테이너) 위반할 대상도 없음
            entry["min_words_fraction_ok"] = round(frac, 4)
            entry["min_words_passed"] = frac >= cum_percentile
        if max_words is not None:
            # max_words는 컨테이너 포함 모든 노드에 그대로 적용한다.
            frac = sum(1 for w in all_counts if w <= max_words) / len(all_counts)
            entry["max_words_fraction_ok"] = round(frac, 4)
            entry["max_words_passed"] = frac >= cum_percentile
        per_depth[depth] = entry

    if min_words is not None and max_words is None:
        passing = [d for d, e in per_depth.items() if e["min_words_passed"]]
        chosen = max(passing) if passing else None
        mode = "min_words_only(maximize_levels)"
    elif max_words is not None and min_words is None:
        passing = [d for d, e in per_depth.items() if e["max_words_passed"]]
        chosen = min(passing) if passing else None
        mode = "max_words_only(minimize_levels)"
    else:
        passing = [
            d for d, e in per_depth.items() if e["min_words_passed"] and e["max_words_passed"]
        ]
        chosen = None  # 둘 다 있으면 단일 depth가 아니라 만족하는 depth 집합을 그대로 보고한다
        mode = "both_conditions(intersection)"

    return {
        "cum_percentile": cum_percentile,
        "min_words": min_words,
        "max_words": max_words,
        "mode": mode,
        "per_depth": per_depth,
        "passing_depths": sorted(passing),
        "chosen_depth": chosen,
        "failed": len(passing) == 0,
    }


def record_experiment(
    level_stats: dict[int, dict[str, Any]],
    condition_results: dict[str, dict[str, Any]],
    pollution: dict[int, dict[str, Any]],
    candidate_count: int,
) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    finding_parts = [
        f"L{level}: node_count={s['node_count']} max_words={s['max_words']} median_words={s['median_words']} mean_words={s['mean_words']}"
        for level, s in sorted(level_stats.items())
    ]
    selection_parts = []
    for name, result in condition_results.items():
        if result["failed"]:
            outcome = "FAIL(no level satisfies both conditions)"
        elif result["chosen_depth"] is not None:
            outcome = f"chosen_depth=L{result['chosen_depth']}"
        else:
            outcome = f"passing_depths={result['passing_depths']}"
        selection_parts.append(
            f"{name}(p={result['cum_percentile']},min={result['min_words']},max={result['max_words']}): {outcome}"
        )
    pollution_parts = [
        f"L{level}: max_title_word_count={p['max_title_word_count']} "
        f"polluted_item_count={p['polluted_item_count']} is_polluted={p['is_polluted']}"
        for level, p in sorted(pollution.items())
    ]
    finding = (
        " | ".join(finding_parts)
        + " || "
        + " | ".join(selection_parts)
        + " || pollution(title>10words): "
        + " | ".join(pollution_parts)
    )

    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "074(bpe_min15, mode_and_smaller)로 만든 Zvi Bodie candidate tree에서, "
            "cutoff depth D(level 1..D 전체를 파일 경계로 삼음, level==D만 보는 게 "
            "아니라 - terminal node 처리 버그 수정)별로 본문 단어 수 분포를 구하고, "
            "cumulative percentile 기반 min_words/max_words 조건(둘 중 하나 또는 "
            "둘 다)으로 depth를 선택하는 규칙을 검증한다. min_words 조건은 "
            "'파일의 cum_percentile 이상이 min_words 이상'을 만족하는 가장 깊은 "
            "depth(최대 세분화)를, max_words 조건은 '파일의 cum_percentile 이상이 "
            "max_words 이하'를 만족하는 가장 얕은 depth(최소 세분화)를 고른다. 둘 "
            "다 주면 교집합을 구하고 비어 있으면 명시적으로 fail한다."
        ),
        "inputs": [str(BOOK_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": ["074_bpe_style_page_local_tier_merge"],
        "body_mode": BODY_MODE,
        "min_pair_count": MIN_PAIR_COUNT,
        "candidate_count": candidate_count,
        "level_length_stats": {
            str(k): {
                key: value
                for key, value in v.items()
                if key not in {"segment_word_counts", "leaf_segment_word_counts"}
            }
            for k, v in level_stats.items()
        },
        "condition_results": {
            name: {
                "cum_percentile": result["cum_percentile"],
                "min_words": result["min_words"],
                "max_words": result["max_words"],
                "mode": result["mode"],
                "per_depth": result["per_depth"],
                "passing_depths": result["passing_depths"],
                "chosen_depth": result["chosen_depth"],
                "failed": result["failed"],
            }
            for name, result in condition_results.items()
        },
        "pollution": {str(level): p for level, p in pollution.items()},
        "finding": finding,
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


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not BOOK_PDF.exists():
        print(f"PDF 없음: {BOOK_PDF}")
        return

    print(f"... zvi_bodie_investments 전체 page 훑는 중: {BOOK_PDF.name}")
    candidates, page_word_counts, page_count, removed_nodes = build_candidate_tree(
        BOOK_PDF, max_title_words=20
    )
    print(
        f"    candidate_count={len(candidates)} page_count={page_count} "
        f"removed_polluted_count={len(removed_nodes)}"
    )
    print("    제거된 오염 후보(title>20단어, stack 알고리즘 실행 전에 제거):")
    for r in sorted(removed_nodes, key=lambda d: -d["title_word_count"])[:15]:
        print(f"      p.{r['pdf_page']} ({r['title_word_count']}단어) {r['title']!r}")

    (OUTPUT_DIR / "candidate_tree.json").write_text(
        json.dumps(
            [
                {"idx": c.idx, "pdf_page": c.pdf_page, "level": c.level, "title": c.text, "tier": c.tier}
                for c in candidates
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # candidates는 이미 title>20단어 후보를 제거하고 만든 tree이므로, 여기서는
    # 검증 차원에서 재확인한다(전부 is_polluted=False로 나와야 정상).
    pollution = check_level_pollution(candidates, max_title_words=20)
    print("\n=== level별 title 오염(pollution) 재검증 (개별 후보 제거 후, 전부 False여야 정상) ===")
    for level, p in sorted(pollution.items()):
        print(
            f"L{level}: node_count={p['node_count']:>4} max_title_word_count={p['max_title_word_count']:>4} "
            f"polluted_item_count={p['polluted_item_count']:>4} is_polluted={p['is_polluted']}"
        )
        for sample in p["polluted_samples"]:
            print(f"     오염 샘플: p.{sample['pdf_page']} ({sample['title_word_count']}단어) {sample['title']!r}")

    level_stats = compute_level_length_stats(candidates, page_word_counts, page_count)
    print("\n=== level별 본문 길이 통계 (같은 level 다음 heading까지) ===")
    for level, s in sorted(level_stats.items()):
        print(
            f"L{level}: node_count={s['node_count']:>4} max_words={s['max_words']:>7} "
            f"median_words={s['median_words']:>6} mean_words={s['mean_words']:>8} "
            f"top5={s['top5_longest']}"
        )
        print(f"     최장 구간 샘플: {s['longest_segment_sample']}")

    # [075 신규] 사용자 규칙: cumulative percentile 기반 min_words/max_words 조건.
    # 기본값(cum_percentile=0.9, min_words=1000, max_words=None)이 이번 실험의
    # 핵심 질문에 대한 답이다. 추가로 max_words 단독 조건, 두 조건을 동시에 준
    # 경우(교집합/실패 케이스 포함)도 같이 보여준다.
    condition_results = {
        "default_min_words_1000_p90": select_level_by_conditions(
            level_stats, cum_percentile=0.9, min_words=1000, max_words=None
        ),
        "max_words_1000_p90": select_level_by_conditions(
            level_stats, cum_percentile=0.9, min_words=None, max_words=1000
        ),
        "max_words_10000_p90": select_level_by_conditions(
            level_stats, cum_percentile=0.9, min_words=None, max_words=10000
        ),
        "both_min1000_max10000_p90": select_level_by_conditions(
            level_stats, cum_percentile=0.9, min_words=1000, max_words=10000
        ),
        "both_min1000_max2000_p90": select_level_by_conditions(
            level_stats, cum_percentile=0.9, min_words=1000, max_words=2000
        ),
    }
    for name, result in condition_results.items():
        print(f"\n=== condition: {name} ===")
        print(
            f"cum_percentile={result['cum_percentile']} min_words={result['min_words']} "
            f"max_words={result['max_words']} mode={result['mode']}"
        )
        for depth, e in sorted(result["per_depth"].items()):
            print(f"  L{depth}: {e}")
        if result["failed"]:
            print("  -> FAIL: 두 조건을 동시에 만족하는 level이 없음")
        elif result["chosen_depth"] is not None:
            print(f"  -> chosen_depth=L{result['chosen_depth']}")
        else:
            print(f"  -> passing_depths={result['passing_depths']} (두 조건 교집합, 단일 depth로 좁히지 않음)")

    (OUTPUT_DIR / "level_length_stats.json").write_text(
        json.dumps(
            {
                "level_length_stats": {str(k): v for k, v in level_stats.items()},
                "condition_results": condition_results,
                "pollution": {str(k): v for k, v in pollution.items()},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    record_experiment(level_stats, condition_results, pollution, len(candidates))
    print(f"\nsummary: {OUTPUT_DIR / 'level_length_stats.json'}")


if __name__ == "__main__":
    main()
