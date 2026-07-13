"""experiment 024: 번호 거터 geometry + 시퀀스 합의로 목차 계층 복원(digit 미독).

배경
- experiment 023은 height + x0 + 번호구조(regex)를 LLM에 주고 level을 추론시켰다.
  그러나 번호 줄 자체가 OCR로 noisy하다(1->l, 1.1->11/l.l, 점 누락). hard regex가
  실패하면 그 줄이 number_kind=none으로 떨어지고, 바로 그 "번호 없는 줄"을 LLM이
  자유롭게 깊이 매기면서 john_hull 계층이 weakref 0.90->0.07로 붕괴했다.

핵심 아이디어(사용자와 확립)
- (idea 2) 번호의 '값'이 아니라 '거터 기하 구조'로 계층 skeleton을 만든다. 제목 글자가
  시작하는 x(title_x) 들여쓰기 컬럼과, 거터의 구분자(.) 개수만으로 깊이를 정한다.
  digit을 한 글자도 안 읽으므로 1->l 류 오인식과 직교한다.
- (idea 1) 읽히는 번호만 골라 depth 그룹 내 시퀀스(단조 증가) 합의로 geometry를
  검증/보정한다(gap 복원, orphan 재배치). 안 읽히는 번호는 건드리지 않는다.
- 번호가 없는 책(한국어 OCR)은 들여쓰기 컬럼이 1개로 붕괴 -> height tier fallback ->
  021과 동일 동작(평탄 유지). 즉 회귀 가드를 설계로 보존한다.

설계(세 arm 비교, 전부 결정론·LLM 미사용으로 계층 메커니즘만 격리)
- Arm A : 021 height-only tier->level baseline.
- Arm B1: geometry only(title_x 컬럼, 단일 컬럼이면 height fallback).
- Arm B2: B1 + 시퀀스 합의 보정(idea 1).

평가(023의 자기비판 반영)
- relative_depth_agreement: bookmark를 fuzzy 매칭한 뒤 읽는 순서 인접 쌍의 깊이 전이
  부호(깊어짐/같음/얕아짐)가 예측과 bookmark에서 일치하는 비율. 절대 level 편향 회피.
- 참고로 023식 절대 level weakref도 병기한다.

범위: 계층(depth)만. printed_page/항목분리/LLM 제목복원은 다음 라운드.

출력: experiments/outputs/024_toc_geometry_sequence_hierarchy/
실행: uv run python experiments/024_toc_geometry_sequence_hierarchy.py
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
from rapidfuzz import fuzz, process

from pdfbooktree.models import TocItem
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, title_has_letter
from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "024_toc_geometry_sequence_hierarchy"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "024_toc_geometry_sequence_hierarchy"

TARGET_IDS = [
    "john_hull",
    "luenberger_investment_science",
    "shreve_binomial",
    "algorithms_to_live_by",
    "algorithm_nine",
]
BOOKMARKED_IDS = {"john_hull", "luenberger_investment_science", "shreve_binomial"}

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_TITLE_WORDS = {
    "목차",
    "목 차",
    "차례",
    "contents",
    "contents in brief",
    "brief contents",
    "table of contents",
}
# 거터에 '번호 슬롯'이 있는지 판정용(값은 안 읽고 존재만 본다).
_DIGITISH = re.compile(r"[0-9lI|]")
# 거터/제목 끝 인쇄 페이지 번호 후보를 읽을 때만 쓰는 lenient 정수 추출.
_INT_RE = re.compile(r"\d+")


def is_content_span(text: str) -> bool:
    """제목 글자(한글/라틴 2자 이상)를 담은 span인지 판정한다."""

    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def is_title_word(text: str) -> bool:
    """목차 page 머리말 단독 줄인지 판정한다."""

    return normalize_for_match(text) in _TITLE_WORDS


# ---------------------------------------------------------------------------
# 1단계: 줄 신호 추출 (숫자 span을 버리지 않고 거터/제목을 분리)
# ---------------------------------------------------------------------------
def extract_toc_lines(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    """TOC page들에서 줄별 거터/제목 기하 신호를 뽑는다.

    각 줄에서 '첫 글자 span' 이전을 거터로 보고, title_x(제목 시작 x), gutter_x(줄 첫
    span x), sep_count(거터 구분자 수), has_gutter(번호 슬롯 존재), height(대표 글자
    높이), text(제목), leading_raw(거터 원문), trailing_page(끝 페이지번호)를 담는다.
    """

    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pno in toc_pages:
            page = document.load_page(pno - 1)
            for block in page.get_text("dict")["blocks"]:
                for raw_line in block.get("lines", []):
                    spans = [s for s in raw_line["spans"] if s["text"].strip()]
                    if not spans:
                        continue
                    spans.sort(key=lambda s: s["bbox"][0])

                    first_letter_idx = next(
                        (i for i, s in enumerate(spans) if is_content_span(s["text"])),
                        None,
                    )
                    if first_letter_idx is None:
                        continue  # 글자 없는 줄(순수 숫자/장식)은 항목이 아니다.

                    letter_spans = spans[first_letter_idx:]
                    lead_spans = spans[:first_letter_idx]

                    heights = [
                        round(s["bbox"][3] - s["bbox"][1], 2)
                        for s in letter_spans
                        if is_content_span(s["text"])
                    ]
                    title = normalize_text(
                        " ".join(s["text"].strip() for s in letter_spans)
                    )
                    leading_raw = " ".join(s["text"].strip() for s in lead_spans)

                    title_x = float(spans[first_letter_idx]["bbox"][0])
                    gutter_x = float(spans[0]["bbox"][0])
                    sep_count = leading_raw.count(".") + leading_raw.count("·")
                    has_gutter = bool(lead_spans) and bool(_DIGITISH.search(leading_raw))

                    # 끝쪽 인쇄 페이지 번호(가독성용; 채점 안 함).
                    trailing_page = None
                    tail_nums = _INT_RE.findall(title)
                    if tail_nums:
                        trailing_page = int(tail_nums[-1])

                    lines.append(
                        {
                            "pdf_page": pno,
                            "text": title,
                            "height": max(heights),
                            "title_x": round(title_x, 2),
                            "gutter_x": round(gutter_x, 2),
                            "sep_count": sep_count,
                            "has_gutter": has_gutter,
                            "leading_raw": leading_raw,
                            "trailing_page": trailing_page,
                        }
                    )
    return lines


# ---------------------------------------------------------------------------
# 1D KDE 클러스터 (height/title_x 공용)
# ---------------------------------------------------------------------------
def cluster_cut_points(values: list[float]) -> list[float]:
    """1D 값 분포의 봉우리 사이 골짜기를 경계로 찾는다(numpy gaussian KDE)."""

    if not values:
        return []
    arr = np.asarray(values, dtype=float)
    if np.unique(arr).size <= 1:
        return []
    std = float(np.std(arr, ddof=1))
    if std <= 0.0:
        return []
    bandwidth = 1.06 * std * (len(arr) ** -0.2)
    if bandwidth <= 0.0 or not math.isfinite(bandwidth):
        return []
    grid = np.linspace(float(arr.min()) - 1.0, float(arr.max()) + 1.0, 1024)
    z = (grid[:, None] - arr[None, :]) / bandwidth
    density = np.exp(-0.5 * z * z).sum(axis=1)
    peak_idx = [
        i for i in range(1, len(density) - 1)
        if density[i - 1] < density[i] > density[i + 1]
    ]
    if not peak_idx:
        return []
    valley_idx = [
        i for i in range(1, len(density) - 1)
        if density[i - 1] > density[i] < density[i + 1]
    ]
    peaks = [float(grid[i]) for i in peak_idx]
    cuts = [
        float(grid[i])
        for i in valley_idx
        if min(peaks) < float(grid[i]) < max(peaks)
    ]
    return sorted(cuts)


def band_high_first(value: float, cuts: list[float]) -> int:
    """큰 값이 1번(상위)인 band 인덱스. height tier용."""

    band = 1
    for cut in sorted(cuts, reverse=True):
        if value >= cut:
            return band
        band += 1
    return band


def band_low_first(value: float, cuts: list[float]) -> int:
    """작은 값이 1번(상위)인 band 인덱스. title_x 들여쓰기 컬럼용."""

    band = 1
    for cut in sorted(cuts):
        if value < cut:
            return band
        band += 1
    return band


# ---------------------------------------------------------------------------
# Arm A: height-only tier->level baseline (021)
# ---------------------------------------------------------------------------
def depth_height_only(lines: list[dict[str, Any]]) -> dict[int, int]:
    """줄 인덱스->level. height tier를 content tier 순으로 1..n 매핑."""

    cuts = cluster_cut_points([ln["height"] for ln in lines])
    content_tiers = sorted(
        {
            band_high_first(ln["height"], cuts)
            for ln in lines
            if not is_title_word(ln["text"])
        }
    )
    tier_to_level = {tier: idx + 1 for idx, tier in enumerate(content_tiers)}
    max_level = max(tier_to_level.values()) if tier_to_level else 1
    out: dict[int, int] = {}
    for i, ln in enumerate(lines):
        tier = band_high_first(ln["height"], cuts)
        out[i] = tier_to_level.get(tier, max_level)
    return out


# ---------------------------------------------------------------------------
# Arm B1: geometry depth (title_x 컬럼; 단일 컬럼이면 height fallback)
# ---------------------------------------------------------------------------
def depth_geometry(lines: list[dict[str, Any]]) -> tuple[dict[int, int], str]:
    """줄 인덱스->level과 사용한 regime("indent"/"height")을 반환한다.

    제목 들여쓰기(title_x)를 컬럼으로 클러스터해 깊이를 만든다. 컬럼이 1개로 붕괴하는
    평탄/번호없는 책은 height tier로 fallback해 021 동작(평탄 유지)을 보존한다.
    번호 거터 깊이(sep_count)는 같은 들여쓰기 컬럼 안에서 보조 세분에만 쓴다.
    """

    content = [ln for ln in lines if not is_title_word(ln["text"])]
    x_cuts = cluster_cut_points([ln["title_x"] for ln in content])

    if not x_cuts:
        return depth_height_only(lines), "height"

    # 들여쓰기 컬럼(작은 x = 상위) + 같은 컬럼 내 거터 구분자 깊이로 세분.
    keys: dict[int, tuple[int, int]] = {}
    for i, ln in enumerate(lines):
        col = band_low_first(ln["title_x"], x_cuts)
        sub = ln["sep_count"] if ln["has_gutter"] else 0
        keys[i] = (col, sub)
    # content 줄에 실재하는 (col, sub) 조합만 모아 1..n level로 정규화.
    distinct = sorted(
        {keys[i] for i, ln in enumerate(lines) if not is_title_word(ln["text"])}
    )
    key_to_level = {key: idx + 1 for idx, key in enumerate(distinct)}
    max_level = max(key_to_level.values()) if key_to_level else 1
    out = {i: key_to_level.get(keys[i], max_level) for i in range(len(lines))}
    return out, "indent"


# ---------------------------------------------------------------------------
# Arm B2: 시퀀스 합의 보정 (idea 1) — 읽히는 번호만 사용
# ---------------------------------------------------------------------------
def read_leading_int(leading_raw: str) -> int | None:
    """거터에서 마지막 정수(지역 카운터)를 lenient하게 읽는다. 없으면 None."""

    nums = _INT_RE.findall(leading_raw)
    if not nums:
        return None
    return int(nums[-1])


def reconcile_sequence(
    lines: list[dict[str, Any]],
    base_depth: dict[int, int],
) -> tuple[dict[int, int], list[dict[str, Any]]]:
    """geometry depth를 읽히는 번호 시퀀스로 검증/보정한다.

    보정 규칙(결정론, 읽히는 번호만):
    - orphan 재배치: 어떤 줄의 번호가 자기 depth 시퀀스를 깨고, 인접한 한 단계 위
      depth의 직전 카운터+1과 정확히 맞으면 그 위 depth로 옮긴다.
    - gap 복원: 같은 depth에서 직전 카운터 n 다음 줄이 번호 미해독인데 그 다음 해독
      줄이 n+2면, 가운데 줄을 같은 depth로 확정(geometry가 흔든 멤버십 회복).
    번호가 전혀 안 읽히는 책은 변경이 0건이라 geometry 결과가 그대로 남는다.
    """

    depth = dict(base_depth)
    changes: list[dict[str, Any]] = []
    # depth별 직전 카운터(부모 변경 시 리셋은 단순화를 위해 생략, 단조성만 본다).
    last_counter: dict[int, int] = {}

    order = sorted(range(len(lines)), key=lambda i: (lines[i]["pdf_page"], i))
    for pos, i in enumerate(order):
        if is_title_word(lines[i]["text"]):
            continue
        d = depth[i]
        num = read_leading_int(lines[i]["leading_raw"]) if lines[i]["has_gutter"] else None
        if num is None:
            # gap 복원: 직전(같은 depth, 번호 n) ... [현재 미해독] ... 다음(번호 n+2) 패턴.
            prev_n = last_counter.get(d)
            nxt = _next_legible(order, pos, lines, depth, d)
            if prev_n is not None and nxt is not None and nxt == prev_n + 2:
                changes.append(
                    {"idx": i, "rule": "gap_fill", "depth": d, "filled": prev_n + 1}
                )
                last_counter[d] = prev_n + 1
            continue

        expected = last_counter.get(d)
        if expected is not None and num == expected + 1:
            last_counter[d] = num
            continue

        # 자기 depth를 깸 -> 한 단계 위 depth 시퀀스에 맞는지 확인.
        up = d - 1
        if up >= 1 and last_counter.get(up) is not None and num == last_counter[up] + 1:
            changes.append(
                {"idx": i, "rule": "orphan_up", "from": d, "to": up, "num": num}
            )
            depth[i] = up
            last_counter[up] = num
            continue

        # 그 외에는 현재 depth의 카운터를 num으로 갱신(새 부모/리셋 등 허용).
        last_counter[d] = num

    return depth, changes


def _next_legible(
    order: list[int],
    pos: int,
    lines: list[dict[str, Any]],
    depth: dict[int, int],
    d: int,
) -> int | None:
    """order에서 pos 이후, 같은 depth d의 다음 '번호 해독 가능' 줄의 카운터."""

    for j in order[pos + 1 :]:
        if is_title_word(lines[j]["text"]) or depth[j] != d:
            continue
        if lines[j]["has_gutter"]:
            return read_leading_int(lines[j]["leading_raw"])
        return None
    return None


# ---------------------------------------------------------------------------
# 줄 depth -> TocItem
# ---------------------------------------------------------------------------
def to_items(lines: list[dict[str, Any]], depth: dict[int, int]) -> list[TocItem]:
    items: list[TocItem] = []
    for i, ln in enumerate(lines):
        if is_title_word(ln["text"]):
            continue
        if len(normalize_for_match(ln["text"]).replace(" ", "")) < 2:
            continue
        items.append(
            TocItem(
                title=ln["text"],
                level=depth[i],
                printed_page=ln["trailing_page"],
                raw_text=ln["text"],
                source_pdf_page=ln["pdf_page"],
                confidence=0.8,
            )
        )
    return normalize_levels_to_one(items)


def normalize_levels_to_one(items: list[TocItem]) -> list[TocItem]:
    if not items:
        return items
    shift = min(it.level for it in items) - 1
    if shift <= 0:
        return items
    return [
        TocItem(
            title=it.title,
            level=it.level - shift,
            printed_page=it.printed_page,
            raw_text=it.raw_text,
            source_pdf_page=it.source_pdf_page,
            confidence=it.confidence,
        )
        for it in items
    ]


# ---------------------------------------------------------------------------
# bookmark weak-ref 지표 (절대 level + 상대 깊이 전이)
# ---------------------------------------------------------------------------
def normalize_bookmark_levels(bookmarks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [bm for bm in bookmarks if title_has_letter(bm["title"])]
    if not kept:
        return []
    min_level = min(bm["level"] for bm in kept)
    return [
        {"title": bm["title"], "level": bm["level"] - min_level + 1, "order": bm["order"]}
        for bm in kept
    ]


def match_items_to_bookmarks(
    items: list[TocItem], ref: list[dict[str, Any]], score_cutoff: float = 88.0
) -> list[tuple[dict[str, Any], TocItem]]:
    """각 bookmark를 최선의 추출 항목과 fuzzy 매칭한 (bookmark, item) 쌍 목록."""

    item_norms = [normalize_for_match(it.title) for it in items]
    index_by_norm: dict[str, int] = {}
    choices: list[str] = []
    for idx, norm in enumerate(item_norms):
        if norm and norm not in index_by_norm:
            index_by_norm[norm] = idx
            choices.append(norm)

    pairs: list[tuple[dict[str, Any], TocItem]] = []
    for bm in ref:
        bm_norm = normalize_for_match(bm["title"])
        if not bm_norm:
            continue
        result = process.extractOne(
            bm_norm, choices, scorer=fuzz.token_set_ratio, score_cutoff=score_cutoff
        )
        if result is None:
            continue
        pairs.append((bm, items[index_by_norm[result[0]]]))
    return pairs


def weakref_metrics(
    items: list[TocItem], bookmarks: list[dict[str, Any]]
) -> dict[str, Any]:
    """절대 level 일치율 + 상대 깊이 전이 일치율을 함께 잰다."""

    ref = normalize_bookmark_levels(bookmarks)
    if not ref or not items:
        return {"bookmark_letter_count": len(ref), "matched": 0}

    pairs = match_items_to_bookmarks(items, ref)
    matched = len(pairs)
    abs_agree = sum(1 for bm, it in pairs if bm["level"] == it.level)

    # 상대 깊이 전이: bookmark order 순으로 인접 매칭 쌍의 깊이 변화 부호 비교.
    pairs_sorted = sorted(pairs, key=lambda p: p[0]["order"])
    trans_total = 0
    trans_agree = 0
    for (bm_a, it_a), (bm_b, it_b) in zip(pairs_sorted, pairs_sorted[1:]):
        trans_total += 1
        if _sign(bm_b["level"] - bm_a["level"]) == _sign(it_b.level - it_a.level):
            trans_agree += 1

    return {
        "bookmark_letter_count": len(ref),
        "matched": matched,
        "match_rate": round(matched / len(ref), 4) if ref else 0.0,
        "abs_level_agreement": round(abs_agree / matched, 4) if matched else None,
        "rel_depth_agreement": round(trans_agree / trans_total, 4) if trans_total else None,
        "transitions": trans_total,
    }


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


# ---------------------------------------------------------------------------
# 트리/지표/실행
# ---------------------------------------------------------------------------
def render_tree(items: list[TocItem]) -> list[str]:
    out: list[str] = []
    for it in items:
        indent = "    " * max(it.level - 1, 0)
        page = it.printed_page if it.printed_page is not None else "-"
        out.append(f"{indent}[{page}] L{it.level} {it.title}")
    return out


def hierarchy_metrics(items: list[TocItem]) -> dict[str, Any]:
    levels = [it.level for it in items]
    return {
        "item_count": len(items),
        "level_distribution": {str(k): v for k, v in sorted(Counter(levels).items())},
        "distinct_levels": len(set(levels)),
        "starts_at_level_1": bool(levels) and min(levels) == 1,
    }


def contents_segment_pages(label: dict[str, Any]) -> list[int]:
    pages: list[int] = []
    for seg in label.get("toc_segments") or []:
        if seg.get("kind") == "contents":
            pages.extend(range(seg["start_page"], seg["end_page"] + 1))
    if not pages:
        pages = list(label["toc_pages"])
    return sorted(dict.fromkeys(pages))


def _case_id(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_")[:80]


def run_book(label: dict[str, Any]) -> dict[str, Any]:
    pdf_path = ROOT_DIR / label["input_pdf"]
    case_id = label["id"]
    toc_pages = contents_segment_pages(label)
    record: dict[str, Any] = {
        "id": case_id,
        "input_pdf": label["input_pdf"],
        "contents_pages": toc_pages,
    }
    if not pdf_path.exists():
        record["status"] = "missing_pdf"
        return record

    lines = extract_toc_lines(pdf_path, toc_pages)
    if not lines:
        record["status"] = "no_lines"
        return record

    depth_a = depth_height_only(lines)
    depth_b1, regime = depth_geometry(lines)
    depth_b2, changes = reconcile_sequence(lines, depth_b1)

    items_a = to_items(lines, depth_a)
    items_b1 = to_items(lines, depth_b1)
    items_b2 = to_items(lines, depth_b2)

    cid = _case_id(case_id)
    (OUTPUT_DIR / f"{cid}_lines.json").write_text(
        json.dumps(lines, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name, items in [("A", items_a), ("B1", items_b1), ("B2", items_b2)]:
        (OUTPUT_DIR / f"{cid}_tree_{name}.txt").write_text(
            "\n".join(render_tree(items)) + "\n", encoding="utf-8"
        )
    (OUTPUT_DIR / f"{cid}_debug.json").write_text(
        json.dumps(
            {"regime": regime, "reconcile_changes": changes}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )

    record["status"] = "ok"
    record["regime"] = regime
    record["gutter_line_ratio"] = round(
        sum(1 for ln in lines if ln["has_gutter"]) / len(lines), 3
    )
    record["reconcile_change_count"] = len(changes)
    record["arm_a"] = hierarchy_metrics(items_a)
    record["arm_b1"] = hierarchy_metrics(items_b1)
    record["arm_b2"] = hierarchy_metrics(items_b2)
    record["b2_tree_preview"] = render_tree(items_b2)[:24]

    if case_id in BOOKMARKED_IDS:
        bookmarks = extract_existing_bookmarks(pdf_path)
        record["weakref_a"] = weakref_metrics(items_a, bookmarks)
        record["weakref_b1"] = weakref_metrics(items_b1, bookmarks)
        record["weakref_b2"] = weakref_metrics(items_b2, bookmarks)

    return record


def build_finding(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        piece = (
            f"{r['id']}(regime={r['regime']},gutter={r['gutter_line_ratio']}): "
            f"A={r['arm_a']['level_distribution']} "
            f"B1={r['arm_b1']['level_distribution']} "
            f"B2={r['arm_b2']['level_distribution']}(changes={r['reconcile_change_count']})"
        )
        if "weakref_b2" in r:
            piece += (
                f". rel_depth A={r['weakref_a'].get('rel_depth_agreement')}"
                f"/B1={r['weakref_b1'].get('rel_depth_agreement')}"
                f"/B2={r['weakref_b2'].get('rel_depth_agreement')}"
                f" (abs A={r['weakref_a'].get('abs_level_agreement')}"
                f"/B2={r['weakref_b2'].get('abs_level_agreement')})"
            )
        parts.append(piece)
    return " | ".join(parts)


def record_experiment(summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "번호의 값을 안 읽고 거터 geometry(title_x 들여쓰기 컬럼 + 구분자 깊이)로 "
            "계층 skeleton을 만들고, 읽히는 번호만 시퀀스 합의로 보정한다. height-only "
            "baseline(A), geometry(B1), geometry+sequence(B2)를 비교하고 bookmark "
            "weak ref로 상대 깊이 전이/절대 level 일치율을 잰다."
        ),
        "inputs": [lab["input_pdf"] for lab in summary["_labels_used"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "experiments\\labels\\answer_toc_ranges_manual.json",
        "model": "none(deterministic)",
        "finding": summary["finding"],
        "ran_at": summary["ran_at"],
    }
    experiments = data.get("experiments", data) if isinstance(data, dict) else data
    experiments = [e for e in experiments if e.get("id") != EXPERIMENT_ID]
    experiments.append(entry)
    if isinstance(data, dict):
        data["experiments"] = experiments
    else:
        data = experiments
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = {
        lab["id"]: lab
        for lab in json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]
    }
    used_labels = [labels[i] for i in TARGET_IDS if i in labels]
    results = [run_book(lab) for lab in used_labels]

    finding = build_finding(results)
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "scope": "hierarchy_only_deterministic",
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "finding": finding,
        "results": results,
        "_labels_used": used_labels,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(
            {k: v for k, v in summary.items() if k != "_labels_used"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    record_experiment(summary)

    print("=== exp 024: 거터 geometry + 시퀀스 합의 (A vs B1 vs B2) ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']}: {r.get('status')}")
            continue
        print(
            f"\n- {r['id']} (pages={r['contents_pages']}, regime={r['regime']}, "
            f"gutter={r['gutter_line_ratio']})"
        )
        print(f"    A : {r['arm_a']['level_distribution']}")
        print(f"    B1: {r['arm_b1']['level_distribution']}")
        print(
            f"    B2: {r['arm_b2']['level_distribution']} "
            f"(reconcile changes={r['reconcile_change_count']})"
        )
        if "weakref_b2" in r:
            print(
                f"    rel_depth  A={r['weakref_a'].get('rel_depth_agreement')} "
                f"B1={r['weakref_b1'].get('rel_depth_agreement')} "
                f"B2={r['weakref_b2'].get('rel_depth_agreement')}"
            )
            print(
                f"    abs_level  A={r['weakref_a'].get('abs_level_agreement')} "
                f"B2={r['weakref_b2'].get('abs_level_agreement')} "
                f"(matched {r['weakref_b2'].get('matched')}/"
                f"{r['weakref_b2'].get('bookmark_letter_count')})"
            )
        print("    B2 tree preview:")
        for line in r["b2_tree_preview"][:14]:
            print(f"      {line}")
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
