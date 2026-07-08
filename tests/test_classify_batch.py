"""ScanBookmarkClassifier의 배치 분류/report 생성을 검증한다."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import fitz

from pdfbooktree.classify.batch_classify import (
    ClassifyBatchConfig,
    ScanBookmarkClassifier,
)


def _insert_full_page_image(page: fitz.Page) -> None:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100))
    pixmap.set_rect(pixmap.irect, (200, 200, 200))
    page.insert_image(page.rect, pixmap=pixmap)


def _write_native_pdf_with_bookmark(path: Path) -> None:
    document = fitz.open()
    try:
        for index in range(2):
            page = document.new_page(width=200, height=200)
            page.insert_text((30, 100), f"Native page {index + 1} body", fontsize=12)
        document.set_toc([[1, "Chapter 1", 1], [2, "1.1 Topic", 2]])
        document.save(path)
    finally:
        document.close()


def _write_scanned_pdf_without_bookmark(path: Path) -> None:
    document = fitz.open()
    try:
        for _ in range(2):
            page = document.new_page(width=200, height=200)
            _insert_full_page_image(page)
        document.save(path)
    finally:
        document.close()


def _write_scanned_pdf_with_meaningful_bookmark(path: Path) -> None:
    document = fitz.open()
    try:
        for _ in range(2):
            page = document.new_page(width=200, height=200)
            _insert_full_page_image(page)
        document.set_toc([[1, "Part 1", 1], [2, "Chapter 1", 1]])
        document.save(path)
    finally:
        document.close()


def _write_corrupt_pdf(path: Path) -> None:
    path.write_bytes(b"not a real pdf")


def test_batch_writes_csv_and_jsonl_reports_with_correct_targets(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()
    _write_native_pdf_with_bookmark(input_dir / "native.pdf")
    _write_scanned_pdf_without_bookmark(input_dir / "scanned_no_bookmark.pdf")
    _write_scanned_pdf_with_meaningful_bookmark(input_dir / "scanned_with_bookmark.pdf")
    _write_corrupt_pdf(input_dir / "broken.pdf")

    output_dir = tmp_path / "out"
    config = ClassifyBatchConfig(input_dir=input_dir, output_dir=output_dir)
    result = ScanBookmarkClassifier(config).run()

    assert result.total_pdf_count == 4
    assert result.error_count == 1
    assert result.target_count == 1

    by_relative_path = {item.relative_path: item for item in result.results}
    assert by_relative_path["native.pdf"].is_ocr_overwrite_target is False
    assert by_relative_path["native.pdf"].target_reject_reason.startswith("not_scanned")
    assert by_relative_path["scanned_no_bookmark.pdf"].is_ocr_overwrite_target is True
    assert by_relative_path["scanned_no_bookmark.pdf"].target_reject_reason == ""
    assert (
        by_relative_path["scanned_with_bookmark.pdf"].is_ocr_overwrite_target is False
    )
    assert (
        by_relative_path["scanned_with_bookmark.pdf"].target_reject_reason
        == "has_meaningful_bookmark"
    )
    assert by_relative_path["broken.pdf"].error is not None

    csv_path = output_dir / "classification_report.csv"
    assert csv_path.exists()
    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 4
    target_row = next(
        row for row in rows if row["relative_path"] == "scanned_no_bookmark.pdf"
    )
    assert target_row["is_ocr_overwrite_target"] == "True"

    jsonl_path = output_dir / "classification_detail.jsonl"
    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4
    detail = json.loads(lines[0])
    assert "relative_path" in detail

    summary_path = output_dir / "classification_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["total_pdf_count"] == 4
    assert summary["target_count"] == 1
    assert summary["error_count"] == 1


def test_batch_dry_run_writes_report_files_when_enabled(tmp_path: Path) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()
    _write_scanned_pdf_without_bookmark(input_dir / "scanned_no_bookmark.pdf")

    output_dir = tmp_path / "out"
    config = ClassifyBatchConfig(
        input_dir=input_dir, output_dir=output_dir, dry_run=True
    )
    result = ScanBookmarkClassifier(config).run()

    assert result.total_pdf_count == 1
    assert result.target_count == 1
    assert result.report_csv_path == output_dir / "classification_report.csv"
    assert result.detail_jsonl_path == output_dir / "classification_detail.jsonl"
    assert (output_dir / "classification_report.csv").exists()
    assert (output_dir / "classification_detail.jsonl").exists()
    assert (output_dir / "classification_summary.json").exists()


def test_batch_skips_report_files_when_disabled(tmp_path: Path) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()
    _write_scanned_pdf_without_bookmark(input_dir / "scanned_no_bookmark.pdf")

    output_dir = tmp_path / "out"
    config = ClassifyBatchConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        dry_run=True,
        write_report=False,
    )
    result = ScanBookmarkClassifier(config).run()

    assert result.total_pdf_count == 1
    assert result.target_count == 1
    assert result.report_csv_path is None
    assert result.detail_jsonl_path is None
    assert not output_dir.exists()


def test_batch_recursive_finds_pdfs_in_subdirectories(tmp_path: Path) -> None:
    input_dir = tmp_path / "pdfs"
    (input_dir / "sub").mkdir(parents=True)
    _write_scanned_pdf_without_bookmark(input_dir / "sub" / "scanned.pdf")

    non_recursive = ScanBookmarkClassifier(
        ClassifyBatchConfig(
            input_dir=input_dir, output_dir=tmp_path / "out1", dry_run=True
        )
    ).run()
    recursive = ScanBookmarkClassifier(
        ClassifyBatchConfig(
            input_dir=input_dir,
            output_dir=tmp_path / "out2",
            recursive=True,
            dry_run=True,
        )
    ).run()

    assert non_recursive.total_pdf_count == 0
    assert recursive.total_pdf_count == 1
