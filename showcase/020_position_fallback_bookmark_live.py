"""showcase 020: body-tier position fallback을 실제 scanned/OCR 책 3권으로 검증한다.

실험 097~101에서 검증한 body-tier position fallback(current-anchor 2D,
tolerance=2.0, support>=5, isolation>=1.0, 대표 본문 폰트 ±3%, 물리 line 1개,
가장 깊은 font 골격 parent+1 삽입)을 이제 production Processor 기본 동작으로
옮겼다. 이 showcase는 그 production 경로를 실제 scanned/OCR PDF 3권
(금리의 경제학, 통계학원론, 한경 읽는법)에 그대로 돌려, 실험 101에서 사람이
직접 읽고 판단한 strict fallback tree와 결과가 비슷하거나 더 나은지 확인한다.

비교 기준:
  - showcase 019(이전 기본값 position_and_font, fallback 없음)의
    금리의 경제학/통계학원론 bookmark 수 — 최소 그 이상이어야 한다.
  - 실험 101 strict fallback의 book별 후보 수(금리의 경제학=9, 통계학원론=0,
    한경 읽는법=5) — 이 production 경로로도 비슷한 규모의 후보가 나와야 한다.

실행:
    uv run python showcase/020_position_fallback_bookmark_live.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree import (
    MarkdownSplitConfig,
    ProcessingConfig,
    Processor,
    TypographyConfig,
    inspect_bookmarks,
    inspect_page_count,
)

try:  # 콘솔에서 한글이 깨지지 않게 한다.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "020_position_fallback_bookmark_live"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "020_position_fallback_bookmark_live"
MAX_WORDS = 10_000
MAX_WORDS_COVERAGE = 0.95

# showcase 019(fallback 없는 이전 기본 position_and_font)의 실측값이다.
BASELINE_BOOKMARK_COUNTS = {
    "interest_economics": 79,
    "statistics_principles": 33,
}
# 실험 101 strict fallback(수동 eye check)의 후보 수다.
EXPERIMENT_101_STRICT_FALLBACK_COUNTS = {
    "interest_economics": 9,
    "statistics_principles": 0,
    "hankyung_reading": 5,
}

BOOKS = [
    {
        "key": "interest_economics",
        "title": "금리의 경제학",
        "pdf": ROOT_DIR
        / "showcase"
        / "outputs"
        / "017_interest_economics_ocr_overlay"
        / "interest_economics_ocr.pdf",
    },
    {
        "key": "statistics_principles",
        "title": "통계학원론",
        "pdf": ROOT_DIR
        / "showcase"
        / "outputs"
        / "018_statistics_principles_ocr_overlay"
        / "statistics_principles_ocr.pdf",
    },
    {
        "key": "hankyung_reading",
        "title": "한경 읽는법",
        "pdf": ROOT_DIR
        / "data"
        / "scanned-pdf-not-indexed"
        / "한경_읽는법_-_한국경제신문-compressed[econ macro book].pdf",
    },
]


def render_tree(title: str, bookmarks: list[dict[str, Any]]) -> str:
    """export된 PDF bookmark를 검토 가능한 tree txt로 만든다."""

    lines = [f"# {title} position-fallback bookmark tree", ""]
    for bookmark in bookmarks:
        indent = "  " * max(bookmark["level"] - 1, 0)
        lines.append(
            f"{indent}- [L{bookmark['level']}, p.{bookmark['pdf_page']}] "
            f"{bookmark['title']}"
        )
    return "\n".join(lines) + "\n"


def process_book(spec: dict[str, Any]) -> dict[str, Any]:
    """한 scanned/OCR PDF를 production 기본 설정 Processor로 처리한다."""

    pdf: Path = spec["pdf"]
    if not pdf.exists():
        raise FileNotFoundError(f"입력 PDF가 없다: {pdf}")

    book_output = OUTPUT_DIR / spec["key"]
    config = ProcessingConfig(
        skip_existing_bookmarks=False,
        typography=TypographyConfig(position_min_repeated_pages=5),
        markdown_split=MarkdownSplitConfig(
            max_words=MAX_WORDS, max_words_coverage=MAX_WORDS_COVERAGE
        ),
    )
    existing = inspect_bookmarks(pdf)
    page_info = inspect_page_count(pdf)
    result = Processor(pdf, book_output, config).run()
    if result.status != "processed" or result.output_pdf is None:
        raise RuntimeError(
            f"{spec['title']} public Processor 실패: "
            f"status={result.status}, warnings={result.warnings}"
        )
    if result.markdown_export is None:
        raise RuntimeError(f"{spec['title']} Markdown split 결과가 없다.")

    export = result.markdown_export
    coverage = float(export.word_count_stats.get("coverage", 0.0))

    font_candidates_path = result.artifact_paths["heading_candidates"]
    font_candidates = json.loads(font_candidates_path.read_text(encoding="utf-8"))
    fallback_path = result.artifact_paths["position_fallback_candidates"]
    fallback_candidates = json.loads(fallback_path.read_text(encoding="utf-8"))

    exported = inspect_bookmarks(result.output_pdf)
    bookmarks = exported["bookmarks"]
    fallback_bookmark_count = sum(
        1
        for item in json.loads(
            result.artifact_paths["bookmark_plan"].read_text(encoding="utf-8")
        )
        if item["source"] == "geometry_position_fallback"
    )

    tree_path = book_output / "bookmark_tree.txt"
    tree_text = render_tree(spec["title"], bookmarks)
    tree_path.write_text(tree_text, encoding="utf-8")
    level_counts = dict(sorted(Counter(item["level"] for item in bookmarks).items()))

    baseline_count = BASELINE_BOOKMARK_COUNTS.get(spec["key"])
    return {
        "key": spec["key"],
        "title": spec["title"],
        "input_pdf": str(pdf.relative_to(ROOT_DIR)),
        "page_count": page_info["page_count"],
        "existing_bookmark_count": existing["bookmark_count"],
        "status": result.status,
        "output_pdf": str(result.output_pdf.relative_to(ROOT_DIR)),
        "bookmark_count": exported["bookmark_count"],
        "level_counts": level_counts,
        "font_candidate_count": len(font_candidates),
        "position_fallback_candidate_count": len(fallback_candidates),
        "position_fallback_candidates_kept_in_plan": fallback_bookmark_count,
        "baseline_showcase_019_bookmark_count": baseline_count,
        "at_or_above_baseline": (
            baseline_count is None or exported["bookmark_count"] >= baseline_count
        ),
        "experiment_101_strict_fallback_count": EXPERIMENT_101_STRICT_FALLBACK_COUNTS[
            spec["key"]
        ],
        "tree_file": str(tree_path.relative_to(ROOT_DIR)),
        "tree_preview": tree_text.splitlines()[2:40],
        "markdown_split": {
            "max_words": MAX_WORDS,
            "max_words_coverage": MAX_WORDS_COVERAGE,
            "constraint_satisfied": export.constraint_satisfied,
            "fallback_used": export.fallback_used,
            "chosen_level": export.chosen_level,
            "file_count": export.file_count,
            "reported_coverage": coverage,
        },
        "warnings": result.warnings,
    }


def record_showcase(summary: dict[str, Any]) -> None:
    """position fallback live 결과를 showcase registry에 기록한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "실험 097~101에서 검증한 body-tier position fallback이 옮겨진 "
            "production Processor 기본 경로를 실제 scanned/OCR PDF 3권(금리의 "
            "경제학, 통계학원론, 한경 읽는법)으로 검증하고, showcase 019 baseline과 "
            "실험 101 strict fallback 후보 수 대비 같거나 나은지 확인한다."
        ),
        "inputs": [str(spec["pdf"].relative_to(ROOT_DIR)) for spec in BOOKS],
        "outputs": str(OUTPUT_PATH.relative_to(ROOT_DIR)),
        "finding": summary["finding"],
        "command": "uv run python showcase/020_position_fallback_bookmark_live.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    showcases = data["showcases"]
    for index, existing in enumerate(showcases):
        if existing.get("id") == SHOWCASE_ID:
            showcases[index] = entry
            break
    else:
        showcases.append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = [process_book(spec) for spec in BOOKS]
    finding_parts = []
    for result in results:
        finding_parts.append(
            f"{result['title']}: bookmarks={result['bookmark_count']} "
            f"(baseline={result['baseline_showcase_019_bookmark_count']}, "
            f"at_or_above={result['at_or_above_baseline']}), "
            f"font_candidates={result['font_candidate_count']}, "
            f"position_fallback_candidates="
            f"{result['position_fallback_candidate_count']} "
            f"(실험101 strict={result['experiment_101_strict_fallback_count']}), "
            f"kept_in_plan={result['position_fallback_candidates_kept_in_plan']}"
        )
    summary = {
        "config": {
            "heading_candidate_mode": "font (production default)",
            "position_fallback_enabled": True,
            "position_min_repeated_pages": 5,
            "position_fallback_tolerance": 2.0,
            "markdown_max_words": MAX_WORDS,
            "markdown_max_words_coverage": MAX_WORDS_COVERAGE,
        },
        "books": results,
        "all_at_or_above_baseline": all(
            result["at_or_above_baseline"] for result in results
        ),
        "finding": " | ".join(finding_parts),
    }
    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record_showcase(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
