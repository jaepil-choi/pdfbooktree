"""실험 117: OCR overlay가 typography 신호를 파괴해 heading 추론이 무너지는지 확인한다.

제품의 전제는 "책 전체의 글자 크기와 시각적 계층으로 bookmark를 만든다"이다.
그런데 고정 corpus는 전부 OCR overlay PDF다. overlay가 invisible text를 쓸 때
font size를 어떻게 정하느냐에 따라 이 전제가 성립하지 않을 수 있다.

이 실험은 네 가지를 측정한다.

1. overlay text의 font 종류 수와 font size 종류 수
2. font_size와 bbox height의 상관계수
3. density clustering이 만들어내는 tier 수
4. 최상위 tier(=level 1 heading이 되는 줄)의 실제 구성

측정만 하고 제품 코드는 건드리지 않는다.
"""

from __future__ import annotations

import collections
import json
import pathlib
import random
import re
import statistics
from typing import Any

from pdfbooktree.config import ProcessingConfig
from pdfbooktree.pipeline import analyze_pdf
from pdfbooktree.typography.geometry import compute_geometry_font_tier_set
from pdfbooktree.typography.margins import exclude_margin_artifacts
from pdfbooktree.typography.tiers import assign_tier

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "117_ocr_overlay_typography_signal_loss"
CORPUS_DIR = ROOT_DIR / "data" / "300STUDY_ocr_overlay" / "pdfs"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
RESULT_PATH = OUTPUT_DIR / "results.json"

SAMPLE_SIZE = 8
MIN_LINES = 800
SEED = 20260818

WORD_RE = re.compile(r"[A-Za-z\uac00-\ud7a3]+")


def line_kind(text: str | None) -> str:
    """줄 하나가 본문 text인지, 아니면 비텍스트 조각인지 분류한다."""

    value = (text or "").strip()
    if "![image](" in value:
        return "image"
    if value.count("|") >= 2:
        return "table"
    if not value:
        return "empty"
    if not WORD_RE.search(value):
        return "nonword"
    if len(WORD_RE.findall(value)) <= 1:
        return "single"
    return "text"


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """두 신호의 상관계수를 계산한다. 분산이 0이면 정의할 수 없다."""

    if len(xs) < 2:
        return None
    mean_x = statistics.mean(xs)
    mean_y = statistics.mean(ys)
    sd_x = statistics.pstdev(xs)
    sd_y = statistics.pstdev(ys)
    if sd_x == 0.0 or sd_y == 0.0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return cov / len(xs) / (sd_x * sd_y)


def measure(pdf_path: pathlib.Path, config: Any) -> dict[str, Any] | None:
    """PDF 한 권에서 네 가지 신호를 측정한다."""

    analysis = analyze_pdf(pdf_path, config)
    lines = exclude_margin_artifacts(analysis.lines, config)
    if len(lines) < MIN_LINES:
        return None

    font_sizes = [float(line.font_size) for line in lines]
    heights = [float(line.height) for line in lines]
    fonts = collections.Counter(
        name for line in lines for name in (line.font_names or ())
    )

    tier_set = compute_geometry_font_tier_set(lines)
    top_tier = [
        line
        for line in lines
        if tier_set.tiers and assign_tier(line.font_size, tier_set.cut_points) == 1
    ]
    composition = collections.Counter(line_kind(line.text) for line in top_tier)
    non_text = sum(count for kind, count in composition.items() if kind != "text")

    return {
        "pdf": pdf_path.name,
        "pages": analysis.total_pages,
        "body_lines": len(lines),
        "distinct_fonts": len(fonts),
        "font_names": sorted(fonts)[:3],
        "distinct_font_sizes": len({round(size, 2) for size in font_sizes}),
        "font_size_height_correlation": (
            round(value, 4)
            if (value := pearson(font_sizes, heights)) is not None
            else None
        ),
        "tier_count": len(tier_set.tiers),
        "top_tier_lines": len(top_tier),
        "top_tier_composition": dict(composition.most_common()),
        "top_tier_non_text_ratio": (
            round(non_text / len(top_tier), 4) if top_tier else None
        ),
    }


def main() -> None:
    if not CORPUS_DIR.is_dir():
        raise RuntimeError(f"corpus directory가 없다: {CORPUS_DIR}")

    config = ProcessingConfig().typography
    candidates = sorted(CORPUS_DIR.rglob("*.pdf"))
    random.Random(SEED).shuffle(candidates)

    rows: list[dict[str, Any]] = []
    for pdf_path in candidates:
        if len(rows) >= SAMPLE_SIZE:
            break
        try:
            row = measure(pdf_path, config)
        except Exception as error:  # noqa: BLE001 - 관측값으로 남긴다
            rows.append(
                {"pdf": pdf_path.name, "error": f"{type(error).__name__}: {error}"}
            )
            continue
        if row is None:
            continue
        rows.append(row)
        print(
            "[{:>2}] corr={} fonts={} sizes={} tiers={} top1_non_text={} {}".format(
                len(rows),
                row["font_size_height_correlation"],
                row["distinct_fonts"],
                row["distinct_font_sizes"],
                row["tier_count"],
                row["top_tier_non_text_ratio"],
                row["pdf"][:40],
            )
        )

    measured = [row for row in rows if "error" not in row]
    summary = {
        "sampled_books": len(measured),
        "single_font_books": sum(1 for row in measured if row["distinct_fonts"] == 1),
        "min_font_size_height_correlation": min(
            (row["font_size_height_correlation"] or 0.0) for row in measured
        ),
        "median_distinct_font_sizes": statistics.median(
            row["distinct_font_sizes"] for row in measured
        ),
        "median_tier_count": statistics.median(row["tier_count"] for row in measured),
        "median_top_tier_non_text_ratio": statistics.median(
            row["top_tier_non_text_ratio"] or 0.0 for row in measured
        ),
        "max_top_tier_non_text_ratio": max(
            row["top_tier_non_text_ratio"] or 0.0 for row in measured
        ),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(
            {"experiment_id": EXPERIMENT_ID, "summary": summary, "books": rows},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
