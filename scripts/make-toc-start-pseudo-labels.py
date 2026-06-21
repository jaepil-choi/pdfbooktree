"""bookmark 보유 PDF에서 TOC start page pseudo label 산출물을 만든다.

이 스크립트는 데이터 제작 job이다. 생성된 label은 수동 검수 전 ground truth가
아니며, `review_status`가 바뀌기 전에는 학습 정답으로 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Literal

import fitz

from pdfbooktree.models import TocDetectionResult
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.toc.detect_from_bookmarks import detect_toc_pages_from_bookmarks
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.utils.jsonio import to_jsonable


Outcome = Literal["labeled", "not_detected", "failed", "skipped"]
DiagnosticSink = Callable[[str], None]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="bookmark 보유 PDF에서 TOC start page pseudo label을 만든다.",
    )
    parser.add_argument("input_dir", type=Path, help="PDF를 찾을 입력 디렉터리")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("outputs/300study_toc_start_pseudo_labels.json"),
        help="pseudo label batch 결과 JSON 경로",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path("outputs/300study_toc_start_pseudo_labels.csv"),
        help="pseudo label row CSV 경로",
    )
    parser.add_argument(
        "--max-text-pages",
        type=int,
        default=80,
        help="각 PDF 앞부분에서 TOC 탐지에 사용할 최대 page 수",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="PDF 파일 단위 병렬 처리 worker 수",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="하위 디렉터리를 검색하지 않는다.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="진행 상황 출력을 줄인다.",
    )
    args = parser.parse_args()

    result = run_batch(
        input_dir=args.input_dir,
        output_json=args.output_json,
        output_csv=args.output_csv,
        max_text_pages=args.max_text_pages,
        workers=max(1, args.workers),
        recursive=not args.no_recursive,
        diagnostics=None if args.quiet else print,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


def run_batch(
    input_dir: Path,
    output_json: Path,
    output_csv: Path,
    max_text_pages: int,
    workers: int,
    recursive: bool,
    diagnostics: DiagnosticSink | None,
) -> dict[str, Any]:
    emit(diagnostics, f"PDF 검색 시작: root={input_dir}, recursive={recursive}")
    if not input_dir.exists():
        raise FileNotFoundError(f"입력 경로가 없다: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"입력 경로가 디렉터리가 아니다: {input_dir}")

    pdf_paths = find_pdfs(input_dir, recursive=recursive)
    emit(diagnostics, f"PDF 검색 완료: {len(pdf_paths)}개 발견")
    labels: list[dict[str, Any]] = []
    skipped_no_bookmark_count = 0

    emit(diagnostics, f"start page pseudo label 생성 시작: workers={workers}")
    completed_count = 0
    if workers == 1:
        processed_items = [
            process_pdf(
                root_dir=input_dir,
                pdf_path=pdf_path,
                max_text_pages=max_text_pages,
            )
            for pdf_path in pdf_paths
        ]
        for item in processed_items:
            completed_count += 1
            skipped_no_bookmark_count += handle_processed_item(
                item,
                completed_count,
                len(pdf_paths),
                labels,
                diagnostics,
            )
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    process_pdf,
                    input_dir,
                    pdf_path,
                    max_text_pages,
                )
                for pdf_path in pdf_paths
            ]
            for future in as_completed(futures):
                completed_count += 1
                skipped_no_bookmark_count += handle_processed_item(
                    future.result(),
                    completed_count,
                    len(pdf_paths),
                    labels,
                    diagnostics,
                )

    summary = {
        "root_dir": input_dir,
        "recursive": recursive,
        "max_text_pages": max_text_pages,
        "workers": workers,
        "total_pdf_count": len(pdf_paths),
        "bookmarked_pdf_count": sum(
            1 for label in labels if int(label.get("bookmark_count") or 0) > 0
        ),
        "skipped_no_bookmark_count": skipped_no_bookmark_count,
        "labeled_count": sum(1 for label in labels if label["status"] == "labeled"),
        "not_detected_count": sum(
            1 for label in labels if label["status"] == "not_detected"
        ),
        "failed_count": sum(1 for label in labels if label["status"] == "failed"),
        "output_json": output_json,
        "output_csv": output_csv,
    }
    result = {**summary, "labels": labels}
    write_json(output_json, result)
    write_csv(output_csv, labels)
    emit(diagnostics, f"bookmark 보유 PDF 요약: {summary['bookmarked_pdf_count']}개")
    return {"summary": to_jsonable(summary), "labels": labels}


def find_pdfs(input_dir: Path, recursive: bool) -> list[Path]:
    iterator = input_dir.rglob("*") if recursive else input_dir.iterdir()
    return sorted(
        path for path in iterator if path.is_file() and path.suffix.lower() == ".pdf"
    )


def process_pdf(
    root_dir: Path,
    pdf_path: Path,
    max_text_pages: int,
) -> tuple[Outcome, dict[str, Any] | None]:
    try:
        bookmarks = extract_existing_bookmarks(pdf_path)
    except Exception as error:  # noqa: BLE001
        return ("failed", failed_label(root_dir, pdf_path, error))

    if not bookmarks:
        return ("skipped", None)

    try:
        with fitz.open(pdf_path) as document:
            total_pages = document.page_count

        pages = extract_page_texts(pdf_path, max_pages=max_text_pages)
        features = calculate_page_features(pages, total_pages=total_pages)
        detection = detect_toc_pages_from_bookmarks(
            pages,
            bookmarks,
            features=features,
        )
    except Exception as error:  # noqa: BLE001
        return (
            "failed",
            failed_label(root_dir, pdf_path, error, bookmark_count=len(bookmarks)),
        )

    warnings: list[str] = []
    if not pages:
        warnings.append("PDF 앞부분에서 text layer를 읽지 못했다.")
    if not detection.pages:
        warnings.append("bookmark-guided TOC page 후보를 찾지 못했다.")

    label = build_label(
        root_dir=root_dir,
        pdf_path=pdf_path,
        total_pages=total_pages,
        observed_text_pages=len(pages),
        bookmark_count=len(bookmarks),
        detection=detection,
        warnings=warnings,
    )
    return (label["status"], label)


def build_label(
    root_dir: Path,
    pdf_path: Path,
    total_pages: int,
    observed_text_pages: int,
    bookmark_count: int,
    detection: TocDetectionResult,
    warnings: list[str],
) -> dict[str, Any]:
    toc_page_count = len(detection.pages)
    if toc_page_count > 30:
        warnings.append(
            "TOC range가 30 page를 넘어 start page pseudo label 검수가 필요하다."
        )
    evidence = build_start_page_evidence(detection)
    return {
        "status": "labeled" if detection.start_page is not None else "not_detected",
        "input_pdf": pdf_path,
        "root_relative_pdf": relative_to_root(root_dir, pdf_path),
        "total_pages": total_pages,
        "observed_text_pages": observed_text_pages,
        "bookmark_count": bookmark_count,
        "toc_start_page": detection.start_page,
        "toc_end_page": detection.end_page,
        "toc_page_count": toc_page_count,
        "confidence": calculate_start_page_confidence(detection, evidence),
        "detection_confidence": detection.confidence,
        "method": detection.method,
        "label_source": "bookmark_guided_toc_start_pseudo_label",
        "review_status": "unreviewed",
        "warnings": warnings,
        "evidence": evidence,
        "error": None,
    }


def build_start_page_evidence(detection: TocDetectionResult) -> dict[str, Any]:
    if detection.start_page is None:
        return {"start_candidate": None, "candidate_count": len(detection.candidates)}

    start_candidate = next(
        (
            candidate
            for candidate in detection.candidates
            if int(candidate.get("pdf_page", 0)) == detection.start_page
        ),
        None,
    )
    return {
        "start_candidate": start_candidate,
        "candidate_count": len(detection.candidates),
        "toc_pages": detection.pages,
    }


def calculate_start_page_confidence(
    detection: TocDetectionResult,
    evidence: dict[str, Any],
) -> float:
    if detection.start_page is None:
        return 0.0

    candidate = evidence.get("start_candidate")
    if not isinstance(candidate, dict):
        return round(detection.confidence * 0.7, 6)

    vote_component = min(1.0, float(candidate.get("vote_count", 0)) / 5)
    anchor_component = min(1.0, float(candidate.get("bookmark_anchor_score", 0.0)) / 8)
    offset_component = min(
        1.0,
        float(candidate.get("offset_consistency_score", 0.0)) / 5,
    )
    confidence = (
        detection.confidence * 0.55
        + vote_component * 0.25
        + anchor_component * 0.10
        + offset_component * 0.10
    )
    return round(min(1.0, confidence), 6)


def failed_label(
    root_dir: Path,
    pdf_path: Path,
    error: Exception,
    bookmark_count: int = 0,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "input_pdf": pdf_path,
        "root_relative_pdf": relative_to_root(root_dir, pdf_path),
        "total_pages": 0,
        "observed_text_pages": 0,
        "bookmark_count": bookmark_count,
        "toc_start_page": None,
        "toc_end_page": None,
        "toc_page_count": 0,
        "confidence": 0.0,
        "detection_confidence": 0.0,
        "method": None,
        "label_source": "bookmark_guided_toc_start_pseudo_label",
        "review_status": "unreviewed",
        "warnings": [],
        "evidence": {},
        "error": f"{type(error).__name__}: {error}",
    }


def handle_processed_item(
    item: tuple[Outcome, dict[str, Any] | None],
    completed_count: int,
    total_count: int,
    labels: list[dict[str, Any]],
    diagnostics: DiagnosticSink | None,
) -> int:
    outcome, label = item
    if outcome == "skipped":
        return 1
    if label is None:
        return 0

    labels.append(label)
    display_path = str(label.get("root_relative_pdf") or label["input_pdf"])
    if label["status"] == "failed":
        emit(
            diagnostics,
            f"PDF 처리 실패 ({completed_count}/{total_count}): "
            f"{display_path} ({label['error']})",
        )
        return 0
    if label["status"] == "labeled":
        emit(
            diagnostics,
            f"start page label 생성 완료 ({completed_count}/{total_count}): "
            f"{display_path} start={label['toc_start_page']} "
            f"confidence={float(label['confidence']):.3f}",
        )
        return 0

    emit(
        diagnostics,
        f"TOC start page 후보 없음 ({completed_count}/{total_count}): {display_path}",
    )
    return 0


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_csv(path: Path, labels: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "status",
        "input_pdf",
        "root_relative_pdf",
        "total_pages",
        "observed_text_pages",
        "bookmark_count",
        "toc_start_page",
        "toc_end_page",
        "toc_page_count",
        "confidence",
        "detection_confidence",
        "method",
        "label_source",
        "review_status",
        "warnings",
        "evidence",
        "error",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for label in labels:
            writer.writerow(csv_safe_label(label))


def csv_safe_label(label: dict[str, Any]) -> dict[str, Any]:
    raw_label = to_jsonable(label)
    return {
        key: json.dumps(value, ensure_ascii=False)
        if isinstance(value, list | dict)
        else value
        for key, value in raw_label.items()
    }


def relative_to_root(root_dir: Path, pdf_path: Path) -> Path | None:
    try:
        return pdf_path.relative_to(root_dir)
    except ValueError:
        return None


def emit(diagnostics: DiagnosticSink | None, message: str) -> None:
    if diagnostics is not None:
        diagnostics(message)


if __name__ == "__main__":
    main()
