"""experiment 028: height+indent+is_bold+font_type 멀티피처 클러스터로 계층 결정.

배경
- experiment 027에서 'LLM이 계층 결정'은 결정론(026 HC)보다 전권 나빴다(한국어 역전 등).
  -> 계층은 코드가 결정론적으로 소유한다.
- 026 HC(height tier x indent 컬럼)는 shreve를 돌파(0.14->0.84)했지만 luenberger를 0복원
  했다. 원인: luenberger는 글씨 '높이'가 균일하고 들여쓰기가 스캔 노이즈라 두 신호가 죽는다.
  그러나 글꼴/굵기는 계층을 담고 있었다(Chapter=Helvetica-Bold, Section=Times, Subsection=
  Helvetica). 이는 lexical이 아니라 'font' 신호다.

아이디어(사용자)
- height, indent, is_bold, font_type 네 feature를 한꺼번에 넣어 클러스터하고, 클러스터를
  계층 레벨로 매핑한다. 어느 한 신호가 죽어도 다른 신호가 깊이를 준다.

구현(결정론)
- 각 줄 feature: height_tier(KDE), indent col(026 robust 컬럼 + 신뢰도 게이트),
  is_bold(flags/폰트명), font_type(글꼴 base family).
- indent 신뢰도 게이트: 컬럼이 노이즈(pooled within-std 큼)면 col=1로 죽인다(luenberger).
  -> 025의 10-bin이 shreve를 뭉갠 문제도, 024의 raw-x 과분할도 피한다.
- 클러스터 = 동일 signature (col, height_tier, is_bold, font_type) 묶음.
- 레벨 = 클러스터를 prominence로 정렬한 dense-rank.
  prominence 우선순위: is_bold 큰 것 -> 평균 height 큰 것 -> col 작은(왼쪽) 것.
  (강조=상위, 큰 글씨=상위, 왼쪽=상위. font_type은 signature를 갈라 같은 height라도 Times/
  Helvetica를 분리하고, 그 순서는 평균 height로 결정됨.)

평가(024~026 계승): rel_depth_agreement + abs_level + bookmark weakref. 026 HC와 비교.
luenberger bookmark는 Part/Chapter까지뿐이라 정답 아님(Part는 Times라 Section과 글꼴이
같아 font만으론 못 가름 -> 육안 검수). 범위: 계층(depth)만.

출력: experiments/outputs/028_toc_multifeature_cluster/
실행: uv run python experiments/028_toc_multifeature_cluster.py
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
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
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "028_toc_multifeature_cluster"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "028_toc_multifeature_cluster"

TARGET_IDS = [
    "john_hull",
    "luenberger_investment_science",
    "shreve_binomial",
    "algorithms_to_live_by",
    "algorithm_nine",
]
BOOKMARKED_IDS = {"john_hull", "luenberger_investment_science", "shreve_binomial"}

COLUMN_GAP_FRAC = 0.03
COLUMN_MIN_SUPPORT = 2
COLUMN_RELIABLE_STD_FRAC = 0.025  # pooled within-std가 page폭의 이 비율보다 크면 컬럼 폐기.

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")
_SUBSET = re.compile(r"^[A-Z]{6}\+")
_TITLE_WORDS = {
    "목차", "목 차", "차례", "contents", "contents in brief",
    "brief contents", "table of contents",
}


def is_content_span(text: str) -> bool:
    s = text.strip()
    return bool(s and (_HANGUL.search(s) or _LATIN2.search(s)))


def is_title_word(text: str) -> bool:
    return normalize_for_match(text) in _TITLE_WORDS


def base_font(name: str) -> str:
    return _SUBSET.sub("", name).split("-")[0].split(",")[0].lower()


def span_is_bold(span: dict[str, Any]) -> bool:
    return bool(span["flags"] & 2**4) or ("bold" in span["font"].lower())


# ---------------------------------------------------------------------------
# 줄 신호 추출 (height + title_x + is_bold + font_type)
# ---------------------------------------------------------------------------
def extract_toc_lines(pdf_path: Path, toc_pages: list[int]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for pno in toc_pages:
            page = document.load_page(pno - 1)
            page_width = float(page.rect.width) or 1.0
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    spans = [s for s in line["spans"] if s["text"].strip()]
                    content_spans = [s for s in spans if is_content_span(s["text"])]
                    if not content_spans:
                        continue
                    content_spans.sort(key=lambda s: s["bbox"][0])
                    head = content_spans[0]  # 제목 시작 span의 글꼴/굵기를 대표로 쓴다.
                    heights = [round(s["bbox"][3] - s["bbox"][1], 2) for s in content_spans]
                    parts = [s["text"].strip() for s in spans]
                    trailing = re.findall(r"\d+", " ".join(parts))
                    lines.append(
                        {
                            "pdf_page": pno,
                            "text": normalize_text(" ".join(parts)),
                            "height": max(heights),
                            "title_x": round(float(head["bbox"][0]), 2),
                            "page_width": page_width,
                            "is_bold": span_is_bold(head),
                            "font_type": base_font(head["font"]),
                            "trailing_page": int(trailing[-1]) if trailing else None,
                        }
                    )
    return lines


# ---------------------------------------------------------------------------
# height tier (KDE)
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
    bw = 1.06 * std * (len(arr) ** -0.2)
    if bw <= 0.0 or not math.isfinite(bw):
        return []
    grid = np.linspace(float(arr.min()) - 1.0, float(arr.max()) + 1.0, 1024)
    z = (grid[:, None] - arr[None, :]) / bw
    density = np.exp(-0.5 * z * z).sum(axis=1)
    peak = [i for i in range(1, len(density) - 1)
            if density[i - 1] < density[i] > density[i + 1]]
    if not peak:
        return []
    valley = [i for i in range(1, len(density) - 1)
              if density[i - 1] > density[i] < density[i + 1]]
    peaks = [float(grid[i]) for i in peak]
    return sorted(float(grid[i]) for i in valley if min(peaks) < float(grid[i]) < max(peaks))


def assign_tier(height: float, cuts: list[float]) -> int:
    tier = 1
    for cut in sorted(cuts, reverse=True):
        if height >= cut:
            return tier
        tier += 1
    return tier


# ---------------------------------------------------------------------------
# indent 컬럼 (robust gap) + 신뢰도 게이트
# ---------------------------------------------------------------------------
def build_columns(lines: list[dict[str, Any]]) -> list[float]:
    content = [ln for ln in lines if not is_title_word(ln["text"])]
    if not content:
        return []
    gap = content[0]["page_width"] * COLUMN_GAP_FRAC
    xs = sorted(ln["title_x"] for ln in content)
    clusters: list[list[float]] = [[xs[0]]]
    for v in xs[1:]:
        if v - clusters[-1][-1] <= gap:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return sorted(float(np.mean(c)) for c in clusters if len(c) >= COLUMN_MIN_SUPPORT)


def columns_reliable(lines: list[dict[str, Any]], centers: list[float]) -> bool:
    """컬럼이 진짜 들여쓰기인지(타이트한지) 판정. 노이즈 스캔이면 False."""

    if len(centers) < 2:
        return False
    content = [ln for ln in lines if not is_title_word(ln["text"])]
    page_width = content[0]["page_width"]
    devs = [ln["title_x"] - min(centers, key=lambda c: abs(ln["title_x"] - c))
            for ln in content]
    pooled_std = float(np.std(devs))
    return pooled_std < COLUMN_RELIABLE_STD_FRAC * page_width


def assign_column(title_x: float, centers: list[float]) -> int:
    if not centers:
        return 1
    return min(range(len(centers)), key=lambda i: abs(title_x - centers[i])) + 1


# ---------------------------------------------------------------------------
# 멀티피처 클러스터 -> 레벨
# ---------------------------------------------------------------------------
def multifeature_levels(
    lines: list[dict[str, Any]],
) -> tuple[dict[int, int], dict[str, Any]]:
    """4 feature signature 클러스터를 prominence로 정렬해 레벨을 부여한다."""

    cuts = cluster_cut_points([ln["height"] for ln in lines])
    centers = build_columns(lines)
    reliable = columns_reliable(lines, centers)
    use_centers = centers if reliable else []

    sig_of: dict[int, tuple] = {}
    for i, ln in enumerate(lines):
        tier = assign_tier(ln["height"], cuts)
        col = assign_column(ln["title_x"], use_centers)
        sig_of[i] = (col, tier, ln["is_bold"], ln["font_type"])

    # content 줄에 실재하는 signature만 모아 prominence로 정렬.
    groups: dict[tuple, list[float]] = defaultdict(list)
    for i, ln in enumerate(lines):
        if is_title_word(ln["text"]):
            continue
        groups[sig_of[i]].append(ln["height"])

    def prominence(sig: tuple) -> tuple:
        col, tier, is_bold, _font = sig
        mean_h = float(np.mean(groups[sig]))
        # 정렬 키(오름차순 정렬 시 상위 레벨이 앞): bold 먼저, height 큰 것 먼저, 왼쪽 먼저.
        return (0 if is_bold else 1, -mean_h, col)

    ordered = sorted(groups.keys(), key=prominence)
    sig_to_level = {sig: idx + 1 for idx, sig in enumerate(ordered)}
    max_level = len(ordered) or 1

    depth = {
        i: sig_to_level.get(sig_of[i], max_level) for i in range(len(lines))
    }
    debug = {
        "height_cuts": [round(c, 2) for c in cuts],
        "column_centers": [round(c, 1) for c in centers],
        "columns_reliable": reliable,
        "n_levels": max_level,
        "clusters": [
            {
                "level": sig_to_level[sig],
                "signature": {"col": sig[0], "htier": sig[1], "bold": sig[2], "font": sig[3]},
                "count": len(groups[sig]),
                "mean_height": round(float(np.mean(groups[sig])), 2),
            }
            for sig in ordered
        ],
    }
    return depth, debug


# ---------------------------------------------------------------------------
# 026 HC baseline (height tier x col)
# ---------------------------------------------------------------------------
def hc_levels(lines: list[dict[str, Any]]) -> dict[int, int]:
    cuts = cluster_cut_points([ln["height"] for ln in lines])
    centers = build_columns(lines)
    content_idx = [i for i, ln in enumerate(lines) if not is_title_word(ln["text"])]
    tier_of = {i: assign_tier(lines[i]["height"], cuts) for i in range(len(lines))}
    col_of = {i: assign_column(lines[i]["title_x"], centers) for i in range(len(lines))}
    keys = sorted({(col_of[i], tier_of[i]) for i in content_idx})
    rank = {k: idx + 1 for idx, k in enumerate(keys)}
    mx = max(rank.values(), default=1)
    return {i: rank.get((col_of[i], tier_of[i]), mx) for i in range(len(lines))}


# ---------------------------------------------------------------------------
# items / weakref / 트리 (024~026 계승)
# ---------------------------------------------------------------------------
def to_items(lines: list[dict[str, Any]], depth: dict[int, int]) -> list[TocItem]:
    items: list[TocItem] = []
    for i, ln in enumerate(lines):
        if is_title_word(ln["text"]):
            continue
        if len(normalize_for_match(ln["text"]).replace(" ", "")) < 2:
            continue
        items.append(
            TocItem(title=ln["text"], level=depth[i], printed_page=ln["trailing_page"],
                    raw_text=ln["text"], source_pdf_page=ln["pdf_page"], confidence=0.8)
        )
    return normalize_levels(items)


def normalize_levels(items: list[TocItem]) -> list[TocItem]:
    if not items:
        return items
    shift = min(it.level for it in items) - 1
    if shift <= 0:
        return items
    return [
        TocItem(title=it.title, level=it.level - shift, printed_page=it.printed_page,
                raw_text=it.raw_text, source_pdf_page=it.source_pdf_page,
                confidence=it.confidence)
        for it in items
    ]


def normalize_bookmark_levels(bms):
    kept = [b for b in bms if title_has_letter(b["title"])]
    if not kept:
        return []
    mn = min(b["level"] for b in kept)
    return [{"title": b["title"], "level": b["level"] - mn + 1, "order": b["order"]} for b in kept]


def _sign(x):
    return (x > 0) - (x < 0)


def weakref_metrics(items, bms):
    ref = normalize_bookmark_levels(bms)
    if not ref or not items:
        return {"bookmark_letter_count": len(ref), "matched": 0}
    norms = [normalize_for_match(it.title) for it in items]
    idx_by, choices = {}, []
    for i, n in enumerate(norms):
        if n and n not in idx_by:
            idx_by[n] = i
            choices.append(n)
    pairs = []
    for bm in ref:
        bn = normalize_for_match(bm["title"])
        if not bn:
            continue
        r = process.extractOne(bn, choices, scorer=fuzz.token_set_ratio, score_cutoff=88.0)
        if r:
            pairs.append((bm, items[idx_by[r[0]]]))
    matched = len(pairs)
    abs_a = sum(1 for bm, it in pairs if bm["level"] == it.level)
    ps = sorted(pairs, key=lambda p: p[0]["order"])
    tt = ta = 0
    for (ba, ia), (bb, ib) in zip(ps, ps[1:]):
        tt += 1
        if _sign(bb["level"] - ba["level"]) == _sign(ib.level - ia.level):
            ta += 1
    return {
        "bookmark_letter_count": len(ref), "matched": matched,
        "match_rate": round(matched / len(ref), 4),
        "abs_level_agreement": round(abs_a / matched, 4) if matched else None,
        "rel_depth_agreement": round(ta / tt, 4) if tt else None,
    }


def render_tree(items):
    out = []
    for it in items:
        ind = "    " * max(it.level - 1, 0)
        pg = it.printed_page if it.printed_page is not None else "-"
        out.append(f"{ind}[{pg}] L{it.level} {it.title}")
    return out


def hmetrics(items):
    lv = [it.level for it in items]
    return {
        "item_count": len(items),
        "level_distribution": {str(k): v for k, v in sorted(Counter(lv).items())},
        "distinct_levels": len(set(lv)),
        "starts_at_level_1": bool(lv) and min(lv) == 1,
    }


def contents_pages(label):
    pages = []
    for seg in label.get("toc_segments") or []:
        if seg.get("kind") == "contents":
            pages.extend(range(seg["start_page"], seg["end_page"] + 1))
    return sorted(dict.fromkeys(pages or list(label["toc_pages"])))


def _cid(t):
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", t).strip("_")[:80]


def run_book(label):
    pdf = ROOT_DIR / label["input_pdf"]
    cid = _cid(label["id"])
    toc_pages = contents_pages(label)
    rec = {"id": label["id"], "input_pdf": label["input_pdf"], "contents_pages": toc_pages}
    if not pdf.exists():
        rec["status"] = "missing_pdf"
        return rec
    lines = extract_toc_lines(pdf, toc_pages)
    if not lines:
        rec["status"] = "no_lines"
        return rec

    depth_mf, debug = multifeature_levels(lines)
    items_mf = to_items(lines, depth_mf)
    items_hc = to_items(lines, hc_levels(lines))

    (OUTPUT_DIR / f"{cid}_lines.json").write_text(
        json.dumps(lines, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / f"{cid}_debug.json").write_text(
        json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, items in [("MF", items_mf), ("HC", items_hc)]:
        (OUTPUT_DIR / f"{cid}_tree_{name}.txt").write_text(
            "\n".join(render_tree(items)) + "\n", encoding="utf-8")

    rec["status"] = "ok"
    rec["debug"] = debug
    rec["arm_hc"] = hmetrics(items_hc)
    rec["arm_mf"] = hmetrics(items_mf)
    rec["mf_tree_preview"] = render_tree(items_mf)[:26]
    if label["id"] in BOOKMARKED_IDS:
        bms = extract_existing_bookmarks(pdf)
        rec["weakref_hc"] = weakref_metrics(items_hc, bms)
        rec["weakref_mf"] = weakref_metrics(items_mf, bms)
    return rec


def build_finding(results):
    parts = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        d = r["debug"]
        p = (f"{r['id']}(reliable_cols={d['columns_reliable']},n={d['n_levels']}): "
             f"HC={r['arm_hc']['level_distribution']} MF={r['arm_mf']['level_distribution']}")
        if "weakref_mf" in r:
            p += (f". rel_depth HC={r['weakref_hc'].get('rel_depth_agreement')}"
                  f"/MF={r['weakref_mf'].get('rel_depth_agreement')}"
                  f" abs HC={r['weakref_hc'].get('abs_level_agreement')}"
                  f"/MF={r['weakref_mf'].get('abs_level_agreement')}")
        parts.append(p)
    return " | ".join(parts)


def record_experiment(summary):
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "height+indent+is_bold+font_type 4 feature를 signature 클러스터로 묶고 prominence"
            "(bold>height>왼쪽)로 정렬해 계층 레벨을 결정한다(결정론). indent는 026 robust 컬럼 + "
            "신뢰도 게이트(노이즈 스캔이면 폐기). 026 HC와 비교하고 bookmark weak ref로 "
            "rel_depth/abs를 잰다. 목표: luenberger를 글꼴/굵기로 복원하면서 shreve/한국어 회귀 방지."
        ),
        "inputs": [lab["input_pdf"] for lab in summary["_labels_used"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "experiments\\labels\\answer_toc_ranges_manual.json",
        "model": "none(deterministic)",
        "finding": summary["finding"], "ran_at": summary["ran_at"],
    }
    exps = data.get("experiments", data) if isinstance(data, dict) else data
    exps = [e for e in exps if e.get("id") != EXPERIMENT_ID]
    exps.append(entry)
    if isinstance(data, dict):
        data["experiments"] = exps
    else:
        data = exps
    EXPERIMENTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = {lab["id"]: lab for lab in json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]}
    used = [labels[i] for i in TARGET_IDS if i in labels]
    results = [run_book(lab) for lab in used]

    summary = {
        "experiment_id": EXPERIMENT_ID, "scope": "hierarchy_only_deterministic",
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "finding": build_finding(results), "results": results, "_labels_used": used,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "_labels_used"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    record_experiment(summary)

    print("=== exp 028: 멀티피처 클러스터 (height+indent+bold+font) vs 026 HC ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']}: {r.get('status')}")
            continue
        d = r["debug"]
        print(f"\n- {r['id']} (reliable_cols={d['columns_reliable']}, n_levels={d['n_levels']})")
        print(f"    clusters:")
        for c in d["clusters"]:
            s = c["signature"]
            print(f"      L{c['level']}: col={s['col']} htier={s['htier']} "
                  f"bold={s['bold']} font={s['font']} (n={c['count']}, h={c['mean_height']})")
        print(f"    HC: {r['arm_hc']['level_distribution']}")
        print(f"    MF: {r['arm_mf']['level_distribution']}")
        if "weakref_mf" in r:
            print(f"    rel_depth HC={r['weakref_hc'].get('rel_depth_agreement')} "
                  f"MF={r['weakref_mf'].get('rel_depth_agreement')} | "
                  f"abs HC={r['weakref_hc'].get('abs_level_agreement')} "
                  f"MF={r['weakref_mf'].get('abs_level_agreement')}")
        print("    MF tree preview:")
        for line in r["mf_tree_preview"][:14]:
            print(f"      {line}")
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
