"""experiment 073: 같은 page에서 인접하고 font tier가 같은 line을 하나의 heading 후보로 합친다.

072에서 발견한 문제(사용자 제공 지적):
    072의 parent_mismatch_sample을 까보니, "Chapter 1: The Investment Environment"처럼
    한 heading이 실제로는 "CHAPTER" / "1" / "The Investment Environment"처럼 여러
    visual line에 걸쳐 렌더링돼 있는데, 072(=069 그대로)는 line 하나 = candidate
    하나로 취급했다. 그 결과 ground-truth title과의 fuzzy 매칭이 헤딩 전체가 아니라
    "CHAPTER"라는 짧은 배너 fragment에 잘못 매칭되고, 그 fragment의 실제 stack 부모가
    front matter 잔재(Acknowledgments 등)라서 Chapter 1 밑의 모든 하위 항목이 연쇄적
    으로 부모 불일치(parent_accuracy 오답)로 잡혔다.

    사용자 지적: "같은 페이지에서 붙어있고(neighboring line) 같은 font size면 한
    덩어리로 봐야 해." 즉 line 병합은 응당 heading 후보를 만들기 "이전에" 처리해야
    하는 전처리 책임이다(src/pdfbooktree/typography/headings.py가 최종 목적지).
    이 실험은 그 가설을 src에 반영하기 전에 072와 동일한 pipeline/평가 위에서
    A/B로 검증한다:
        - no_merge   : 072와 동일(line 하나 = candidate 하나, baseline)
        - merge_gap1.5: 같은 page + 같은 tier + 인접(line 사이 다른 tier 없음) +
                        수직 gap이 line height의 1.5배 이하인 line들을 병합
        - merge_nogap : 위와 동일하되 gap 조건 없이(같은 page + 같은 tier + 인접이면
                        무조건) 병합 — gap gate 자체가 결과에 영향을 주는지 확인하는
                        대조군

    각 변형을 mode_only/mode_and_smaller 두 body_mode에 모두 적용해
    recall/level_accuracy/parent_accuracy 변화를 비교한다. 072와 마찬가지로
    local_monotonicity는 tautology이므로 참고용으로만 유지한다.

072와의 코드 관계:
    line 추출/tiering/본문 제외/stack level 부여(parent_idx 포함)/ground-truth
    평가(parent_accuracy 포함) 로직은 072를 그대로 재사용한다(파일 복사, import
    아님 — AGENTS.md 3절 monolithic 원칙). 신규 로직은 merge_adjacent_same_tier_lines
    하나뿐이며, [073 신규]로 표시했다.

실행:
    uv run python experiments/073_heading_line_merge_bodie.py
출력:
    experiments/outputs/073_heading_line_merge_bodie/
        zvi_bodie_investments/<body_mode>/<merge_variant>/
            - inferred_bookmark_tree.txt/json
            - nested_bookmark_tree.json
            - stack_trace.txt
            - eval_vs_truth.json
        summary.json
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
EXPERIMENT_ID = "073_heading_line_merge_bodie"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

MIN_TIER_COUNT = 5
BODY_EXCLUSION_MODES = ["mode_only", "mode_and_smaller"]
MERGE_VARIANTS = [
    {"name": "no_merge", "max_gap_ratio": None},
    {"name": "merge_gap1.5", "max_gap_ratio": 1.5},
    {"name": "merge_nogap", "max_gap_ratio": None, "ignore_gap": True},
]
TITLE_MATCH_THRESHOLD = 70
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
# 1단계: line 추출 (072와 동일)
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
# 2단계: tier 계산 (072와 동일, valley 선택 버그 수정 포함)
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
# 3단계: 본문 tier 제외 (072와 동일)
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
# 3.5단계: 인접 동일 tier line 병합 ([073 신규])
# ---------------------------------------------------------------------------


def merge_adjacent_same_tier_lines(
    filtered_lines: list[tuple[dict[str, Any], int]],
    max_gap_ratio: float | None,
    ignore_gap: bool = False,
) -> list[dict[str, Any]]:
    """본문 tier가 제외된 heading-candidate line들(page order 유지)을 대상으로,
    같은 page + 같은 tier + 순서상 바로 인접한 line을 하나의 후보로 합친다.

    [073 신규] 사용자 지적: "같은 페이지에서 붙어있고 같은 font size면 한 덩어리로
    봐야 한다." heading이 "CHAPTER" / "1" / "The Investment Environment"처럼 여러
    line으로 쪼개져 렌더링될 때, line 단위로 candidate를 만들면 fuzzy title 매칭이
    fragment 하나에 잘못 꽂혀 그 아래 전체 서브트리의 parent_accuracy가 연쇄로
    틀어진다(072 parent_mismatch_sample 실측).

    max_gap_ratio가 None이 아니면 두 line 사이 수직 gap(다음 line의 y0 - 현재 line의
    y0+height)이 `max(두 line height) * max_gap_ratio`를 넘으면 병합하지 않는다 —
    같은 tier라도 페이지 안에서 멀리 떨어진 두 텍스트(예: 서로 무관한 pull quote
    두 개)까지 합쳐지는 것을 막기 위한 gate다. ignore_gap=True면 이 gate 없이 같은
    page+tier+인접이면 무조건 합친다(gate의 실제 효과를 보기 위한 대조군).
    """

    merged: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_tier: int | None = None

    for line, tier in filtered_lines:
        can_merge = (
            current is not None
            and current_tier == tier
            and current["pdf_page"] == line["pdf_page"]
        )
        if can_merge and not ignore_gap and max_gap_ratio is not None:
            gap = line["y0"] - (current["y0"] + current["height"])
            gate = max(current["height"], line["height"]) * max_gap_ratio
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
        }
        current_tier = tier

    if current is not None:
        merged.append(current)

    for node, (_, tier) in zip(merged, _representative_tier_pairs(filtered_lines, merged)):
        node["tier"] = tier
    return merged


def _representative_tier_pairs(
    filtered_lines: list[tuple[dict[str, Any], int]], merged: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], int]]:
    """merge 결과 각 그룹의 tier 번호를 원본 (line, tier) 순서를 다시 훑어 복원한다."""

    pairs: list[tuple[dict[str, Any], int]] = []
    src_idx = 0
    for node in merged:
        # node는 merged_line_count개의 원본 line을 흡수했다 — 그 첫 줄의 tier를 대표값으로 쓴다.
        _, tier = filtered_lines[src_idx]
        pairs.append((node, tier))
        src_idx += node["merged_line_count"]
    return pairs


# ---------------------------------------------------------------------------
# 4단계: stack 기반 level 부여 + parent-child edge 기록 (072와 동일)
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
# 5단계: 구조 검증 (072와 동일)
# ---------------------------------------------------------------------------


def check_global_monotonicity(candidates: list[HeadingCandidate]) -> dict[str, Any]:
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
# 6단계: ground truth 비교 (072와 동일, parent_accuracy 포함)
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

    if merge_variant["name"] == "no_merge":
        merged_nodes = [
            {**line, "tier": tier, "merged_line_count": 1} for line, tier in filtered_lines
        ]
    else:
        merged_nodes = merge_adjacent_same_tier_lines(
            filtered_lines,
            max_gap_ratio=merge_variant.get("max_gap_ratio"),
            ignore_gap=merge_variant.get("ignore_gap", False),
        )

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

    global_monotonicity = check_global_monotonicity(candidates)
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

    result = {
        "body_mode": body_mode,
        "merge_variant": merge_variant["name"],
        "body_tiers_excluded": sorted(body_tiers),
        "candidate_count": len(candidates),
        "merged_line_count_total": sum(node.get("merged_line_count", 1) for node in merged_nodes),
        "multi_line_candidate_count": sum(1 for node in merged_nodes if node.get("merged_line_count", 1) > 1),
        "global_monotonicity": global_monotonicity,
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


def build_finding(book_summary: dict[str, Any]) -> str:
    parts = []
    for body_mode, variant_results in book_summary["body_mode_results"].items():
        for variant_name, result in variant_results.items():
            eval_info = result["eval_vs_truth"]
            if eval_info is None:
                continue
            parts.append(
                f"{body_mode}/{variant_name}: candidates={result['candidate_count']} "
                f"multi_line={result['multi_line_candidate_count']} "
                f"recall={eval_info['recall']}({eval_info['matched_count']}/{eval_info['truth_count']}) "
                f"level_accuracy={eval_info['level_accuracy']} "
                f"parent_accuracy={eval_info['parent_accuracy']} "
                f"local_monotonic={result['local_monotonicity']['is_locally_monotonic']}"
            )
    return " | ".join(parts)


def record_experiment(finding: str, book_summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "072의 parent_mismatch_sample에서 발견한 문제(heading이 여러 line으로 "
            "쪼개져 렌더링되면 fuzzy title 매칭이 fragment 하나에 잘못 꽂혀 그 아래 "
            "서브트리 전체의 parent_accuracy가 연쇄로 틀어짐)를 바로잡는다. 사용자 "
            "지적: 같은 page에서 인접하고 font tier가 같은 line은 heading 후보를 "
            "만들기 전에 하나로 합쳐야 한다. no_merge(072와 동일, baseline) / "
            "merge_gap1.5(같은 page+tier+인접, 수직 gap<=line height*1.5) / "
            "merge_nogap(gap 조건 없이 같은 page+tier+인접이면 병합) 세 변형을 "
            "mode_only/mode_and_smaller 두 body_mode에 각각 적용해 Zvi Bodie "
            "Investments에서 recall/level_accuracy/parent_accuracy 변화를 비교한다."
        ),
        "inputs": [str(BOOK["pdf"].relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": [
            "069_page_order_stack_hierarchy",
            "072_local_parent_child_monotonicity_bodie",
        ],
        "min_tier_count": MIN_TIER_COUNT,
        "title_match_threshold": TITLE_MATCH_THRESHOLD,
        "merge_variants": [variant["name"] for variant in MERGE_VARIANTS],
        "finding": finding,
        "book": {
            "tiers": book_summary["tiers"],
            "ground_truth_count": book_summary["ground_truth_count"],
            "body_mode_results": {
                body_mode: {
                    variant_name: {
                        "candidate_count": result["candidate_count"],
                        "multi_line_candidate_count": result["multi_line_candidate_count"],
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

    print("\n=== exp 073: heading line merge (Zvi Bodie Investments) ===")
    print(finding)
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
