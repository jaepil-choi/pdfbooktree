"""experiment 069: page order상의 stack nesting pattern으로 bookmark level을 부여한다.

가설(사용자 제공):
    1. 같은 chapter/sub-chapter는 같은 font size를 가진다.
    2. 서로 다른 계층(level)은 서로 다른 font size를 가진다.
    3. font size 간 hierarchy는 "무조건 큰 게 level 1"이 아니라, page order상에서
       실제로 어떻게 중첩(nesting)되는지 그 패턴으로 정해진다.
    4. 책 전체에서 가장 많이 등장하는 font size(tier)는 본문/각주일 가능성이 높다
       (bookmark 후보가 아니다).
    5. bookmark tree 특성상 상위 level의 노드 수는 하위 level의 노드 수보다 항상
       작거나 같아야 한다(count(level=k) <= count(level=k+1)).

이 실험은 052~055에서 이미 검증된 "line 추출(span -> y좌표 재군집화 -> median)"과
"KDE valley-cut + 2px 병합 + 최소 등장 병합 tier" 코드를 그대로 재사용하고, 그 위에
새로운 stack 기반 level 부여 알고리즘을 추가한다.

stack 알고리즘 핵심:
    stack = []
    for candidate in heading_candidates_in_page_order:
        t = candidate.tier_size  # 값이 클수록 큰 글씨(더 상위 계층 후보)
        while stack and stack[-1] < t:
            stack.pop()
        if stack and stack[-1] == t:
            level = len(stack)          # 같은 크기 -> sibling, 깊이 유지
        else:
            stack.append(t)
            level = len(stack)          # 새로운(더 작은) 크기 -> 한 단계 깊어짐
        candidate.level = level

이 방식은 (a) push가 항상 len(stack)+1이므로 level jump가 구조적으로 불가능하고,
(b) 같은 font size라도 등장 문맥(현재 stack 깊이)에 따라 다른 level을 받을 수 있어
053에서 발견된 "front matter vs 진짜 장 표제가 같은 level 1 안에 섞이는" 문제,
"Appendix vs 일반 절이 같은 level 2 안에 섞이는" 문제를 완화할 것으로 기대한다.

검증 순서:
    1. John Hull(native, 가장 clean, 기존 bookmark 470개) - 100%에 가까운 recall/
       precision/level-accuracy를 목표로 파라미터(본문 제외 기준, tiering 파라미터)를
       튜닝한다.
    2. Shreve Binomial(scanned-pdf-indexed, 기존 bookmark 보유) - John Hull에서 고른
       파라미터를 그대로(재튜닝 없이) 적용해 일반화 여부를 확인한다.

실행:
    uv run python experiments/069_page_order_stack_hierarchy.py
출력:
    experiments/outputs/069_page_order_stack_hierarchy/<book_id>/
        - inferred_bookmark_tree.txt/json : stack 알고리즘이 만든 tree
        - stack_trace.txt                 : candidate별 stack 상태 변화 덤프
        - eval_vs_truth.json              : recall/precision/level-accuracy/
                                             level-jump-count/monotonicity 결과
        - summary.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
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
EXPERIMENT_ID = "069_page_order_stack_hierarchy"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

MIN_TIER_COUNT = 5
BODY_EXCLUSION_MODES = ["mode_only", "mode_and_smaller"]
BODY_SHARE_THRESHOLD = 0.15  # (미사용, 참고용) share_threshold 실험에서는 mode_only와 결과가 같았다
TITLE_MATCH_THRESHOLD = 70  # 053과 동일한 rapidfuzz token_set_ratio 기준
MAX_STACK_TRACE_LINES = 4000

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
]

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_NORM_STRIP = re.compile(r"[^a-z0-9가-힣 ]")
_MULTI_SPACE = re.compile(r"\s+")


def normalize_for_match(text: str) -> str:
    """053과 동일한 정규화. 소문자화 없이 rapidfuzz token_set_ratio를 쓰면 'PREFACE' vs
    'Preface'처럼 대소문자만 다른 완전 일치도 점수가 크게 깎인다(실측: 14.3점)."""

    text = text.lower()
    text = _NORM_STRIP.sub(" ", text)
    return _MULTI_SPACE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# 1단계: line 추출 (054/055와 동일한 로직 재사용)
# ---------------------------------------------------------------------------


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
                "text": " ".join(span["text"] for span in group_sorted)[:160],
                "y0": min(item["yc"] for item in group_sorted),
            }
        )
    return merged


def extract_book_lines(pdf_path: Path) -> list[dict[str, Any]]:
    """책 전체 page를 훑어, page order(page asc, y asc)를 유지한 line 목록을 만든다."""

    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            spans = extract_page_content_spans(page)
            for merged_line in merge_spans_into_lines(spans):
                lines.append({"pdf_page": page_index + 1, **merged_line})
    return lines


# ---------------------------------------------------------------------------
# 2단계: tier 계산 (054/055 기반, 2px chain merge는 제외 — 아래 compute_tiers 참고)
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
    cut_points = [float(grid[vi]) for vi in valley_idx if peaks[0] < grid[vi] < peaks[-1]]
    cut_points = sorted(cut_points)[: max(len(peaks) - 1, 0)]

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
    """KDE 봉우리/골짜기 -> 최소 등장 횟수 병합만 적용한다.

    [069 수정] 054/055의 2px 거리 기반 chain merge(merge_close_tiers)를 뺐다. body
    text 구간(9~12pt)처럼 KDE 봉우리가 촘촘히 이어지는 곳에서는 인접 peak 쌍이 매번
    2px 미만이어도 누적하면 3pt 이상 벌어지는데, chain merge는 이 누적 폭을 무시하고
    body(9~10pt)와 section 제목(11~12pt) tier를 하나로 합쳐버렸다(실측: John Hull
    최종 tier가 3개로 줄고 section 제목 tier가 통째로 사라짐). min-count 병합만
    raw KDE cut으로 직접 적용하면 진짜 노이즈(등장 5회 미만) tier만 흡수되고 body/
    section/chapter 경계가 보존된다(실측: 최종 10개 tier, chapter=96줄,
    section=875줄, body=27998줄로 052의 육안 검증치와 일치).
    """

    raw = cluster_by_density(values)
    final_peaks, final_cuts = merge_tiers_by_min_count(values, raw["peaks"], raw["cut_points"], min_count)
    return {
        "raw_tier_count": raw["tier_count"],
        "final_peaks": final_peaks,
        "final_cuts": final_cuts,
        "final_tier_count": len(final_peaks),
    }


# ---------------------------------------------------------------------------
# 3단계: 본문 tier 제외 (가설 4)
# ---------------------------------------------------------------------------


def exclude_body_tiers(
    lines: list[dict[str, Any]], tier_of_line: list[int], tier_count: int, mode: str
) -> set[int]:
    """본문/각주로 볼 tier 번호 집합을 반환한다. 이 tier에 속한 line은 heading candidate에서 뺀다.

    tier 번호는 assign_tier가 만드는 순서상 1이 가장 큰 font_size, tier_count가 가장
    작은 font_size다(final_peaks가 내림차순이라 tier 번호와 font 크기가 단조 대응한다).
    """

    counts = Counter(tier_of_line)
    if mode == "mode_only":
        # 가장 많이 등장하는 tier 단 하나만 본문으로 본다(가설 4 원문 그대로).
        mode_tier = max(counts, key=counts.get)
        return {mode_tier}
    if mode == "mode_and_smaller":
        # 실측 결과 본문 tier보다 작은 tier(각주/캡션/러닝헤더/차트 라벨)가 여럿 존재했다
        # (예: John Hull tier6 599줄이 전부 차트 축 라벨/각주였다). heading은 절대
        # 본문보다 작을 수 없다는 전제로, 본문 tier와 그보다 작은 tier를 모두 제외한다.
        mode_tier = max(counts, key=counts.get)
        return set(range(mode_tier, tier_count + 1))
    raise ValueError(f"unknown body exclusion mode: {mode}")


# ---------------------------------------------------------------------------
# 4단계: stack 기반 level 부여 (가설 3, 핵심 신규 로직)
# ---------------------------------------------------------------------------


@dataclass
class HeadingCandidate:
    pdf_page: int
    text: str
    font_size: float  # 원본 median 값(참고/리포트용)
    tier_value: float  # tier 대표값(peak) — stack 비교는 반드시 이 값을 써야 한다
    tier: int  # tier 번호(작을수록 큰 글씨)
    level: int = 0
    stack_action: str = ""  # 디버깅용: "push" | "sibling"
    stack_after: list[float] = field(default_factory=list)


def assign_levels_by_stack(candidates: list[HeadingCandidate]) -> list[str]:
    """page order로 정렬된 candidate에 stack 기반 level을 부여하고 trace 로그를 남긴다.

    [069 수정] 비교 기준을 raw font_size(line별 median)가 아니라 tier_value(해당
    tier의 KDE peak 대표값)로 바꿨다. raw 값으로 비교하면 같은 tier 안에서도(예:
    커버 페이지의 32.0pt와 30.0pt가 같은 tier1 범위) 미세하게 다른 값이 서로 다른
    크기로 취급돼 sibling이어야 할 두 제목이 push/push로 잘못 중첩됐다(가설 1 "같은
    chapter/sub-chapter는 같은 font size를 가진다"를 tier 단위로 해석해야 함).
    """

    stack: list[float] = []
    trace: list[str] = []
    for candidate in candidates:
        size = candidate.tier_value
        while stack and stack[-1] < size:
            popped = stack.pop()
            trace.append(f"  pop {popped} (< {size})")
        if stack and stack[-1] == size:
            candidate.level = len(stack)
            candidate.stack_action = "sibling"
        else:
            stack.append(size)
            candidate.level = len(stack)
            candidate.stack_action = "push"
        candidate.stack_after = list(stack)
        trace.append(
            f"p{candidate.pdf_page:>4} size={size:>6} tier=T{candidate.tier} "
            f"action={candidate.stack_action:<7} level={candidate.level} "
            f"stack={stack!r} text={candidate.text[:60]!r}"
        )
    return trace


# ---------------------------------------------------------------------------
# 5단계: 구조 검증 (가설 5)
# ---------------------------------------------------------------------------


def check_count_monotonicity(candidates: list[HeadingCandidate]) -> dict[str, Any]:
    """count(level=k) <= count(level=k+1)가 모든 k에 대해 성립하는지 확인한다."""

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


def check_level_jumps(candidates: list[HeadingCandidate]) -> int:
    """연속된 두 candidate 사이 level이 2 이상 벌어지는 경우를 센다(설계상 0이어야 정상)."""

    jumps = 0
    for prev, cur in zip(candidates, candidates[1:]):
        if cur.level - prev.level > 1:
            jumps += 1
    return jumps


# ---------------------------------------------------------------------------
# 6/7단계: ground truth 비교
# ---------------------------------------------------------------------------


def load_ground_truth(pdf_path: Path) -> list[dict[str, Any]]:
    with fitz.open(pdf_path) as document:
        toc = document.get_toc(simple=False)
    return [
        {"level": level, "title": title, "page": page_no}
        for level, title, page_no, _dest in toc
        if page_no > 0
    ]


def evaluate_against_ground_truth(
    candidates: list[HeadingCandidate], truth: list[dict[str, Any]]
) -> dict[str, Any]:
    """053과 동일하게 rapidfuzz token_set_ratio로 truth title <-> candidate title을 매칭한다.

    같은 page(±0)에 있는 candidate 중 title이 threshold 이상으로 가장 잘 맞는 것을 고른다.
    """

    by_page: dict[int, list[HeadingCandidate]] = {}
    for candidate in candidates:
        by_page.setdefault(candidate.pdf_page, []).append(candidate)

    matched = 0
    level_correct = 0
    level_off_by = Counter()
    unmatched_truth: list[dict[str, Any]] = []
    match_rows: list[dict[str, Any]] = []

    for entry in truth:
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

    recall = matched / len(truth) if truth else 0.0
    level_accuracy = level_correct / matched if matched else 0.0
    # candidate 중 truth와 매칭되지 않고 남는 것의 비율(precision 근사, page 단위 재사용 매칭이라 근사치)
    return {
        "truth_count": len(truth),
        "matched_count": matched,
        "recall": round(recall, 4),
        "level_correct_count": level_correct,
        "level_accuracy": round(level_accuracy, 4),
        "level_off_by_histogram": {str(k): v for k, v in sorted(level_off_by.items())},
        "unmatched_truth_sample": unmatched_truth[:20],
        "match_rows": match_rows,
    }


# ---------------------------------------------------------------------------
# 파이프라인 조립
# ---------------------------------------------------------------------------


def run_body_mode(
    book_id: str,
    lines: list[dict[str, Any]],
    tiers: dict[str, Any],
    body_mode: str,
    truth: list[dict[str, Any]],
    book_output_dir: Path,
) -> dict[str, Any]:
    tier_of_line = [assign_tier(line["font_size"], tiers["final_cuts"]) for line in lines]
    body_tiers = exclude_body_tiers(lines, tier_of_line, tiers["final_tier_count"], body_mode)

    candidates = [
        HeadingCandidate(
            pdf_page=line["pdf_page"],
            text=line["text"],
            font_size=line["font_size"],
            tier_value=tiers["final_peaks"][tier - 1],
            tier=tier,
        )
        for line, tier in zip(lines, tier_of_line)
        if tier not in body_tiers
    ]

    trace = assign_levels_by_stack(candidates)

    monotonicity = check_count_monotonicity(candidates)
    level_jumps = check_level_jumps(candidates)
    eval_result = evaluate_against_ground_truth(candidates, truth) if truth else None

    mode_dir = book_output_dir / body_mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    (mode_dir / "stack_trace.txt").write_text("\n".join(trace[:MAX_STACK_TRACE_LINES]), encoding="utf-8")

    tree = [
        {"pdf_page": c.pdf_page, "level": c.level, "title": c.text, "font_size": c.font_size, "tier": c.tier}
        for c in candidates
    ]
    (mode_dir / "inferred_bookmark_tree.json").write_text(
        json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tree_text = [f"총 {len(tree)}개 heading candidate (body_mode={body_mode})", ""]
    for node in tree:
        tree_text.append(f"{'  ' * (node['level'] - 1)}L{node['level']} p.{node['pdf_page']} {node['title']}")
    (mode_dir / "inferred_bookmark_tree.txt").write_text("\n".join(tree_text), encoding="utf-8")

    result = {
        "body_mode": body_mode,
        "body_tiers_excluded": sorted(body_tiers),
        "candidate_count": len(candidates),
        "monotonicity": monotonicity,
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
        result = run_body_mode(book_id, lines, tiers, body_mode, truth, book_output_dir)
        body_mode_results[body_mode] = result
        eval_info = result["eval_vs_truth"]
        if eval_info:
            print(
                f"    [{body_mode}] candidates={result['candidate_count']} "
                f"recall={eval_info['recall']} level_accuracy={eval_info['level_accuracy']} "
                f"level_jumps={result['level_jumps']} monotonic={result['monotonicity']['is_monotonic']}",
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


def build_finding(book_summaries: list[dict[str, Any]]) -> str:
    parts = []
    for summary in book_summaries:
        for body_mode, result in summary["body_mode_results"].items():
            eval_info = result["eval_vs_truth"]
            if eval_info is None:
                continue
            parts.append(
                f"{summary['book_id']}/{body_mode}: candidates={result['candidate_count']} "
                f"recall={eval_info['recall']}({eval_info['matched_count']}/{eval_info['truth_count']}) "
                f"level_accuracy={eval_info['level_accuracy']} level_jumps={result['level_jumps']} "
                f"monotonic={result['monotonicity']['is_monotonic']} "
                f"level_off_by={eval_info['level_off_by_histogram']}"
            )
    return " | ".join(parts)


def record_experiment(finding: str, book_summaries: list[dict[str, Any]]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "font size hierarchy가 global 크기 정렬이 아니라 page order상의 nesting "
            "pattern(stack)으로 정해진다는 가설을 검증한다. 가장 많이 등장하는 tier를 "
            "본문/각주로 제외한 뒤 남은 heading candidate를 stack 알고리즘으로 level "
            "부여하고, level 개수가 깊어질수록 줄지 않는다는 구조 제약(count "
            "monotonicity)과 level jump 없음을 함께 검증한다. John Hull(native, 기존 "
            "bookmark 정답)에서 recall/level-accuracy를 최대화한 뒤, 같은 파라미터를 "
            "Shreve Binomial(scanned-indexed)에 재튜닝 없이 그대로 적용해 일반화를 본다."
        ),
        "inputs": [str(book["pdf"].relative_to(ROOT_DIR)) for book in BOOKS],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": [
            "052_whole_book_line_font_height_kde",
            "053_bookmark_depth_font_size_kde",
            "054_tier_merge_and_scanned_font_check",
            "055_page_tier_distribution_clustering",
        ],
        "min_tier_count": MIN_TIER_COUNT,
        "body_share_threshold": BODY_SHARE_THRESHOLD,
        "title_match_threshold": TITLE_MATCH_THRESHOLD,
        "finding": finding,
        "books": {
            summary["book_id"]: {
                "tiers": summary["tiers"],
                "ground_truth_count": summary["ground_truth_count"],
                "body_mode_results": {
                    mode: {
                        "candidate_count": result["candidate_count"],
                        "monotonicity": result["monotonicity"],
                        "level_jumps": result["level_jumps"],
                        "eval_vs_truth": (
                            {
                                key: value
                                for key, value in result["eval_vs_truth"].items()
                                if key not in {"match_rows", "unmatched_truth_sample"}
                            }
                            if result["eval_vs_truth"]
                            else None
                        ),
                    }
                    for mode, result in summary["body_mode_results"].items()
                },
            }
            for summary in book_summaries
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

    book_summaries = [run_book(config) for config in BOOKS]

    finding = build_finding(book_summaries)
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps({"experiment_id": EXPERIMENT_ID, "books": book_summaries, "finding": finding}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_experiment(finding, book_summaries)

    print("\n=== exp 069: page order stack hierarchy ===")
    print(finding)
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
