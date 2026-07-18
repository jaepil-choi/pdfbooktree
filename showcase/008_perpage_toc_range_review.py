"""showcase 008: per-page LlmTocRangeReviewer를 real data + live call로 검증한다.

experiment 038에서 검증한 per-page TOC range 보정 흐름을 src 공개 인터페이스
(`LlmTocRangeReviewer`)로 옮긴 뒤, 로컬에 있는 정답 라벨 PDF에 대해 실제로
TOC page range를 복구하는지 확인한다.

흐름(책별):
1. 학습된 ML detector(`detect_toc_pages`)로 후보 range를 얻어 seed를 만든다.
2. `LlmTocRangeReviewer.review()`를 live 호출해 per-page 판정으로 range를 보정한다.
3. ML range와 LLM 보정 range를 각각 정답(`answer_toc_ranges_manual.json`)과
   비교해 precision/recall과 start/end error를 기록한다.

정답 라벨은 평가용이며 입력 신호로는 쓰지 않는다(검증 비교에만 사용). LLM은
Upstage Solar chat(solar-pro3) 텍스트 경로만 쓴다. synthetic/mock/stub 입력은
쓰지 않는다.

실행:
    uv run python showcase/008_perpage_toc_range_review.py

주의: ML detector는 학습된 모델 artifact가 필요하다
(outputs/300study_toc_page_dataset_model/toc_page_dataset_model.joblib).
없으면 해당 책은 blocked로 기록한다.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
from dotenv import load_dotenv

from pdfbooktree.config import LlmRangeReviewConfig, TocMlDetectionConfig
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.toc.detect import detect_toc_pages
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.toc.llm_range_review import LlmTocRangeReviewer

try:  # 콘솔에서 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "008_perpage_toc_range_review"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "008_perpage_toc_range_review"
LABELS_JSON = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"
MODEL_PATH = (
    ROOT_DIR
    / "outputs"
    / "300study_toc_page_dataset_model"
    / "toc_page_dataset_model.joblib"
)
MAX_SEARCH_PAGES = 80


def _prf(predicted: list[int], gold: list[int]) -> dict[str, Any]:
    """예측 page와 정답 page의 precision/recall/start·end error를 계산한다."""

    pred_set, gold_set = set(predicted), set(gold)
    tp = len(pred_set & gold_set)
    precision = tp / len(pred_set) if pred_set else 0.0
    recall = tp / len(gold_set) if gold_set else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    start_err = abs(min(predicted) - min(gold)) if predicted and gold else None
    end_err = abs(max(predicted) - max(gold)) if predicted and gold else None
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "start_error": start_err,
        "end_error": end_err,
        "missing": sorted(gold_set - pred_set),
        "extra": sorted(pred_set - gold_set),
    }


def run_label(label: dict[str, Any], reviewer: LlmTocRangeReviewer) -> dict[str, Any]:
    """단일 정답 라벨 PDF에 ML detect + LLM review를 live 호출한다."""

    pdf_path = ROOT_DIR / label["input_pdf"]
    gold = label["toc_pages"]
    record: dict[str, Any] = {
        "id": label["id"],
        "input_pdf": label["input_pdf"],
        "gold_pages": gold,
    }
    if not pdf_path.exists():
        record["status"] = "missing_pdf"
        return record
    if not MODEL_PATH.exists():
        record["status"] = "blocked_no_model"
        return record

    with fitz.open(pdf_path) as document:
        total_pages = document.page_count

    pages = extract_page_texts(pdf_path, max_pages=min(MAX_SEARCH_PAGES, total_pages))
    features = calculate_page_features(pages, total_pages)
    detection = detect_toc_pages(features, TocMlDetectionConfig(model_path=MODEL_PATH))
    record["ml_pages"] = detection.pages
    record["ml_metrics"] = _prf(detection.pages, gold)

    review = reviewer.review(pdf_path, detection, total_pages)
    record["llm_pages"] = review.pages
    record["llm_anchor"] = review.anchor_page
    record["llm_stage"] = review.stage
    record["llm_calls"] = review.llm_calls
    record["llm_metrics"] = _prf(review.pages, gold)
    record["status"] = "ok"

    case_dir = OUTPUT_DIR / label["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "review.json").write_text(
        json.dumps(
            {
                "ml_pages": detection.pages,
                "llm_pages": review.pages,
                "anchor": review.anchor_page,
                "stage": review.stage,
                "decisions": review.decisions,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return record


def build_finding(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    perfect = 0
    for r in results:
        if r.get("status") != "ok":
            parts.append(f"{r['id']}: {r.get('status')}")
            continue
        llm = r["llm_metrics"]
        ml = r["ml_metrics"]
        if llm["precision"] == 1.0 and llm["recall"] == 1.0:
            perfect += 1
        parts.append(
            f"{r['id']}: ML={r['ml_pages']}(P{ml['precision']}/R{ml['recall']}) "
            f"-> LLM={r['llm_pages']}(P{llm['precision']}/R{llm['recall']}, "
            f"stage={r['llm_stage']}, calls={r['llm_calls']})"
        )
    ok = [r for r in results if r.get("status") == "ok"]
    head = (
        f"ML detector seed -> per-page LlmTocRangeReviewer로 {len(ok)}권의 TOC range를 "
        f"live 보정했다. LLM 보정 후 precision/recall 동시 1.0인 책은 {perfect}/{len(ok)}권이다. "
    )
    return head + " | ".join(parts)


def record_showcase(results: list[dict[str, Any]], finding: str) -> None:
    """showcase.json에 이번 실행 기록을 추가한다(같은 id는 교체)."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "experiment 038에서 검증한 per-page TOC range 보정을 src 공개 인터페이스"
            "(LlmTocRangeReviewer)로 옮긴 뒤, 로컬 정답 라벨 PDF에서 ML detector seed "
            "-> LLM per-page 보정 range가 정답에 얼마나 맞는지 real data + live call로 "
            "검증한다. has_page_numbers gate와 forward gap/backward 엄격 확장을 확인한다."
        ),
        "inputs": [r["input_pdf"] for r in results],
        "outputs": "showcase/outputs/008_perpage_toc_range_review/result.json",
        "labels": "experiments/labels/answer_toc_ranges_manual.json",
        "model": "solar-pro3",
        "finding": finding,
        "command": "uv run python showcase/008_perpage_toc_range_review.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    data["showcases"] = [s for s in data["showcases"] if s.get("id") != SHOWCASE_ID]
    data["showcases"].append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    # 사내 프록시 self-signed CA 대응: OS 신뢰 저장소 사용.
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        pass
    load_dotenv(ROOT_DIR / ".env")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    labels = json.loads(LABELS_JSON.read_text(encoding="utf-8"))["labels"]
    reviewer = LlmTocRangeReviewer(LlmRangeReviewConfig())
    results = [run_label(label, reviewer) for label in labels]

    finding = build_finding(results)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "purpose": (
                    "per-page LlmTocRangeReviewer를 로컬 정답 라벨 PDF에 live 호출해 "
                    "TOC range 복구 정확도를 검증한다."
                ),
                "source_experiment": "038_full_flow_toc_to_bookmark",
                "case_count": len(results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    record_showcase(results, finding)

    print("=== per-page LlmTocRangeReviewer (real data, GT labeled PDFs) ===")
    for r in results:
        if r.get("status") != "ok":
            print(f"- {r['id']}: {r.get('status')}")
            continue
        llm = r["llm_metrics"]
        print(
            f"- {r['id']}: ML={r['ml_pages']} -> LLM={r['llm_pages']} "
            f"(P{llm['precision']}/R{llm['recall']} stage={r['llm_stage']} "
            f"calls={r['llm_calls']} gold={r['gold_pages']})"
        )


if __name__ == "__main__":
    main()
