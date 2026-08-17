"""고수준 Python workflow와 canonical plan 계약을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from pdfbooktree import (
    ProcessingConfig,
    apply_plan_file,
    infer_pdf,
    package_version,
    preview_apply_plan,
    process_pdf,
    resolve_processing_config,
)
from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import ExistingOutlineItem


def _make_existing_outline_book(path: Path) -> None:
    document = fitz.open()
    try:
        for page_number in range(1, 4):
            page = document.new_page()
            page.insert_text((72, 72), f"Page {page_number} body")
        document.set_toc(
            [
                [1, "Chapter 1", 1],
                [2, "Section 1.1", 2],
                [1, "Chapter 2", 3],
                [2, "Section 2.1", 3],
            ]
        )
        document.save(path)
    finally:
        document.close()


def test_infer_preview_apply는_같은_canonical_plan을_사용한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_existing_outline_book(pdf)

    inferred = infer_pdf(pdf, tmp_path / "infer-runs")

    assert inferred.command == "infer"
    assert inferred.manifest.status == "succeeded"
    assert inferred.result.bookmark_plan_path == inferred.run_dir / "bookmark_plan.json"
    assert inferred.result.bookmark_plan_path.is_file()
    assert inferred.result.review_summary_path is None
    assert inferred.result.review_items_path is None
    assert inferred.result.existing_outline_quality_path is not None

    preview_root = tmp_path / "preview-must-not-exist"
    preview = preview_apply_plan(
        pdf,
        inferred.result.bookmark_plan_path,
        preview_root,
    )

    assert preview.status == "valid"
    assert preview.validation.valid is True
    assert preview.bookmark_count == 4
    assert not preview_root.exists()

    applied = apply_plan_file(
        pdf,
        inferred.result.bookmark_plan_path,
        tmp_path / "apply-runs",
    )

    assert applied.command == "apply"
    assert applied.manifest.status == "succeeded"
    assert applied.result.output_pdf is not None
    assert applied.result.output_pdf.is_file()
    assert applied.result.markdown_manifest_path is not None
    assert applied.result.bookmark_plan_path == applied.run_dir / "bookmark_plan.json"
    assert (
        applied.run_dir / "bookmark_plan_full.json"
    ).read_bytes() == inferred.result.bookmark_plan_path.read_bytes()
    with fitz.open(applied.result.output_pdf) as document:
        assert len(document.get_toc()) == applied.result.bookmark_count
    assert applied.manifest.plan_source == {
        "path": str(inferred.result.bookmark_plan_path),
        "sha256": preview.plan_sha256,
    }


def test_process_pdf는_python_api_config_source와_typed_artifact를_보존한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_existing_outline_book(pdf)

    run = process_pdf(pdf, tmp_path / "runs", ProcessingConfig())

    assert run.command == "process"
    assert run.manifest.config_sources == ({"kind": "python_api"},)
    assert run.manifest.tool.package_version == package_version()
    assert run.result.bookmark_plan_path == run.run_dir / "bookmark_plan.json"
    assert run.result.bookmark_validation_path is not None
    assert run.result.markdown_manifest_path is not None
    assert run.result.existing_outline_quality_path is not None

    same_config_run = process_pdf(
        pdf,
        tmp_path / "same-config-runs",
        ProcessingConfig(),
    )
    assert same_config_run.config_hash == run.config_hash

    resolved = resolve_processing_config()
    resolved_run = process_pdf(pdf, tmp_path / "resolved-runs", resolved)
    assert resolved_run.config_hash == resolved.config_hash
    assert resolved_run.manifest.config_sources == resolved.sources


def test_failed_process_run도_manifest와_canonical_plan을_남긴다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "blank.pdf"
    document = fitz.open()
    document.new_page()
    document.save(pdf)
    document.close()

    run = process_pdf(pdf, tmp_path / "runs")

    assert run.result.status == "failed"
    assert run.manifest.status == "failed"
    assert run.result.bookmark_plan_path == run.run_dir / "bookmark_plan.json"
    assert json.loads(run.result.bookmark_plan_path.read_text(encoding="utf-8")) == []


def test_invalid_apply_preview와_실행은_output을_생성하지_않는다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_existing_outline_book(pdf)
    plan_path = tmp_path / "invalid-plan.json"
    plan_path.write_text(
        json.dumps([{"title": "Broken", "level": 2, "pdf_page": 99}]),
        encoding="utf-8",
    )
    preview_root = tmp_path / "preview"

    preview = preview_apply_plan(pdf, plan_path, preview_root)

    assert preview.status == "failed"
    assert preview.validation.valid is False
    assert not preview_root.exists()

    applied = apply_plan_file(pdf, plan_path, tmp_path / "apply-runs")

    assert applied.result.status == "failed"
    assert applied.manifest.status == "failed"
    assert applied.result.output_pdf is None
    assert applied.result.output_markdown_dir is None
    assert applied.result.bookmark_plan_path.is_file()


def test_infer_pdf_surfaces_reuse_rejected_reason_for_invalid_structure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """구조가 무효한 outline은 quality가 acceptable해도 재사용을 포기하고,
    그 이유가 warnings와 bookmark_review_summary에 남아야 한다."""

    pdf = tmp_path / "book.pdf"
    document = fitz.open()
    try:
        for page_no in range(1, 10):
            page = document.new_page()
            if page_no in (1, 4, 7):
                chapter = {1: 1, 4: 2, 7: 3}[page_no]
                page.insert_text((72, 90), f"Chapter {chapter} Title", fontsize=28)
                page.insert_text((72, 155), f"{chapter}.1 Section", fontsize=16)
            for row in range(15):
                page.insert_text(
                    (72, 260 + row * 15),
                    "This is ordinary body text for the chapter.",
                    fontsize=10,
                )
        document.save(pdf)
    finally:
        document.close()
    invalid_outline = [
        ExistingOutlineItem(1, "Part 1", 1, 1),
        ExistingOutlineItem(2, "Part 2", 1, 4),
        ExistingOutlineItem(3, "Part 3", 1, 7),
        ExistingOutlineItem(4, "Part 4", 1, 999),
    ]
    monkeypatch.setattr("pdfbooktree.pipeline.read_outline", lambda _: invalid_outline)

    run = infer_pdf(
        pdf,
        tmp_path / "infer-runs",
        ProcessingConfig(
            typography=TypographyConfig(min_tier_count=1, max_heading_tier=2)
        ),
    )

    assert any("유효하지 않아" in warning for warning in run.result.warnings)
    assert run.result.review_summary_path is not None
    summary = json.loads(run.result.review_summary_path.read_text("utf-8"))
    assert summary["existing_outline"]["reuse_rejected_reason"] == "invalid_structure"
    assert summary["existing_outline"]["is_low_quality"] is False


def test_apply_exception도_manifest와_canonical_plan을_보존한다(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_existing_outline_book(pdf)
    inferred = infer_pdf(pdf, tmp_path / "infer-runs")
    plan_path = inferred.result.bookmark_plan_path
    assert plan_path is not None
    apply_root = tmp_path / "apply-runs"

    def fail_apply(*args, **kwargs):
        raise RuntimeError("apply failed")

    monkeypatch.setattr("pdfbooktree.workflows.apply_plan", fail_apply)

    with pytest.raises(RuntimeError, match="apply failed"):
        apply_plan_file(pdf, plan_path, apply_root)

    manifests = list(apply_root.rglob("run_manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["plan_source"]["path"] == str(plan_path)
    assert (manifests[0].parent / "bookmark_plan.json").is_file()
