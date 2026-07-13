"""experiment 026: indentation 컬럼 + font tier 결합 계층(어느 쪽도 레벨 수를 cap 안 함).

배경/정정
- experiment 025는 레벨 수를 height tier 개수로 못 박았다. 그러나 영어책은 TOC 글씨가
  균일(tier=1)이고 계층이 '들여쓰기'에 있다. tier로 강제하면 영어 다단계 책이 평탄해진다.
  (사용자 정정) shreve는 1/1.1/1.5.1로 실제 3단계인데 tier=1이라 025에서 강제 평탄됐다.

데이터로 확인한 두 계열(상보적)
- 영어(shreve/hull): font 균일, title_x 들여쓰기가 깨끗한 다중 컬럼(shreve 106/131/166,
  hull 72/97/123/152/177)에 계층이 있다.
- 한국어 OCR(algorithms): font가 2 tier(항목 8~9 vs 장 제목 24~30), 들여쓰기는 한 덩어리.

024가 title_x로 실패한 원인은 신호가 아니라 clustering: wrapped 줄(140/248)이 가짜 컬럼을
만들고 OCR jitter(94~107)를 못 뭉쳤다. -> gap 기반 + 최소 support로 robust하게 묶는다.

설계(결정론, LLM 미사용)
- Arm H : height tier만 (021 baseline).
- Arm C : indentation 컬럼만.
- Arm HC: (컬럼, tier) 사전식 dense-rank. 컬럼이 갈리면 컬럼이, 컬럼이 한 덩어리면 tier가
  깊이를 준다. **어느 신호도 레벨 수를 cap 하지 않는다.**

평가(024/025 계승): rel_depth_agreement(주력) + abs_level + bookmark weakref, level 분포.

범위: 계층(depth)만. 항목 분리/제목 교정(025 Call3)은 검증 후 결합.

출력: experiments/outputs/026_toc_indent_font_levels/
실행: uv run python experiments/026_toc_indent_font_levels.py
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
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "026_toc_indent_font_levels"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "026_toc_indent_font_levels"

TARGET_IDS = [
    "john_hull",
    "luenberger_investment_science",
    "shreve_binomial",
    "algorithms_to_live_by",
    "algorithm_nine",
]
BOOKMARKED_IDS = {"john_hull", "luenberger_investment_science", "shreve_binomial"}

# 컬럼 gap 임계값(page 폭 비율). OCR jitter(<~1.5%)는 뭉치고 실제 들여쓰기 step(~4%)은
# 가르도록 3%로 둔다. 컬럼당 최소 줄 수 미만은 singleton 잡음으로 보고 인접 컬럼에 흡수.
COLUMN_GAP_FRAC = 0.03
COLUMN_MIN_SUPPORT = 2

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


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def is_title_word(text: str) -> bool:
    return normalize_for_match(text) in _TITLE_WORDS


# ---------------------------------------------------------------------------
# 줄 신호 추출 (title_x + height)
# ---------------------------------------------------------------------------
def extract_toc_lines(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pno in toc_pages:
            page = document.load_page(pno - 1)
            page_width = float(page.rect.width) or 1.0
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    heights: list[float] = []
                    x_lefts: list[float] = []
                    parts: list[str] = []
                    for span in line["spans"]:
                        text = span["text"]
                        if not text.strip():
                            continue
                        parts.append(text.strip())
                        if is_content_span(text):
                            heights.append(round(span["bbox"][3] - span["bbox"][1], 2))
                            x_lefts.append(float(span["bbox"][0]))
                    if not heights:
                        continue
                    trailing = re.findall(r"\d+", " ".join(parts))
                    lines.append(
                        {
                            "pdf_page": pno,
                            "text": normalize_text(" ".join(parts)),
                            "height": max(heights),
                            "title_x": round(min(x_lefts), 2),
                            "page_width": page_width,
                            "trailing_page": int(trailing[-1]) if trailing else None,
                        }
                    )
    return lines


# ---------------------------------------------------------------------------
# height tier (021)
# ---------------------------------------------------------------------------
def cluster_cut_points(values: list[float]) -> list[float]:
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
    return sorted(
        float(grid[i]) for i in valley_idx if min(peaks) < float(grid[i]) < max(peaks)
    )


def assign_tier(height: float, cuts: list[float]) -> int:
    """height tier(큰 글씨=1). content tier를 1..n으로 정규화한 값을 반환한다."""

    tier = 1
    for cut in sorted(cuts, reverse=True):
        if height >= cut:
            return tier
        tier += 1
    return tier


# ---------------------------------------------------------------------------
# indentation 컬럼 (robust gap 클러스터)
# ---------------------------------------------------------------------------
def build_columns(lines: list[dict[str, Any]]) -> list[float]:
    """content 줄 title_x를 gap 기반으로 묶어 컬럼 center 목록(오름차순)을 만든다.

    consecutive 정렬값 gap이 page 폭의 COLUMN_GAP_FRAC를 넘으면 분리한다. 줄 수가
    COLUMN_MIN_SUPPORT 미만인 cluster는 잡음(wrapped/singleton)으로 보고 버린다(남은
    컬럼에 흡수). 컬럼이 0개면 빈 목록(=평탄, height fallback 신호).
    """

    content = [ln for ln in lines if not is_title_word(ln["text"])]
    if not content:
        return []
    page_width = content[0]["page_width"]
    gap = page_width * COLUMN_GAP_FRAC

    xs = sorted(ln["title_x"] for ln in content)
    clusters: list[list[float]] = [[xs[0]]]
    for v in xs[1:]:
        if v - clusters[-1][-1] <= gap:
            clusters[-1].append(v)
        else:
            clusters.append([v])

    centers = [
        float(np.mean(c)) for c in clusters if len(c) >= COLUMN_MIN_SUPPORT
    ]
    return sorted(centers)


def assign_column(title_x: float, centers: list[float]) -> int:
    """title_x를 가장 가까운 컬럼 center에 배정해 컬럼 rank(왼쪽=1)를 준다."""

    if not centers:
        return 1
    nearest = min(range(len(centers)), key=lambda i: abs(title_x - centers[i]))
    return nearest + 1


# ---------------------------------------------------------------------------
# arm별 depth 부여
# ---------------------------------------------------------------------------
def _dense_rank(keys: list[tuple[int, ...]]) -> dict[tuple[int, ...], int]:
    distinct = sorted(set(keys))
    return {key: idx + 1 for idx, key in enumerate(distinct)}


def depths_three_arms(
    lines: list[dict[str, Any]],
) -> tuple[dict[int, int], dict[int, int], dict[int, int], dict[str, Any]]:
    """Arm H(tier만)/C(컬럼만)/HC(결합) depth를 한 번에 만든다."""

    cuts = cluster_cut_points([ln["height"] for ln in lines])
    centers = build_columns(lines)

    content_idx = [i for i, ln in enumerate(lines) if not is_title_word(ln["text"])]
    tier_of = {i: assign_tier(lines[i]["height"], cuts) for i in range(len(lines))}
    col_of = {i: assign_column(lines[i]["title_x"], centers) for i in range(len(lines))}

    # 각 arm의 key를 content 줄에 실재하는 것만으로 dense-rank.
    tier_rank = _dense_rank([(tier_of[i],) for i in content_idx])
    col_rank = _dense_rank([(col_of[i],) for i in content_idx])
    hc_rank = _dense_rank([(col_of[i], tier_of[i]) for i in content_idx])

    max_h = max(tier_rank.values(), default=1)
    max_c = max(col_rank.values(), default=1)
    max_hc = max(hc_rank.values(), default=1)

    depth_h = {i: tier_rank.get((tier_of[i],), max_h) for i in range(len(lines))}
    depth_c = {i: col_rank.get((col_of[i],), max_c) for i in range(len(lines))}
    depth_hc = {
        i: hc_rank.get((col_of[i], tier_of[i]), max_hc) for i in range(len(lines))
    }

    debug = {
        "height_cuts": [round(c, 2) for c in cuts],
        "column_centers": [round(c, 1) for c in centers],
        "n_levels_H": max_h,
        "n_levels_C": max_c,
        "n_levels_HC": max_hc,
    }
    return depth_h, depth_c, depth_hc, debug


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
# bookmark weak-ref 지표 (024/025 계승)
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


def match_pairs(
    items: list[TocItem], ref: list[dict[str, Any]], score_cutoff: float = 88.0
) -> list[tuple[dict[str, Any], TocItem]]:
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


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def weakref_metrics(
    items: list[TocItem], bookmarks: list[dict[str, Any]]
) -> dict[str, Any]:
    ref = normalize_bookmark_levels(bookmarks)
    if not ref or not items:
        return {"bookmark_letter_count": len(ref), "matched": 0}
    pairs = match_pairs(items, ref)
    matched = len(pairs)
    abs_agree = sum(1 for bm, it in pairs if bm["level"] == it.level)
    pairs_sorted = sorted(pairs, key=lambda p: p[0]["order"])
    trans_total, trans_agree = 0, 0
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
    }


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

    depth_h, depth_c, depth_hc, debug = depths_three_arms(lines)
    items_h = to_items(lines, depth_h)
    items_c = to_items(lines, depth_c)
    items_hc = to_items(lines, depth_hc)

    cid = _case_id(case_id)
    (OUTPUT_DIR / f"{cid}_lines.json").write_text(
        json.dumps(lines, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / f"{cid}_debug.json").write_text(
        json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name, items in [("H", items_h), ("C", items_c), ("HC", items_hc)]:
        (OUTPUT_DIR / f"{cid}_tree_{name}.txt").write_text(
            "\n".join(render_tree(items)) + "\n", encoding="utf-8"
        )

    record["status"] = "ok"
    record["debug"] = debug
    record["arm_h"] = hierarchy_metrics(items_h)
    record["arm_c"] = hierarchy_metrics(items_c)
    record["arm_hc"] = hierarchy_metrics(items_hc)
    record["hc_tree_preview"] = render_tree(items_hc)[:24]

    if case_id in BOOKMARKED_IDS:
        bookmarks = extract_existing_bookmarks(pdf_path)
        record["weakref_h"] = weakref_metrics(items_h, bookmarks)
        record["weakref_c"] = weakref_metrics(items_c, bookmarks)
        record["weakref_hc"] = weakref_metrics(items_hc, bookmarks)
    return record


def build_finding(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        d = r["debug"]
        piece = (
            f"{r['id']}(cols={d['column_centers']},nH={d['n_levels_H']},"
            f"nC={d['n_levels_C']},nHC={d['n_levels_HC']}): "
            f"H={r['arm_h']['level_distribution']} "
            f"C={r['arm_c']['level_distribution']} "
            f"HC={r['arm_hc']['level_distribution']}"
        )
        if "weakref_hc" in r:
            piece += (
                f". rel_depth H={r['weakref_h'].get('rel_depth_agreement')}"
                f"/C={r['weakref_c'].get('rel_depth_agreement')}"
                f"/HC={r['weakref_hc'].get('rel_depth_agreement')}"
                f" abs H={r['weakref_h'].get('abs_level_agreement')}"
                f"/HC={r['weakref_hc'].get('abs_level_agreement')}"
            )
        parts.append(piece)
    return " | ".join(parts)


def record_experiment(summary: dict[str, Any]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "영어책은 들여쓰기, 한국어책은 font가 계층을 진다는 관찰에 따라 indentation 컬럼"
            "(robust gap 클러스터)과 height tier를 결합하되 어느 쪽도 레벨 수를 cap 하지 "
            "않는다. Arm H(tier만)/C(컬럼만)/HC(결합)를 비교하고 bookmark weak ref로 "
            "rel_depth/abs level 일치율을 잰다. 결정론(LLM 미사용)."
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
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    record_experiment(summary)

    print("=== exp 026: indentation 컬럼 + font tier 결합 (H / C / HC) ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']}: {r.get('status')}")
            continue
        d = r["debug"]
        print(
            f"\n- {r['id']} cols={d['column_centers']} "
            f"(nH={d['n_levels_H']}, nC={d['n_levels_C']}, nHC={d['n_levels_HC']})"
        )
        print(f"    H : {r['arm_h']['level_distribution']}")
        print(f"    C : {r['arm_c']['level_distribution']}")
        print(f"    HC: {r['arm_hc']['level_distribution']}")
        if "weakref_hc" in r:
            print(
                f"    rel_depth H={r['weakref_h'].get('rel_depth_agreement')} "
                f"C={r['weakref_c'].get('rel_depth_agreement')} "
                f"HC={r['weakref_hc'].get('rel_depth_agreement')}"
            )
            print(
                f"    abs_level H={r['weakref_h'].get('abs_level_agreement')} "
                f"HC={r['weakref_hc'].get('abs_level_agreement')} "
                f"(matched {r['weakref_hc'].get('matched')}/"
                f"{r['weakref_hc'].get('bookmark_letter_count')})"
            )
        print("    HC tree preview:")
        for line in r["hc_tree_preview"][:14]:
            print(f"      {line}")
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
