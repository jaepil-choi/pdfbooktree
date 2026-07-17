"""``process`` Python/CLI 결과와 주요 artifact의 golden 계약을 고정한다.

알고리즘의 plan 값은 ``test_pipeline_parity.py``가 별도로 고정한다. 이 파일은
agent-friendly interface 리팩터링 전에 결과 필드, artifact 이름과 JSON shape,
immutable run manifest가 실제 파일과 연결되는 방식을 characterization한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz
from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.config import ProcessingConfig, TypographyConfig
from pdfbooktree.processor import Processor
from pdfbooktree.utils.jsonio import to_jsonable

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0

PROCESSING_RESULT_FIELDS = {
    "status",
    "input_pdf",
    "output_pdf",
    "output_markdown_dir",
    "markdown_export",
    "ocr_pdf",
    "bookmark_count",
    "confidence_summary",
    "warnings",
    "artifact_paths",
    "report_path",
    "existing_outline_quality",
}

INFERENCE_ARTIFACT_FILES = {
    "whole_book_lines": "whole_book_lines.jsonl",
    "font_size_tiers": "font_size_tiers.json",
    "height_tiers": "height_tiers.json",
    "heading_candidates": "heading_candidates.json",
    "position_fallback_candidates": "position_fallback_candidates.json",
    "bookmark_plan": "bookmark_plan.json",
    "bookmark_plan_validation": "bookmark_plan_validation.json",
    "bookmark_review_summary": "bookmark_review_summary.json",
    "bookmark_review_items": "bookmark_review_items.jsonl",
    "markdown_manifest": "book_markdown/markdown_manifest.json",
}

EXISTING_OUTLINE_ARTIFACT_FILES = {
    "existing_outline_plan": "existing_outline_plan.json",
    "bookmark_plan_validation": "bookmark_plan_validation.json",
    "existing_outline_quality": "existing_outline_quality.json",
    "markdown_manifest": "bookmarked_markdown/markdown_manifest.json",
}


def _make_inference_book(path: Path) -> None:
    """font heading과 body-tier position fallback을 함께 노출하는 PDF를 만든다."""

    document = fitz.open()
    try:
        for page_no in range(1, 10):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            if page_no in (1, 4, 7):
                chapter = {1: 1, 4: 2, 7: 3}[page_no]
                page.insert_text((72, 90), f"Chapter {chapter} Title", fontsize=28)
                page.insert_text((72, 155), f"{chapter}.1 Section", fontsize=16)
            page.insert_text((72, 200), f"Note {page_no}", fontsize=10)
            for row in range(15):
                page.insert_text(
                    (72, 260 + row * 15),
                    "This is ordinary body text for the chapter.",
                    fontsize=10,
                )
        document.save(path)
    finally:
        document.close()


def _make_existing_outline_book(path: Path) -> None:
    """low-quality 판정도 결과 계약에 남도록 2-item outline PDF를 만든다."""

    document = fitz.open()
    try:
        for page_no in range(1, 4):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            page.insert_text((72, 72), f"Page {page_no}", fontsize=12)
        document.set_toc([[1, "Chapter 1", 1], [2, "1.1 Topic", 2]])
        document.save(path)
    finally:
        document.close()


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_processor_inference_result와_artifact_shape_golden(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_inference_book(pdf)

    result = Processor(
        pdf,
        output_dir,
        ProcessingConfig(
            typography=TypographyConfig(
                min_tier_count=1,
                max_heading_tier=2,
                position_min_repeated_pages=5,
            )
        ),
    ).run()
    payload = to_jsonable(result)

    assert set(payload) == PROCESSING_RESULT_FIELDS
    assert payload["status"] == "processed"
    assert payload["input_pdf"] == str(pdf)
    assert payload["output_pdf"] == str(output_dir / "book_bookmarked.pdf")
    assert payload["output_markdown_dir"] == str(output_dir / "book_markdown")
    assert payload["markdown_export"]["export_mode"] == "tree_graph"
    assert payload["markdown_export"]["file_count"] == payload["bookmark_count"]
    assert payload["markdown_export"]["manifest_path"] == str(
        output_dir / "book_markdown" / "markdown_manifest.json"
    )
    assert payload["ocr_pdf"] is None
    assert payload["bookmark_count"] == 15
    assert payload["existing_outline_quality"] is None
    assert payload["report_path"] == str(output_dir / "book_report.json")
    assert payload["artifact_paths"] == {
        name: str(output_dir / filename)
        for name, filename in INFERENCE_ARTIFACT_FILES.items()
    }

    line_rows = [
        json.loads(line)
        for line in (output_dir / "whole_book_lines.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert line_rows
    assert set(line_rows[0]) == {
        "pdf_page",
        "text",
        "x0",
        "y0",
        "x1",
        "y1",
        "page_width",
        "page_height",
        "font_size",
        "height",
        "is_bold",
        "font_names",
    }

    tier_fields = {
        "signal",
        "cut_points",
        "tiers",
        "raw_tier_count",
        "gap_merged_tier_count",
        "final_tier_count",
    }
    tier_item_fields = {"tier", "lower_bound", "upper_bound", "peak", "count"}
    for filename in ("font_size_tiers.json", "height_tiers.json"):
        tier_payload = _read_json(output_dir / filename)
        assert isinstance(tier_payload, dict)
        assert set(tier_payload) == tier_fields
        assert tier_payload["tiers"]
        assert set(tier_payload["tiers"][0]) == tier_item_fields

    heading_payload = _read_json(output_dir / "heading_candidates.json")
    assert isinstance(heading_payload, list) and heading_payload
    assert set(heading_payload[0]) == {
        "title",
        "pdf_page",
        "tier",
        "y0",
        "y1",
        "merged_line_count",
        "is_pollution",
        "confidence",
        "source",
        "evidence",
    }

    fallback_payload = _read_json(output_dir / "position_fallback_candidates.json")
    assert isinstance(fallback_payload, list) and fallback_payload
    assert set(fallback_payload[0]) == {
        "title",
        "pdf_page",
        "y0",
        "y1",
        "support_pages",
        "isolation_ratio",
        "font_ratio",
        "confidence",
        "evidence",
    }

    plan_payload = _read_json(output_dir / "bookmark_plan.json")
    assert isinstance(plan_payload, list) and len(plan_payload) == 15
    assert set(plan_payload[0]) == {
        "title",
        "level",
        "pdf_page",
        "source",
        "confidence",
        "evidence",
    }
    assert _read_json(output_dir / "bookmark_plan_validation.json") == {
        "valid": True,
        "item_count": 15,
        "warnings": [],
    }

    report = _read_json(output_dir / "book_report.json")
    assert isinstance(report, dict)
    assert set(report) == PROCESSING_RESULT_FIELDS
    assert report["status"] == payload["status"]
    assert report["bookmark_count"] == payload["bookmark_count"]
    assert report["artifact_paths"] == payload["artifact_paths"]
    assert report["report_path"] is None


def test_processor_existing_outline_fast_path_contract_golden(tmp_path: Path) -> None:
    pdf = tmp_path / "bookmarked.pdf"
    output_dir = tmp_path / "out"
    _make_existing_outline_book(pdf)

    result = Processor(pdf, output_dir).run()
    payload = to_jsonable(result)

    assert set(payload) == PROCESSING_RESULT_FIELDS
    assert payload["status"] == "processed"
    assert payload["output_pdf"] is None
    assert payload["output_markdown_dir"] == str(output_dir / "bookmarked_markdown")
    assert payload["bookmark_count"] == 2
    assert payload["confidence_summary"] == {
        "line_extraction": None,
        "tiering": None,
        "heading_candidates": None,
        "outline": 1.0,
    }
    assert payload["artifact_paths"] == {
        name: str(output_dir / filename)
        for name, filename in EXISTING_OUTLINE_ARTIFACT_FILES.items()
    }
    assert payload["existing_outline_quality"] == {
        "is_low_quality": True,
        "item_count": 2,
        "reasons": ["too_few_items"],
        "evidence": ["item_count=2 < min_item_count=4"],
    }
    assert any("low quality" in warning for warning in payload["warnings"])

    assert _read_json(output_dir / "existing_outline_plan.json") == [
        {
            "title": "Chapter 1",
            "level": 1,
            "pdf_page": 1,
            "source": "existing_outline",
            "confidence": 1.0,
            "evidence": [],
        },
        {
            "title": "1.1 Topic",
            "level": 2,
            "pdf_page": 2,
            "source": "existing_outline",
            "confidence": 1.0,
            "evidence": [],
        },
    ]
    assert _read_json(output_dir / "bookmark_plan_validation.json") == {
        "valid": True,
        "item_count": 2,
        "warnings": [],
    }
    assert not (output_dir / "whole_book_lines.jsonl").exists()
    assert (output_dir / "bookmarked_markdown" / "toc.md").exists()
    assert payload["report_path"] == str(output_dir / "bookmarked_report.json")


def test_process_cli_real_run_manifest_contract_golden(tmp_path: Path) -> None:
    pdf = tmp_path / "bookmarked.pdf"
    output_root = tmp_path / "runs"
    _make_existing_outline_book(pdf)

    result = CliRunner().invoke(
        app,
        ["process", str(pdf), "--output-dir", str(output_root)],
    )

    assert result.exit_code == 0
    for key in ("run_id", "run_dir", "manifest_path", "config_hash", "result"):
        assert key in result.stdout

    manifests = list(output_root.rglob("run_manifest.json"))
    assert len(manifests) == 1
    manifest_path = manifests[0]
    manifest = _read_json(manifest_path)
    assert isinstance(manifest, dict)
    assert set(manifest) == {
        "schema_version",
        "run_id",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "run_dir",
        "input",
        "tool",
        "config_hash",
        "resolved_config_path",
        "config_sources",
        "processing_status",
        "artifact_paths",
        "output_paths",
        "report_path",
        "warnings",
        "error",
        "plan_source",
    }
    assert manifest["schema_version"] == 1
    assert manifest["status"] == "succeeded"
    assert manifest["processing_status"] == "processed"
    assert manifest["error"] is None
    assert manifest["plan_source"] is None
    assert manifest["started_at"] is not None
    assert manifest["finished_at"] is not None

    run_dir = Path(manifest["run_dir"])
    assert manifest_path.parent == run_dir
    assert Path(manifest["resolved_config_path"]).is_file()
    assert manifest["artifact_paths"] == {
        name: str(run_dir / filename)
        for name, filename in EXISTING_OUTLINE_ARTIFACT_FILES.items()
    }
    assert manifest["output_paths"] == {
        "output_markdown_dir": str(run_dir / "bookmarked_markdown")
    }
    assert manifest["report_path"] == str(run_dir / "bookmarked_report.json")
    for path in manifest["artifact_paths"].values():
        assert Path(path).is_file()
    for path in manifest["output_paths"].values():
        assert Path(path).is_dir()
    assert Path(manifest["report_path"]).is_file()
