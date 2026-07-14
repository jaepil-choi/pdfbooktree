"""experiment 029: 결정론 멀티피처 클러스터 + LLM이 클러스터 '순서(레벨)'만 결정.

배경
- experiment 028: height+indent+is_bold+font_type 클러스터링은 각 책의 판별 신호를 정확히
  잡았다(luenberger를 글꼴로 Chapter/Section/Subsection 분리). 그러나 클러스터를 레벨로
  '정렬'하는 축이 책마다 달라(shreve=col, luenberger=font, algorithms=height) 고정
  prominence(bold>height>col)가 shreve를 회귀시켰다(abs 0.84->0.22).
- experiment 027: LLM이 '줄마다' level을 정하면 한국어 계층이 역전됐다(과한 자유).

아이디어(사용자)
- 클러스터링은 결정론으로 그대로 두고, '클러스터의 순서(레벨)'만 LLM에게 맡긴다.
  LLM은 줄이 아니라 소수의 클러스터(보통 3~7개)를 보고 순서만 정한다 -> 작업이 좁아 안전.
- 추가 이점: LLM이 여러 클러스터에 같은 레벨을 줄 수 있어(병합) hull의 드리프트(같은 '장'이
  col1/col2 두 클러스터로 갈린 것)를 examples를 읽고 한 레벨로 합칠 수 있다.

구현
- 028의 signature 클러스터(col 신뢰도 게이트 포함)를 그대로 만든다.
- 각 클러스터 요약(글꼴/굵기/평균높이/컬럼/개수 + 대표 제목 예시)을 만들어 LLM에 1콜.
- LLM은 클러스터별 level을 출력(같은 level 허용=병합). dense-rank 후 각 줄에 적용.
- baseline: 026 HC, 028 MF(고정 prominence)와 비교.

평가(024~028 계승): rel_depth_agreement + abs_level + bookmark weakref. luenberger bookmark는
Part/Chapter까지뿐이라 정답 아님(Part는 Times라 Section 클러스터에 섞임 -> 육안 검수).

출력: experiments/outputs/029_toc_cluster_llm_order/
실행: uv run python experiments/029_toc_cluster_llm_order.py
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from dotenv import load_dotenv
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
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "029_toc_cluster_llm_order"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "029_toc_cluster_llm_order"

TARGET_IDS = [
    "john_hull",
    "luenberger_investment_science",
    "shreve_binomial",
    "algorithms_to_live_by",
    "algorithm_nine",
]
BOOKMARKED_IDS = {"john_hull", "luenberger_investment_science", "shreve_binomial"}

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
MODEL = "solar-pro3"
COLUMN_GAP_FRAC = 0.03
COLUMN_MIN_SUPPORT = 2
COLUMN_RELIABLE_STD_FRAC = 0.025

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
# 줄 신호 추출 + tier + robust 컬럼 (028 재사용)
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
                    head = content_spans[0]
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


def columns_reliable(lines, centers) -> bool:
    if len(centers) < 2:
        return False
    content = [ln for ln in lines if not is_title_word(ln["text"])]
    pw = content[0]["page_width"]
    devs = [ln["title_x"] - min(centers, key=lambda c: abs(ln["title_x"] - c)) for ln in content]
    return float(np.std(devs)) < COLUMN_RELIABLE_STD_FRAC * pw


def assign_column(title_x: float, centers: list[float]) -> int:
    if not centers:
        return 1
    return min(range(len(centers)), key=lambda i: abs(title_x - centers[i])) + 1


# ---------------------------------------------------------------------------
# 결정론 클러스터 형성 (028과 동일 signature)
# ---------------------------------------------------------------------------
def build_clusters(lines: list[dict[str, Any]]) -> tuple[dict[int, int], list[dict[str, Any]], dict[str, Any]]:
    """각 줄을 signature 클러스터에 배정하고, 클러스터 요약 목록을 만든다.

    반환: (line_idx -> cluster_id, clusters 요약 list, debug). cluster_id는 0..K-1.
    """

    cuts = cluster_cut_points([ln["height"] for ln in lines])
    centers = build_columns(lines)
    reliable = columns_reliable(lines, centers)
    use_centers = centers if reliable else []

    sig_of: dict[int, tuple] = {}
    for i, ln in enumerate(lines):
        sig_of[i] = (
            assign_column(ln["title_x"], use_centers),
            assign_tier(ln["height"], cuts),
            ln["is_bold"],
            ln["font_type"],
        )

    members: dict[tuple, list[int]] = defaultdict(list)
    for i, ln in enumerate(lines):
        if is_title_word(ln["text"]):
            continue
        members[sig_of[i]].append(i)

    # 안정적 cluster_id: signature 정렬 순.
    sigs = sorted(members.keys())
    sig_to_id = {sig: cid for cid, sig in enumerate(sigs)}

    clusters: list[dict[str, Any]] = []
    for sig in sigs:
        idxs = members[sig]
        # 대표 예시: 읽기 순서로 고르게 4개.
        ordered = sorted(idxs, key=lambda i: (lines[i]["pdf_page"], i))
        if len(ordered) <= 4:
            picks = ordered
        else:
            step = len(ordered) / 4.0
            picks = [ordered[int(k * step)] for k in range(4)]
        clusters.append(
            {
                "cluster_id": sig_to_id[sig],
                "col": sig[0],
                "height_tier": sig[1],
                "is_bold": sig[2],
                "font_type": sig[3],
                "count": len(idxs),
                "mean_height": round(float(np.mean([lines[i]["height"] for i in idxs])), 2),
                "examples": [lines[i]["text"][:70] for i in picks],
            }
        )

    # title-word 줄은 클러스터에서 빠지므로(items에서도 제외) 매핑에 넣지 않는다.
    line_cluster = {
        i: sig_to_id[sig_of[i]] for i in range(len(lines)) if sig_of[i] in sig_to_id
    }
    debug = {
        "height_cuts": [round(c, 2) for c in cuts],
        "column_centers": [round(c, 1) for c in centers],
        "columns_reliable": reliable,
        "n_clusters": len(clusters),
    }
    return line_cluster, clusters, debug


# ---------------------------------------------------------------------------
# LLM: 클러스터 순서(레벨)만 결정
# ---------------------------------------------------------------------------
_CLIENT: Any = None
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def client():
    global _CLIENT
    if _CLIENT is None:
        from openai import OpenAI
        key = os.environ.get("UPSTAGE_API_KEY")
        if not key:
            raise RuntimeError("UPSTAGE_API_KEY가 설정되지 않았다.")
        _CLIENT = OpenAI(api_key=key, base_url=UPSTAGE_BASE_URL)
    return _CLIENT


def loads_lenient(content):
    if not content:
        return {}
    t = content.strip()
    for cand in (t, (_FENCE.search(t).group(1) if _FENCE.search(t) else None)):
        if cand:
            try:
                return json.loads(cand)
            except json.JSONDecodeError:
                pass
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e > s:
        try:
            return json.loads(t[s : e + 1])
        except json.JSONDecodeError:
            pass
    return {}


ORDER_SYSTEM = (
    "너는 책 목차의 계층을 정하는 도구다. 입력은 목차 줄들을 이미 묶어 놓은 '클러스터' 목록이다. "
    "각 클러스터에는 글꼴(font_type), 굵기(is_bold), 평균 글씨 높이(mean_height), 들여쓰기 "
    "컬럼(col, 작을수록 왼쪽), 줄 수(count), 대표 제목 예시(examples)가 있다.\n"
    "네 일은 '각 클러스터의 계층 level을 정하는 것'뿐이다(1=최상위). 규칙:\n"
    "- 줄을 다시 묶거나 나누지 마라. 오직 클러스터마다 level 정수 하나만 부여한다.\n"
    "- 큰 글씨/굵게/왼쪽일수록, 그리고 예시 제목이 장/부(chapter/part)처럼 상위 단위면 상위 "
    "level이다. 작은 글씨/들여쓰기/세부 항목 예시는 하위 level이다.\n"
    "- 여러 클러스터가 같은 계층이면 같은 level을 줘도 된다(예: 같은 '장'인데 들여쓰기만 살짝 "
    "다른 두 클러스터는 같은 level).\n"
    "- 예시 제목의 의미를 반드시 활용하라(신호가 애매하면 제목이 판단 근거다)."
)

ORDER_FMT = {
    "type": "json_schema",
    "json_schema": {
        "name": "cluster_levels",
        "schema": {
            "type": "object",
            "properties": {
                "clusters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cluster_id": {"type": "integer"},
                            "level": {"type": "integer"},
                        },
                        "required": ["cluster_id", "level"],
                    },
                }
            },
            "required": ["clusters"],
        },
    },
}


def llm_cluster_levels(clusters: list[dict[str, Any]]) -> dict[int, int]:
    payload = [
        {
            "cluster_id": c["cluster_id"],
            "font_type": c["font_type"],
            "is_bold": c["is_bold"],
            "mean_height": c["mean_height"],
            "indent_col": c["col"],
            "count": c["count"],
            "examples": c["examples"],
        }
        for c in clusters
    ]
    user = "클러스터 목록:\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    resp = client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": ORDER_SYSTEM}, {"role": "user", "content": user}],
        response_format=ORDER_FMT,
        temperature=0.0,
    )
    raw = loads_lenient(resp.choices[0].message.content).get("clusters", [])
    return {int(r["cluster_id"]): int(r["level"]) for r in raw if "cluster_id" in r and "level" in r}


def levels_from_clusters(
    line_cluster: dict[int, int], clusters: list[dict[str, Any]], cluster_level: dict[int, int]
) -> dict[int, int]:
    """클러스터 level을 dense-rank 후 각 줄에 부여한다."""

    all_ids = [c["cluster_id"] for c in clusters]
    max_assigned = max(cluster_level.values(), default=1)
    raw_level = {cid: cluster_level.get(cid, max_assigned + 1) for cid in all_ids}
    distinct = sorted(set(raw_level.values()))
    rank = {lv: i + 1 for i, lv in enumerate(distinct)}
    cid_level = {cid: rank[raw_level[cid]] for cid in all_ids}
    deepest = max(cid_level.values(), default=1)
    return {i: cid_level.get(line_cluster[i], deepest) for i in line_cluster}


# ---------------------------------------------------------------------------
# 028 MF (고정 prominence) baseline
# ---------------------------------------------------------------------------
def mf_levels(line_cluster, clusters) -> dict[int, int]:
    by_id = {c["cluster_id"]: c for c in clusters}

    def key(cid):
        c = by_id[cid]
        return (0 if c["is_bold"] else 1, -c["mean_height"], c["col"])

    ordered = sorted(by_id.keys(), key=key)
    cid_level = {cid: i + 1 for i, cid in enumerate(ordered)}
    deepest = max(cid_level.values(), default=1)
    return {i: cid_level.get(line_cluster[i], deepest) for i in line_cluster}


# ---------------------------------------------------------------------------
# items / weakref / 트리
# ---------------------------------------------------------------------------
def to_items(lines, depth) -> list[TocItem]:
    items = []
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


def normalize_levels(items):
    if not items:
        return items
    shift = min(it.level for it in items) - 1
    if shift <= 0:
        return items
    return [
        TocItem(title=it.title, level=it.level - shift, printed_page=it.printed_page,
                raw_text=it.raw_text, source_pdf_page=it.source_pdf_page, confidence=it.confidence)
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

    line_cluster, clusters, debug = build_clusters(lines)
    cluster_level = llm_cluster_levels(clusters)

    items_llm = to_items(lines, levels_from_clusters(line_cluster, clusters, cluster_level))
    items_mf = to_items(lines, mf_levels(line_cluster, clusters))

    (OUTPUT_DIR / f"{cid}_clusters.json").write_text(
        json.dumps({"debug": debug, "clusters": clusters,
                    "llm_levels": {str(k): v for k, v in cluster_level.items()}},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    for name, items in [("LLMorder", items_llm), ("MF", items_mf)]:
        (OUTPUT_DIR / f"{cid}_tree_{name}.txt").write_text(
            "\n".join(render_tree(items)) + "\n", encoding="utf-8")

    rec["status"] = "ok"
    rec["debug"] = debug
    rec["llm_cluster_levels"] = {str(c["cluster_id"]): cluster_level.get(c["cluster_id"]) for c in clusters}
    rec["arm_mf"] = hmetrics(items_mf)
    rec["arm_llm"] = hmetrics(items_llm)
    rec["llm_tree_preview"] = render_tree(items_llm)[:26]
    if label["id"] in BOOKMARKED_IDS:
        bms = extract_existing_bookmarks(pdf)
        rec["weakref_mf"] = weakref_metrics(items_mf, bms)
        rec["weakref_llm"] = weakref_metrics(items_llm, bms)
    return rec


def build_finding(results):
    parts = []
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        p = (f"{r['id']}(clusters={r['debug']['n_clusters']},reliable_cols="
             f"{r['debug']['columns_reliable']}): MF={r['arm_mf']['level_distribution']} "
             f"LLM={r['arm_llm']['level_distribution']}")
        if "weakref_llm" in r:
            p += (f". rel_depth MF={r['weakref_mf'].get('rel_depth_agreement')}"
                  f"/LLM={r['weakref_llm'].get('rel_depth_agreement')}"
                  f" abs MF={r['weakref_mf'].get('abs_level_agreement')}"
                  f"/LLM={r['weakref_llm'].get('abs_level_agreement')}")
        parts.append(p)
    return " | ".join(parts)


def record_experiment(summary):
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "결정론 멀티피처 클러스터(028)는 그대로 두고, 클러스터의 순서(레벨)만 LLM이 1콜로 "
            "결정한다(같은 level 허용=병합). LLM은 줄이 아니라 소수 클러스터를 글꼴/굵기/높이/컬럼/"
            "예시 제목으로 보고 순서만 정한다. 028 MF(고정 prominence)와 비교하고 bookmark weak ref로 "
            "rel_depth/abs를 잰다."
        ),
        "inputs": [lab["input_pdf"] for lab in summary["_labels_used"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "labels": "experiments\\labels\\answer_toc_ranges_manual.json",
        "model": MODEL, "temperature": 0.0,
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
    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = {lab["id"]: lab for lab in json.loads(LABELS_PATH.read_text(encoding="utf-8"))["labels"]}
    used = [labels[i] for i in TARGET_IDS if i in labels]
    results = []
    for lab in used:
        print(f"... running {lab['id']}", flush=True)
        results.append(run_book(lab))

    summary = {
        "experiment_id": EXPERIMENT_ID, "scope": "cluster_deterministic_llm_orders",
        "model": MODEL, "ran_at": datetime.now().isoformat(timespec="seconds"),
        "finding": build_finding(results), "results": results, "_labels_used": used,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "_labels_used"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    record_experiment(summary)

    print("\n=== exp 029: 결정론 클러스터 + LLM 순서 (vs 028 MF) ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"\n- {r['id']}: {r.get('status')}")
            continue
        print(f"\n- {r['id']} (clusters={r['debug']['n_clusters']}, "
              f"reliable_cols={r['debug']['columns_reliable']})")
        print(f"    LLM cluster->level: {r['llm_cluster_levels']}")
        print(f"    MF : {r['arm_mf']['level_distribution']}")
        print(f"    LLM: {r['arm_llm']['level_distribution']}")
        if "weakref_llm" in r:
            print(f"    rel_depth MF={r['weakref_mf'].get('rel_depth_agreement')} "
                  f"LLM={r['weakref_llm'].get('rel_depth_agreement')} | "
                  f"abs MF={r['weakref_mf'].get('abs_level_agreement')} "
                  f"LLM={r['weakref_llm'].get('abs_level_agreement')}")
        print("    LLM tree preview:")
        for line in r["llm_tree_preview"][:14]:
            print(f"      {line}")
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
