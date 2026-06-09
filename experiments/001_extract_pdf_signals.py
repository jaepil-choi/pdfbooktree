from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "001_extract_pdf_signals"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
MAX_TEXT_PAGES = 30

INPUT_PDFS = [
    {
        "id": "john_hull",
        "path": ROOT_DIR
        / "data"
        / "native-pdf-indexed"
        / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf",
    },
    {
        "id": "shreve_binomial",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf",
    },
]

TOC_KEYWORDS = (
    "contents",
    "table of contents",
    "목차",
    "차례",
)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_lines(text: str) -> list[str]:
    return [normalize_text(line) for line in text.splitlines() if normalize_text(line)]


def extract_line_final_number(line: str) -> int | None:
    cleaned = line.strip()
    match = re.search(r"(?<![\w.])(\d{1,4})[\s.)\]]*$", cleaned)
    if not match:
        return None
    return int(match.group(1))


def monotonicity(numbers: list[int]) -> float | None:
    if len(numbers) < 2:
        return None
    pairs = zip(numbers, numbers[1:], strict=False)
    non_decreasing_count = sum(1 for left, right in pairs if right >= left)
    return non_decreasing_count / (len(numbers) - 1)


def gap_stats(numbers: list[int]) -> dict[str, float | int | None]:
    if len(numbers) < 2:
        return {
            "mean_gap": None,
            "median_gap": None,
            "max_gap": None,
            "negative_gap_count": 0,
        }

    gaps = [right - left for left, right in zip(numbers, numbers[1:], strict=False)]
    return {
        "mean_gap": statistics.mean(gaps),
        "median_gap": statistics.median(gaps),
        "max_gap": max(gaps),
        "negative_gap_count": sum(1 for gap in gaps if gap < 0),
    }


def has_toc_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in TOC_KEYWORDS)


def calculate_page_feature(page_number: int, total_pages: int, text: str) -> dict[str, Any]:
    lines = extract_lines(text)
    line_lengths = [len(line) for line in lines]
    final_numbers = [
        final_number
        for line in lines
        if (final_number := extract_line_final_number(line)) is not None
    ]

    line_final_number_monotonicity = monotonicity(final_numbers)
    toc_keyword_presence = has_toc_keyword(text)
    mean_line_length = statistics.mean(line_lengths) if line_lengths else 0

    # 첫 실험용 임시 점수다. 모델 점수가 아니라 후보 페이지를 사람이 빠르게 보기 위한 정렬 기준이다.
    candidate_score = (
        len(final_numbers) * 2
        + (line_final_number_monotonicity or 0) * 5
        + (3 if toc_keyword_presence else 0)
        - (page_number / total_pages)
    )

    return {
        "pdf_page": page_number,
        "line_count": len(lines),
        "word_count": len(text.split()),
        "mean_line_length": mean_line_length,
        "line_final_number_count": len(final_numbers),
        "line_final_numbers": final_numbers,
        "line_final_number_monotonicity": line_final_number_monotonicity,
        "line_final_number_gap_stats": gap_stats(final_numbers),
        "page_position": page_number / total_pages,
        "toc_keyword_presence": toc_keyword_presence,
        "candidate_score": candidate_score,
    }


def extract_bookmarks(document: fitz.Document) -> list[dict[str, Any]]:
    bookmarks = []
    for order, item in enumerate(document.get_toc(simple=False), start=1):
        level, title, pdf_page = item[:3]
        bookmarks.append(
            {
                "order": order,
                "level": level,
                "title": normalize_text(title),
                "pdf_page": pdf_page if pdf_page and pdf_page > 0 else None,
            }
        )
    return bookmarks


def summarize_bookmarks(bookmarks: list[dict[str, Any]]) -> dict[str, Any]:
    page_numbers = [
        bookmark["pdf_page"]
        for bookmark in bookmarks
        if isinstance(bookmark.get("pdf_page"), int)
    ]
    level_counts = Counter(str(bookmark["level"]) for bookmark in bookmarks)
    empty_title_count = sum(1 for bookmark in bookmarks if not bookmark["title"])
    page_decrease_count = sum(
        1
        for left, right in zip(page_numbers, page_numbers[1:], strict=False)
        if right < left
    )

    return {
        "bookmark_count": len(bookmarks),
        "level_counts": dict(sorted(level_counts.items(), key=lambda item: int(item[0]))),
        "empty_title_count": empty_title_count,
        "page_decrease_count": page_decrease_count,
        "has_level_structure": len(level_counts) >= 2,
        "is_silver_label_candidate": (
            len(bookmarks) >= 20
            and empty_title_count == 0
            and page_decrease_count <= max(1, len(page_numbers) // 20)
            and len(level_counts) >= 2
        ),
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(text + "\n", encoding="utf-8")


def analyze_pdf(pdf_id: str, pdf_path: Path) -> dict[str, Any]:
    output_dir = OUTPUT_DIR / pdf_id
    text_output_dir = output_dir / "page_text_first_30"
    text_output_dir.mkdir(parents=True, exist_ok=True)

    with fitz.open(pdf_path) as document:
        metadata = {
            "pdf_id": pdf_id,
            "input_pdf": str(pdf_path.relative_to(ROOT_DIR)),
            "page_count": document.page_count,
            "extracted_text_page_count": min(MAX_TEXT_PAGES, document.page_count),
            "metadata": document.metadata,
        }
        bookmarks = extract_bookmarks(document)
        bookmark_summary = summarize_bookmarks(bookmarks)

        pages = []
        for page_index in range(min(MAX_TEXT_PAGES, document.page_count)):
            page_number = page_index + 1
            text = document.load_page(page_index).get_text("text")
            feature = calculate_page_feature(page_number, document.page_count, text)
            pages.append(feature | {"text_preview": normalize_text(text)[:500]})
            (text_output_dir / f"{page_number:03}.txt").write_text(text, encoding="utf-8")

    toc_candidates = sorted(
        pages,
        key=lambda page: page["candidate_score"],
        reverse=True,
    )[:10]

    write_json(output_dir / "metadata.json", metadata)
    write_json(output_dir / "bookmarks.json", bookmarks)
    write_json(output_dir / "bookmark_summary.json", bookmark_summary)
    write_jsonl(output_dir / "pages_first_30.jsonl", pages)
    write_json(output_dir / "toc_candidate_pages_first_30.json", toc_candidates)

    report = build_report(
        pdf_id=pdf_id,
        metadata=metadata,
        bookmark_summary=bookmark_summary,
        toc_candidates=toc_candidates,
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")

    return {
        "pdf_id": pdf_id,
        "metadata": metadata,
        "bookmark_summary": bookmark_summary,
        "top_toc_candidates": [
            {
                "pdf_page": candidate["pdf_page"],
                "candidate_score": candidate["candidate_score"],
                "line_final_number_count": candidate["line_final_number_count"],
                "line_final_number_monotonicity": candidate[
                    "line_final_number_monotonicity"
                ],
                "toc_keyword_presence": candidate["toc_keyword_presence"],
            }
            for candidate in toc_candidates[:5]
        ],
    }


def build_report(
    pdf_id: str,
    metadata: dict[str, Any],
    bookmark_summary: dict[str, Any],
    toc_candidates: list[dict[str, Any]],
) -> str:
    candidate_lines = "\n".join(
        (
            f"- PDF page {candidate['pdf_page']}: "
            f"score={candidate['candidate_score']:.2f}, "
            f"final_numbers={candidate['line_final_number_count']}, "
            f"monotonicity={candidate['line_final_number_monotonicity']}, "
            f"keyword={candidate['toc_keyword_presence']}"
        )
        for candidate in toc_candidates[:10]
    )

    return f"""# {pdf_id} PDF signal extraction

## 입력

- PDF: `{metadata["input_pdf"]}`
- 전체 페이지 수: {metadata["page_count"]}
- 텍스트 추출 페이지 수: {metadata["extracted_text_page_count"]}

## 북마크 요약

- 북마크 수: {bookmark_summary["bookmark_count"]}
- 레벨 분포: {bookmark_summary["level_counts"]}
- 빈 제목 수: {bookmark_summary["empty_title_count"]}
- 페이지 역행 수: {bookmark_summary["page_decrease_count"]}
- 계층 구조 존재: {bookmark_summary["has_level_structure"]}
- silver label 후보: {bookmark_summary["is_silver_label_candidate"]}

## 첫 30페이지 TOC 후보

{candidate_lines}
"""


def load_experiment_registry() -> dict[str, Any]:
    if not EXPERIMENTS_JSON.exists():
        return {"experiments": []}

    text = EXPERIMENTS_JSON.read_text(encoding="utf-8").strip()
    if not text:
        return {"experiments": []}

    loaded = json.loads(text)
    if isinstance(loaded, list):
        return {"experiments": loaded}
    if "experiments" not in loaded:
        loaded["experiments"] = []
    return loaded


def build_finding(results: list[dict[str, Any]]) -> str:
    parts = []
    for result in results:
        summary = result["bookmark_summary"]
        candidates = result["top_toc_candidates"]
        top_pages = ", ".join(str(candidate["pdf_page"]) for candidate in candidates[:3])
        candidate_with_keyword = [
            candidate["pdf_page"]
            for candidate in candidates
            if candidate["toc_keyword_presence"]
        ]
        keyword_text = (
            f"keyword 후보 page {candidate_with_keyword}"
            if candidate_with_keyword
            else "상위 후보에서 keyword는 확인되지 않음"
        )
        parts.append(
            f"{result['pdf_id']}는 bookmark {summary['bookmark_count']}개를 "
            f"추출했고 level 분포는 {summary['level_counts']}이다. "
            f"빈 제목 {summary['empty_title_count']}개, 페이지 역행 "
            f"{summary['page_decrease_count']}개로 silver label 후보 판단은 "
            f"{summary['is_silver_label_candidate']}이다. 첫 30페이지 임시 TOC "
            f"후보 상위 page는 {top_pages}이며 {keyword_text}."
        )

    return " ".join(parts)


def update_experiment_registry(results: list[dict[str, Any]]) -> None:
    registry = load_experiment_registry()
    experiments = [
        experiment
        for experiment in registry["experiments"]
        if experiment.get("id") != EXPERIMENT_ID
    ]
    experiments.append(
        {
            "id": EXPERIMENT_ID,
            "purpose": (
                "silver label PDF에서 기존 bookmark를 정답 후보로 추출할 수 있는지 "
                "확인하고, 첫 30페이지의 text layer와 TOC 탐지용 page feature가 "
                "충분히 안정적인지 검증한다."
            ),
            "inputs": [
                str(item["path"].relative_to(ROOT_DIR))
                for item in INPUT_PDFS
            ],
            "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
            "finding": build_finding(results),
            "ran_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    registry["experiments"] = experiments
    write_json(EXPERIMENTS_JSON, registry)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for item in INPUT_PDFS:
        if not item["path"].exists():
            raise FileNotFoundError(item["path"])
        results.append(analyze_pdf(item["id"], item["path"]))

    write_json(OUTPUT_DIR / "summary.json", results)
    update_experiment_registry(results)

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
