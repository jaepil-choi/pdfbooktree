"""immutable run directory와 manifest lifecycle을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from pdfbooktree.config_io import resolve_processing_config
from pdfbooktree.run import RunError, create_run_context


def make_pdf(path: Path, page_count: int = 2) -> None:
    """run identity 검사용 작은 PDF를 만든다."""

    document = fitz.open()
    try:
        for index in range(page_count):
            page = document.new_page()
            page.insert_text((72, 72), f"Page {index + 1}")
        document.save(path)
    finally:
        document.close()


def test_create_run_context는_input_config_identity를_기록한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "한국어 책.pdf"
    make_pdf(pdf)
    resolved = resolve_processing_config(
        set_overrides=["typography.position_fallback_tolerance=1.5"]
    )

    context = create_run_context(pdf, tmp_path / "runs", resolved)

    assert context.run_dir.is_dir()
    assert context.manifest.status == "created"
    assert context.manifest.input.path == pdf.resolve()
    assert context.manifest.input.page_count == 2
    assert len(context.manifest.input.sha256) == 64
    assert context.manifest.config_hash == resolved.config_hash
    assert context.manifest.resolved_config_path.is_file()
    assert context.manifest_path.is_file()
    assert "한국어_책" in context.run_dir.parent.name


def test_same_input_config도_서로_다른_immutable_run을_만든다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    make_pdf(pdf)
    resolved = resolve_processing_config()

    first = create_run_context(pdf, tmp_path / "runs", resolved)
    second = create_run_context(pdf, tmp_path / "runs", resolved)

    assert first.run_dir != second.run_dir
    assert first.manifest.input.sha256 == second.manifest.input.sha256
    assert first.manifest.config_hash == second.manifest.config_hash


def test_existing_explicit_run_directory는_덮어쓰지_않는다(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    make_pdf(pdf)
    run_dir = tmp_path / "chosen-run"
    run_dir.mkdir()

    with pytest.raises(RunError, match="이미 있다"):
        create_run_context(
            pdf,
            tmp_path / "runs",
            resolve_processing_config(),
            run_dir=run_dir,
        )


def test_run_manifest는_running과_success를_기록한다(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    make_pdf(pdf)
    context = create_run_context(pdf, tmp_path / "runs", resolve_processing_config())
    artifact = context.run_dir / "bookmark_plan.json"
    artifact.write_text("[]", encoding="utf-8")
    output_pdf = context.run_dir / "book_bookmarked.pdf"
    output_pdf.write_bytes(b"%PDF-1.7\n")
    report = context.run_dir / "book_report.json"
    report.write_text("{}", encoding="utf-8")

    context.start()
    context.complete(
        SimpleNamespace(
            status="processed",
            artifact_paths={"bookmark_plan": artifact},
            output_pdf=output_pdf,
            output_markdown_dir=None,
            ocr_pdf=None,
            report_path=report,
            warnings=["검토 필요"],
        )
    )

    payload = json.loads(context.manifest_path.read_text(encoding="utf-8"))
    assert payload["status"] == "succeeded"
    assert payload["processing_status"] == "processed"
    assert payload["artifact_paths"]["bookmark_plan"] == str(artifact)
    assert payload["output_paths"]["output_pdf"] == str(output_pdf)
    assert payload["warnings"] == ["검토 필요"]
    assert payload["started_at"] is not None
    assert payload["finished_at"] is not None


def test_run_manifest는_exception을_failed로_기록한다(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    make_pdf(pdf)
    context = create_run_context(pdf, tmp_path / "runs", resolve_processing_config())

    context.start()
    context.fail(RuntimeError("boom"))

    payload = json.loads(context.manifest_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["error"] == {"type": "RuntimeError", "message": "boom"}
