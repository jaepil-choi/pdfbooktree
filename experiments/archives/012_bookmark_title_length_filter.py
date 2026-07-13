"""bookmark 제목 길이/문자 구성으로 잘못 들어간 bookmark를 거르는 실험.

배경:
- 010~011에서 본 max_children 임계값은 412개 중 3개만 걸러 변별력이 약했다.
- 가설(사용자 제안): 잘못 들어간 bookmark는 제목에 짧은 토큰이 들어간다.
- 실제 데이터를 보니 잘못된 bookmark 제목은 '1', '001', '1110001', '~~0003' 처럼
  숫자/OCR 아티팩트였고, 특히 한국어 OCR 책의 flat 덤프가 이런 형태였다.

토큰 수(공백 분리)는 한국어 제목이 띄어쓰기 없이 1토큰으로 잡혀 정상 책까지 걸리므로
신호로 쓸 수 없다. 대신 다음 두 지표를 쓴다.
- median title 글자수: 정상 제목은 길고, 깨진 제목은 짧다.
- frac_no_letter: 알파벳/한글이 하나도 없는(숫자/기호만) 제목의 비율. 언어 무관하게
  '1110001' 같은 쓰레기 제목을 잡는다. 분포가 이중봉이라 임계값을 정하기 쉽다.

monolithic script로 작성했고, bookmark 추출만 패키지 함수를 재사용한다.
plot label은 한글 폰트 두부 현상을 피해 영어로 둔다.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "012_bookmark_title_length_filter"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DETECTION_JSON = ROOT_DIR / "outputs" / "300study_detection.json"

# 알파벳/한글 한 글자라도 있으면 '글자 있는 제목'으로 본다.
LETTER_RE = re.compile(r"[A-Za-z가-힣]")
# frac_no_letter가 이 값을 넘으면 깨진 bookmark로 판단해 제외한다.
NO_LETTER_THRESHOLD = 0.5


def title_metrics(titles: list[str]) -> dict[str, Any]:
    """제목 리스트에서 길이/문자 구성 지표를 계산한다."""

    char_lens = [len(t) for t in titles]
    no_letter = sum(1 for t in titles if not LETTER_RE.search(t))
    short = sum(1 for t in titles if len(t) <= 3)
    return {
        "mean_char": statistics.mean(char_lens),
        "median_char": statistics.median(char_lens),
        "min_char": min(char_lens),
        "frac_short_char": short / len(titles),
        "frac_no_letter": no_letter / len(titles),
    }


def collect() -> tuple[list[dict[str, Any]], list[int], list[dict[str, str]]]:
    """detection.json의 PDF별 제목 지표와 전체 제목 길이 풀을 모은다."""

    detection = json.loads(DETECTION_JSON.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    pooled_lens: list[int] = []
    errors: list[dict[str, str]] = []

    for result in detection["results"]:
        pdf_path = Path(result["input_pdf"])
        rel = result.get("root_relative_pdf") or result["input_pdf"]
        if not pdf_path.exists():
            errors.append({"pdf": rel, "error": "missing_file"})
            continue
        try:
            bookmarks = extract_existing_bookmarks(pdf_path)
        except Exception as exc:  # noqa: BLE001
            errors.append({"pdf": rel, "error": str(exc)[:80]})
            continue
        titles = [b["title"] for b in bookmarks]
        if not titles:
            continue
        metrics = title_metrics(titles)
        pooled_lens.extend(len(t) for t in titles)
        rows.append(
            {
                "pdf": rel,
                "bookmark_count": len(bookmarks),
                **metrics,
                "is_broken_title": metrics["frac_no_letter"] > NO_LETTER_THRESHOLD,
            }
        )
    return rows, pooled_lens, errors


def build_figure(rows: list[dict[str, Any]], pooled_lens: list[int]) -> Path:
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle(
        f"Bookmark title length / composition ({len(rows)} bookmarked PDFs)",
        fontsize=15,
        fontweight="bold",
    )

    # 1) 전체 bookmark 제목 글자수 분포
    ax = axes[0][0]
    clipped = [min(l, 80) for l in pooled_lens]
    ax.hist(clipped, bins=40, color="#4C72B0", edgecolor="white")
    ax.axvline(3, color="#C44E52", linestyle="--", linewidth=1.2, label="len<=3")
    ax.set_yscale("log")
    ax.set_title("Per-bookmark title length (all titles, clipped at 80)")
    ax.set_xlabel("title char length")
    ax.set_ylabel("bookmark count (log)")
    ax.legend(fontsize=8)

    # 2) PDF별 median title 글자수
    ax = axes[0][1]
    med = [r["median_char"] for r in rows]
    ax.hist([min(m, 60) for m in med], bins=40, color="#55A868", edgecolor="white")
    ax.axvline(3, color="#C44E52", linestyle="--", linewidth=1.2, label="median<=3")
    ax.set_title("Per-PDF median title length")
    ax.set_xlabel("median title char length")
    ax.set_ylabel("PDF count")
    ax.legend(fontsize=8)

    # 3) frac_no_letter 분포 (이중봉 기대)
    ax = axes[0][2]
    fnl = [r["frac_no_letter"] for r in rows]
    ax.hist(fnl, bins=25, color="#937860", edgecolor="white")
    ax.axvline(
        NO_LETTER_THRESHOLD,
        color="#C44E52",
        linestyle="--",
        linewidth=1.4,
        label=f"threshold {NO_LETTER_THRESHOLD}",
    )
    ax.set_yscale("log")
    ax.set_title("Fraction of titles with NO letter (digits/symbols only)")
    ax.set_xlabel("frac_no_letter")
    ax.set_ylabel("PDF count (log)")
    ax.legend(fontsize=8)

    # 4) frac_no_letter vs median_char, 점 크기 = bookmark 수
    ax = axes[1][0]
    sizes = [min(r["bookmark_count"], 800) / 4 + 8 for r in rows]
    colors = ["#C44E52" if r["is_broken_title"] else "#4C72B0" for r in rows]
    ax.scatter(
        fnl,
        [min(m, 60) for m in med],
        s=sizes,
        c=colors,
        alpha=0.6,
        edgecolor="white",
        linewidth=0.3,
    )
    ax.axvline(NO_LETTER_THRESHOLD, color="#C44E52", linestyle="--", linewidth=1.0)
    ax.set_title("frac_no_letter vs median length\n(red = broken, size = bookmark count)")
    ax.set_xlabel("frac_no_letter")
    ax.set_ylabel("median title char length")

    # 5) frac_short_char 분포
    ax = axes[1][1]
    fs = [r["frac_short_char"] for r in rows]
    ax.hist(fs, bins=25, color="#8172B3", edgecolor="white")
    ax.set_yscale("log")
    ax.set_title("Fraction of titles with length <= 3")
    ax.set_xlabel("frac_short_char")
    ax.set_ylabel("PDF count (log)")

    # 6) 필터 결과
    ax = axes[1][2]
    broken = sum(1 for r in rows if r["is_broken_title"])
    kept = len(rows) - broken
    bars = ax.bar(
        ["keep", f"drop:\nno_letter>{NO_LETTER_THRESHOLD}"],
        [kept, broken],
        color=["#55A868", "#C44E52"],
        edgecolor="white",
    )
    for bar, v in zip(bars, [kept, broken], strict=False):
        ax.text(bar.get_x() + bar.get_width() / 2, v, str(v), ha="center", va="bottom", fontsize=12)
    ax.set_title("Filter outcome (broken-title removal)")
    ax.set_ylabel("PDF count")

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    figure_path = OUTPUT_DIR / "bookmark_title_length.png"
    fig.savefig(figure_path, dpi=130)
    plt.close(fig)
    return figure_path


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "pdf",
        "bookmark_count",
        "mean_char",
        "median_char",
        "min_char",
        "frac_short_char",
        "frac_no_letter",
        "is_broken_title",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_summary(rows: list[dict[str, Any]], errors: list[dict[str, str]]) -> dict[str, Any]:
    broken = [r for r in rows if r["is_broken_title"]]
    return {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "bookmarked_pdf_count": len(rows),
        "error_count": len(errors),
        "no_letter_threshold": NO_LETTER_THRESHOLD,
        "kept_count": len(rows) - len(broken),
        "dropped_count": len(broken),
        "dropped": [
            {
                "pdf": r["pdf"],
                "bookmark_count": r["bookmark_count"],
                "median_char": r["median_char"],
                "frac_no_letter": round(r["frac_no_letter"], 3),
            }
            for r in sorted(broken, key=lambda r: -r["frac_no_letter"])
        ],
    }


def update_experiment_registry(summary: dict[str, Any]) -> None:
    if not EXPERIMENTS_JSON.exists():
        return
    registry = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    dropped_names = ", ".join(d["pdf"].split("\\")[-1][:40] for d in summary["dropped"][:10])
    finding = (
        f"300study bookmark 보유 PDF {summary['bookmarked_pdf_count']}개의 제목 길이/문자 "
        f"구성을 시각화했다. 토큰 수는 한국어 제목이 1토큰으로 잡혀 신호로 못 쓰고, "
        f"frac_no_letter(알파벳/한글 없는 제목 비율)가 이중봉으로 갈렸다. "
        f"frac_no_letter > {summary['no_letter_threshold']} 기준으로 "
        f"{summary['dropped_count']}개 PDF를 깨진 bookmark로 제외했다(keep "
        f"{summary['kept_count']}개). 제외 PDF는 제목이 '1', '001', '1110001' 같은 "
        f"숫자/OCR 아티팩트였다. 대표 제외 목록: {dropped_names}."
    )
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "잘못 들어간 bookmark는 제목이 짧은 숫자/OCR 토큰이라는 가설을 검증하기 위해 "
            "bookmark 제목 길이와 문자 구성 분포를 시각화하고, frac_no_letter 기준으로 "
            "깨진 bookmark PDF를 거른다."
        ),
        "inputs": ["outputs\\300study_detection.json"],
        "outputs": "experiments\\outputs\\012_bookmark_title_length_filter",
        "finding": finding,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    registry["experiments"] = [
        e for e in registry["experiments"] if e.get("id") != EXPERIMENT_ID
    ]
    registry["experiments"].append(entry)
    EXPERIMENTS_JSON.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    rows, pooled_lens, errors = collect()
    figure_path = build_figure(rows, pooled_lens)
    summary = build_summary(rows, errors)

    write_csv(OUTPUT_DIR / "bookmark_title_metrics.csv", rows)
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    update_experiment_registry(summary)

    if not args.quiet:
        print(f"figure: {figure_path}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
