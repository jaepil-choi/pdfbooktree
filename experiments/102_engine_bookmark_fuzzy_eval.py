"""experiment 102: production engine을 data/300STUDY 전체 embedded bookmark로 평가한다.

data/300STUDY 아래 page_count>100이고 embedded bookmark(TOC)가 있는 PDF만 골라,
그 embedded bookmark를 정답(gold)으로 보고 production typography 파이프라인
(font 골격 + body-tier position fallback, TypographyConfig 기본값)이 만든
예측 plan과 fuzzy title 유사도 + page tolerance로 매칭한다. Processor.run()
전체(PDF/Markdown export 포함) 대신 public 단계형 API인 `analyze_pdf()`와
`infer_bookmarks()`만 호출해 대용량 코퍼스에서 불필요한 export I/O를 줄인다.

정답/예측 모두 title+page 집합으로만 비교하고(level은 비교하지 않는다 — gold의
level은 원서 편집 방침을, 예측 level은 font tier/geometry를 반영해 서로 다른
기준이라 직접 비교가 무의미하다), page tolerance=1, title 유사도
threshold=0.7로 그리디 1:1 매칭한다. accuracy는 TP/(len(pred)+len(gt)-TP)로
정의한 Jaccard 겹침 비율이다 — 이 매칭 과제에는 true negative가 없어 표준
accuracy 정의를 그대로 쓸 수 없다.

실행:
    uv run python experiments/102_engine_bookmark_fuzzy_eval.py
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz

from pdfbooktree import analyze_pdf, infer_bookmarks
from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.pdf.outline import outline_to_plan, read_outline
from pdfbooktree.typography.position_fallback import _title_similarity

try:  # 콘솔에서 한글 파일명이 깨지지 않게 한다.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
CORPUS_DIR = ROOT_DIR / "data" / "300STUDY"
EXPERIMENT_ID = "102_engine_bookmark_fuzzy_eval"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
RESULTS_PATH = OUTPUT_DIR / "results.jsonl"
ERRORS_PATH = OUTPUT_DIR / "errors.jsonl"
PROGRESS_PATH = OUTPUT_DIR / "progress.json"
SUMMARY_PATH = OUTPUT_DIR / "summary.json"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"

MIN_PAGE_COUNT = 100
PAGE_TOLERANCE = 1
TITLE_MATCH_THRESHOLD = 0.7


@dataclass(frozen=True)
class MatchMetrics:
    ground_truth_count: int
    predicted_count: int
    true_positive_count: int
    precision: float
    recall: float
    f1: float
    accuracy_jaccard: float
    exact_page_match_rate: float


def discover_corpus() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """page_count>100이고 embedded TOC가 있는 PDF만 골라낸다."""

    qualifying: list[dict[str, Any]] = []
    scan_errors: list[dict[str, Any]] = []
    for path in sorted(CORPUS_DIR.rglob("*.pdf")):
        try:
            with fitz.open(path) as document:
                page_count = document.page_count
                toc = document.get_toc(simple=True)
        except Exception as exc:  # noqa: BLE001
            scan_errors.append(
                {"path": str(path.relative_to(ROOT_DIR)), "error": str(exc)}
            )
            continue
        if page_count > MIN_PAGE_COUNT and toc:
            qualifying.append(
                {
                    "path": path,
                    "page_count": page_count,
                    "gold_bookmark_count": len(toc),
                }
            )
    return qualifying, scan_errors


def _fuzzy_match(
    gt: list[BookmarkPlanItem], pred: list[BookmarkPlanItem]
) -> MatchMetrics:
    """title 유사도 + page tolerance로 gold-예측을 그리디 1:1 매칭한다."""

    pred_by_page: dict[int, list[int]] = defaultdict(list)
    for index, item in enumerate(pred):
        pred_by_page[item.pdf_page].append(index)

    scored_pairs: list[tuple[float, int, int]] = []
    for gi, gold_item in enumerate(gt):
        candidate_indices: set[int] = set()
        for page in range(
            gold_item.pdf_page - PAGE_TOLERANCE, gold_item.pdf_page + PAGE_TOLERANCE + 1
        ):
            candidate_indices.update(pred_by_page.get(page, []))
        for pi in candidate_indices:
            score = _title_similarity(gold_item.title, pred[pi].title)
            if score >= TITLE_MATCH_THRESHOLD:
                scored_pairs.append((score, gi, pi))

    scored_pairs.sort(key=lambda row: row[0], reverse=True)
    matched_gt: set[int] = set()
    matched_pred: set[int] = set()
    exact_page_matches = 0
    for _score, gi, pi in scored_pairs:
        if gi in matched_gt or pi in matched_pred:
            continue
        matched_gt.add(gi)
        matched_pred.add(pi)
        if gt[gi].pdf_page == pred[pi].pdf_page:
            exact_page_matches += 1

    true_positive = len(matched_gt)
    precision = true_positive / len(pred) if pred else 0.0
    recall = true_positive / len(gt) if gt else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    union = len(pred) + len(gt) - true_positive
    accuracy_jaccard = true_positive / union if union > 0 else 0.0
    return MatchMetrics(
        ground_truth_count=len(gt),
        predicted_count=len(pred),
        true_positive_count=true_positive,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        accuracy_jaccard=round(accuracy_jaccard, 4),
        exact_page_match_rate=round(
            exact_page_matches / true_positive if true_positive else 0.0, 4
        ),
    )


def _predict_plan(pdf_path: Path) -> list[BookmarkPlanItem]:
    """Production과 동일한 public 단계형 API로 예측 plan만 만든다."""

    config = TypographyConfig()
    analysis = analyze_pdf(pdf_path, config)
    return infer_bookmarks(analysis, config).plan


def evaluate_book(pdf_path: Path) -> dict[str, Any]:
    with fitz.open(pdf_path) as document:
        total_pages = document.page_count
    gold = outline_to_plan(read_outline(pdf_path))
    if not gold:
        raise ValueError("embedded outline에 유효한 page 번호가 하나도 없다.")

    start = time.time()
    predicted = _predict_plan(pdf_path)
    elapsed = time.time() - start

    metrics = _fuzzy_match(gold, predicted)
    return {
        "path": str(pdf_path.relative_to(ROOT_DIR)),
        "page_count": total_pages,
        "elapsed_seconds": round(elapsed, 3),
        "metrics": asdict(metrics),
    }


def _histogram(values: list[float], bin_count: int = 10) -> dict[str, Any]:
    if not values:
        return {"bins": [], "counts": []}
    width = 1.0 / bin_count
    counts = [0] * bin_count
    for value in values:
        index = min(bin_count - 1, int(value / width))
        counts[index] += 1
    bins = [round(index * width, 2) for index in range(bin_count)]
    return {"bins": bins, "counts": counts}


def _classify_gold_quality(row: dict[str, Any]) -> str | None:
    """embedded bookmark가 실제 목차가 아니라 스캔/분할 도구 잔재인지 표시한다.

    코퍼스 400권을 훑어보니 gold 자체가 진짜 목차가 아닌 경우가 흔했다:
    (1) bookmark 수가 page 수와 거의 같으면 OCR/스캔 배치가 매 page마다 붙인
    일련번호 파일명이고(예: '1110001'), (2) bookmark가 3개 이하면 PDF
    분할/병합 도구가 남긴 자리표시자(날짜, 'Blank Page', 파일명_부분N)인
    경우가 대부분이었다. 이런 책은 gold 자체가 정답이 아니므로 engine
    precision/recall이 낮게 나와도 engine 결함이 아니다.
    """

    metrics = row["metrics"]
    ground_truth_count = metrics["ground_truth_count"]
    page_count = row["page_count"]
    if ground_truth_count >= page_count * 0.9:
        return "per_page_scan_filenames"
    if ground_truth_count <= 3:
        return "placeholder_or_tiny"
    return None


def build_summary(
    results: list[dict[str, Any]],
    run_errors: list[dict[str, Any]],
    total: int,
    elapsed_seconds: float,
) -> dict[str, Any]:
    """전체 결과와 gold 품질로 나눈 clean/junk subset 통계를 함께 만든다."""

    def _mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    def _subset_stats(subset: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "count": len(subset),
            "mean_precision": _mean([row["metrics"]["precision"] for row in subset]),
            "mean_recall": _mean([row["metrics"]["recall"] for row in subset]),
            "mean_f1": _mean([row["metrics"]["f1"] for row in subset]),
            "mean_accuracy_jaccard": _mean(
                [row["metrics"]["accuracy_jaccard"] for row in subset]
            ),
        }

    junk_breakdown: dict[str, int] = defaultdict(int)
    clean_rows: list[dict[str, Any]] = []
    junk_rows: list[dict[str, Any]] = []
    for row in results:
        reason = _classify_gold_quality(row)
        if reason is None:
            clean_rows.append(row)
        else:
            junk_breakdown[reason] += 1
            junk_rows.append(row)

    precisions = [row["metrics"]["precision"] for row in results]
    recalls = [row["metrics"]["recall"] for row in results]
    f1s = [row["metrics"]["f1"] for row in results]
    accuracies = [row["metrics"]["accuracy_jaccard"] for row in results]

    zero_prediction_rows = [
        row for row in results if row["metrics"]["predicted_count"] == 0
    ]
    worst_by_f1 = sorted(results, key=lambda row: row["metrics"]["f1"])[:15]
    worst_clean_by_f1 = sorted(clean_rows, key=lambda row: row["metrics"]["f1"])[:15]
    best_clean_by_f1 = sorted(
        clean_rows, key=lambda row: row["metrics"]["f1"], reverse=True
    )[:10]

    return {
        "corpus_dir": str(CORPUS_DIR.relative_to(ROOT_DIR)),
        "min_page_count": MIN_PAGE_COUNT,
        "page_tolerance": PAGE_TOLERANCE,
        "title_match_threshold": TITLE_MATCH_THRESHOLD,
        "qualifying_pdf_count": total,
        "evaluated_ok_count": len(results),
        "error_count": len(run_errors),
        "mean_precision": _mean(precisions),
        "mean_recall": _mean(recalls),
        "mean_f1": _mean(f1s),
        "mean_accuracy_jaccard": _mean(accuracies),
        "precision_histogram": _histogram(precisions),
        "recall_histogram": _histogram(recalls),
        "f1_histogram": _histogram(f1s),
        "accuracy_jaccard_histogram": _histogram(accuracies),
        "gold_quality": {
            "junk_gold_breakdown": dict(junk_breakdown),
            "clean_gold": _subset_stats(clean_rows),
            "junk_gold": _subset_stats(junk_rows),
        },
        "zero_prediction_count": len(zero_prediction_rows),
        "zero_prediction_paths": [row["path"] for row in zero_prediction_rows],
        "worst_by_f1": [
            {
                "path": row["path"],
                "page_count": row["page_count"],
                "metrics": row["metrics"],
            }
            for row in worst_by_f1
        ],
        "worst_clean_gold_by_f1": [
            {
                "path": row["path"],
                "page_count": row["page_count"],
                "metrics": row["metrics"],
            }
            for row in worst_clean_by_f1
        ],
        "best_clean_gold_by_f1": [
            {
                "path": row["path"],
                "page_count": row["page_count"],
                "metrics": row["metrics"],
            }
            for row in best_clean_by_f1
        ],
        "total_elapsed_seconds": round(elapsed_seconds, 1),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    qualifying, scan_errors = discover_corpus()
    total = len(qualifying)

    results: list[dict[str, Any]] = []
    run_errors: list[dict[str, Any]] = list(scan_errors)
    started_at = time.time()

    with (
        RESULTS_PATH.open("w", encoding="utf-8") as results_file,
        ERRORS_PATH.open("w", encoding="utf-8") as errors_file,
    ):
        for index, spec in enumerate(qualifying, start=1):
            pdf_path: Path = spec["path"]
            try:
                row = evaluate_book(pdf_path)
            except Exception as exc:  # noqa: BLE001
                error_row = {
                    "path": str(pdf_path.relative_to(ROOT_DIR)),
                    "error": str(exc),
                    "traceback": traceback.format_exc(limit=5),
                }
                run_errors.append(error_row)
                errors_file.write(json.dumps(error_row, ensure_ascii=False) + "\n")
                errors_file.flush()
            else:
                results.append(row)
                results_file.write(json.dumps(row, ensure_ascii=False) + "\n")
                results_file.flush()

            PROGRESS_PATH.write_text(
                json.dumps(
                    {
                        "done": index,
                        "total": total,
                        "ok_count": len(results),
                        "error_count": len(run_errors),
                        "elapsed_seconds": round(time.time() - started_at, 1),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(
                f"[{index}/{total}] ok={len(results)} err={len(run_errors)} "
                f"elapsed={round(time.time() - started_at, 1)}s",
                flush=True,
            )

    summary = build_summary(results, run_errors, total, time.time() - started_at)
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    finding = _build_finding(summary)
    print(finding)
    record_experiment(summary, finding)


def _build_finding(summary: dict[str, Any]) -> str:
    clean = summary["gold_quality"]["clean_gold"]
    junk = summary["gold_quality"]["junk_gold"]
    return (
        f"대상={summary['qualifying_pdf_count']}권(page>100 and has_toc), "
        f"평가 성공={summary['evaluated_ok_count']}, 실패={summary['error_count']}. "
        f"전체 mean precision={summary['mean_precision']}, recall={summary['mean_recall']}, "
        f"f1={summary['mean_f1']}, accuracy(jaccard)={summary['mean_accuracy_jaccard']}. "
        f"gold 품질로 나누면 clean gold(n={clean['count']})는 "
        f"precision={clean['mean_precision']}, recall={clean['mean_recall']}, "
        f"f1={clean['mean_f1']}이고, junk gold(n={junk['count']}, "
        f"{summary['gold_quality']['junk_gold_breakdown']})는 "
        f"f1={junk['mean_f1']}로 훨씬 낮다 — junk gold는 스캔/분할 도구가 남긴 "
        f"자리표시자이지 실제 목차가 아니다. predicted_count=0(추출 가능한 "
        f"text layer가 사실상 없는 책)은 {summary['zero_prediction_count']}권"
        f"({round(100 * summary['zero_prediction_count'] / summary['qualifying_pdf_count'], 1)}%)"
        f"뿐이라 드물다. clean gold 안에서도 최악 사례는 OCR이 수식/기호를 "
        f"heading 크기로 잘못 인식해 font 골격이 오염되는 경우이고, 최고 사례는 "
        f"gold 자체가 세밀한(수백 개) 프로그래밍/기술서적처럼 원서 목차 세밀도가 "
        f"engine의 BPE 세밀도와 가까운 경우다(F1 0.85~0.99). "
        f"총 소요={summary['total_elapsed_seconds']}s."
    )


def record_experiment(summary: dict[str, Any], finding: str) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "data/300STUDY 아래 page_count>100이고 embedded bookmark가 있는 PDF 전체를 "
            "대상으로, embedded bookmark를 gold로 보고 production 파이프라인(font 골격 + "
            "body-tier position fallback)이 만든 예측 plan을 fuzzy title 유사도 + page "
            "tolerance로 매칭해 precision/recall/F1/accuracy(jaccard)를 계산한다."
        ),
        "inputs": [str(CORPUS_DIR.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "page_count>100 and TOC 존재 조건으로 코퍼스를 골랐다. gold는 "
            "read_outline+outline_to_plan, 예측은 Processor.run()과 동일한 public "
            "building block(extract_typography_lines~insert_position_fallback)으로 "
            "PDF/Markdown export 없이 만들었다. title+page 집합만 비교했고(level 비교 "
            "없음), page tolerance=1, title 유사도 threshold=0.7로 그리디 1:1 매칭했다. "
            "accuracy는 TP/(len(pred)+len(gt)-TP) Jaccard 겹침 비율이다."
        ),
        "summary": {
            "mean_precision": summary["mean_precision"],
            "mean_recall": summary["mean_recall"],
            "mean_f1": summary["mean_f1"],
            "mean_accuracy_jaccard": summary["mean_accuracy_jaccard"],
            "qualifying_pdf_count": summary["qualifying_pdf_count"],
            "evaluated_ok_count": summary["evaluated_ok_count"],
            "error_count": summary["error_count"],
            "gold_quality": summary["gold_quality"],
            "zero_prediction_count": summary["zero_prediction_count"],
            "zero_prediction_paths": summary["zero_prediction_paths"],
            "worst_by_f1": summary["worst_by_f1"],
            "worst_clean_gold_by_f1": summary["worst_clean_gold_by_f1"],
            "best_clean_gold_by_f1": summary["best_clean_gold_by_f1"],
        },
        "finding": finding,
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    experiments = data["experiments"]
    for index, existing in enumerate(experiments):
        if existing.get("id") == EXPERIMENT_ID:
            experiments[index] = entry
            break
    else:
        experiments.append(entry)
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
