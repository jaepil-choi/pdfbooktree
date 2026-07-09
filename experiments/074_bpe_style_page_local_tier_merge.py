"""experiment 074: BPE 스타일 page-local tier sequence 병합.

배경 (사용자 가설):
    073의 병합 규칙은 "같은 page + 같은 tier + 인접"이었다. 그래서 챕터 오프너처럼
    서로 다른 tier로 쪼개진 heading("CHAPTER"[T10, 배너] / "1"[T1, 거대한 챕터 번호]
    / "The Investment Environment"[T2, 타이틀])은 절대 하나로 합쳐지지 않았다. 게다가
    순수 숫자로만 이뤄진 line("1")은 기존 content span 필터(_LATIN2: 라틴 2글자 이상,
    _HANGUL)에 아예 걸리지 않아 후보 자체에서 탈락했다.

    사용자 지적 두 가지:
      1. 페이지 여백의 인쇄 페이지 번호/각주 번호/표·그림 번호 같은 순수 숫자는 대부분
         작은 tier라서 어차피 body tier 제외 단계(mode_only/mode_and_smaller)에서
         사라진다. "숫자라서 제외"는 너무 noisy한 규칙이다 -> content span 필터에서
         숫자 허용 여부로 거르지 않는다.
      2. tier가 다른 줄이라도, 같은 page 안에서 반복적으로 함께 나타나는 tier
         시퀀스(예: T10 -> T1 -> T2가 책 전체 챕터 시작마다 반복)는 BPE가 코퍼스에서
         가장 빈번한 인접 byte pair를 찾아 반복적으로 새 심볼로 병합해 vocabulary를
         만드는 것과 같은 방식으로 다뤄야 한다. "토큰" = heading-tier line, "심볼" =
         해당 line의 font tier, "코퍼스" = 책의 각 page 안에서 남은 candidate line을
         읽는 순서대로 나열한 시퀀스(병합은 같은 page 안에서만 일어나므로 page 경계를
         넘는 병합은 애초에 발생하지 않는다).

    이 실험은 (1) content span 필터에서 숫자 배제를 없애고, (2) same-tier-only 병합
    대신 book-wide tier pair 빈도 기반 반복 병합(BPE)을 073의 same-tier 병합과
    A/B 비교한다. 072/073과 동일한 stack 기반 level 부여 + parent_accuracy 평가
    파이프라인을 그대로 재사용한다(파일 복사, import 아님 - AGENTS.md 3절 monolithic
    원칙).

    no_merge / same_tier_gap1.5(073과 동일, baseline) / bpe_min3 / bpe_min5 네
    변형을 mode_only/mode_and_smaller 두 body_mode에 적용해 Zvi Bodie Investments
    (parent_accuracy가 가장 낮았던 책)에서 평가하고, John Hull / Shreve Binomial에도
    재튜닝 없이 그대로 적용해 회귀가 없는지 확인한다.

실행:
    uv run python experiments/074_bpe_style_page_local_tier_merge.py
출력:
    experiments/outputs/074_bpe_style_page_local_tier_merge/<book_id>/<body_mode>/<merge_variant>/
        - inferred_bookmark_tree.txt/json
        - nested_bookmark_tree.json
        - stack_trace.txt
        - eval_vs_truth.json
        - bpe_merge_log.json (bpe 변형만: 어떤 pair가 몇 번 병합됐는지 기록)
    experiments/outputs/074_bpe_style_page_local_tier_merge/summary.json
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
from rapidfuzz import fuzz
from scipy.signal import argrelextrema
from scipy.stats import gaussian_kde

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "074_bpe_style_page_local_tier_merge"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

MIN_TIER_COUNT = 5
BODY_EXCLUSION_MODES = ["mode_only", "mode_and_smaller"]
MERGE_GAP_RATIO = 1.5  # 073에서 검증한 값을 그대로 재사용
MERGE_VARIANTS: list[dict[str, Any]] = [
    {"name": "no_merge", "kind": "no_merge"},
    {"name": "same_tier_gap1.5", "kind": "same_tier", "gap_ratio": MERGE_GAP_RATIO},
    {"name": "bpe_min3", "kind": "bpe", "gap_ratio": MERGE_GAP_RATIO, "min_pair_count": 3},
    {"name": "bpe_min5", "kind": "bpe", "gap_ratio": MERGE_GAP_RATIO, "min_pair_count": 5},
    # [074 추가 스윕] min3/min5에서 level_accuracy가 무너진 원인(섹션+하위항목처럼
    # 책 전체에 수백 번 반복되는 다른 2-tier 패턴까지 과병합)을 확인하기 위해 훨씬
    # 높은 threshold도 시도한다 - 챕터 오프너(~20회)와 일반 섹션 반복(~100-200회)을
    # 구분할 수 있는 지점이 있는지 본다.
    {"name": "bpe_min15", "kind": "bpe", "gap_ratio": MERGE_GAP_RATIO, "min_pair_count": 15},
    {"name": "bpe_min30", "kind": "bpe", "gap_ratio": MERGE_GAP_RATIO, "min_pair_count": 30},
    {"name": "bpe_min60", "kind": "bpe", "gap_ratio": MERGE_GAP_RATIO, "min_pair_count": 60},
]
TITLE_MATCH_THRESHOLD = 70
MAX_STACK_TRACE_LINES = 4000
MAX_BPE_ITERATIONS = 50

BOOKS = [
    {
        "id": "john_hull",
        "pdf": ROOT_DIR
        / "data"
        / "native-pdf-indexed"
        / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf",
    },
    {
        "id": "shreve_binomial",
        "pdf": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf",
    },
    {
        "id": "zvi_bodie_investments",
        "pdf": ROOT_DIR
        / "data"
        / "native-pdf-indexed"
        / "Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf",
    },
]

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_DIGIT = re.compile(r"\d")  # [074 신규] 순수 숫자도 content span으로 인정
_NORM_STRIP = re.compile(r"[^a-z0-9가-힣 ]")
_MULTI_SPACE = re.compile(r"\s+")


def normalize_for_match(text: str) -> str:
    text = text.lower()
    text = _NORM_STRIP.sub(" ", text)
    return _MULTI_SPACE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# 1단계: line 추출 ([074 신규] 숫자만 있는 span도 content로 인정)
# ---------------------------------------------------------------------------


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    # [074 신규] 072/073은 라틴 2글자 이상 또는 한글만 content로 인정해 순수 숫자
    # ("1" 같은 거대한 챕터 번호)를 통째로 버렸다. 페이지 여백 번호/각주 번호처럼
    # 노이즈가 되는 숫자는 대부분 작은 font tier라 body tier 제외 단계에서 자연히
    # 사라지므로, 숫자라는 이유만으로 여기서 미리 배제하지 않는다.
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


def extract_book_lines(pdf_path: Path) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            spans = extract_page_content_spans(page)
            for merged_line in merge_spans_into_lines(spans):
                lines.append({"pdf_page": page_index + 1, **merged_line})
    return lines


# ---------------------------------------------------------------------------
# 2단계: tier 계산 (072/073과 동일)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 3단계: 본문 tier 제외 (072/073과 동일)
# ---------------------------------------------------------------------------


def exclude_body_tiers(tier_of_line: list[int], tier_count: int, mode: str) -> set[int]:
    counts = Counter(tier_of_line)
    if mode == "mode_only":
        mode_tier = max(counts, key=counts.get)
        return {mode_tier}
    if mode == "mode_and_smaller":
        mode_tier = max(counts, key=counts.get)
        return set(range(mode_tier, tier_count + 1))
    raise ValueError(f"unknown body exclusion mode: {mode}")


# ---------------------------------------------------------------------------
# 3.5단계 (a): 인접 동일 tier line 병합 (073과 동일, 비교 baseline용으로 재사용)
# ---------------------------------------------------------------------------


def merge_adjacent_same_tier_lines(
    filtered_lines: list[tuple[dict[str, Any], int]],
    gap_ratio: float,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_tier: int | None = None

    for line, tier in filtered_lines:
        can_merge = (
            current is not None
            and current_tier == tier
            and current["pdf_page"] == line["pdf_page"]
        )
        if can_merge:
            gap = line["y0"] - (current["y0"] + current["height"])
            gate = max(current["height"], line["height"]) * gap_ratio
            can_merge = gap <= gate

        if can_merge:
            current["text"] = f"{current['text']} {line['text']}".strip()
            current["y1"] = line["y0"] + line["height"]
            current["height"] = current["y1"] - current["y0"]
            current["font_size"] = float(np.median([current["font_size"], line["font_size"]]))
            current["merged_line_count"] += 1
            continue

        if current is not None:
            merged.append(current)
        current = {
            "pdf_page": line["pdf_page"],
            "text": line["text"],
            "font_size": line["font_size"],
            "y0": line["y0"],
            "y1": line["y0"] + line["height"],
            "height": line["height"],
            "merged_line_count": 1,
            "tier": tier,
        }
        current_tier = tier

    if current is not None:
        merged.append(current)
    return merged


# ---------------------------------------------------------------------------
# 3.5단계 (b): BPE 스타일 page-local tier sequence 병합 ([074 신규])
# ---------------------------------------------------------------------------


def bpe_merge_page_local(
    filtered_lines: list[tuple[dict[str, Any], int]],
    gap_ratio: float,
    min_pair_count: int,
    max_iterations: int = MAX_BPE_ITERATIONS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """본문 tier가 제외된 heading-candidate line들을, tier를 "심볼"로 하는 BPE
    tokenizer 학습과 같은 방식으로 반복 병합한다.

    [074 신규] 073의 same-tier 병합은 "같은 tier"인 인접 line만 합쳤다. 하지만
    실제 챕터 오프너는 배너(작은 tier) + 거대한 챕터 번호(가장 큰 tier) + 타이틀
    (중간 tier)처럼 서로 다른 tier 3개가 한 덩어리로 렌더링된다. 이 함수는 "같은
    page 안에서 반복적으로 함께 나타나는 tier 시퀀스"를 book 전체 통계로 찾아
    병합한다 - BPE가 코퍼스 전체에서 가장 빈번한 인접 byte pair를 찾아 새 심볼로
    병합하고 이를 반복하는 것과 동일한 절차다.

    - "토큰" = heading-tier line 하나, "심볼" = 그 line(또는 이미 병합된 compound
      line)이 대표하는 tier 번호의 튜플(tier_seq).
    - "코퍼스"는 책의 각 page 안에서 남은 candidate line을 읽는 순서(book 원래
      순서 = page 다음 y좌표순)대로 나열한 시퀀스다. pair 후보는 반드시 같은 page +
      수직 gap이 `max(두 line height) * gap_ratio` 이내인 인접 line 사이에서만
      만들어지므로, 병합이 page 경계를 넘는 일은 애초에 발생하지 않는다.
    - 매 iteration마다 book 전체에서 가장 빈번한 (좌측 tier_seq, 우측 tier_seq)
      pair를 찾는다. 그 빈도가 `min_pair_count` 미만이면 중단한다(우연히 한두 번
      붙어있는 pair까지 병합하는 것을 막는 gate - `merge_tiers_by_min_count`의
      min_count와 같은 역할).
    - 선택된 pair의 모든 등장 위치를 한 번의 pass에서 왼쪽부터 겹치지 않게 병합한다
      (표준 BPE trainer와 동일한 방식). 병합 후 다시 pair 빈도를 계산해 반복한다.
    - 병합된 node의 대표 tier는 `min(tier_seq)`로 잡는다(tier 번호가 작을수록
      큰 font이므로, 압축된 chapter-opener 블록 안에서 가장 큰 폰트가 그 블록
      전체의 계층 수준을 대표해야 stack 알고리즘이 올바르게 pop/push한다).

    반환값: (병합된 node 목록, 실제 적용된 merge 기록 - 진단/리포팅용)
    """

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

    merge_log: list[dict[str, Any]] = []

    for iteration in range(max_iterations):
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
        merge_log.append(
            {
                "iteration": iteration,
                "pair": [list(best_pair[0]), list(best_pair[1])],
                "applied_count": len(merge_at),
                "book_wide_pair_frequency": best_count,
            }
        )

    return nodes, merge_log


# ---------------------------------------------------------------------------
# 4단계: stack 기반 level 부여 + parent-child edge 기록 (072/073과 동일)
# ---------------------------------------------------------------------------


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
    stack_action: str = ""


def assign_levels_by_stack(candidates: list[HeadingCandidate]) -> list[str]:
    stack: list[dict[str, Any]] = []
    trace: list[str] = []
    for candidate in candidates:
        size = candidate.tier_value
        while stack and stack[-1]["value"] < size:
            popped = stack.pop()
            trace.append(f"  pop {popped['value']} (< {size})")
        if stack and stack[-1]["value"] == size:
            candidate.level = len(stack)
            candidate.parent_idx = stack[-2]["idx"] if len(stack) >= 2 else None
            candidate.stack_action = "sibling"
            stack[-1] = {"value": size, "idx": candidate.idx}
        else:
            candidate.parent_idx = stack[-1]["idx"] if stack else None
            stack.append({"value": size, "idx": candidate.idx})
            candidate.level = len(stack)
            candidate.stack_action = "push"
        trace.append(
            f"p{candidate.pdf_page:>4} size={size:>6} tier=T{candidate.tier} "
            f"action={candidate.stack_action:<7} level={candidate.level} "
            f"parent_idx={candidate.parent_idx} text={candidate.text[:60]!r}"
        )
    return trace


# ---------------------------------------------------------------------------
# 5단계: 구조 검증 (072/073과 동일)
# ---------------------------------------------------------------------------


def check_local_monotonicity(candidates: list[HeadingCandidate]) -> dict[str, Any]:
    level_of_idx = {c.idx: c.level for c in candidates}
    level_counts = Counter(c.level for c in candidates)
    max_level = max(level_counts) if level_counts else 0

    parents_with_children_by_level: dict[int, set[int]] = defaultdict(set)
    for c in candidates:
        if c.parent_idx is not None:
            parent_level = level_of_idx[c.parent_idx]
            parents_with_children_by_level[parent_level].add(c.parent_idx)

    violations = []
    parents_with_children_counts = {}
    for level in range(1, max_level):
        parent_count = len(parents_with_children_by_level.get(level, set()))
        next_count = level_counts.get(level + 1, 0)
        parents_with_children_counts[str(level)] = parent_count
        if parent_count > next_count:
            violations.append(
                {"level": level, "parents_with_children": parent_count, "next_level": level + 1, "next_count": next_count}
            )

    return {
        "level_counts": {str(i): level_counts.get(i, 0) for i in range(1, max_level + 1)},
        "parents_with_children_by_level": parents_with_children_counts,
        "max_level": max_level,
        "violations": violations,
        "is_locally_monotonic": len(violations) == 0,
    }


def check_level_jumps(candidates: list[HeadingCandidate]) -> int:
    jumps = 0
    for prev, cur in zip(candidates, candidates[1:]):
        if cur.level - prev.level > 1:
            jumps += 1
    return jumps


def build_nested_tree(candidates: list[HeadingCandidate]) -> list[dict[str, Any]]:
    nodes: dict[int, dict[str, Any]] = {
        c.idx: {"pdf_page": c.pdf_page, "level": c.level, "title": c.text, "children": []} for c in candidates
    }
    roots: list[dict[str, Any]] = []
    for c in candidates:
        node = nodes[c.idx]
        if c.parent_idx is None:
            roots.append(node)
        else:
            nodes[c.parent_idx]["children"].append(node)
    return roots


# ---------------------------------------------------------------------------
# 6단계: ground truth 비교 (072/073과 동일, parent_accuracy 포함)
# ---------------------------------------------------------------------------


def load_ground_truth(pdf_path: Path) -> list[dict[str, Any]]:
    with fitz.open(pdf_path) as document:
        toc = document.get_toc(simple=False)
    return [
        {"level": level, "title": title, "page": page_no}
        for level, title, page_no, _dest in toc
        if page_no > 0
    ]


def build_truth_parent_index(truth: list[dict[str, Any]]) -> list[int | None]:
    parent_of: list[int | None] = [None] * len(truth)
    last_by_level: dict[int, int] = {}
    for i, entry in enumerate(truth):
        lvl = entry["level"]
        parent_of[i] = last_by_level.get(lvl - 1)
        for deeper_level in [l for l in last_by_level if l >= lvl]:
            del last_by_level[deeper_level]
        last_by_level[lvl] = i
    return parent_of


def evaluate_against_ground_truth(
    candidates: list[HeadingCandidate], truth: list[dict[str, Any]]
) -> dict[str, Any]:
    by_page: dict[int, list[HeadingCandidate]] = {}
    for candidate in candidates:
        by_page.setdefault(candidate.pdf_page, []).append(candidate)
    candidates_by_idx = {c.idx: c for c in candidates}

    truth_parent_of = build_truth_parent_index(truth)
    matched_candidate_for_truth: dict[int, HeadingCandidate] = {}

    matched = 0
    level_correct = 0
    level_off_by = Counter()
    unmatched_truth: list[dict[str, Any]] = []
    match_rows: list[dict[str, Any]] = []

    for i, entry in enumerate(truth):
        page_candidates = by_page.get(entry["page"], [])
        truth_norm = normalize_for_match(entry["title"])
        best = None
        best_score = -1.0
        for candidate in page_candidates:
            score = fuzz.token_set_ratio(truth_norm, normalize_for_match(candidate.text))
            if score > best_score:
                best_score = score
                best = candidate
        if best is not None and best_score >= TITLE_MATCH_THRESHOLD:
            matched += 1
            matched_candidate_for_truth[i] = best
            diff = best.level - entry["level"]
            if diff == 0:
                level_correct += 1
            level_off_by[diff] += 1
            match_rows.append(
                {
                    "truth_page": entry["page"],
                    "truth_level": entry["level"],
                    "truth_title": entry["title"],
                    "matched_text": best.text,
                    "matched_level": best.level,
                    "match_score": round(best_score, 1),
                    "level_diff": diff,
                }
            )
        else:
            unmatched_truth.append(entry)

    candidate_idx_to_truth_idx = {c.idx: ti for ti, c in matched_candidate_for_truth.items()}

    def nearest_matched_truth_ancestor(truth_idx: int) -> HeadingCandidate | None:
        cur = truth_parent_of[truth_idx]
        while cur is not None:
            cand = matched_candidate_for_truth.get(cur)
            if cand is not None:
                return cand
            cur = truth_parent_of[cur]
        return None

    def nearest_matched_inferred_ancestor(candidate: HeadingCandidate) -> HeadingCandidate | None:
        cur = candidate.parent_idx
        while cur is not None:
            cand = candidates_by_idx[cur]
            if cand.idx in candidate_idx_to_truth_idx:
                return cand
            cur = cand.parent_idx
        return None

    parent_correct = 0
    parent_mismatch_sample: list[dict[str, Any]] = []
    for i, entry in enumerate(truth):
        cand = matched_candidate_for_truth.get(i)
        if cand is None:
            continue
        expected_parent = nearest_matched_truth_ancestor(i)
        actual_parent = nearest_matched_inferred_ancestor(cand)
        is_correct = (
            expected_parent is None and actual_parent is None
        ) or (
            expected_parent is not None
            and actual_parent is not None
            and expected_parent.idx == actual_parent.idx
        )
        if is_correct:
            parent_correct += 1
        elif len(parent_mismatch_sample) < 20:
            parent_mismatch_sample.append(
                {
                    "truth_page": entry["page"],
                    "truth_title": entry["title"],
                    "matched_text": cand.text,
                    "expected_parent_text": expected_parent.text if expected_parent else "(root)",
                    "actual_parent_text": actual_parent.text if actual_parent else "(root)",
                }
            )

    recall = matched / len(truth) if truth else 0.0
    level_accuracy = level_correct / matched if matched else 0.0
    parent_accuracy = parent_correct / matched if matched else 0.0
    return {
        "truth_count": len(truth),
        "matched_count": matched,
        "recall": round(recall, 4),
        "level_correct_count": level_correct,
        "level_accuracy": round(level_accuracy, 4),
        "parent_correct_count": parent_correct,
        "parent_accuracy": round(parent_accuracy, 4),
        "level_off_by_histogram": {str(k): v for k, v in sorted(level_off_by.items())},
        "unmatched_truth_sample": unmatched_truth[:20],
        "match_rows": match_rows,
        "parent_mismatch_sample": parent_mismatch_sample,
    }


# ---------------------------------------------------------------------------
# 파이프라인 조립
# ---------------------------------------------------------------------------


def run_variant(
    lines: list[dict[str, Any]],
    tiers: dict[str, Any],
    body_mode: str,
    merge_variant: dict[str, Any],
    truth: list[dict[str, Any]],
    variant_output_dir: Path,
) -> dict[str, Any]:
    tier_of_line = [assign_tier(line["font_size"], tiers["final_cuts"]) for line in lines]
    body_tiers = exclude_body_tiers(tier_of_line, tiers["final_tier_count"], body_mode)

    filtered_lines = [(line, tier) for line, tier in zip(lines, tier_of_line) if tier not in body_tiers]

    merge_log: list[dict[str, Any]] = []
    if merge_variant["kind"] == "no_merge":
        merged_nodes = [{**line, "tier": tier, "merged_line_count": 1} for line, tier in filtered_lines]
    elif merge_variant["kind"] == "same_tier":
        merged_nodes = merge_adjacent_same_tier_lines(filtered_lines, gap_ratio=merge_variant["gap_ratio"])
    elif merge_variant["kind"] == "bpe":
        bpe_nodes, merge_log = bpe_merge_page_local(
            filtered_lines,
            gap_ratio=merge_variant["gap_ratio"],
            min_pair_count=merge_variant["min_pair_count"],
        )
        merged_nodes = []
        for node in bpe_nodes:
            node = dict(node)
            node["tier"] = min(node["tier_seq"])
            merged_nodes.append(node)
    else:
        raise ValueError(f"unknown merge kind: {merge_variant['kind']}")

    candidates = [
        HeadingCandidate(
            idx=idx,
            pdf_page=node["pdf_page"],
            text=node["text"],
            font_size=node["font_size"],
            tier_value=tiers["final_peaks"][node["tier"] - 1],
            tier=node["tier"],
        )
        for idx, node in enumerate(merged_nodes)
    ]

    trace = assign_levels_by_stack(candidates)

    local_monotonicity = check_local_monotonicity(candidates)
    level_jumps = check_level_jumps(candidates)
    eval_result = evaluate_against_ground_truth(candidates, truth) if truth else None
    nested_tree = build_nested_tree(candidates)

    variant_output_dir.mkdir(parents=True, exist_ok=True)
    (variant_output_dir / "stack_trace.txt").write_text("\n".join(trace[:MAX_STACK_TRACE_LINES]), encoding="utf-8")

    flat_tree = [
        {"pdf_page": c.pdf_page, "level": c.level, "title": c.text, "font_size": c.font_size, "tier": c.tier}
        for c in candidates
    ]
    (variant_output_dir / "inferred_bookmark_tree.json").write_text(
        json.dumps(flat_tree, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tree_text = [
        f"총 {len(flat_tree)}개 heading candidate (body_mode={body_mode}, merge={merge_variant['name']})",
        "",
    ]
    for node in flat_tree:
        tree_text.append(f"{'  ' * (node['level'] - 1)}L{node['level']} p.{node['pdf_page']} {node['title']}")
    (variant_output_dir / "inferred_bookmark_tree.txt").write_text("\n".join(tree_text), encoding="utf-8")

    (variant_output_dir / "nested_bookmark_tree.json").write_text(
        json.dumps(nested_tree, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if merge_log:
        (variant_output_dir / "bpe_merge_log.json").write_text(
            json.dumps(merge_log, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    result = {
        "body_mode": body_mode,
        "merge_variant": merge_variant["name"],
        "body_tiers_excluded": sorted(body_tiers),
        "candidate_count": len(candidates),
        "merged_line_count_total": sum(node.get("merged_line_count", 1) for node in merged_nodes),
        "multi_line_candidate_count": sum(1 for node in merged_nodes if node.get("merged_line_count", 1) > 1),
        "max_merged_line_count": max((node.get("merged_line_count", 1) for node in merged_nodes), default=1),
        "bpe_merge_step_count": len(merge_log),
        "local_monotonicity": local_monotonicity,
        "level_jumps": level_jumps,
        "eval_vs_truth": eval_result,
    }
    (variant_output_dir / "eval_vs_truth.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def run_book(config: dict[str, Any]) -> dict[str, Any]:
    book_id = config["id"]
    pdf_path: Path = config["pdf"]
    book_output_dir = OUTPUT_DIR / book_id
    book_output_dir.mkdir(parents=True, exist_ok=True)

    print(f"... {book_id} 전체 page 훑는 중: {pdf_path.name}", flush=True)
    lines = extract_book_lines(pdf_path)
    print(f"    extracted_lines={len(lines)}", flush=True)

    font_sizes = [line["font_size"] for line in lines]
    tiers = compute_tiers(font_sizes, MIN_TIER_COUNT)
    print(
        f"    font_size tiers: raw={tiers['raw_tier_count']} -> final={tiers['final_tier_count']} "
        f"peaks={[round(p, 2) for p in tiers['final_peaks']]}",
        flush=True,
    )

    truth = load_ground_truth(pdf_path)
    print(f"    ground_truth_bookmarks={len(truth)}", flush=True)

    body_mode_results: dict[str, dict[str, Any]] = {}
    for body_mode in BODY_EXCLUSION_MODES:
        variant_results = {}
        for merge_variant in MERGE_VARIANTS:
            variant_dir = book_output_dir / body_mode / merge_variant["name"]
            result = run_variant(lines, tiers, body_mode, merge_variant, truth, variant_dir)
            variant_results[merge_variant["name"]] = result
            eval_info = result["eval_vs_truth"]
            if eval_info:
                print(
                    f"    [{body_mode}/{merge_variant['name']}] candidates={result['candidate_count']} "
                    f"multi_line={result['multi_line_candidate_count']} "
                    f"recall={eval_info['recall']} level_accuracy={eval_info['level_accuracy']} "
                    f"parent_accuracy={eval_info['parent_accuracy']} "
                    f"local_monotonic={result['local_monotonicity']['is_locally_monotonic']}",
                    flush=True,
                )
        body_mode_results[body_mode] = variant_results

    book_summary = {
        "book_id": book_id,
        "line_count": len(lines),
        "tiers": {
            "raw_tier_count": tiers["raw_tier_count"],
            "final_tier_count": tiers["final_tier_count"],
            "final_peaks": [round(p, 2) for p in tiers["final_peaks"]],
        },
        "ground_truth_count": len(truth),
        "body_mode_results": body_mode_results,
    }
    (book_output_dir / "summary.json").write_text(json.dumps(book_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return book_summary


def build_finding(book_summaries: list[dict[str, Any]]) -> str:
    parts = []
    for book_summary in book_summaries:
        book_id = book_summary["book_id"]
        for body_mode, variant_results in book_summary["body_mode_results"].items():
            for variant_name, result in variant_results.items():
                eval_info = result["eval_vs_truth"]
                if eval_info is None:
                    continue
                parts.append(
                    f"{book_id}/{body_mode}/{variant_name}: candidates={result['candidate_count']} "
                    f"multi_line={result['multi_line_candidate_count']} "
                    f"recall={eval_info['recall']}({eval_info['matched_count']}/{eval_info['truth_count']}) "
                    f"level_accuracy={eval_info['level_accuracy']} "
                    f"parent_accuracy={eval_info['parent_accuracy']}"
                )
    return " | ".join(parts)


def record_experiment(
    finding: str, book_summaries: list[dict[str, Any]], available_books: list[dict[str, Any]]
) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "073의 same-tier 병합으로도 못 잡는 문제(챕터 오프너가 배너/거대 숫자/타이틀처럼 "
            "서로 다른 tier로 쪼개짐, 순수 숫자 line은 content span 필터에서 아예 탈락)를 "
            "겨냥해, (1) content span 필터에서 숫자 배제를 없애고 (2) BPE tokenizer 학습과 "
            "같은 방식으로 book 전체에서 반복적으로 함께 나타나는 page-local tier pair를 "
            "찾아 반복 병합한다. no_merge / same_tier_gap1.5(073 baseline) / bpe_min3 / "
            "bpe_min5 네 변형을 John Hull, Shreve Binomial(회귀 확인용), Zvi Bodie "
            "Investments(주 타겟)에 재튜닝 없이 동일 파라미터로 적용해 "
            "recall/level_accuracy/parent_accuracy를 비교한다."
        ),
        "inputs": [str(book["pdf"].relative_to(ROOT_DIR)) for book in available_books],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": [
            "069_page_order_stack_hierarchy",
            "072_local_parent_child_monotonicity_bodie",
            "073_heading_line_merge_bodie",
        ],
        "min_tier_count": MIN_TIER_COUNT,
        "title_match_threshold": TITLE_MATCH_THRESHOLD,
        "merge_variants": [variant["name"] for variant in MERGE_VARIANTS],
        "finding": finding,
        "books": {
            book_summary["book_id"]: {
                "tiers": book_summary["tiers"],
                "ground_truth_count": book_summary["ground_truth_count"],
                "body_mode_results": {
                    body_mode: {
                        variant_name: {
                            "candidate_count": result["candidate_count"],
                            "multi_line_candidate_count": result["multi_line_candidate_count"],
                            "max_merged_line_count": result["max_merged_line_count"],
                            "bpe_merge_step_count": result["bpe_merge_step_count"],
                            "local_monotonicity": result["local_monotonicity"],
                            "eval_vs_truth": (
                                {
                                    key: value
                                    for key, value in result["eval_vs_truth"].items()
                                    if key not in {"match_rows", "unmatched_truth_sample", "parent_mismatch_sample"}
                                }
                                if result["eval_vs_truth"]
                                else None
                            ),
                        }
                        for variant_name, result in variant_results.items()
                    }
                    for body_mode, variant_results in book_summary["body_mode_results"].items()
                },
            }
            for book_summary in book_summaries
        },
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

    # [074 신규] John Hull/Shreve Binomial 회귀 확인용 PDF는 이 작업 컴퓨터의
    # data/(gitignored)에 없을 수 있다 - 다른 작업 컴퓨터에만 있는 로컬 파일이라
    # 실패시키지 않고 건너뛴 뒤 finding에 명시한다(AGENTS.md: 실제 데이터가 없으면
    # 가짜 데이터로 대체하지 않고 사유를 기록한다).
    available_books = []
    skipped_books = []
    for book in BOOKS:
        if book["pdf"].exists():
            available_books.append(book)
        else:
            skipped_books.append(book["id"])
            print(f"... {book['id']} 건너뜀: PDF 없음 ({book['pdf']})", flush=True)

    book_summaries = [run_book(book) for book in available_books]
    if skipped_books:
        print(f"\n건너뛴 책(로컬 PDF 없음): {skipped_books}")

    finding = build_finding(book_summaries)
    if skipped_books:
        finding = f"{finding} | skipped(no local pdf)={skipped_books}"
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(
            {
                "experiment_id": EXPERIMENT_ID,
                "books": book_summaries,
                "skipped_books": skipped_books,
                "finding": finding,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    record_experiment(finding, book_summaries, available_books)

    print("\n=== exp 074: BPE 스타일 page-local tier merge ===")
    print(finding)
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
