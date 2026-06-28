"""bookmark가 있는 PDF들에 TOC page detection을 일괄 적용한다."""

from __future__ import annotations

import csv
import json
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Literal

import fitz

from pdfbooktree.models import (
    BookmarkedPdfTocBatchResult,
    BookmarkedPdfTocDetection,
    PageFeature,
    TocPageDatasetRow,
)
from pdfbooktree.pdf.bookmarks import (
    extract_existing_bookmarks,
    has_letter_bookmark,
)
from pdfbooktree.pdf.text import extract_page_texts, extract_selected_page_texts
from pdfbooktree.toc.detect_from_bookmarks import detect_toc_pages_from_bookmarks
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.utils.jsonio import to_jsonable


DiagnosticSink = Callable[[str], None]


class BookmarkTocBatchDetector:
    """임의 디렉터리의 bookmark 보유 PDF들에서 TOC page range를 찾는다."""

    def __init__(
        self,
        input_dir: Path | str,
        max_text_pages: int = 80,
        min_total_pages: int = 50,
        recursive: bool = True,
        random_seed: int = 42,
        workers: int = 1,
        diagnostics: DiagnosticSink | None = None,
    ) -> None:
        self.input_dir = Path(input_dir)
        self.max_text_pages = max_text_pages
        self.min_total_pages = min_total_pages
        self.recursive = recursive
        self.random_seed = random_seed
        self.workers = max(1, workers)
        self.diagnostics = diagnostics

    def run(self) -> BookmarkedPdfTocBatchResult:
        """PDF를 찾고 bookmark가 있는 파일만 bookmark-guided detector로 분석한다."""

        self._emit(f"PDF 검색 시작: root={self.input_dir}, recursive={self.recursive}")
        if not self.input_dir.exists():
            raise FileNotFoundError(f"입력 경로가 없다: {self.input_dir}")
        if not self.input_dir.is_dir():
            raise NotADirectoryError(f"입력 경로가 디렉터리가 아니다: {self.input_dir}")

        pdf_paths = self._find_pdfs()
        self._emit(f"PDF 검색 완료: {len(pdf_paths)}개 발견")
        results: list[BookmarkedPdfTocDetection] = []
        skipped_no_bookmark_count = 0
        skipped_short_pdf_count = 0
        skipped_no_letter_bookmark_count = 0

        self._emit(f"PDF 처리 시작: workers={self.workers}")
        completed_count = 0
        if self.workers == 1:
            processed_items = [
                _process_pdf_for_bookmark_toc(
                    root_dir=self.input_dir,
                    pdf_path=pdf_path,
                    max_text_pages=self.max_text_pages,
                    min_total_pages=self.min_total_pages,
                    random_seed=self.random_seed + index,
                )
                for index, pdf_path in enumerate(pdf_paths, start=1)
            ]
            for item in processed_items:
                completed_count += 1
                skipped_no_bookmark, skipped_short_pdf, skipped_no_letter = (
                    self._handle_processed_item(
                        item,
                        completed_count,
                        len(pdf_paths),
                        results,
                    )
                )
                skipped_no_bookmark_count += skipped_no_bookmark
                skipped_short_pdf_count += skipped_short_pdf
                skipped_no_letter_bookmark_count += skipped_no_letter
        else:
            with ProcessPoolExecutor(max_workers=self.workers) as executor:
                futures = [
                    executor.submit(
                        _process_pdf_for_bookmark_toc,
                        self.input_dir,
                        pdf_path,
                        self.max_text_pages,
                        self.min_total_pages,
                        self.random_seed + index,
                    )
                    for index, pdf_path in enumerate(pdf_paths, start=1)
                ]
                for future in as_completed(futures):
                    completed_count += 1
                    skipped_no_bookmark, skipped_short_pdf, skipped_no_letter = (
                        self._handle_processed_item(
                            future.result(),
                            completed_count,
                            len(pdf_paths),
                            results,
                        )
                    )
                    skipped_no_bookmark_count += skipped_no_bookmark
                    skipped_short_pdf_count += skipped_short_pdf
                    skipped_no_letter_bookmark_count += skipped_no_letter

        detected_count = sum(1 for result in results if result.status == "detected")
        not_detected_count = sum(
            1 for result in results if result.status == "not_detected"
        )
        failed_count = sum(1 for result in results if result.status == "failed")
        bookmarked_pdf_count = sum(1 for result in results if result.bookmark_count > 0)
        self._emit(f"bookmark 보유 PDF 요약: {bookmarked_pdf_count}개")
        dataset_rows = [row for result in results for row in result.dataset_rows]
        return BookmarkedPdfTocBatchResult(
            root_dir=self.input_dir,
            recursive=self.recursive,
            max_text_pages=self.max_text_pages,
            workers=self.workers,
            total_pdf_count=len(pdf_paths),
            bookmarked_pdf_count=bookmarked_pdf_count,
            skipped_no_bookmark_count=skipped_no_bookmark_count,
            detected_count=detected_count,
            not_detected_count=not_detected_count,
            failed_count=failed_count,
            min_total_pages=self.min_total_pages,
            skipped_short_pdf_count=skipped_short_pdf_count,
            skipped_no_letter_bookmark_count=skipped_no_letter_bookmark_count,
            dataset_row_count=len(dataset_rows),
            results=results,
            dataset_rows=dataset_rows,
        )

    def _handle_processed_item(
        self,
        item: tuple[str, BookmarkedPdfTocDetection | None],
        completed_count: int,
        total_count: int,
        results: list[BookmarkedPdfTocDetection],
    ) -> tuple[int, int, int]:
        outcome, result = item
        if outcome == "skipped":
            return (1, 0, 0)
        if outcome == "skipped_short":
            return (0, 1, 0)
        if outcome == "skipped_no_letter":
            return (0, 0, 1)
        if result is None:
            return (0, 0, 0)

        results.append(result)
        display_path = str(result.root_relative_pdf or result.input_pdf)
        if result.status == "failed":
            self._emit(
                f"PDF 처리 실패 ({completed_count}/{total_count}): "
                f"{display_path} ({result.error})"
            )
            return (0, 0, 0)

        self._emit(f"bookmark 있음: {display_path} ({result.bookmark_count}개)")
        if result.status == "detected":
            negative_count = sum(1 for row in result.dataset_rows if row.label == 0)
            self._emit(
                f"TOC/dataset 생성 완료 ({completed_count}/{total_count}): "
                f"{display_path} positives={len(result.toc_pages)} "
                f"negatives={negative_count} confidence={result.confidence:.3f}"
            )
        else:
            self._emit(
                f"TOC 탐지 결과 없음 ({completed_count}/{total_count}): {display_path}"
            )
        return (0, 0, 0)

    def _find_pdfs(self) -> list[Path]:
        iterator = (
            self.input_dir.rglob("*") if self.recursive else self.input_dir.iterdir()
        )
        return sorted(
            path
            for path in iterator
            if path.is_file() and path.suffix.lower() == ".pdf"
        )

    def _emit(self, message: str) -> None:
        if self.diagnostics is not None:
            self.diagnostics(message)


def _process_pdf_for_bookmark_toc(
    root_dir: Path,
    pdf_path: Path,
    max_text_pages: int,
    min_total_pages: int,
    random_seed: int,
) -> tuple[str, BookmarkedPdfTocDetection | None]:
    try:
        with fitz.open(pdf_path) as document:
            total_pages = document.page_count
    except Exception as error:  # noqa: BLE001
        return ("failed", _failed_result(root_dir, pdf_path, error))

    if total_pages < min_total_pages:
        return ("skipped_short", None)

    try:
        bookmarks = extract_existing_bookmarks(pdf_path)
    except Exception as error:  # noqa: BLE001
        return ("failed", _failed_result(root_dir, pdf_path, error))

    if not bookmarks:
        return ("skipped", None)

    if not has_letter_bookmark(bookmarks):
        # 제목이 모두 숫자/기호뿐인 깨진 bookmark는 pseudo label 소스에서 제외한다.
        return ("skipped_no_letter", None)

    try:
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
            _failed_result(root_dir, pdf_path, error, bookmark_count=len(bookmarks)),
        )

    warnings: list[str] = []
    if not pages:
        warnings.append("PDF 앞부분에서 text layer를 읽지 못했다.")
    if not detection.pages:
        warnings.append("bookmark-guided TOC page 후보를 찾지 못했다.")

    dataset_rows: list[TocPageDatasetRow] = []
    if detection.pages:
        try:
            dataset_rows, dataset_warnings = _build_dataset_rows(
                root_dir=root_dir,
                pdf_path=pdf_path,
                total_pages=total_pages,
                bookmark_count=len(bookmarks),
                detection_pages=detection.pages,
                detection_confidence=detection.confidence,
                positive_features=features,
                rng=random.Random(random_seed),
            )
            warnings.extend(dataset_warnings)
        except Exception as error:  # noqa: BLE001
            warnings.append(f"dataset row 생성 실패: {type(error).__name__}: {error}")

    status = "detected" if detection.pages else "not_detected"
    return (
        status,
        BookmarkedPdfTocDetection(
            status=status,
            input_pdf=pdf_path,
            root_relative_pdf=_relative_to_root(root_dir, pdf_path),
            total_pages=total_pages,
            observed_text_pages=len(pages),
            bookmark_count=len(bookmarks),
            toc_pages=detection.pages,
            confidence=detection.confidence,
            method=detection.method,
            detection=detection,
            dataset_rows=dataset_rows,
            warnings=warnings,
        ),
    )


def _build_dataset_rows(
    root_dir: Path,
    pdf_path: Path,
    total_pages: int,
    bookmark_count: int,
    detection_pages: list[int],
    detection_confidence: float,
    positive_features: list[PageFeature],
    rng: random.Random,
) -> tuple[list[TocPageDatasetRow], list[str]]:
    positive_pages = sorted(dict.fromkeys(detection_pages))
    positive_page_set = set(positive_pages)
    negative_candidates = [
        pdf_page
        for pdf_page in range(1, total_pages + 1)
        if pdf_page not in positive_page_set
    ]
    negative_count = min(len(positive_pages), len(negative_candidates))
    negative_pages = sorted(rng.sample(negative_candidates, negative_count))
    warnings: list[str] = []
    if negative_count < len(positive_pages):
        warnings.append(
            "negative page 후보가 부족해 positive와 1:1 비율을 맞추지 못했다."
        )

    feature_by_page = {feature.pdf_page: feature for feature in positive_features}
    missing_positive_pages = [
        pdf_page for pdf_page in positive_pages if pdf_page not in feature_by_page
    ]
    previous_pages = [
        pdf_page - 1 for pdf_page in positive_pages + negative_pages if pdf_page > 1
    ]
    selected_pages = sorted(
        set(missing_positive_pages + negative_pages + previous_pages)
    )
    if selected_pages:
        selected_texts = extract_selected_page_texts(pdf_path, selected_pages)
        selected_features = calculate_page_features(selected_texts, total_pages)
        feature_by_page.update(
            {feature.pdf_page: feature for feature in selected_features}
        )

    rows: list[TocPageDatasetRow] = []
    for pdf_page in positive_pages:
        rows.append(
            _build_dataset_row(
                root_dir=root_dir,
                pdf_path=pdf_path,
                feature=feature_by_page[pdf_page],
                previous_feature=feature_by_page.get(pdf_page - 1),
                label=1,
                sample_role="positive",
                total_pages=total_pages,
                bookmark_count=bookmark_count,
                detection_confidence=detection_confidence,
            )
        )
    for pdf_page in negative_pages:
        rows.append(
            _build_dataset_row(
                root_dir=root_dir,
                pdf_path=pdf_path,
                feature=feature_by_page[pdf_page],
                previous_feature=feature_by_page.get(pdf_page - 1),
                label=0,
                sample_role="negative",
                total_pages=total_pages,
                bookmark_count=bookmark_count,
                detection_confidence=detection_confidence,
            )
        )
    return rows, warnings


def _build_dataset_row(
    root_dir: Path,
    pdf_path: Path,
    feature: PageFeature,
    previous_feature: PageFeature | None,
    label: int,
    sample_role: Literal["positive", "negative"],
    total_pages: int,
    bookmark_count: int,
    detection_confidence: float,
) -> TocPageDatasetRow:
    return TocPageDatasetRow(
        input_pdf=pdf_path,
        root_relative_pdf=_relative_to_root(root_dir, pdf_path),
        pdf_page=feature.pdf_page,
        label=label,
        sample_role=sample_role,
        label_source="bookmark_guided_toc_detection",
        total_pages=total_pages,
        bookmark_count=bookmark_count,
        detection_confidence=detection_confidence,
        line_count=feature.line_count,
        word_count=feature.word_count,
        mean_line_length=feature.mean_line_length,
        line_length_std=feature.line_length_std,
        line_final_number_count=feature.line_final_number_count,
        line_final_numbers=feature.line_final_numbers,
        line_final_number_monotonicity=feature.line_final_number_monotonicity,
        line_final_number_gap_mean=feature.line_final_number_gap_mean,
        line_final_number_gap_median=feature.line_final_number_gap_median,
        line_final_number_gap_max=feature.line_final_number_gap_max,
        line_final_number_negative_gap_count=(
            feature.line_final_number_negative_gap_count
        ),
        toc_entry_pattern_count=feature.toc_entry_pattern_count,
        toc_entry_pattern_ratio=feature.toc_entry_pattern_ratio,
        chapter_or_part_line_count=feature.chapter_or_part_line_count,
        page_position=feature.page_position,
        toc_keyword_presence=feature.toc_keyword_presence,
        prev_page_available=previous_feature is not None,
        prev_line_count=previous_feature.line_count
        if previous_feature is not None
        else None,
        prev_word_count=previous_feature.word_count
        if previous_feature is not None
        else None,
        prev_mean_line_length=previous_feature.mean_line_length
        if previous_feature is not None
        else None,
        prev_line_length_std=previous_feature.line_length_std
        if previous_feature is not None
        else None,
        prev_line_final_number_count=previous_feature.line_final_number_count
        if previous_feature is not None
        else None,
        prev_line_final_number_monotonicity=(
            previous_feature.line_final_number_monotonicity
            if previous_feature is not None
            else None
        ),
        prev_line_final_number_gap_mean=previous_feature.line_final_number_gap_mean
        if previous_feature is not None
        else None,
        prev_line_final_number_gap_median=(
            previous_feature.line_final_number_gap_median
            if previous_feature is not None
            else None
        ),
        prev_line_final_number_gap_max=previous_feature.line_final_number_gap_max
        if previous_feature is not None
        else None,
        prev_line_final_number_negative_gap_count=(
            previous_feature.line_final_number_negative_gap_count
            if previous_feature is not None
            else None
        ),
        prev_toc_entry_pattern_count=previous_feature.toc_entry_pattern_count
        if previous_feature is not None
        else None,
        prev_toc_entry_pattern_ratio=previous_feature.toc_entry_pattern_ratio
        if previous_feature is not None
        else None,
        prev_chapter_or_part_line_count=(
            previous_feature.chapter_or_part_line_count
            if previous_feature is not None
            else None
        ),
        prev_toc_keyword_presence=previous_feature.toc_keyword_presence
        if previous_feature is not None
        else None,
    )


def _failed_result(
    root_dir: Path,
    pdf_path: Path,
    error: Exception,
    bookmark_count: int = 0,
) -> BookmarkedPdfTocDetection:
    return BookmarkedPdfTocDetection(
        status="failed",
        input_pdf=pdf_path,
        root_relative_pdf=_relative_to_root(root_dir, pdf_path),
        bookmark_count=bookmark_count,
        error=f"{type(error).__name__}: {error}",
    )


def _relative_to_root(root_dir: Path, pdf_path: Path) -> Path | None:
    try:
        return pdf_path.relative_to(root_dir)
    except ValueError:
        return None


def write_toc_page_dataset_csv(
    path: Path,
    rows: list[TocPageDatasetRow],
) -> None:
    """TOC page dataset row를 CSV 파일로 저장한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        list(asdict(rows[0]).keys())
        if rows
        else list(TocPageDatasetRow.__annotations__)
    )
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(_csv_safe_row(row))


def _csv_safe_row(row: TocPageDatasetRow) -> dict[str, object]:
    raw_row = to_jsonable(asdict(row))
    return {
        key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
        for key, value in raw_row.items()
    }
