from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree.pdf.text import extract_selected_page_texts
from pdfbooktree.toc.features import (
    calculate_page_features,
    extract_line_final_number,
    is_toc_entry_like,
)
from pdfbooktree.utils.jsonio import to_jsonable, write_json


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "007_boundary_toc_page_review"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DEFAULT_DATASET_CSV = ROOT_DIR / "showcase" / "outputs" / "300study_toc_dataset.csv"
DEFAULT_DETECTION_JSON = ROOT_DIR / "showcase" / "outputs" / "300study_detection.json"

KEY_FEATURES = [
    "line_count",
    "word_count",
    "line_final_number_count",
    "line_final_number_monotonicity",
    "line_final_number_gap_mean",
    "line_final_number_gap_median",
    "line_final_number_gap_max",
    "line_final_number_negative_gap_count",
    "toc_entry_pattern_count",
    "toc_entry_pattern_ratio",
    "chapter_or_part_line_count",
    "toc_keyword_presence",
]


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def load_dataset_positive_pages(path: Path) -> dict[str, list[int]]:
    if not path.exists():
        raise FileNotFoundError(path)

    positive_pages: dict[str, set[int]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if int(row["label"]) != 1:
                continue
            positive_pages.setdefault(row["root_relative_pdf"], set()).add(
                int(row["pdf_page"])
            )
    return {
        pdf: sorted(pages)
        for pdf, pages in sorted(positive_pages.items(), key=lambda item: item[0])
    }


def contiguous_ranges(pages: list[int]) -> list[dict[str, int]]:
    if not pages:
        return []

    ranges = []
    sorted_pages = sorted(dict.fromkeys(pages))
    start = sorted_pages[0]
    previous = sorted_pages[0]
    for page in sorted_pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append({"start_page": start, "end_page": previous})
        start = page
        previous = page
    ranges.append({"start_page": start, "end_page": previous})
    return ranges


def candidate_by_page(result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    detection = result.get("detection") or {}
    candidates = detection.get("candidates") or []
    return {int(candidate["pdf_page"]): candidate for candidate in candidates}


def short_text(value: str, limit: int = 180) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def evidence_lines(lines: list[str], max_lines: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_indexes: set[int] = set()

    for index, line in enumerate(lines, start=1):
        reasons = []
        if extract_line_final_number(line) is not None:
            reasons.append("line_final_number")
        if is_toc_entry_like(line):
            reasons.append("toc_entry_pattern")
        lowered = line.lower()
        if "contents" in lowered or "table of contents" in lowered or "목차" in line or "차례" in line:
            reasons.append("toc_keyword")
        if not reasons:
            continue
        selected.append(
            {
                "line_index": index,
                "reasons": reasons,
                "text": short_text(line),
            }
        )
        selected_indexes.add(index)
        if len(selected) >= max_lines:
            return selected

    for index, line in enumerate(lines, start=1):
        if index in selected_indexes or not line.strip():
            continue
        selected.append(
            {
                "line_index": index,
                "reasons": ["context"],
                "text": short_text(line),
            }
        )
        if len(selected) >= max_lines:
            break
    return selected


def summarize_candidate(candidate: dict[str, Any] | None) -> dict[str, Any]:
    if candidate is None:
        return {
            "vote_count": 0,
            "voters": [],
            "matched_bookmark_count": 0,
            "bookmark_anchor_score": 0.0,
            "offset_consistency_score": 0.0,
        }
    return {
        "vote_count": int(candidate.get("vote_count", 0)),
        "voters": candidate.get("voters", []),
        "matched_bookmark_count": int(candidate.get("matched_bookmark_count", 0)),
        "bookmark_anchor_score": float(candidate.get("bookmark_anchor_score", 0.0)),
        "offset_consistency_score": float(
            candidate.get("offset_consistency_score", 0.0)
        ),
        "printed_page_sequence_score": float(
            candidate.get("printed_page_sequence_score", 0.0)
        ),
        "toc_entry_pattern_score": float(candidate.get("toc_entry_pattern_score", 0.0)),
        "window_mass_score": float(candidate.get("window_mass_score", 0.0)),
    }


def feature_dict(feature: Any) -> dict[str, Any]:
    return {name: getattr(feature, name) for name in KEY_FEATURES}


def structural_signal_count(features: dict[str, Any]) -> int:
    monotonicity = features["line_final_number_monotonicity"]
    return sum(
        [
            features["line_final_number_count"] >= 3,
            monotonicity is not None and monotonicity >= 0.7,
            features["toc_entry_pattern_count"] >= 1,
            bool(features["toc_keyword_presence"]),
        ]
    )


def guided_signal_count(candidate: dict[str, Any]) -> int:
    return sum(
        [
            candidate["vote_count"] >= 1,
            candidate["matched_bookmark_count"] >= 1,
            candidate["bookmark_anchor_score"] > 0,
            candidate["offset_consistency_score"] > 0,
        ]
    )


def review_verdict(features: dict[str, Any], candidate: dict[str, Any]) -> str:
    structural = structural_signal_count(features)
    guided = guided_signal_count(candidate)
    if structural >= 2 or (structural >= 1 and guided >= 1):
        return "likely_toc"
    if guided >= 2:
        return "needs_manual_review_guided_only"
    return "weak_boundary_evidence"


def review_score(features: dict[str, Any], candidate: dict[str, Any]) -> int:
    return structural_signal_count(features) * 2 + guided_signal_count(candidate)


def boundary_pages_for_range(
    page_range: dict[str, int],
    total_pages: int,
) -> dict[str, int]:
    start = page_range["start_page"]
    end = page_range["end_page"]
    pages = {
        "outside_before": start - 1,
        "boundary_start": start,
        "boundary_end": end,
        "outside_after": end + 1,
    }
    return {
        role: page
        for role, page in pages.items()
        if 1 <= page <= total_pages and page is not None
    }


def analyze_case(
    result: dict[str, Any],
    dataset_positive_pages: dict[str, list[int]],
    max_evidence_lines: int,
) -> dict[str, Any]:
    input_pdf = Path(result["input_pdf"])
    total_pages = int(result["total_pages"])
    root_relative_pdf = result["root_relative_pdf"]
    toc_pages = [int(page) for page in result["toc_pages"]]
    detection_ranges = contiguous_ranges(toc_pages)
    dataset_ranges = contiguous_ranges(dataset_positive_pages.get(root_relative_pdf, []))
    candidates = candidate_by_page(result)

    pages_to_extract = sorted(
        {
            page
            for page_range in detection_ranges
            for page in boundary_pages_for_range(page_range, total_pages).values()
        }
    )
    page_texts = extract_selected_page_texts(input_pdf, pages_to_extract)
    features = {
        feature.pdf_page: feature
        for feature in calculate_page_features(page_texts, total_pages=total_pages)
    }
    text_by_page = {page.pdf_page: page for page in page_texts}

    page_reviews = []
    range_reviews = []
    for range_index, page_range in enumerate(detection_ranges, start=1):
        boundary_map = boundary_pages_for_range(page_range, total_pages)
        role_reviews = {}
        for role, pdf_page in boundary_map.items():
            page_features = feature_dict(features[pdf_page])
            candidate = summarize_candidate(candidates.get(pdf_page))
            verdict = review_verdict(page_features, candidate)
            score = review_score(page_features, candidate)
            page_review = {
                "root_relative_pdf": root_relative_pdf,
                "range_index": range_index,
                "role": role,
                "pdf_page": pdf_page,
                "inside_detected_range": role.startswith("boundary"),
                "verdict": verdict,
                "review_score": score,
                "structural_signal_count": structural_signal_count(page_features),
                "guided_signal_count": guided_signal_count(candidate),
                "features": page_features,
                "candidate": candidate,
                "evidence_lines": evidence_lines(
                    text_by_page[pdf_page].lines,
                    max_lines=max_evidence_lines,
                ),
            }
            page_reviews.append(page_review)
            role_reviews[role] = page_review

        start_review = role_reviews.get("boundary_start")
        end_review = role_reviews.get("boundary_end")
        before_review = role_reviews.get("outside_before")
        after_review = role_reviews.get("outside_after")
        range_reviews.append(
            {
                "root_relative_pdf": root_relative_pdf,
                "range_index": range_index,
                "start_page": page_range["start_page"],
                "end_page": page_range["end_page"],
                "page_count": page_range["end_page"] - page_range["start_page"] + 1,
                "start_verdict": start_review["verdict"] if start_review else None,
                "end_verdict": end_review["verdict"] if end_review else None,
                "outside_before_score": before_review["review_score"]
                if before_review
                else None,
                "start_score": start_review["review_score"] if start_review else None,
                "end_score": end_review["review_score"] if end_review else None,
                "outside_after_score": after_review["review_score"] if after_review else None,
                "start_beats_outside_before": (
                    before_review is None
                    or start_review["review_score"] > before_review["review_score"]
                )
                if start_review
                else None,
                "end_beats_outside_after": (
                    after_review is None
                    or end_review["review_score"] > after_review["review_score"]
                )
                if end_review
                else None,
            }
        )

    return {
        "status": "reviewed",
        "input_pdf": str(input_pdf),
        "root_relative_pdf": root_relative_pdf,
        "total_pages": total_pages,
        "bookmark_count": result.get("bookmark_count", 0),
        "confidence": result.get("confidence"),
        "detection_ranges": detection_ranges,
        "dataset_positive_ranges": dataset_ranges,
        "range_reviews": range_reviews,
        "page_reviews": page_reviews,
    }


def safe_analyze_case(
    result: dict[str, Any],
    dataset_positive_pages: dict[str, list[int]],
    max_evidence_lines: int,
) -> dict[str, Any]:
    try:
        return analyze_case(
            result=result,
            dataset_positive_pages=dataset_positive_pages,
            max_evidence_lines=max_evidence_lines,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "input_pdf": result.get("input_pdf"),
            "root_relative_pdf": result.get("root_relative_pdf"),
            "toc_pages": result.get("toc_pages", []),
            "error": repr(exc),
        }


def write_boundary_csv(path: Path, results: list[dict[str, Any]]) -> None:
    fieldnames = [
        "root_relative_pdf",
        "range_index",
        "role",
        "pdf_page",
        "inside_detected_range",
        "verdict",
        "review_score",
        "structural_signal_count",
        "guided_signal_count",
        "line_final_number_count",
        "line_final_number_monotonicity",
        "toc_entry_pattern_count",
        "toc_keyword_presence",
        "vote_count",
        "matched_bookmark_count",
        "bookmark_anchor_score",
        "offset_consistency_score",
        "voters",
        "evidence_preview",
    ]
    rows = []
    for result in results:
        if result["status"] != "reviewed":
            continue
        for page in result["page_reviews"]:
            features = page["features"]
            candidate = page["candidate"]
            rows.append(
                {
                    "root_relative_pdf": page["root_relative_pdf"],
                    "range_index": page["range_index"],
                    "role": page["role"],
                    "pdf_page": page["pdf_page"],
                    "inside_detected_range": page["inside_detected_range"],
                    "verdict": page["verdict"],
                    "review_score": page["review_score"],
                    "structural_signal_count": page["structural_signal_count"],
                    "guided_signal_count": page["guided_signal_count"],
                    "line_final_number_count": features["line_final_number_count"],
                    "line_final_number_monotonicity": features[
                        "line_final_number_monotonicity"
                    ],
                    "toc_entry_pattern_count": features["toc_entry_pattern_count"],
                    "toc_keyword_presence": features["toc_keyword_presence"],
                    "vote_count": candidate["vote_count"],
                    "matched_bookmark_count": candidate["matched_bookmark_count"],
                    "bookmark_anchor_score": candidate["bookmark_anchor_score"],
                    "offset_consistency_score": candidate["offset_consistency_score"],
                    "voters": "|".join(candidate["voters"]),
                    "evidence_preview": " / ".join(
                        line["text"] for line in page["evidence_lines"][:3]
                    ),
                }
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    reviewed = [result for result in results if result["status"] == "reviewed"]
    failed = [result for result in results if result["status"] == "failed"]
    page_reviews = [
        page
        for result in reviewed
        for page in result["page_reviews"]
        if page["inside_detected_range"]
    ]
    range_reviews = [
        page_range for result in reviewed for page_range in result["range_reviews"]
    ]
    verdict_counts: dict[str, int] = {}
    for page in page_reviews:
        verdict_counts[page["verdict"]] = verdict_counts.get(page["verdict"], 0) + 1
    weak_boundary_pages = [
        {
            "root_relative_pdf": page["root_relative_pdf"],
            "range_index": page["range_index"],
            "role": page["role"],
            "pdf_page": page["pdf_page"],
            "verdict": page["verdict"],
            "review_score": page["review_score"],
            "evidence_preview": " / ".join(
                line["text"] for line in page["evidence_lines"][:3]
            ),
        }
        for page in page_reviews
        if page["verdict"] != "likely_toc"
    ]
    weak_ranges = [
        page_range
        for page_range in range_reviews
        if page_range["start_verdict"] != "likely_toc"
        or page_range["end_verdict"] != "likely_toc"
    ]
    return {
        "reviewed_case_count": len(reviewed),
        "failed_case_count": len(failed),
        "range_count": len(range_reviews),
        "boundary_page_count": len(page_reviews),
        "boundary_verdict_counts": verdict_counts,
        "weak_boundary_page_count": len(weak_boundary_pages),
        "weak_range_count": len(weak_ranges),
        "weak_boundary_pages_sample": weak_boundary_pages[:30],
        "failed_cases_sample": failed[:20],
    }


def build_finding(summary: dict[str, Any]) -> str:
    counts = summary["boundary_verdict_counts"]
    likely = counts.get("likely_toc", 0)
    guided = counts.get("needs_manual_review_guided_only", 0)
    weak = counts.get("weak_boundary_evidence", 0)
    return (
        f"300study detection 결과의 {summary['reviewed_case_count']}개 PDF에서 "
        f"{summary['range_count']}개 TOC range와 {summary['boundary_page_count']}개 "
        "시작/끝 경계 page를 검수했다. "
        f"경계 page 판정은 likely_toc {likely}개, "
        f"needs_manual_review_guided_only {guided}개, "
        f"weak_boundary_evidence {weak}개이며, "
        f"약한 경계 range는 {summary['weak_range_count']}개다. "
        "상세 page별 근거 line과 feature는 boundary_pages.csv와 summary.json에 남겼다."
    )


def write_markdown_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# 007 Boundary TOC Page Review",
        "",
        "## 요약",
        "",
        f"- 검수 PDF 수: {summary['reviewed_case_count']}",
        f"- 검수 TOC range 수: {summary['range_count']}",
        f"- 검수 경계 page 수: {summary['boundary_page_count']}",
        f"- 약한 경계 page 수: {summary['weak_boundary_page_count']}",
        f"- 약한 경계 range 수: {summary['weak_range_count']}",
        "",
        "## 경계 판정 분포",
        "",
    ]
    for verdict, count in sorted(summary["boundary_verdict_counts"].items()):
        lines.append(f"- {verdict}: {count}")
    lines.extend(
        [
            "",
            "## 약한 경계 page 표본",
            "",
        ]
    )
    for page in summary["weak_boundary_pages_sample"]:
        lines.append(
            "- "
            f"{page['root_relative_pdf']} "
            f"range {page['range_index']} {page['role']} page {page['pdf_page']}: "
            f"{page['verdict']} score={page['review_score']} / "
            f"{page['evidence_preview']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_experiment_registry() -> dict[str, Any]:
    if not EXPERIMENTS_JSON.exists():
        return {"experiments": []}
    return load_json(EXPERIMENTS_JSON)


def update_experiment_registry(summary: dict[str, Any]) -> None:
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
                "300study 새 데이터셋에서 bookmark-guided TOC range의 시작/끝 "
                "경계 page가 실제 목차 page인지 확인하기 위해 경계 page와 바로 "
                "바깥 page의 text, 구조 feature, detector 후보 근거를 비교한다."
            ),
            "inputs": [
                str(DEFAULT_DATASET_CSV.relative_to(ROOT_DIR)),
                str(DEFAULT_DETECTION_JSON.relative_to(ROOT_DIR)),
            ],
            "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
            "source_showcase": "showcase/outputs/300study_detection.json",
            "finding": build_finding(summary),
            "ran_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    registry["experiments"] = experiments
    write_json(EXPERIMENTS_JSON, registry)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="새 TOC dataset의 시작/끝 경계 page가 목차인지 검수한다.",
    )
    parser.add_argument(
        "--dataset-csv",
        type=Path,
        default=DEFAULT_DATASET_CSV,
        help="검수할 TOC dataset CSV 경로다.",
    )
    parser.add_argument(
        "--detection-json",
        type=Path,
        default=DEFAULT_DETECTION_JSON,
        help="showcase batch detection JSON 경로다.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=0,
        help="앞에서부터 검수할 detected case 수다. 0이면 전체를 검수한다.",
    )
    parser.add_argument(
        "--max-evidence-lines",
        type=int,
        default=10,
        help="page별로 남길 근거 line 최대 개수다.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="결과 파일만 쓰고 콘솔 JSON 출력은 생략한다.",
    )
    return parser.parse_args()


def resolve_input_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT_DIR / path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    dataset_csv = resolve_input_path(args.dataset_csv)
    detection_json = resolve_input_path(args.detection_json)

    dataset_positive_pages = load_dataset_positive_pages(dataset_csv)
    detection_summary = load_json(detection_json)
    detected_results = [
        result
        for result in detection_summary["results"]
        if result.get("status") == "detected" and result.get("toc_pages")
    ]
    if args.max_cases > 0:
        detected_results = detected_results[: args.max_cases]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = [
        safe_analyze_case(
            result=result,
            dataset_positive_pages=dataset_positive_pages,
            max_evidence_lines=args.max_evidence_lines,
        )
        for result in detected_results
    ]
    summary = summarize(results)
    output = {
        "experiment_id": EXPERIMENT_ID,
        "dataset_csv": str(dataset_csv.relative_to(ROOT_DIR)),
        "detection_json": str(detection_json.relative_to(ROOT_DIR)),
        "source_detected_case_count": len(detected_results),
        "summary": summary,
        "results": results,
    }

    write_json(OUTPUT_DIR / "summary.json", output)
    write_boundary_csv(OUTPUT_DIR / "boundary_pages.csv", results)
    write_markdown_report(OUTPUT_DIR / "report.md", summary)
    update_experiment_registry(summary)
    if not args.quiet:
        print(json.dumps(to_jsonable(output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
