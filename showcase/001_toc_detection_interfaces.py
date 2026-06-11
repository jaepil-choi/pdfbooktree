from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fitz

from pdfbooktree.metrics.toc_pages import compare_toc_pages
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.toc.detect import detect_toc_pages
from pdfbooktree.toc.detect_from_bookmarks import detect_toc_pages_from_bookmarks
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.utils.jsonio import to_jsonable


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "001_toc_detection_interfaces"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
MAX_TEXT_PAGES = 30

PDF_CASES = [
    {
        "id": "john_hull",
        "path": ROOT_DIR
        / "data"
        / "native-pdf-indexed"
        / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf",
        "expected_pages": list(range(5, 16)),
    },
    {
        "id": "shreve_binomial",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf",
        "expected_pages": list(range(3, 12)),
    },
    {
        "id": "luenberger_investment_science",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "David G. Luenberger, Investment Science 2nd - adobeOCR - indexed.pdf",
        "expected_pages": list(range(7, 21)),
    },
]


def analyze_case(case: dict[str, Any]) -> dict[str, Any]:
    """실제 PDF에서 text와 bookmark를 읽어 TOC detector interface를 호출한다."""

    pdf_path = Path(case["path"])
    if not pdf_path.exists():
        raise FileNotFoundError(f"showcase real data가 없다: {pdf_path}")

    with fitz.open(pdf_path) as document:
        total_pages = document.page_count

    pages = extract_page_texts(pdf_path, max_pages=MAX_TEXT_PAGES)
    bookmarks = extract_existing_bookmarks(pdf_path)
    features = calculate_page_features(pages, total_pages=total_pages)
    runtime_detection = detect_toc_pages(features)
    bookmark_detection = detect_toc_pages_from_bookmarks(
        pages,
        bookmarks,
        features=features,
    )
    expected_pages = list(case["expected_pages"])
    runtime_comparison = compare_toc_pages(
        runtime_detection.pages,
        expected_pages,
    )
    bookmark_comparison = compare_toc_pages(
        bookmark_detection.pages,
        expected_pages,
    )

    assert pages, "실제 PDF text layer에서 page text를 읽어야 한다."
    assert bookmarks, "기존 bookmark를 실제 PDF에서 읽어야 한다."
    assert runtime_detection.pages, (
        "runtime detector가 실제 PDF에서 후보를 찾아야 한다."
    )
    assert bookmark_detection.pages, (
        "bookmark-guided detector가 실제 PDF에서 후보를 찾아야 한다."
    )
    assert runtime_comparison.precision is not None
    assert runtime_comparison.recall is not None
    assert bookmark_comparison.precision is not None
    assert bookmark_comparison.recall is not None

    return {
        "id": case["id"],
        "input_pdf": str(pdf_path.relative_to(ROOT_DIR)),
        "total_pages": total_pages,
        "observed_text_pages": len(pages),
        "bookmark_count": len(bookmarks),
        "expected_pages_from_experiment_003": expected_pages,
        "runtime_detection": summarize_detection(runtime_detection),
        "bookmark_detection": summarize_detection(bookmark_detection),
        "runtime_comparison": runtime_comparison,
        "bookmark_comparison": bookmark_comparison,
    }


def summarize_detection(detection: Any) -> dict[str, Any]:
    """showcase 결과 파일에 남길 detector 출력을 핵심 필드로 줄인다."""

    return {
        "pages": detection.pages,
        "start_page": detection.start_page,
        "end_page": detection.end_page,
        "confidence": detection.confidence,
        "method": detection.method,
        "candidate_count": len(detection.candidates),
    }


def main() -> None:
    """experiments.json의 실제 PDF들로 TOC 탐지 interface 동작을 보여준다."""

    results = [analyze_case(case) for case in PDF_CASES]
    runtime_exact_count = sum(
        1
        for result in results
        if result["runtime_detection"]["pages"]
        == result["expected_pages_from_experiment_003"]
    )
    bookmark_exact_count = sum(
        1
        for result in results
        if result["bookmark_detection"]["pages"]
        == result["expected_pages_from_experiment_003"]
    )
    summary = {
        "purpose": (
            "experiments.json에 기록된 실제 PDF text layer와 기존 bookmark를 읽어 "
            "TOC page detection interface가 live call로 동작하는지 보여준다."
        ),
        "source_experiment": "003_ensemble_toc_page_labelers",
        "max_text_pages": MAX_TEXT_PAGES,
        "case_count": len(results),
        "runtime_exact_count": runtime_exact_count,
        "bookmark_exact_count": bookmark_exact_count,
        "results": results,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(to_jsonable(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(to_jsonable(summary), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
