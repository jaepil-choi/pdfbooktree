from __future__ import annotations

import json
from pathlib import Path

from pdfbooktree.metrics.toc_pages import compare_toc_pages
from pdfbooktree.models import PdfPageText
from pdfbooktree.toc.detect import detect_toc_pages
from pdfbooktree.toc.detect_from_bookmarks import detect_toc_pages_from_bookmarks
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.utils.jsonio import to_jsonable


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "001_toc_detection_interfaces"
OUTPUT_PATH = OUTPUT_DIR / "result.json"


def build_pages() -> list[PdfPageText]:
    """TOC page 탐지 인터페이스를 보여주기 위한 작은 page text를 만든다."""

    rows = [
        (
            1,
            [
                "Preface",
                "This page is narrative front matter without table entries.",
            ],
        ),
        (
            2,
            [
                "Contents",
                "Chapter 1 Introduction 3",
                "1.1 Motivation 7",
                "1.2 Background 12",
            ],
        ),
        (
            3,
            [
                "Chapter 2 Probability 25",
                "2.1 Random Variables 27",
                "2.2 Expectations 39",
            ],
        ),
        (
            4,
            [
                "Chapter 1 Introduction",
                "This is normal body text and should not be treated as TOC.",
            ],
        ),
    ]
    pages: list[PdfPageText] = []
    for pdf_page, lines in rows:
        text = "\n".join(lines)
        pages.append(
            PdfPageText(
                pdf_page=pdf_page,
                text=text,
                lines=lines,
                char_count=len(text),
            )
        )
    return pages


def build_bookmarks() -> list[dict[str, object]]:
    """bookmark 기반 detector에 넘길 기준 bookmark title을 만든다."""

    return [
        {"order": 1, "level": 1, "title": "Chapter 1 Introduction", "pdf_page": 5},
        {"order": 2, "level": 2, "title": "1.1 Motivation", "pdf_page": 9},
        {"order": 3, "level": 2, "title": "1.2 Background", "pdf_page": 14},
        {"order": 4, "level": 1, "title": "Chapter 2 Probability", "pdf_page": 27},
        {"order": 5, "level": 2, "title": "2.1 Random Variables", "pdf_page": 29},
        {"order": 6, "level": 2, "title": "2.2 Expectations", "pdf_page": 41},
    ]


def main() -> None:
    """TOC 탐지 public interface가 기대 page range를 반환하는지 보여준다."""

    pages = build_pages()
    features = calculate_page_features(pages, total_pages=120)
    runtime_detection = detect_toc_pages(features)
    bookmark_detection = detect_toc_pages_from_bookmarks(
        pages,
        build_bookmarks(),
        features=features,
    )
    expected_pages = [2, 3]
    runtime_comparison = compare_toc_pages(runtime_detection.pages, expected_pages)
    bookmark_comparison = compare_toc_pages(bookmark_detection.pages, expected_pages)

    assert runtime_detection.pages == expected_pages
    assert bookmark_detection.pages == expected_pages
    assert runtime_comparison.precision == 1.0
    assert runtime_comparison.recall == 1.0
    assert bookmark_comparison.precision == 1.0
    assert bookmark_comparison.recall == 1.0

    result = {
        "purpose": "TOC page detection interface를 synthetic page text로 검증한다.",
        "expected_pages": expected_pages,
        "runtime_detection": runtime_detection,
        "bookmark_detection": bookmark_detection,
        "runtime_comparison": runtime_comparison,
        "bookmark_comparison": bookmark_comparison,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(to_jsonable(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
