"""experiment 054: 2px 미만 tier 병합 후처리 + scanned OCR 책에서 font size가 쓸모있는지 확인.

052/053에서 만든 KDE 봉우리/골짜기 tier 방식은 골짜기 깊이나 봉우리 간 거리를 전혀
따지지 않고 "봉우리 사이에 있는 극소값이면 무조건 cut"으로 처리해서, 거의 같은 값(예:
font_size 5.53 vs 5.98)조차 서로 다른 tier로 쪼갰다(052의 tiers=15~19 과분할).

이 실험은 두 가지를 한다.

(1) tier 병합: bbox 좌표는 pixel/point 단위이므로, 두 tier의 대표값(peak) 차이가
    MIN_GAP(기본 2.0) 미만이면 사실상 같은 크기라고 보고 병합한다. KDE로 1차 tier를
    만든 뒤, 인접 tier peak 차이가 min_gap 미만이면 사슬(chain)식으로 합치는 후처리를
    추가한다. John Hull에서 병합 전/후 tier 개수와 실제 소속 텍스트를 txt로 남긴다
    (tier당 최대 50줄 샘플).

(2) scanned/OCR PDF에서 font size 신뢰성 확인: data/scanned-pdf-not-indexed의
    "수리통계학(개정판)-김우철_upocr_merged.pdf"(Upstage OCR로 만든 숨은 텍스트 레이어)
    에서 같은 방식으로 font_size와 height를 뽑아 KDE+병합을 적용해본다. 052/053은
    John Hull처럼 폰트 크기가 진짜 조판 설계값인 native PDF만 다뤘는데, scanned OCR
    책은 OCR 엔진이 글자 하나하나에 박스 맞춤으로 임의의 font_size를 매기기 때문에
    같은 시각적 크기의 글자도 span마다 값이 들쭉날쭉할 수 있다는 가설을 검증한다.

[재작업] 최초 버전은 fitz가 자체적으로 나눈 block/line 경계를 그대로 믿고 그 안의
content span height/font_size에 max()를 썼다. 이러면 (a) 같은 시각적 줄인데 OCR이
서로 다른 block/line으로 쪼갠 조각(TOC의 '제목 ... 쪽번호'처럼)이 따로따로 잡히고,
(b) 수식처럼 한 줄에 크기가 다른 여러 span이 섞이면 가장 큰 span 하나가 그 줄 전체를
대표해버려 과대평가된다. 그래서 extract_page_content_spans + merge_spans_into_lines로
다시 짰다: block/line 경계를 무시하고 page의 모든 content span을 풀어 y좌표(중심)로
직접 재군집화해 진짜 시각적 줄을 만들고, 그 줄에 속한 span들의 height/font_size는
median으로 대표값을 낸다(더 이상 max를 쓰지 않는다). 이 line 단위 값을 page마다
모아 책 전체로 이어붙인 뒤 KDE tier를 나누는 흐름은 그대로다.

실행:
    uv run python experiments/054_tier_merge_and_scanned_font_check.py
출력:
    experiments/outputs/054_tier_merge_and_scanned_font_check/
        - <book_id>_<key>_tiers_raw.txt    : 병합 전 tier별 텍스트 샘플(최대 50줄)
        - <book_id>_<key>_tiers_merged.txt : 병합 후 tier별 텍스트 샘플(최대 50줄)
        - summary.json
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
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
EXPERIMENT_ID = "054_tier_merge_and_scanned_font_check"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

MIN_GAP = 2.0
MAX_LINES_PER_TIER = 50

BOOKS = {
    "john_hull": ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf",
    "suri_tonggyehak_scanned": ROOT_DIR
    / "data"
    / "scanned-pdf-not-indexed"
    / "수리통계학(개정판)-김우철_upocr_merged.pdf",
}

_HANGUL = re.compile(r"[가-힣]")
_LATIN2 = re.compile(r"[A-Za-z]{2,}")


def is_content_span(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HANGUL.search(stripped) or _LATIN2.search(stripped))


def extract_page_content_spans(page: fitz.Page) -> list[dict[str, Any]]:
    """page의 모든 content span을 fitz block/line 경계와 무관하게 평평하게 뽑는다.

    fitz가 자체적으로 나눈 block/line 경계를 그대로 믿지 않는다 — 특히 OCR 문서는
    같은 시각적 한 줄(예: TOC의 '제목 ... 쪽번호')이 서로 다른 block/line으로
    쪼개지는 경우가 흔하다. 그래서 일단 spans를 전부 풀어서(y 중심, x0, height,
    font_size) 모은 뒤, 뒤에서 y좌표 기준으로 직접 다시 줄을 묶는다.
    """

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
    """같은 시각적 줄에 있는 text box(span)들을 y좌표로 다시 묶고 median height/size를 낸다."""

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
        heights = [span["height"] for span in group_sorted]
        sizes = [span["font_size"] for span in group_sorted]
        merged.append(
            {
                "height": round(float(np.median(heights)), 2),
                "font_size": round(float(np.median(sizes)), 2),
                "font_size_span_std": round(float(np.std(sizes)), 3),
                "text": " ".join(span["text"] for span in group_sorted)[:120],
            }
        )
    return merged


def extract_book_lines(pdf_path: Path) -> list[dict[str, Any]]:
    """책 전체 page를 훑어, 같은 줄에 있는 text box를 병합한 뒤 median height/font_size를 낸다."""

    lines: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            spans = extract_page_content_spans(page)
            for merged_line in merge_spans_into_lines(spans):
                lines.append({"pdf_page": page_index + 1, **merged_line})
    return lines


def cluster_by_density(values: list[float]) -> dict[str, Any]:
    """1D 값을 KDE 밀도의 봉우리/골짜기로 클러스터링한다(k 미고정, 052/053과 동일)."""

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


def merge_close_tiers(peaks: list[float], cut_points: list[float], min_gap: float) -> dict[str, Any]:
    """인접 tier의 peak 차이가 min_gap 미만이면 사슬식으로 병합한다.

    bbox 좌표는 point/pixel 단위 실측값이므로, 2 단위 미만 차이는 같은 크기의 측정
    잡음으로 본다. cut_points는 peaks_asc[i]와 peaks_asc[i+1] 사이에 하나씩 대응한다고
    가정한다(cluster_by_density가 그렇게 만든다).
    """

    peaks_asc = sorted(peaks)
    cuts_asc = sorted(cut_points)
    if len(peaks_asc) <= 1:
        return {"tier_count": len(peaks_asc), "cut_points": [], "peaks": sorted(peaks, reverse=True)}

    merged_peaks = [peaks_asc[0]]
    merged_cuts: list[float] = []
    for i in range(1, len(peaks_asc)):
        gap = peaks_asc[i] - merged_peaks[-1]
        if gap < min_gap:
            merged_peaks[-1] = (merged_peaks[-1] + peaks_asc[i]) / 2.0
        else:
            # cut_points가 valley 개수 부족 등으로 peaks-1보다 짧을 수 있어, 없으면
            # 두 peak의 중점을 대신 cut으로 쓴다.
            cut = cuts_asc[i - 1] if i - 1 < len(cuts_asc) else (peaks_asc[i - 1] + peaks_asc[i]) / 2.0
            merged_cuts.append(cut)
            merged_peaks.append(peaks_asc[i])

    return {
        "tier_count": len(merged_peaks),
        "cut_points": merged_cuts,
        "peaks": sorted(merged_peaks, reverse=True),
    }


def assign_tier(value: float, cut_points: list[float]) -> int:
    tier = 1
    for cut in sorted(cut_points, reverse=True):
        if value >= cut:
            return tier
        tier += 1
    return tier


def render_tier_dump(lines: list[dict[str, Any]], key: str, cut_points: list[float]) -> list[str]:
    """tier별로 실제 어떤 텍스트가 들어갔는지 최대 MAX_LINES_PER_TIER줄만 남긴다."""

    buckets: dict[int, list[dict[str, Any]]] = {}
    for line in lines:
        tier = assign_tier(line[key], cut_points)
        buckets.setdefault(tier, []).append(line)

    out: list[str] = []
    for tier in sorted(buckets):
        rows = buckets[tier]
        values = sorted({row[key] for row in rows}, reverse=True)
        out.append(
            f"===== T{tier} {key}={values[:6]}{'...' if len(values) > 6 else ''} "
            f"n={len(rows)} (표시 최대 {MAX_LINES_PER_TIER}) ====="
        )
        for row in rows[:MAX_LINES_PER_TIER]:
            out.append(f"  p{row['pdf_page']:>4} {key}={row[key]:>6} {row['text']!r}")
        out.append("")
    return out


def summarize_book(book_id: str, pdf_path: Path) -> dict[str, Any]:
    print(f"... {book_id} 전체 page 훑는 중: {pdf_path.name}", flush=True)
    lines = extract_book_lines(pdf_path)
    with fitz.open(pdf_path) as document:
        total_pages = document.page_count
    print(f"    total_pages={total_pages} extracted_lines={len(lines)}", flush=True)

    book_summary: dict[str, Any] = {
        "book_id": book_id,
        "total_pages": total_pages,
        "line_count": len(lines),
        "keys": {},
    }

    for key in ["font_size", "height"]:
        values = [line[key] for line in lines]
        raw = cluster_by_density(values)
        merged = merge_close_tiers(raw["peaks"], raw["cut_points"], MIN_GAP)

        raw_dump = render_tier_dump(lines, key, raw["cut_points"])
        merged_dump = render_tier_dump(lines, key, merged["cut_points"])
        (OUTPUT_DIR / f"{book_id}_{key}_tiers_raw.txt").write_text(
            "\n".join(raw_dump), encoding="utf-8"
        )
        (OUTPUT_DIR / f"{book_id}_{key}_tiers_merged.txt").write_text(
            "\n".join(merged_dump), encoding="utf-8"
        )

        # OCR span 잡음 진단: 같은 line 안에서 span별 font_size가 얼마나 흔들리는지.
        span_std = [line["font_size_span_std"] for line in lines if line["font_size_span_std"] > 0]

        book_summary["keys"][key] = {
            "raw_tier_count": raw["tier_count"],
            "raw_peaks": [round(p, 2) for p in raw["peaks"]],
            "merged_tier_count": merged["tier_count"],
            "merged_peaks": [round(p, 2) for p in merged["peaks"]],
            "reduced_by": raw["tier_count"] - merged["tier_count"],
        }
        if key == "font_size":
            book_summary["keys"][key]["intra_line_span_font_size_std_mean"] = (
                round(float(np.mean(span_std)), 3) if span_std else 0.0
            )
            book_summary["keys"][key]["intra_line_span_font_size_std_p90"] = (
                round(float(np.percentile(span_std, 90)), 3) if span_std else 0.0
            )

    return book_summary


def build_finding(summaries: dict[str, Any]) -> str:
    parts = [f"MIN_GAP={MIN_GAP}px 병합 후처리를 font_size/height KDE tier에 적용했다."]
    for book_id, summary in summaries.items():
        fs = summary["keys"]["font_size"]
        ht = summary["keys"]["height"]
        parts.append(
            f"{book_id}(n={summary['line_count']}): font_size tiers {fs['raw_tier_count']}->"
            f"{fs['merged_tier_count']}(-{fs['reduced_by']}, peaks={fs['merged_peaks']}), "
            f"height tiers {ht['raw_tier_count']}->{ht['merged_tier_count']}"
            f"(-{ht['reduced_by']}, peaks={ht['merged_peaks']})."
        )
        if "intra_line_span_font_size_std_mean" in fs:
            parts.append(
                f"{book_id} line 내부 span font_size 표준편차 평균={fs['intra_line_span_font_size_std_mean']}, "
                f"p90={fs['intra_line_span_font_size_std_p90']}."
            )
    return " ".join(parts)


def record_experiment(summaries: dict[str, Any], finding: str) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "052/053의 KDE valley cut이 골짜기 깊이/봉우리 간 거리를 따지지 않고 무조건 "
            "cut해 생기는 과분할 문제를 고치기 위해, 인접 tier peak 차이가 2px(point) "
            "미만이면 병합하는 후처리를 추가한다. 동시에 scanned OCR PDF(수리통계학, "
            "Upstage OCR merged)에서도 font_size 신호가 native PDF만큼 유효한지, "
            "line 내부 span별 font_size 흔들림을 직접 재서 확인한다."
        ),
        "inputs": [str(path.relative_to(ROOT_DIR)) for path in BOOKS.values()],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": [
            "052_whole_book_line_font_height_kde",
            "053_bookmark_depth_font_size_kde",
        ],
        "min_gap": MIN_GAP,
        "max_lines_per_tier": MAX_LINES_PER_TIER,
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

    summaries: dict[str, Any] = {}
    for book_id, pdf_path in BOOKS.items():
        summaries[book_id] = summarize_book(book_id, pdf_path)

    finding = build_finding(summaries)
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "min_gap": MIN_GAP,
        "books": summaries,
        "finding": finding,
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    record_experiment(summaries, finding)

    print("\n=== exp 054: tier merge + scanned OCR font size check ===")
    for book_id, book_summary in summaries.items():
        print(f"- {book_id}: n={book_summary['line_count']}")
        for key, stat in book_summary["keys"].items():
            print(
                f"    {key}: raw_tiers={stat['raw_tier_count']} -> merged_tiers={stat['merged_tier_count']} "
                f"peaks={stat['merged_peaks']}"
            )
    print(f"\nsummary: {OUTPUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
