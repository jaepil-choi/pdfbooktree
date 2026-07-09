"""experiment 072: 부모-자식 국소(local) count 제약으로 stack hierarchy의 monotonicity를 재검증한다.

069의 발견 재해석(사용자 제공 지적):
    069는 count(level=k) <= count(level=k+1)이 "책 전체"에서 항상 성립해야 한다고
    보고, John Hull/Shreve Binomial 양쪽에서 이 global 버전이 깨지는 것을
    "구조 제약 위반"으로 기록했다. 이건 알고리즘을 잘못 적용한 것이다.

    tree 구조상 실제로 항상 성립해야 하는 건 global count가 아니라 local(부모-자식)
    count다: level k의 노드가 모두 level k+1 자식을 갖는 게 아니다. 예를 들어 level 2
    노드 10개 중 2개만 각각 level 3 자식을 2개씩 가진다면, level 3 노드는 4개뿐이고
    나머지 8개의 level 2 노드는 leaf다. 이때 "level 2 count(10) <= level 3
    count(4)"는 당연히 깨지지만, 이건 정상적인 tree이지 위반이 아니다.

    tree data structure상 항상 성립하는 진짜 제약은 다음이다:
        count(level=k 중 level k+1 자식을 실제로 가진 노드) <= count(level=k+1)
    (부모 집합의 크기는 자식 집합의 크기를 절대 넘을 수 없다 — 각 자식은 부모를
    정확히 하나만 가지므로.) 이 local 제약은 stack 알고리즘이 실제 parent-child
    edge를 기록하며 tree를 만드는 한 항상(tautology로) 성립해야 한다. 069는 이
    edge를 기록하지 않고 flat level count만 셌기 때문에 진짜로는 문제없는 tree를
    "not monotonic"으로 잘못 판정했다.

이 실험은:
    1. 069의 stack 알고리즘에 parent_idx 추적을 추가해 실제 nested tree(parent-child
       edge)를 만든다. sibling 노드는 직전 sibling으로 anchor를 갱신해, 더 깊은
       push가 "가장 최근" sibling의 자식이 되도록 한다(문서 목차의 자연스러운 nesting).
    2. global(069 방식, flat level count 비교 — 참고용/대조군)과 local(이번 실험,
       parent-with-children count 비교 — 실제 tree 제약) monotonicity를 둘 다
       계산해 대조한다. local은 모든 body_mode에서 항상 True여야 한다(구조상 tautology).
    3. Zvi Bodie Investments(native-pdf-indexed, 기존 bookmark 793개, level 1~4)에
       적용해 실제 bookmark tree를 만들고 정답과 비교한다.

069와의 코드 관계:
    line 추출/tiering/본문 제외/stack level 부여/ground-truth 평가 로직은 069를
    그대로 재사용한다(파일 복사, import 아님 — AGENTS.md 3절 monolithic 원칙).
    변경/추가된 부분만 각 함수 docstring에 "[072 변경]"으로 표시했다.

실행:
    uv run python experiments/072_local_parent_child_monotonicity_bodie.py
출력:
    experiments/outputs/072_local_parent_child_monotonicity_bodie/
        - inferred_bookmark_tree.txt/json : flat list (level 표기)
        - nested_bookmark_tree.json       : parent_idx 기반 실제 nested tree
        - stack_trace.txt
        - eval_vs_truth.json
        - monotonicity_comparison.json    : global(069, 참고용) vs local(072, 실제 제약)
        - summary.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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
EXPERIMENT_ID = "072_local_parent_child_monotonicity_bodie"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

MIN_TIER_COUNT = 5
BODY_EXCLUSION_MODES = ["mode_only", "mode_and_smaller"]
TITLE_MATCH_THRESHOLD = 70  # 053/069와 동일한 rapidfuzz token_set_ratio 기준
MAX_STACK_TRACE_LINES = 4000

BOOK = {
    "id": "zvi_bodie_investments",
    "pdf": ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf",
}

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_NORM_STRIP = re.compile(r"[^a-z0-9가-힣 ]")
_MULTI_SPACE = re.compile(r"\s+")


def normalize_for_match(text: str) -> str:
    text = text.lower()
    text = _NORM_STRIP.sub(" ", text)
    return _MULTI_SPACE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# 1단계: line 추출 (069/054/055와 동일)
# ---------------------------------------------------------------------------


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


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
# 2단계: tier 계산 (069와 동일)
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

    # [072 수정] 069/054/055의 원래 로직은 valley 후보를 전부 모은 뒤
    # `sorted(cut_points)[: len(peaks) - 1]`로 오름차순 앞쪽 N-1개만 잘라썼다. Bodie
    # 책처럼 peak 사이 간격이 고르지 않으면(예: 표지 60pt처럼 희귀한 큰 폰트와 본문
    # 근처의 촘촘한 peak들이 섞이면) 진짜로 필요한 큰 값의 cut(예: 60pt와 42pt 사이)이
    # 오름차순 truncation에서 잘려나가 cut_points 개수가 len(peaks)-1보다 작아지고
    # merge_tiers_by_min_count가 인덱스 범위를 벗어나며 죽었다(실측: 23 peaks인데 21
    # cuts만 남아 60pt~42pt 사이 cut이 사라짐). peak 쌍마다 독립적으로 밀도가 가장 낮은
    # valley를 하나씩 고르면 cut_points 개수가 항상 len(peaks)-1로 보장된다.
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
# 3단계: 본문 tier 제외 (069와 동일)
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
# 4단계: stack 기반 level 부여 + parent-child edge 기록 ([072 신규])
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
    """069의 stack 알고리즘에 parent_idx 추적을 추가한다.

    [072 신규] 069는 level(정수)만 부여하고 어떤 노드가 어떤 노드의 실제 자식인지는
    기록하지 않았다. 그 결과 069의 monotonicity 검증이 "level별 전체 개수"만 비교하는
    global 버전으로 흐를 수밖에 없었다. 여기서는 stack에 (tier_value, candidate_idx)
    쌍을 쌓아, push 시점의 parent를 "push 직전 stack top의 candidate"로, sibling
    시점의 parent를 "한 단계 얕은 stack top의 candidate"로 명시적으로 기록한다.
    sibling이 나올 때마다 해당 깊이의 anchor를 최신 sibling으로 갱신해, 그보다 더
    깊은 push가 "가장 최근 sibling"의 자식이 되도록 한다(실제 문서 목차의 nesting과
    일치하는 자연스러운 동작).
    """

    stack: list[dict[str, Any]] = []  # [{"value": tier_value, "idx": candidate_idx}, ...]
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
# 5단계: 구조 검증 — global(069, 참고용) vs local(072, 실제 제약) ([072 신규])
# ---------------------------------------------------------------------------


def check_global_monotonicity(candidates: list[HeadingCandidate]) -> dict[str, Any]:
    """069와 동일한 flat level count 비교. [072 주의] 이건 tree 구조상 항상 성립해야
    하는 제약이 아니다 — 참고/대조용으로만 남긴다(사용자 지적: "hull에서 만족하지
    않는 경우가 있다고 적었는데 그건 알고리즘을 잘못 적용한 것"). 실제 제약은
    check_local_monotonicity를 보라."""

    counts = Counter(candidate.level for candidate in candidates)
    max_level = max(counts) if counts else 0
    level_counts = [counts.get(level, 0) for level in range(1, max_level + 1)]
    violations = [
        {"level": level, "count": level_counts[level - 1], "next_level": level + 1, "next_count": level_counts[level]}
        for level in range(1, max_level)
        if level_counts[level - 1] > level_counts[level]
    ]
    return {
        "level_counts": {str(i + 1): c for i, c in enumerate(level_counts)},
        "max_level": max_level,
        "violations": violations,
        "is_monotonic": len(violations) == 0,
    }


def check_local_monotonicity(candidates: list[HeadingCandidate]) -> dict[str, Any]:
    """[072 신규] 실제 tree 제약: count(level=k 중 level k+1 자식을 가진 노드) <=
    count(level=k+1). 각 자식은 부모를 정확히 하나만 가지므로, "자식을 가진 부모"의
    집합 크기는 자식 집합 크기를 절대 넘을 수 없다 — parent_idx 기반 tree라면
    tautology로 항상 성립해야 한다. 이 실험에서 모든 body_mode에 대해 True가 나오는지
    확인해, 069가 global count로 검출한 "위반"이 알고리즘 버그가 아니라 검증 방식의
    오류였음을 보인다."""

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
    """[072 신규] parent_idx 기반으로 실제 nested tree(children 배열)를 만든다."""

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
# 6단계: ground truth 비교 (069와 동일)
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
    """[072b 신규] truth의 level 정수 목록에서 실제 부모 truth-entry 인덱스를
    복원한다. PDF outline은 page order로 저장되므로, 어떤 entry의 부모는 "그 앞에
    나온 것 중 level이 하나 얕은 가장 최근 entry"다. 더 얕은 entry가 새로 나오면
    그보다 깊은 level의 "최근 기록"은 전부 무효화한다(다른 하위 트리로 넘어갔으므로)."""

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
    """[072b 변경] 절대 level 정수 일치(level_accuracy)에 더해, 상대적 위치(누가
    부모인가)가 맞았는지 보는 parent_accuracy를 추가했다. 사용자 지적: bookmark
    자동 생성에서는 절대 depth가 아니라 상대적 계층 구조가 중요하다 — 트리 전체가
    일괄로 한 단계 밀려도(front matter 처리 차이 등) 상대 구조는 정상일 수 있는데
    level_accuracy는 이런 경우를 전부 오답으로 센다.

    parent_accuracy 계산: 매칭된 truth entry마다 "진짜 부모"(build_truth_parent_index)와
    "추론된 부모"(candidate.parent_idx)를 비교한다. 다만 recall이 100%가 아니므로
    부모가 매칭 실패한 noise/누락 노드일 수 있다 — 이 경우 truth 쪽/inferred 쪽 모두
    "가장 가까운 매칭된 조상"까지 거슬러 올라가 비교한다(둘 다 root까지 못 찾으면
    None==None으로 정답 처리). 이렇게 해야 매칭 안 된 잡음 후보 하나 때문에 그 아래
    전체 서브트리가 부모 불일치로 오답 처리되는 것을 막는다.
    """

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


def run_body_mode(
    lines: list[dict[str, Any]],
    tiers: dict[str, Any],
    body_mode: str,
    truth: list[dict[str, Any]],
    book_output_dir: Path,
) -> dict[str, Any]:
    tier_of_line = [assign_tier(line["font_size"], tiers["final_cuts"]) for line in lines]
    body_tiers = exclude_body_tiers(tier_of_line, tiers["final_tier_count"], body_mode)

    candidates = [
        HeadingCandidate(
            idx=idx,
            pdf_page=line["pdf_page"],
            text=line["text"],
            font_size=line["font_size"],
            tier_value=tiers["final_peaks"][tier - 1],
            tier=tier,
        )
        for idx, (line, tier) in enumerate(
            (line, tier) for line, tier in zip(lines, tier_of_line) if tier not in body_tiers
        )
    ]

    trace = assign_levels_by_stack(candidates)

    global_monotonicity = check_global_monotonicity(candidates)
    local_monotonicity = check_local_monotonicity(candidates)
    level_jumps = check_level_jumps(candidates)
    eval_result = evaluate_against_ground_truth(candidates, truth) if truth else None
    nested_tree = build_nested_tree(candidates)

    mode_dir = book_output_dir / body_mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    (mode_dir / "stack_trace.txt").write_text("\n".join(trace[:MAX_STACK_TRACE_LINES]), encoding="utf-8")

    flat_tree = [
        {"pdf_page": c.pdf_page, "level": c.level, "title": c.text, "font_size": c.font_size, "tier": c.tier}
        for c in candidates
    ]
    (mode_dir / "inferred_bookmark_tree.json").write_text(
        json.dumps(flat_tree, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tree_text = [f"총 {len(flat_tree)}개 heading candidate (body_mode={body_mode})", ""]
    for node in flat_tree:
        tree_text.append(f"{'  ' * (node['level'] - 1)}L{node['level']} p.{node['pdf_page']} {node['title']}")
    (mode_dir / "inferred_bookmark_tree.txt").write_text("\n".join(tree_text), encoding="utf-8")

    (mode_dir / "nested_bookmark_tree.json").write_text(
        json.dumps(nested_tree, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    result = {
        "body_mode": body_mode,
        "body_tiers_excluded": sorted(body_tiers),
        "candidate_count": len(candidates),
        "global_monotonicity": global_monotonicity,
        "local_monotonicity": local_monotonicity,
        "level_jumps": level_jumps,
        "eval_vs_truth": eval_result,
    }
    (mode_dir / "eval_vs_truth.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
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

    body_mode_results = {}
    for body_mode in BODY_EXCLUSION_MODES:
        result = run_body_mode(lines, tiers, body_mode, truth, book_output_dir)
        body_mode_results[body_mode] = result
        eval_info = result["eval_vs_truth"]
        if eval_info:
            print(
                f"    [{body_mode}] candidates={result['candidate_count']} "
                f"recall={eval_info['recall']} level_accuracy={eval_info['level_accuracy']} "
                f"parent_accuracy={eval_info['parent_accuracy']} "
                f"level_jumps={result['level_jumps']} "
                f"global_monotonic={result['global_monotonicity']['is_monotonic']} "
                f"local_monotonic={result['local_monotonicity']['is_locally_monotonic']}",
                flush=True,
            )

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


def build_finding(book_summary: dict[str, Any]) -> str:
    parts = []
    for body_mode, result in book_summary["body_mode_results"].items():
        eval_info = result["eval_vs_truth"]
        if eval_info is None:
            continue
        parts.append(
            f"{body_mode}: candidates={result['candidate_count']} "
            f"recall={eval_info['recall']}({eval_info['matched_count']}/{eval_info['truth_count']}) "
            f"level_accuracy(절대,참고용)={eval_info['level_accuracy']} "
            f"parent_accuracy(상대,실제지표)={eval_info['parent_accuracy']} "
            f"level_jumps={result['level_jumps']} "
            f"global_monotonic(069식,참고용)={result['global_monotonicity']['is_monotonic']} "
            f"local_monotonic(실제제약)={result['local_monotonicity']['is_locally_monotonic']} "
            f"level_off_by={eval_info['level_off_by_histogram']}"
        )
    return " | ".join(parts)


def record_experiment(finding: str, book_summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "069가 count monotonicity를 global flat level count로 검증해 John Hull/"
            "Shreve Binomial에서 잘못된 '위반'을 보고한 문제를 바로잡는다. tree "
            "구조상 실제로 항상 성립해야 하는 제약은 global count가 아니라 local "
            "(부모-자식) count다: level k 중 level k+1 자식을 실제로 가진 노드의 "
            "수는 level k+1 노드 수를 넘을 수 없다(각 자식은 부모를 정확히 하나만 "
            "가지므로). stack 알고리즘에 parent_idx 추적을 추가해 실제 nested tree를 "
            "만들고, 이 local 제약이 tautology로 항상 성립하는지 확인한 뒤 Zvi Bodie "
            "Investments(native-pdf-indexed, 기존 bookmark 793개)에 적용해 bookmark "
            "tree를 만들고 정답과 비교한다. [072b 추가] bookmark 자동 생성에서는 "
            "절대 depth가 아니라 상대적 계층 구조(누가 부모인가)가 중요하다는 지적에 "
            "따라, 절대 level 정수 일치(level_accuracy)와 별도로 매칭된 truth-entry의 "
            "진짜 부모와 추론된 부모가 일치하는지(가장 가까운 매칭된 조상까지 거슬러 "
            "올라가 비교, recall 누락에 강건) 보는 parent_accuracy를 추가해 재평가한다."
        ),
        "inputs": [str(BOOK["pdf"].relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": ["069_page_order_stack_hierarchy"],
        "min_tier_count": MIN_TIER_COUNT,
        "title_match_threshold": TITLE_MATCH_THRESHOLD,
        "finding": finding,
        "book": {
            "tiers": book_summary["tiers"],
            "ground_truth_count": book_summary["ground_truth_count"],
            "body_mode_results": {
                mode: {
                    "candidate_count": result["candidate_count"],
                    "global_monotonicity": result["global_monotonicity"],
                    "local_monotonicity": result["local_monotonicity"],
                    "level_jumps": result["level_jumps"],
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
                for mode, result in book_summary["body_mode_results"].items()
            },
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

    book_summary = run_book(BOOK)

    finding = build_finding(book_summary)
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps({"experiment_id": EXPERIMENT_ID, "book": book_summary, "finding": finding}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_experiment(finding, book_summary)

    print("\n=== exp 072: local parent-child monotonicity (Zvi Bodie Investments) ===")
    print(finding)
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
