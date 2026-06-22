"""showcase 002: LlmTocExtractor public interface를 real data + live call로 보여준다.

experiments.json의 실제 PDF에서 탐지된 TOC page range를 입력으로
`LlmTocExtractor`(기본 config = solar-pro2 text 경로)를 live 호출해 목차 항목을
구조화 추출한다. bookmark가 있는 책은 bookmark title을 weak reference로 삼아
title-only(소문자 정규화) item precision/recall을 보여준다.

synthetic/mock/stub 입력은 쓰지 않는다. Upstage API와 실제 PDF가 필요하다.

실행:
    uv run python showcase/002_llm_toc_item_extraction.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rapidfuzz import fuzz

from pdfbooktree import LlmTocExtractionConfig, LlmTocExtractor
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks, title_has_letter
from pdfbooktree.utils.jsonio import to_jsonable

try:  # 콘솔에서 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "002_llm_toc_item_extraction"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "002_llm_toc_item_extraction"
MATCH_THRESHOLD = 80

PDF_CASES = [
    {
        "id": "john_hull",
        "path": ROOT_DIR
        / "data"
        / "native-pdf-indexed"
        / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf",
        "toc_pages": list(range(5, 16)),
    },
    {
        "id": "shreve_binomial",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf",
        "toc_pages": list(range(3, 12)),
    },
    {
        "id": "luenberger_investment_science",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "David G. Luenberger, Investment Science 2nd - adobeOCR - indexed.pdf",
        "toc_pages": list(range(7, 21)),
    },
]


def evaluate_against_bookmarks(
    item_titles: list[str], bookmark_titles: list[str]
) -> dict[str, Any]:
    """bookmark title weak reference로 title-only item precision/recall을 잰다.

    bookmark target page와 목차 printed_page는 offset만큼 다르므로 page는 보지
    않고 title로만 매칭하고, OCR 대문자 차이를 없애려 소문자로 정규화한다.
    """

    norm_items = [t.lower() for t in item_titles]
    norm_bookmarks = [t.lower() for t in bookmark_titles]
    matched_items = sum(
        1
        for it in norm_items
        if max((fuzz.token_set_ratio(it, bt) for bt in norm_bookmarks), default=0)
        >= MATCH_THRESHOLD
    )
    matched_bookmarks = sum(
        1
        for bt in norm_bookmarks
        if max((fuzz.token_set_ratio(bt, it) for it in norm_items), default=0)
        >= MATCH_THRESHOLD
    )
    precision = matched_items / len(norm_items) if norm_items else 0.0
    recall = matched_bookmarks / len(norm_bookmarks) if norm_bookmarks else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {
        "item_count": len(norm_items),
        "bookmark_reference_count": len(norm_bookmarks),
        "matched_items": matched_items,
        "matched_bookmarks": matched_bookmarks,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def monotonic_fraction(printed_pages: list[int]) -> float | None:
    """printed_page가 직전 항목보다 작지 않은 비율이다."""

    if len(printed_pages) < 2:
        return None
    non_decreasing = sum(1 for a, b in zip(printed_pages, printed_pages[1:]) if b >= a)
    return round(non_decreasing / (len(printed_pages) - 1), 4)


def analyze_case(case: dict[str, Any], extractor: LlmTocExtractor) -> dict[str, Any]:
    """실제 PDF에서 LlmTocExtractor를 live 호출해 결과를 요약한다."""

    pdf_path = Path(case["path"])
    if not pdf_path.exists():
        raise FileNotFoundError(f"showcase real data가 없다: {pdf_path}")

    items = extractor.extract(pdf_path, case["toc_pages"])
    assert items, "LlmTocExtractor가 실제 PDF에서 목차 항목을 추출해야 한다."

    item_titles = [item.title for item in items]
    printed_pages = [item.printed_page for item in items if item.printed_page]

    bookmark_titles = [
        bookmark["title"]
        for bookmark in extract_existing_bookmarks(pdf_path)
        if bookmark["title"] and title_has_letter(bookmark["title"])
    ]
    weak_reference = (
        evaluate_against_bookmarks(item_titles, bookmark_titles)
        if bookmark_titles
        else None
    )

    return {
        "id": case["id"],
        "input_pdf": str(pdf_path.relative_to(ROOT_DIR)),
        "toc_pages": case["toc_pages"],
        "model": extractor.config.text_model,
        "mode": extractor.config.mode,
        "item_count": len(items),
        "level_distribution": _level_distribution(items),
        "printed_page_monotonic_fraction": monotonic_fraction(printed_pages),
        "bookmark_weak_reference": weak_reference,
        "sample_items": [
            {
                "title": item.title,
                "level": item.level,
                "printed_page": item.printed_page,
                "source_pdf_page": item.source_pdf_page,
                "confidence": item.confidence,
            }
            for item in items[:8]
        ],
    }


def _level_distribution(items: list[Any]) -> dict[int, int]:
    distribution: dict[int, int] = {}
    for item in items:
        distribution[item.level] = distribution.get(item.level, 0) + 1
    return dict(sorted(distribution.items()))


def record_showcase(finding: str) -> None:
    """showcase.json에 이번 실행 기록을 추가한다(같은 id는 교체)."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "LlmTocExtractor public interface가 실제 PDF의 탐지된 TOC page range에서 "
            "Upstage(solar-pro2) live call로 목차 항목을 구조화 추출함을 보여주고, "
            "bookmark title weak reference로 item precision/recall을 확인한다."
        ),
        "inputs": [str(Path(case["path"]).relative_to(ROOT_DIR)) for case in PDF_CASES],
        "outputs": "showcase/outputs/002_llm_toc_item_extraction/result.json",
        "finding": finding,
        "command": "uv run python showcase/002_llm_toc_item_extraction.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    data["showcases"] = [s for s in data["showcases"] if s.get("id") != SHOWCASE_ID]
    data["showcases"].append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def build_finding(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for result in results:
        weak = result["bookmark_weak_reference"]
        weak_text = (
            f"weak ref precision {weak['precision']} recall {weak['recall']} "
            f"f1 {weak['f1']}"
            if weak
            else "weak ref 없음"
        )
        parts.append(
            f"{result['id']}(TOC {result['toc_pages'][0]}-{result['toc_pages'][-1]}): "
            f"{result['item_count']}개 항목, {weak_text}, "
            f"printed_page 단조성 {result['printed_page_monotonic_fraction']}."
        )
    return " ".join(parts)


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    # 기본 config: mode=text, text_model=solar-pro2, temperature=0.0
    extractor = LlmTocExtractor(LlmTocExtractionConfig())

    results = [analyze_case(case, extractor) for case in PDF_CASES]
    summary = {
        "purpose": (
            "LlmTocExtractor public interface를 실제 PDF text layer와 Upstage live "
            "call로 호출해 목차 항목 추출이 동작함을 보여준다."
        ),
        "source_experiment": "014_upstage_toc_item_extraction",
        "model": extractor.config.text_model,
        "case_count": len(results),
        "results": results,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(to_jsonable(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    finding = build_finding(results)
    record_showcase(finding)
    print(json.dumps(to_jsonable(summary), ensure_ascii=False, indent=2))
    print("\n=== finding ===")
    print(finding)


if __name__ == "__main__":
    main()
