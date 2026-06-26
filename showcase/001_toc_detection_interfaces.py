from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz

from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.toc.detect import detect_toc_pages
from pdfbooktree.toc.detect_from_bookmarks import detect_toc_pages_from_bookmarks
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.utils.jsonio import to_jsonable


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "001_toc_detection_interfaces"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "001_toc_detection_interfaces"
MAX_TEXT_PAGES = 40


def discover_pdf_cases() -> list[dict[str, Any]]:
    """현재 data/ 아래 sample PDF를 showcase 입력으로 사용한다."""

    return [
        {
            "id": re.sub(r"[^0-9A-Za-z가-힣]+", "_", path.stem).strip("_")[:80],
            "path": path,
        }
        for path in sorted(DATA_DIR.rglob("*.pdf"))
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

    assert pages, "실제 PDF text layer에서 page text를 읽어야 한다."
    assert bookmarks, "기존 bookmark를 실제 PDF에서 읽어야 한다."

    warnings: list[str] = []
    if not runtime_detection.pages:
        warnings.append("runtime detector가 TOC page 후보를 찾지 못했다.")
    if not bookmark_detection.pages:
        warnings.append("bookmark-guided detector가 TOC page 후보를 찾지 못했다.")

    return {
        "id": case["id"],
        "input_pdf": str(pdf_path.relative_to(ROOT_DIR)),
        "total_pages": total_pages,
        "observed_text_pages": len(pages),
        "bookmark_count": len(bookmarks),
        "runtime_detection": summarize_detection(runtime_detection),
        "bookmark_detection": summarize_detection(bookmark_detection),
        "warnings": warnings,
    }


def summarize_detection(detection: Any) -> dict[str, Any]:
    """showcase 결과 파일에 남길 detector 출력을 핵심 필드로 줄인다."""

    selected_pages = set(detection.pages)
    return {
        "pages": detection.pages,
        "start_page": detection.start_page,
        "end_page": detection.end_page,
        "confidence": detection.confidence,
        "method": detection.method,
        "candidate_count": len(detection.candidates),
        "selected_candidate_features": [
            summarize_candidate(candidate)
            for candidate in detection.candidates
            if candidate["pdf_page"] in selected_pages
        ],
        "top_offset_consistency_candidates": [
            summarize_candidate(candidate)
            for candidate in sorted(
                detection.candidates,
                key=lambda candidate: candidate.get("offset_consistency_score", 0.0),
                reverse=True,
            )[:5]
            if candidate.get("offset_consistency_score", 0.0) > 0
        ],
    }


def summarize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """새 TOC feature가 showcase output에 드러나도록 후보 row를 줄인다."""

    return {
        "pdf_page": candidate["pdf_page"],
        "bookmark_anchor_score": candidate.get("bookmark_anchor_score", 0.0),
        "offset_consistency_score": candidate.get("offset_consistency_score", 0.0),
        "matched_bookmark_count": candidate.get("matched_bookmark_count", 0),
        "vote_count": candidate.get("vote_count", 0),
        "voters": candidate.get("voters", []),
    }


def build_finding(results: list[dict[str, Any]]) -> str:
    """새 sample data에 대한 detector 실행 요약을 만든다."""

    parts: list[str] = []
    for result in results:
        runtime_pages = result["runtime_detection"]["pages"]
        bookmark_pages = result["bookmark_detection"]["pages"]
        runtime_text = (
            f"runtime {runtime_pages}" if runtime_pages else "runtime 후보 없음"
        )
        bookmark_text = (
            f"bookmark-guided {bookmark_pages}"
            if bookmark_pages
            else "bookmark-guided 후보 없음"
        )
        warning_text = f" warning={result['warnings']}" if result["warnings"] else ""
        parts.append(
            f"{result['id']}는 bookmark {result['bookmark_count']}개, "
            f"{runtime_text}, {bookmark_text}.{warning_text}"
        )
    return " ".join(parts)


def record_showcase(results: list[dict[str, Any]], finding: str) -> None:
    """showcase.json에 이번 실행 기록을 추가한다(같은 id는 교체)."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "TOC page detection public interface가 현재 data/ 아래 실제 PDF text layer와 "
            "기존 bookmark를 읽는 live call에서 동작함을 보여준다."
        ),
        "inputs": [result["input_pdf"] for result in results],
        "outputs": "showcase/outputs/001_toc_detection_interfaces/result.json",
        "finding": finding,
        "command": "uv run python showcase/001_toc_detection_interfaces.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    data["showcases"] = [s for s in data["showcases"] if s.get("id") != SHOWCASE_ID]
    data["showcases"].append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    """현재 data/의 실제 PDF들로 TOC 탐지 interface 동작을 보여준다."""

    pdf_cases = discover_pdf_cases()
    if not pdf_cases:
        raise FileNotFoundError(DATA_DIR)

    results = [analyze_case(case) for case in pdf_cases]
    finding = build_finding(results)
    summary = {
        "purpose": (
            "현재 data/ 아래 실제 PDF text layer와 기존 bookmark를 읽어 TOC page "
            "detection interface가 live call로 동작하는지 보여준다."
        ),
        "max_text_pages": MAX_TEXT_PAGES,
        "case_count": len(results),
        "runtime_detected_count": sum(
            1 for result in results if result["runtime_detection"]["pages"]
        ),
        "bookmark_detected_count": sum(
            1 for result in results if result["bookmark_detection"]["pages"]
        ),
        "results": results,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(to_jsonable(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_showcase(results, finding)
    print(json.dumps(to_jsonable(summary), ensure_ascii=False, indent=2))
    print("\n=== finding ===")
    print(finding)


if __name__ == "__main__":
    main()
