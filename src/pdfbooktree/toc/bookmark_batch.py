"""bookmark가 있는 PDF들에 TOC page detection을 일괄 적용한다."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import fitz

from pdfbooktree.models import (
    BookmarkedPdfTocBatchResult,
    BookmarkedPdfTocDetection,
)
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.toc.detect_from_bookmarks import detect_toc_pages_from_bookmarks
from pdfbooktree.toc.features import calculate_page_features


DiagnosticSink = Callable[[str], None]


class BookmarkTocBatchDetector:
    """임의 디렉터리의 bookmark 보유 PDF들에서 TOC page range를 찾는다."""

    def __init__(
        self,
        input_dir: Path | str,
        max_text_pages: int = 80,
        recursive: bool = True,
        diagnostics: DiagnosticSink | None = None,
    ) -> None:
        self.input_dir = Path(input_dir)
        self.max_text_pages = max_text_pages
        self.recursive = recursive
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
        bookmarked_pdf_records: list[tuple[Path, list[dict[str, object]]]] = []

        self._emit("bookmark 확인 시작")
        for index, pdf_path in enumerate(pdf_paths, start=1):
            display_path = self._display_path(pdf_path)
            self._emit(f"bookmark 확인 중 ({index}/{len(pdf_paths)}): {display_path}")
            try:
                bookmarks = extract_existing_bookmarks(pdf_path)
            except Exception as error:  # noqa: BLE001
                self._emit(
                    f"bookmark 확인 실패: {display_path} ({type(error).__name__})"
                )
                results.append(self._failed_result(pdf_path, error))
                continue

            if not bookmarks:
                self._emit(f"bookmark 없음: {display_path}")
                skipped_no_bookmark_count += 1
                continue

            self._emit(f"bookmark 있음: {display_path} ({len(bookmarks)}개)")
            bookmarked_pdf_records.append((pdf_path, bookmarks))

        self._emit(
            "bookmark 보유 PDF 요약: "
            f"{len(bookmarked_pdf_records)}개, bookmark 없음 {skipped_no_bookmark_count}개"
        )
        for pdf_path, bookmarks in bookmarked_pdf_records:
            self._emit(
                f"bookmark 보유 PDF: {self._display_path(pdf_path)} "
                f"({len(bookmarks)}개)"
            )

        self._emit("TOC page detection 시작")
        for index, (pdf_path, bookmarks) in enumerate(bookmarked_pdf_records, start=1):
            results.append(
                self._detect_pdf(
                    pdf_path,
                    bookmarks,
                    index=index,
                    total=len(bookmarked_pdf_records),
                )
            )

        detected_count = sum(1 for result in results if result.status == "detected")
        not_detected_count = sum(
            1 for result in results if result.status == "not_detected"
        )
        failed_count = sum(1 for result in results if result.status == "failed")
        return BookmarkedPdfTocBatchResult(
            root_dir=self.input_dir,
            recursive=self.recursive,
            max_text_pages=self.max_text_pages,
            total_pdf_count=len(pdf_paths),
            bookmarked_pdf_count=sum(
                1 for result in results if result.bookmark_count > 0
            ),
            skipped_no_bookmark_count=skipped_no_bookmark_count,
            detected_count=detected_count,
            not_detected_count=not_detected_count,
            failed_count=failed_count,
            results=results,
        )

    def _find_pdfs(self) -> list[Path]:
        iterator = (
            self.input_dir.rglob("*") if self.recursive else self.input_dir.iterdir()
        )
        return sorted(
            path
            for path in iterator
            if path.is_file() and path.suffix.lower() == ".pdf"
        )

    def _detect_pdf(
        self,
        pdf_path: Path,
        bookmarks: list[dict[str, object]],
        index: int,
        total: int,
    ) -> BookmarkedPdfTocDetection:
        display_path = self._display_path(pdf_path)
        try:
            self._emit(f"PDF 열기 ({index}/{total}): {display_path}")
            with fitz.open(pdf_path) as document:
                total_pages = document.page_count
            self._emit(f"PDF page 수 확인: {display_path} ({total_pages} pages)")

            self._emit(
                f"text layer 추출 중: {display_path} (최대 {self.max_text_pages} pages)"
            )
            pages = extract_page_texts(pdf_path, max_pages=self.max_text_pages)
            self._emit(f"text layer 추출 완료: {display_path} ({len(pages)} pages)")

            self._emit(f"page feature 계산 중: {display_path}")
            features = calculate_page_features(pages, total_pages=total_pages)
            self._emit(f"bookmark-guided TOC 탐지 중: {display_path}")
            detection = detect_toc_pages_from_bookmarks(
                pages,
                bookmarks,
                features=features,
            )
        except Exception as error:  # noqa: BLE001
            self._emit(f"TOC 탐지 실패: {display_path} ({type(error).__name__})")
            return self._failed_result(pdf_path, error, bookmark_count=len(bookmarks))

        warnings: list[str] = []
        if not pages:
            warnings.append("PDF 앞부분에서 text layer를 읽지 못했다.")
        if not detection.pages:
            warnings.append("bookmark-guided TOC page 후보를 찾지 못했다.")

        status = "detected" if detection.pages else "not_detected"
        if detection.pages:
            self._emit(
                f"TOC 탐지 완료: {display_path} "
                f"(pages={detection.pages}, confidence={detection.confidence:.3f})"
            )
        else:
            self._emit(f"TOC 탐지 결과 없음: {display_path}")
        return BookmarkedPdfTocDetection(
            status=status,
            input_pdf=pdf_path,
            root_relative_pdf=self._relative_to_root(pdf_path),
            total_pages=total_pages,
            observed_text_pages=len(pages),
            bookmark_count=len(bookmarks),
            toc_pages=detection.pages,
            confidence=detection.confidence,
            method=detection.method,
            detection=detection,
            warnings=warnings,
        )

    def _failed_result(
        self,
        pdf_path: Path,
        error: Exception,
        bookmark_count: int = 0,
    ) -> BookmarkedPdfTocDetection:
        return BookmarkedPdfTocDetection(
            status="failed",
            input_pdf=pdf_path,
            root_relative_pdf=self._relative_to_root(pdf_path),
            bookmark_count=bookmark_count,
            error=f"{type(error).__name__}: {error}",
        )

    def _relative_to_root(self, pdf_path: Path) -> Path | None:
        try:
            return pdf_path.relative_to(self.input_dir)
        except ValueError:
            return None

    def _display_path(self, pdf_path: Path) -> str:
        relative_path = self._relative_to_root(pdf_path)
        return str(relative_path if relative_path is not None else pdf_path)

    def _emit(self, message: str) -> None:
        if self.diagnostics is not None:
            self.diagnostics(message)
