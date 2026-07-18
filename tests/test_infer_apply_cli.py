"""infer/apply CLI가 로드맵 Phase 2 완료 조건을 지키는지 검증한다."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import fitz
from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.utils.hashing import file_sha256

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
RUNNER = CliRunner()


def _make_typography_book(path: Path, *, toc: list[list[object]] | None = None) -> None:
    document = fitz.open()
    try:
        for page_no in range(1, 7):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            chapter = {1: "Chapter 1 Introduction", 4: "Chapter 2 Methods"}.get(
                page_no, f"Chapter {page_no} Introduction"
            )
            page.insert_text((72, 90), chapter, fontsize=28)
            page.insert_text((72, 155), f"{page_no}.1 Motivation", fontsize=16)
            for row in range(20):
                page.insert_text(
                    (72, 300 + row * 15),
                    "This is ordinary body text for the chapter.",
                    fontsize=10,
                )
        if toc is not None:
            document.set_toc(toc)
        document.save(path)
    finally:
        document.close()


def _typography_set_options() -> list[str]:
    return [
        "--set",
        "typography.min_tier_count=1",
        "--set",
        "typography.max_heading_tier=2",
    ]


def test_infer_does_not_write_pdf_or_markdown(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_typography_book(pdf)

    result = RUNNER.invoke(
        app,
        ["infer", str(pdf), "--output-dir", str(output_dir), "--flat-output"]
        + _typography_set_options(),
    )

    assert result.exit_code == 0, result.output
    assert not list(output_dir.glob("*_bookmarked.pdf"))
    assert not list(output_dir.glob("*_markdown"))
    plan = json.loads((output_dir / "bookmark_plan.json").read_text("utf-8"))
    assert len(plan) > 2
    assert (output_dir / "bookmark_review_summary.json").is_file()
    assert (output_dir / "bookmark_review_items.jsonl").is_file()


def test_infer_run_manifest_links_review_artifacts(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_root = tmp_path / "runs"
    _make_typography_book(pdf)

    result = RUNNER.invoke(
        app,
        ["infer", str(pdf), "--output-dir", str(output_root)]
        + _typography_set_options(),
    )

    assert result.exit_code == 0, result.output
    manifest_path = next(output_root.rglob("run_manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary_path = Path(manifest["artifact_paths"]["bookmark_review_summary"])
    items_path = Path(manifest["artifact_paths"]["bookmark_review_items"])
    assert summary_path.is_file()
    assert items_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["plan_item_count"] > 2
    assert summary["candidate_mapping"]["missing_count"] == 0


def test_infer_skips_when_existing_outline_is_good_quality(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    toc = [[1, f"Chapter {index}", index] for index in range(1, 6)]
    _make_typography_book(pdf, toc=toc)

    result = RUNNER.invoke(
        app, ["infer", str(pdf), "--output-dir", str(output_dir), "--flat-output"]
    )

    assert result.exit_code == 0, result.output
    assert (output_dir / "existing_outline_plan.json").exists()
    assert (output_dir / "bookmark_plan.json").exists()
    assert not (output_dir / "whole_book_lines.jsonl").exists()
    quality = json.loads(
        (output_dir / "existing_outline_quality.json").read_text("utf-8")
    )
    assert quality["is_low_quality"] is False


def test_infer_flags_low_quality_existing_outline_but_still_skips_by_default(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    toc = [[1, "Chapter 1", 1], [1, "Chapter 2", 4]]
    _make_typography_book(pdf, toc=toc)

    result = RUNNER.invoke(
        app, ["infer", str(pdf), "--output-dir", str(output_dir), "--flat-output"]
    )

    assert result.exit_code == 0, result.output
    assert (output_dir / "existing_outline_plan.json").exists()
    assert (output_dir / "bookmark_plan.json").exists()
    assert not (output_dir / "whole_book_lines.jsonl").exists()
    quality = json.loads(
        (output_dir / "existing_outline_quality.json").read_text("utf-8")
    )
    assert quality["is_low_quality"] is True
    assert "too_few_items" in quality["reasons"]


def test_infer_replaces_low_quality_existing_outline_when_configured(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    toc = [[1, "Chapter 1", 1], [1, "Chapter 2", 4]]
    _make_typography_book(pdf, toc=toc)

    result = RUNNER.invoke(
        app,
        ["infer", str(pdf), "--output-dir", str(output_dir), "--flat-output"]
        + _typography_set_options()
        + ["--set", "outline_quality.replace_when_low_quality=true"],
    )

    assert result.exit_code == 0, result.output
    assert (output_dir / "whole_book_lines.jsonl").exists()
    plan = json.loads((output_dir / "bookmark_plan.json").read_text("utf-8"))
    assert len(plan) > 2
    assert not list(output_dir.glob("*_bookmarked.pdf"))


def test_apply_produces_pdf_and_markdown_from_infer_plan(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    infer_dir = tmp_path / "infer_out"
    apply_dir = tmp_path / "apply_out"
    _make_typography_book(pdf)

    infer_result = RUNNER.invoke(
        app,
        ["infer", str(pdf), "--output-dir", str(infer_dir), "--flat-output"]
        + _typography_set_options(),
    )
    assert infer_result.exit_code == 0, infer_result.output
    plan_path = infer_dir / "bookmark_plan.json"

    apply_result = RUNNER.invoke(
        app,
        [
            "apply",
            str(pdf),
            "--plan",
            str(plan_path),
            "--output-dir",
            str(apply_dir),
            "--flat-output",
        ],
    )

    assert apply_result.exit_code == 0, apply_result.output
    assert list(apply_dir.glob("*_bookmarked.pdf"))
    assert list(apply_dir.glob("*_markdown"))


def test_apply_does_not_reextract_typography(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_typography_book(pdf)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps([{"title": "Chapter 1", "level": 1, "pdf_page": 1}]),
        encoding="utf-8",
    )

    with patch("pdfbooktree.pipeline.extract_typography_lines") as extract:
        result = RUNNER.invoke(
            app,
            [
                "apply",
                str(pdf),
                "--plan",
                str(plan_path),
                "--output-dir",
                str(output_dir),
                "--flat-output",
            ],
        )

    assert result.exit_code == 0, result.output
    extract.assert_not_called()


def test_apply_rejects_invalid_plan_json(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_typography_book(pdf)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps([{"title": "Chapter 1"}]), encoding="utf-8")

    result = RUNNER.invoke(
        app,
        [
            "apply",
            str(pdf),
            "--plan",
            str(plan_path),
            "--output-dir",
            str(output_dir),
            "--flat-output",
        ],
    )

    assert result.exit_code != 0
    assert "level" in result.output


def test_apply_dry_run_validates_without_writing(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_root = tmp_path / "runs"
    _make_typography_book(pdf)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps([{"title": "Chapter 1", "level": 1, "pdf_page": 1}]),
        encoding="utf-8",
    )

    result = RUNNER.invoke(
        app,
        [
            "apply",
            str(pdf),
            "--plan",
            str(plan_path),
            "--output-dir",
            str(output_root),
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["result"]["dry_run"] is True
    assert payload["result"]["validation"]["valid"] is True
    assert payload["result"]["bookmark_count"] == 1
    assert payload["result"]["input_sha256"] == file_sha256(pdf)
    assert not output_root.exists()


def test_apply_dry_run_semantic_failure_uses_exit_three_without_writing(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    output_root = tmp_path / "runs"
    _make_typography_book(pdf)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps([{"title": "Outside", "level": 1, "pdf_page": 999}]),
        encoding="utf-8",
    )

    result = RUNNER.invoke(
        app,
        [
            "apply",
            str(pdf),
            "--plan",
            str(plan_path),
            "--output-dir",
            str(output_root),
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 3
    payload = json.loads(result.stderr)
    assert payload["error"]["code"] == "processing_failed"
    assert payload["error"]["details"]["validation"]["valid"] is False
    assert not output_root.exists()


def test_apply_records_plan_source_sha256_in_run_manifest(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_root = tmp_path / "runs"
    _make_typography_book(pdf)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps([{"title": "Chapter 1", "level": 1, "pdf_page": 1}]),
        encoding="utf-8",
    )

    result = RUNNER.invoke(
        app,
        [
            "apply",
            str(pdf),
            "--plan",
            str(plan_path),
            "--output-dir",
            str(output_root),
        ],
    )

    assert result.exit_code == 0, result.output
    manifests = list(output_root.rglob("run_manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text("utf-8"))
    assert manifest["plan_source"]["path"] == str(plan_path)
    assert manifest["plan_source"]["sha256"] == file_sha256(plan_path)
    assert Path(manifest["artifact_paths"]["markdown_manifest"]).is_file()


def test_apply_cli_length_limit은_split_graph_manifest를_연결한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    output_root = tmp_path / "runs"
    _make_typography_book(pdf)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps([{"title": "Chapter 1", "level": 1, "pdf_page": 1}]),
        encoding="utf-8",
    )

    result = RUNNER.invoke(
        app,
        [
            "apply",
            str(pdf),
            "--plan",
            str(plan_path),
            "--output-dir",
            str(output_root),
            "--set",
            "markdown.max_words=1000",
            "--set",
            "markdown.max_words_coverage=1.0",
        ],
    )

    assert result.exit_code == 0, result.output
    run_manifest_path = next(output_root.rglob("run_manifest.json"))
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    markdown_manifest_path = Path(run_manifest["artifact_paths"]["markdown_manifest"])
    markdown_manifest = json.loads(markdown_manifest_path.read_text(encoding="utf-8"))
    assert markdown_manifest_path.name == "markdown_manifest.json"
    assert markdown_manifest["export_mode"] == "split"
    assert markdown_manifest["content_mode"] == "bounded"
    assert markdown_manifest["validation"]["valid"] is True
    assert (markdown_manifest_path.parent / "toc.md").is_file()
    assert (markdown_manifest_path.parent / "nodes").is_dir()
