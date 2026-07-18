"""디렉터리를 recursive로 순회하며 scan/bookmark 배치 분류를 실행한다.

- 실행 자체는 PDF를 전혀 수정하지 않는 읽기 전용 분류 단계다.
- `dry_run`은 후속 OCR overwrite 같은 변경 작업을 하지 않는다는 의미다.
- `write_report=True`면 CSV/JSONL/summary를 저장하고, 파일마다 CSV row와 JSONL
  detail을 즉시 flush한다. 중간에 실패해도 이미 처리한 결과는 남는다.
- `write_report=False`면 디스크 report 없이 진행 로그와 최종 집계만 남긴다.
- 파일 하나가 corrupt/encrypted 등으로 열리지 않아도 배치 전체를 멈추지 않고
  해당 행에 error를 남긴 채 계속 진행한다.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path

from pdfbooktree.classify.logger import (
    ClassifyLogEvent,
    ClassifyLogger,
    NullClassifyLogger,
)
from pdfbooktree.classify.models import ClassifyBatchResult, ClassifyFileResult
from pdfbooktree.pdf.bookmarks import (
    extract_existing_bookmarks,
    has_meaningful_bookmark,
)
from pdfbooktree.pdf.scan_classification import classify_scan
from pdfbooktree.pdf.scan_signals import DEFAULT_MAX_SAMPLE_PAGES
from pdfbooktree.utils.jsonio import to_jsonable
from pdfbooktree.utils.pdf_discovery import discover_pdfs


CSV_FIELDS = [
    "pdf_id",
    "relative_path",
    "page_count",
    "sampled_page_count",
    "scanned_page_fraction",
    "total_visible_chars_sampled",
    "total_invisible_chars_sampled",
    "is_scanned",
    "reject_reasons",
    "bookmark_count",
    "toc_level_count",
    "has_meaningful_bookmark",
    "is_ocr_overwrite_target",
    "target_reject_reason",
    "error",
    "elapsed_sec",
]


@dataclass(frozen=True)
class ClassifyBatchConfig:
    """scan/bookmark 배치 분류 실행 설정이다."""

    input_dir: Path | str
    output_dir: Path | str
    recursive: bool = False
    dry_run: bool = False
    write_report: bool = True
    max_sample_pages: int = DEFAULT_MAX_SAMPLE_PAGES
    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()


class ScanBookmarkClassifier:
    """디렉터리 안 PDF들을 순회하며 scan/bookmark 분류를 실행한다."""

    def __init__(
        self, config: ClassifyBatchConfig, logger: ClassifyLogger | None = None
    ) -> None:
        self.input_dir = Path(config.input_dir)
        self.output_dir = Path(config.output_dir)
        self.config = config
        self.logger = logger or NullClassifyLogger()

    def run(self) -> ClassifyBatchResult:
        """input_dir 아래 PDF를 전부 분류하고 report를 저장한다."""

        discovery = discover_pdfs(
            self.input_dir,
            self.output_dir,
            recursive=self.config.recursive,
            include_globs=self.config.include_globs,
            exclude_globs=self.config.exclude_globs,
        )
        pdf_paths = list(discovery.paths)
        started_at = time.monotonic()

        report_csv_path: Path | None = None
        detail_jsonl_path: Path | None = None
        csv_file = None
        csv_writer = None
        detail_file = None

        if self.config.write_report:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            report_csv_path = self.output_dir / "classification_report.csv"
            detail_jsonl_path = self.output_dir / "classification_detail.jsonl"
            csv_file = report_csv_path.open("w", encoding="utf-8-sig", newline="")
            csv_writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            csv_writer.writeheader()
            detail_file = detail_jsonl_path.open("w", encoding="utf-8")

        results: list[ClassifyFileResult] = []
        target_count = 0
        error_count = 0

        try:
            for index, path in enumerate(pdf_paths, start=1):
                result = self._classify_one(path)
                results.append(result)
                if result.error is not None:
                    error_count += 1
                if result.is_ocr_overwrite_target:
                    target_count += 1

                if csv_writer is not None and csv_file is not None:
                    csv_writer.writerow(_to_csv_row(result))
                    csv_file.flush()
                if detail_file is not None:
                    detail_file.write(
                        json.dumps(to_jsonable(result), ensure_ascii=False) + "\n"
                    )
                    detail_file.flush()

                self.logger.emit(
                    ClassifyLogEvent(
                        event="failed" if result.error is not None else "classified",
                        level="error" if result.error is not None else "info",
                        input_pdf=path,
                        completed_count=index,
                        total_count=len(pdf_paths),
                        target_count=target_count,
                        error_count=error_count,
                        elapsed_sec=time.monotonic() - started_at,
                        message=result.error or result.target_reject_reason,
                    )
                )
        finally:
            if csv_file is not None:
                csv_file.close()
            if detail_file is not None:
                detail_file.close()
            self.logger.close()

        scanned_count = sum(1 for result in results if result.is_scanned)
        native_count = len(results) - scanned_count

        batch_result = ClassifyBatchResult(
            total_pdf_count=len(results),
            scanned_count=scanned_count,
            native_count=native_count,
            target_count=target_count,
            error_count=error_count,
            elapsed_sec=time.monotonic() - started_at,
            report_csv_path=report_csv_path,
            detail_jsonl_path=detail_jsonl_path,
            results=results,
            include_globs=discovery.include_globs,
            exclude_globs=discovery.exclude_globs,
            excluded_output_subtree=discovery.excluded_output_subtree,
        )

        if self.config.write_report:
            self._write_summary(batch_result)

        return batch_result

    def _classify_one(self, path: Path) -> ClassifyFileResult:
        started_at = time.monotonic()
        relative_path = path.relative_to(self.input_dir).as_posix()
        try:
            scan = classify_scan(path, self.config.max_sample_pages)
            bookmarks = extract_existing_bookmarks(path)
            meaningful = has_meaningful_bookmark(bookmarks)
            toc_level_count = len({bookmark["level"] for bookmark in bookmarks})

            is_target = scan.is_scanned and not meaningful
            if is_target:
                target_reject_reason = ""
            elif not scan.is_scanned:
                target_reject_reason = "not_scanned: " + " | ".join(scan.reject_reasons)
            else:
                target_reject_reason = "has_meaningful_bookmark"

            return ClassifyFileResult(
                pdf_path=path,
                relative_path=relative_path,
                page_count=scan.page_count,
                sampled_page_count=scan.sampled_page_count,
                scanned_page_fraction=scan.scanned_page_fraction,
                total_visible_chars_sampled=scan.total_visible_chars_sampled,
                total_invisible_chars_sampled=scan.total_invisible_chars_sampled,
                is_scanned=scan.is_scanned,
                reject_reasons=list(scan.reject_reasons),
                bookmark_count=len(bookmarks),
                toc_level_count=toc_level_count,
                has_meaningful_bookmark=meaningful,
                is_ocr_overwrite_target=is_target,
                target_reject_reason=target_reject_reason,
                error=None,
                elapsed_sec=time.monotonic() - started_at,
                page_features=scan.page_features,
            )
        except Exception as error:  # noqa: BLE001 - 배치는 파일별 실패를 report에 남겨야 한다.
            return ClassifyFileResult(
                pdf_path=path,
                relative_path=relative_path,
                page_count=0,
                sampled_page_count=0,
                scanned_page_fraction=0.0,
                total_visible_chars_sampled=0,
                total_invisible_chars_sampled=0,
                is_scanned=False,
                reject_reasons=[],
                bookmark_count=0,
                toc_level_count=0,
                has_meaningful_bookmark=False,
                is_ocr_overwrite_target=False,
                target_reject_reason="",
                error=str(error),
                elapsed_sec=time.monotonic() - started_at,
            )

    def _write_summary(self, batch_result: ClassifyBatchResult) -> None:
        summary_path = self.output_dir / "classification_summary.json"
        summary_path.write_text(
            json.dumps(
                to_jsonable(
                    {
                        "total_pdf_count": batch_result.total_pdf_count,
                        "scanned_count": batch_result.scanned_count,
                        "native_count": batch_result.native_count,
                        "target_count": batch_result.target_count,
                        "error_count": batch_result.error_count,
                        "include_globs": list(batch_result.include_globs),
                        "exclude_globs": list(batch_result.exclude_globs),
                        "excluded_output_subtree": (
                            str(batch_result.excluded_output_subtree)
                            if batch_result.excluded_output_subtree is not None
                            else None
                        ),
                        "elapsed_sec": batch_result.elapsed_sec,
                    }
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def _to_csv_row(result: ClassifyFileResult) -> dict[str, object]:
    return {
        "pdf_id": result.pdf_path.stem,
        "relative_path": result.relative_path,
        "page_count": result.page_count,
        "sampled_page_count": result.sampled_page_count,
        "scanned_page_fraction": f"{result.scanned_page_fraction:.4f}",
        "total_visible_chars_sampled": result.total_visible_chars_sampled,
        "total_invisible_chars_sampled": result.total_invisible_chars_sampled,
        "is_scanned": result.is_scanned,
        "reject_reasons": " | ".join(result.reject_reasons),
        "bookmark_count": result.bookmark_count,
        "toc_level_count": result.toc_level_count,
        "has_meaningful_bookmark": result.has_meaningful_bookmark,
        "is_ocr_overwrite_target": result.is_ocr_overwrite_target,
        "target_reject_reason": result.target_reject_reason,
        "error": result.error or "",
        "elapsed_sec": f"{result.elapsed_sec:.4f}",
    }
