"""showcase 019: 두 실제 OCR overlay PDF를 geometry와 10K split으로 처리한다.

금리의 경제학 264쪽과 통계학원론 481쪽 OCR 결과를 한 script에서 순차 처리한다.
최상위 ``pdfbooktree`` 공개 API만 사용하며, embedded bookmark는 복사하지 않는다.
기본 position AND font 후보, 본문 line-spacing tolerance, 최소 5페이지 반복으로
bookmark를 만들고 Markdown 파일의 95% 이상이 10,000단어 이하가 되는 가장 얕은
bookmark level을 선택한다. 만족 level이 없으면 명시적 fallback으로 가장 깊은
level을 export한다.

실행:
    uv run python showcase/019_geometry_ocr_markdown_split_live.py
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
    inspect_plan_artifact,
)

try:  # 콘솔에서 한글이 깨지지 않게 한다.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT_DIR / "showcase" / "outputs" / "019_geometry_ocr_markdown_split_fallback_live"
)
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "019_geometry_ocr_markdown_split_live"
MAX_WORDS = 10_000
MAX_WORDS_COVERAGE = 0.95
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
]


def render_tree(title: str, bookmarks: list[dict[str, Any]]) -> str:
    """export된 PDF bookmark를 검토 가능한 tree txt로 만든다."""

    lines = [f"# {title} geometry bookmark tree", ""]
    for bookmark in bookmarks:
        indent = "  " * max(bookmark["level"] - 1, 0)
        lines.append(
            f"{indent}- [L{bookmark['level']}, p.{bookmark['pdf_page']}] "
            f"{bookmark['title']}"
        )
    return "\n".join(lines) + "\n"


def serialize_overflow(export) -> list[dict[str, Any]]:
    """public MarkdownExportResult의 overflow 정보를 JSON으로 바꾼다."""

    return [
        {
            "path": str(item.path.relative_to(ROOT_DIR)),
            "title": item.title,
            "level": item.level,
            "start_pdf_page": item.start_pdf_page,
            "end_pdf_page": item.end_pdf_page,
            "word_count": item.word_count,
        }
        for item in export.overflow_files
    ]


def process_book(spec: dict[str, Any]) -> dict[str, Any]:
    """한 OCR PDF를 공개 Processor로 처리하고 모든 공개 산출물을 검증한다."""

    pdf: Path = spec["pdf"]
    if not pdf.exists():
        raise FileNotFoundError(f"OCR overlay PDF가 없다: {pdf}")

    book_output = OUTPUT_DIR / spec["key"]
    typography = TypographyConfig(
        heading_candidate_mode="position_and_font",
        body_font_text_coverage=0.95,
        position_min_repeated_pages=5,
    )
    config = ProcessingConfig(
        skip_existing_bookmarks=False,
        typography=typography,
        markdown_split=MarkdownSplitConfig(
            max_words=MAX_WORDS,
            max_words_coverage=MAX_WORDS_COVERAGE,
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
    if export.manifest_path is None or not export.manifest_path.exists():
        raise RuntimeError(f"{spec['title']} Markdown manifest가 없다.")

    manifest = json.loads(export.manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("max_words") != MAX_WORDS
        or manifest.get("max_words_coverage") != MAX_WORDS_COVERAGE
    ):
        raise RuntimeError(f"{spec['title']} manifest의 10K 정책이 다르다.")
    trial_levels = manifest.get("levels", {})
    best_trial_level = None
    best_trial_stats: dict[str, Any] | None = None
    if trial_levels:
        best_trial_level, best_trial_stats = max(
            trial_levels.items(),
            key=lambda item: float(item[1].get("coverage", 0.0)),
        )
    reported_coverage = (
        coverage
        if export.constraint_satisfied
        else float((best_trial_stats or {}).get("coverage", 0.0))
    )

    split_files = sorted(export.output_dir.glob("*.md"))
    if len(split_files) != export.file_count:
        raise RuntimeError(
            f"{spec['title']} 실제 Markdown 수와 public result가 다르다: "
            f"{len(split_files)} != {export.file_count}"
        )

    plan_info = inspect_plan_artifact(book_output)
    exported = inspect_bookmarks(result.output_pdf)
    bookmarks = exported["bookmarks"]
    candidates_path = result.artifact_paths["heading_candidates"]
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    tolerance_evidence_count = sum(
        "position_tolerance_body_line_spacing" in item.get("evidence", [])
        for item in candidates
    )
    if tolerance_evidence_count != len(candidates):
        raise RuntimeError(
            f"{spec['title']} 일부 후보에 line-spacing tolerance evidence가 없다."
        )

    tree_path = book_output / "bookmark_tree.txt"
    tree_text = render_tree(spec["title"], bookmarks)
    tree_path.write_text(tree_text, encoding="utf-8")
    level_counts = dict(sorted(Counter(item["level"] for item in bookmarks).items()))
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
        "plan_validation": plan_info["validation"],
        "heading_candidate_count": len(candidates),
        "line_spacing_tolerance_evidence_count": tolerance_evidence_count,
        "tree_file": str(tree_path.relative_to(ROOT_DIR)),
        "tree_preview": tree_text.splitlines()[2:27],
        "markdown_split": {
            "max_words": MAX_WORDS,
            "max_words_coverage": MAX_WORDS_COVERAGE,
            "constraint_satisfied": export.constraint_satisfied,
            "fallback_used": export.fallback_used,
            "fallback_reason": export.fallback_reason,
            "chosen_level": export.chosen_level,
            "file_count": export.file_count,
            "actual_markdown_file_count": len(split_files),
            "total_word_count": export.total_word_count,
            "word_count_stats": export.word_count_stats,
            "reported_coverage": reported_coverage,
            "best_attempted_level": (
                int(best_trial_level) if best_trial_level is not None else None
            ),
            "best_attempted_stats": best_trial_stats,
            "level_trials": trial_levels,
            "overflow_files": serialize_overflow(export),
            "manifest_path": str(export.manifest_path.relative_to(ROOT_DIR)),
            "output_dir": str(export.output_dir.relative_to(ROOT_DIR)),
        },
        "warnings": result.warnings,
    }


def record_showcase(summary: dict[str, Any]) -> None:
    """두 OCR 책의 live 결과를 showcase registry에 기록한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "실제 금리의 경제학 264쪽과 통계학원론 481쪽 OCR overlay PDF를 하나의 "
            "showcase에서 공개 Processor로 재추출하고, 본문 line-spacing position "
            "tolerance와 10,000단어 이하 95% Markdown coverage, 조건 실패 시 가장 "
            "깊은 level을 export하는 명시적 fallback을 검증한다."
        ),
        "inputs": [str(spec["pdf"].relative_to(ROOT_DIR)) for spec in BOOKS],
        "outputs": str(OUTPUT_PATH.relative_to(ROOT_DIR)),
        "finding": summary["finding"],
        "command": "uv run python showcase/019_geometry_ocr_markdown_split_live.py",
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
        split = result["markdown_split"]
        finding_parts.append(
            f"{result['title']}: bookmarks={result['bookmark_count']}, "
            f"Markdown files={split['file_count']}, "
            f"10K satisfied={split['constraint_satisfied']}, "
            f"fallback={split['fallback_used']}, level={split['chosen_level']}, "
            f"coverage={split['reported_coverage']}, "
            f"tolerance evidence={result['line_spacing_tolerance_evidence_count']}/"
            f"{result['heading_candidate_count']}"
        )
    summary = {
        "config": {
            "heading_candidate_mode": "position_and_font",
            "body_font_text_coverage": 0.95,
            "position_min_repeated_pages": 5,
            "position_tolerance": "body_top_to_top_median_line_spacing",
            "markdown_max_words": MAX_WORDS,
            "markdown_max_words_coverage": MAX_WORDS_COVERAGE,
        },
        "books": results,
        "all_constraints_satisfied": all(
            result["markdown_split"]["constraint_satisfied"] for result in results
        ),
        "all_books_exported": all(
            result["markdown_split"]["file_count"] > 0 for result in results
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
