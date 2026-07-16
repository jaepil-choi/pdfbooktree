"""showcase 022: 승격한 evaluation 공개 함수를 실제 책 3권으로 검증한다.

Phase 4 첫 증분에서 `src/pdfbooktree/evaluation.py`로 승격한
``match_bookmark_plans()``와, 기존 ``assess_outline_quality()``를 gold
reference 품질 판정에 재사용하는 방식을 실제 책 3권으로 확인한다. 세 책 모두
실험 102(``experiments/102_engine_bookmark_fuzzy_eval.py``)의 400권 결과에서
고른 실제 사례이고, 세 가지 다른 상황을 보여준다.

1. ``실습과_그림으로_배우는_리눅스_구조`` (305쪽) - clean gold, 실험 102에서
   F1=0.9028로 높게 나온 긍정 사례. ``match_bookmark_plans()``의 matched
   결과가 대부분을 차지하는지 확인한다.
2. ``생각정리를위한_시간의기술`` (225쪽) - embedded bookmark가 2개뿐이라
   ``assess_outline_quality()``가 ``placeholder_or_tiny``로 판정해야 하는
   junk gold. 실험 102에서 predicted_count=0이었던 책이라, gold 품질이
   나쁘면서 예측도 비는 이중 신호를 보여준다.
3. ``Case Studies, 3rd Edition`` (127쪽) - gold item 11개로 quality 판정은
   clean(``is_low_quality=False``)이지만, 실험 102에서 F1=0.0으로 engine이
   실제로 놓친 사례다. gold 품질 판정과 engine 성능 판정이 서로 다른
   신호라는 것, 그리고 missed/extra 상세가 "왜" 실패했는지 보여준다.

실행:
    uv run python showcase/022_bookmark_plan_evaluation.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz

from pdfbooktree import (
    TypographyConfig,
    analyze_pdf,
    assess_outline_quality,
    infer_bookmarks,
    match_bookmark_plans,
)
from pdfbooktree.pdf.outline import outline_to_plan, read_outline

try:  # 콘솔에서 한글이 깨지지 않게 한다.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "022_bookmark_plan_evaluation"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "022_bookmark_plan_evaluation"

SAMPLE_LIMIT = 5

BOOKS = [
    {
        "key": "clean_gold_good_match",
        "title": "실습과 그림으로 배우는 리눅스 구조 (다케우치 사토루)",
        "pdf": ROOT_DIR
        / "data"
        / "300STUDY"
        / "a_books"
        / "textbook"
        / "실습과_그림으로_배우는_리눅스_구조_다케우치_사토루.pdf",
        "expect_low_quality": False,
    },
    {
        "key": "junk_gold_zero_prediction",
        "title": "생각정리를위한 시간의기술 (나가타 도요시)",
        "pdf": ROOT_DIR
        / "data"
        / "300STUDY"
        / "a_books"
        / "normalbook"
        / "생각정리를위한_시간의기술_나가타도요시_생각정리연구소.pdf",
        "expect_low_quality": True,
    },
    {
        "key": "clean_gold_poor_match",
        "title": "Case Studies, 3rd Edition",
        "pdf": ROOT_DIR
        / "data"
        / "300STUDY"
        / "textbooks"
        / "Books"
        / "Case Studies, 3rd Edition"
        / "Case Studies, 3rd Edition.pdf",
        "expect_low_quality": False,
    },
]


def evaluate_book(spec: dict[str, Any]) -> dict[str, Any]:
    """gold quality 판정과 fuzzy matching을 실제 public 함수로 실행한다."""

    pdf: Path = spec["pdf"]
    if not pdf.exists():
        raise FileNotFoundError(f"입력 PDF가 없다: {pdf}")

    with fitz.open(pdf) as document:
        total_pages = document.page_count

    existing_items = read_outline(pdf)
    gold = outline_to_plan(existing_items)
    quality = assess_outline_quality(existing_items, total_pages)
    if quality.is_low_quality is not spec["expect_low_quality"]:
        raise RuntimeError(
            f"{spec['title']}: 예상 gold quality 판정과 다르다 - "
            f"expected={spec['expect_low_quality']}, actual={quality.is_low_quality}, "
            f"reasons={quality.reasons}"
        )

    config = TypographyConfig()
    analysis = analyze_pdf(pdf, config)
    inference = infer_bookmarks(analysis, config)

    match = match_bookmark_plans(gold, inference.plan)

    return {
        "key": spec["key"],
        "title": spec["title"],
        "input_pdf": str(pdf.relative_to(ROOT_DIR)),
        "page_count": total_pages,
        "gold_count": len(gold),
        "predicted_count": len(inference.plan),
        "gold_quality": {
            "is_low_quality": quality.is_low_quality,
            "reasons": quality.reasons,
        },
        "metrics": {
            "true_positive_count": match.metrics.true_positive_count,
            "precision": match.metrics.precision,
            "recall": match.metrics.recall,
            "f1": match.metrics.f1,
            "accuracy_jaccard": match.metrics.accuracy_jaccard,
            "exact_page_match_rate": match.metrics.exact_page_match_rate,
        },
        "missed_sample": [item.title for item in match.missed[:SAMPLE_LIMIT]],
        "missed_count": len(match.missed),
        "extra_sample": [item.title for item in match.extra[:SAMPLE_LIMIT]],
        "extra_count": len(match.extra),
    }


def record_showcase(summary: dict[str, Any]) -> None:
    """evaluation 공개 함수 검증 결과를 showcase registry에 기록한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "src/pdfbooktree/evaluation.py로 승격한 match_bookmark_plans()와 "
            "gold reference 품질 판정에 재사용한 assess_outline_quality()를 "
            "실제 책 3권(clean gold 고성능, junk gold, clean gold 저성능)으로 "
            "검증한다."
        ),
        "inputs": [str(spec["pdf"].relative_to(ROOT_DIR)) for spec in BOOKS],
        "outputs": str(OUTPUT_PATH.relative_to(ROOT_DIR)),
        "finding": summary["finding"],
        "command": "uv run python showcase/022_bookmark_plan_evaluation.py",
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
    results = [evaluate_book(spec) for spec in BOOKS]
    finding_parts = []
    for result in results:
        finding_parts.append(
            f"{result['title']}: gold={result['gold_count']}, "
            f"predicted={result['predicted_count']}, "
            f"is_low_quality={result['gold_quality']['is_low_quality']}"
            f"({result['gold_quality']['reasons']}), "
            f"f1={result['metrics']['f1']}, "
            f"missed={result['missed_count']}, extra={result['extra_count']}"
        )
    summary = {
        "books": results,
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
