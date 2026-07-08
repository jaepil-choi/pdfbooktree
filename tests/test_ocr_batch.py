from __future__ import annotations

import csv
import json
from pathlib import Path

import fitz

from pdfbooktree.ocr.batch import OcrOverlayBatchConfig, OcrOverlayBatchRunner
from pdfbooktree.ocr.models import OcrOverlayResult


def _insert_full_page_image(page: fitz.Page) -> None:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100))
    pixmap.set_rect(pixmap.irect, (200, 200, 200))
    page.insert_image(page.rect, pixmap=pixmap)


def _write_scanned_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    try:
        for _ in range(2):
            page = document.new_page(width=200, height=200)
            _insert_full_page_image(page)
        document.save(path)
    finally:
        document.close()


def _write_native_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    try:
        for index in range(2):
            page = document.new_page(width=200, height=200)
            page.insert_text((30, 100), f"Native page {index + 1}", fontsize=12)
        document.save(path)
    finally:
        document.close()


def test_ocr_overlay_batch_recursively_processes_only_targets(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "300STUDY"
    _write_scanned_pdf(input_dir / "sub" / "scan.pdf")
    _write_native_pdf(input_dir / "native.pdf")
    seen_configs = []

    class FakeBuilder:
        def __init__(self, config, logger=None):
            seen_configs.append(config)

        def run(self):
            config = seen_configs[-1]
            Path(config.output_pdf).parent.mkdir(parents=True, exist_ok=True)
            Path(config.output_pdf).write_bytes(b"%PDF-1.7\n")
            return OcrOverlayResult(
                status="processed",
                input_pdf=Path(config.input_pdf),
                output_pdf=Path(config.output_pdf),
                output_dir=Path(config.output_dir),
                page_count=2,
                processed_pages=[1, 2],
                engine="upstage",
                cache_hit_count=1,
                cache_miss_count=1,
            )

    monkeypatch.setattr("pdfbooktree.ocr.batch.OcrOverlayBuilder", FakeBuilder)

    output_dir = tmp_path / "out"
    result = OcrOverlayBatchRunner(
        OcrOverlayBatchConfig(
            input_dir=input_dir,
            output_dir=output_dir,
            recursive=True,
            force=True,
            confirm_bookmark_ocr_overwrite=True,
        )
    ).run()

    assert result.total_pdf_count == 2
    assert result.target_count == 1
    assert result.processed_count == 1
    assert result.skipped_count == 1
    assert len(seen_configs) == 1
    assert seen_configs[0].output_pdf == output_dir / "pdfs" / "sub" / "scan.pdf"
    assert seen_configs[0].output_dir == output_dir / "artifacts" / "sub" / "scan"
    assert seen_configs[0].force is True
    assert seen_configs[0].confirm_bookmark_ocr_overwrite is True

    with (output_dir / "ocr_overlay_batch_report.csv").open(
        encoding="utf-8-sig", newline=""
    ) as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"processed", "skipped"}

    summary = json.loads(
        (output_dir / "ocr_overlay_batch_summary.json").read_text(encoding="utf-8")
    )
    assert summary["processed_count"] == 1


def test_ocr_overlay_batch_dry_run_does_not_call_builder(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "300STUDY"
    _write_scanned_pdf(input_dir / "scan.pdf")

    def fail_builder(*args, **kwargs):
        raise AssertionError("dry-run must not build OCR overlay")

    monkeypatch.setattr("pdfbooktree.ocr.batch.OcrOverlayBuilder", fail_builder)

    result = OcrOverlayBatchRunner(
        OcrOverlayBatchConfig(
            input_dir=input_dir, output_dir=tmp_path / "out", dry_run=True
        )
    ).run()

    assert result.target_count == 1
    assert result.dry_run_count == 1
    assert result.processed_count == 0
