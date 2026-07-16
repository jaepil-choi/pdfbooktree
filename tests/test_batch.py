"""BatchProcessor를 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from pdfbooktree.batch import BatchProcessor
from pdfbooktree.config import ProcessingConfig, TypographyConfig
from pdfbooktree.models import ProcessingResult


def _write_pdf(path: Path, title: str) -> None:
    document = fitz.open()
    try:
        for page_no in range(1, 6):
            page = document.new_page()
            page.insert_text((72, 90), f"{title} {page_no}", fontsize=28)
            for row in range(10):
                page.insert_text(
                    (72, 160 + row * 15),
                    "Repeated ordinary body text for coverage.",
                    fontsize=10,
                )
        document.save(path)
    finally:
        document.close()


def test_batch_processes_pdfs(tmp_path: Path) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()
    _write_pdf(input_dir / "a.pdf", "Chapter 1 Alpha")
    _write_pdf(input_dir / "b.pdf", "Chapter 1 Beta")

    result = BatchProcessor(
        input_dir,
        tmp_path / "out",
        ProcessingConfig(
            typography=TypographyConfig(min_tier_count=1, max_heading_tier=2)
        ),
    ).run()

    assert result.total_pdf_count == 2
    assert result.processed_count == 2
    assert result.failed_count == 0
    assert len(result.results) == 2
    assert result.batch_run_id is not None
    assert result.batch_run_dir is not None and result.batch_run_dir.is_dir()
    assert result.batch_manifest_path is not None
    batch_manifest = json.loads(result.batch_manifest_path.read_text(encoding="utf-8"))
    assert batch_manifest["schema_version"] == 1
    assert batch_manifest["status"] == "succeeded"
    assert batch_manifest["batch_run_id"] == result.batch_run_id
    assert batch_manifest["config_hash"] == result.config_hash
    assert batch_manifest["summary"]["completed_count"] == 2
    assert batch_manifest["summary"]["failed_count"] == 0
    assert len(batch_manifest["item_runs"]) == 2
    assert {item.config_hash for item in result.results} == {
        result.results[0].config_hash
    }
    for item in result.results:
        assert item.run_id is not None
        assert item.run_dir is not None and item.run_dir.is_dir()
        assert item.manifest_path is not None and item.manifest_path.is_file()
        assert item.output_pdf is not None and item.output_pdf.is_file()
        assert item.output_pdf.is_relative_to(item.run_dir)
        manifest = json.loads(item.manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "succeeded"
        assert manifest["config_hash"] == item.config_hash
        assert manifest["run_id"] == item.run_id
    by_input = {
        Path(item["input_pdf"]).name: item for item in batch_manifest["item_runs"]
    }
    assert set(by_input) == {"a.pdf", "b.pdf"}
    assert all(item["manifest_path"] for item in by_input.values())
    assert all(item["output_paths"]["output_pdf"] for item in by_input.values())


def test_batch_records_processor_exception_in_item_manifest(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()
    pdf = input_dir / "broken.pdf"
    _write_pdf(pdf, "Chapter 1 Broken")

    class FailingProcessor:
        def __init__(self, input_pdf, output_dir, config):
            self.input_pdf = input_pdf

        def run(self):
            raise RuntimeError("item 처리 실패")

    monkeypatch.setattr("pdfbooktree.batch.Processor", FailingProcessor)

    result = BatchProcessor(input_dir, tmp_path / "out").run()

    assert result.total_pdf_count == 1
    assert result.processed_count == 0
    assert result.failed_count == 1
    item = result.results[0]
    assert item.status == "failed"
    assert item.warnings == ["item 처리 실패"]
    assert item.manifest_path is not None and item.manifest_path.is_file()
    manifest = json.loads(item.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["error"] == {
        "type": "RuntimeError",
        "message": "item 처리 실패",
    }


def test_batch_keeps_partial_processing_failure_in_item_manifests(
    monkeypatch, tmp_path: Path
) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()
    _write_pdf(input_dir / "a.pdf", "Chapter 1 Success")
    _write_pdf(input_dir / "b.pdf", "Chapter 1 Failed")

    class PartialFailureProcessor:
        def __init__(self, input_pdf, output_dir, config):
            self.input_pdf = Path(input_pdf)

        def run(self):
            if self.input_pdf.name == "b.pdf":
                return ProcessingResult(
                    status="failed",
                    input_pdf=self.input_pdf,
                    warnings=["bookmark plan 검증 실패"],
                )
            return ProcessingResult(status="processed", input_pdf=self.input_pdf)

    monkeypatch.setattr("pdfbooktree.batch.Processor", PartialFailureProcessor)

    result = BatchProcessor(input_dir, tmp_path / "out").run()

    assert result.processed_count == 1
    assert result.failed_count == 1
    by_name = {item.input_pdf.name: item for item in result.results}
    success_manifest = json.loads(
        by_name["a.pdf"].manifest_path.read_text(encoding="utf-8")
    )
    failed_manifest = json.loads(
        by_name["b.pdf"].manifest_path.read_text(encoding="utf-8")
    )
    assert success_manifest["status"] == "succeeded"
    assert success_manifest["processing_status"] == "processed"
    assert failed_manifest["status"] == "failed"
    assert failed_manifest["processing_status"] == "failed"
    assert failed_manifest["error"] is None
    assert failed_manifest["warnings"] == ["bookmark plan 검증 실패"]
    batch_manifest = json.loads(result.batch_manifest_path.read_text(encoding="utf-8"))
    assert batch_manifest["status"] == "succeeded"
    assert batch_manifest["summary"]["processed_count"] == 1
    assert batch_manifest["summary"]["failed_count"] == 1


def test_batch_records_unreadable_pdf_in_failed_item_manifest(tmp_path: Path) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()
    broken_pdf = input_dir / "broken.pdf"
    broken_pdf.write_bytes(b"not a pdf")

    result = BatchProcessor(input_dir, tmp_path / "out").run()

    assert result.failed_count == 1
    item = result.results[0]
    assert item.manifest_path is not None and item.manifest_path.is_file()
    manifest = json.loads(item.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["input"]["page_count"] is None
    assert manifest["error"]["type"] == "FileDataError"
    batch_manifest = json.loads(result.batch_manifest_path.read_text(encoding="utf-8"))
    assert batch_manifest["status"] == "succeeded"
    assert batch_manifest["summary"]["failed_count"] == 1


def test_batch_records_command_exception_in_failed_batch_manifest(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "pdfs"
    input_dir.mkdir()
    _write_pdf(input_dir / "book.pdf", "Chapter 1 Broken Logger")

    class FailingLogger:
        def emit(self, event) -> None:
            raise RuntimeError("batch event 출력 실패")

        def close(self) -> None:
            return None

    output_dir = tmp_path / "out"
    processor = BatchProcessor(input_dir, output_dir, log=FailingLogger())

    with pytest.raises(RuntimeError, match="batch event 출력 실패"):
        processor.run()

    manifest_paths = list((output_dir / "_batch_runs").glob("*/batch_manifest.json"))
    assert len(manifest_paths) == 1
    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["summary"]["completed_count"] == 1
    assert manifest["error"] == {
        "type": "RuntimeError",
        "message": "batch event 출력 실패",
    }
    assert len(manifest["item_runs"]) == 1
    assert manifest["item_runs"][0]["manifest_path"] is not None
