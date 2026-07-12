from __future__ import annotations

import json
from pathlib import Path

import fitz
from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.inspection import (
    inspect_bookmarks,
    inspect_ocr_artifact,
    inspect_page_count,
    inspect_plan_artifact,
    inspect_text,
)


def make_pdf(path: Path) -> None:
    """검사용 2-page PDF와 기존 bookmark를 만든다."""

    document = fitz.open()
    first = document.new_page()
    first.insert_text((72, 72), "First page text")
    second = document.new_page()
    second.insert_text((72, 72), "Second page text")
    document.set_toc([[1, "Chapter 1", 1], [2, "Section 1.1", 2]])
    document.save(path)
    document.close()


def write_json(path: Path, value: object) -> None:
    """검사용 JSON artifact를 쓴다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_inspect_pdf_page_count_text_and_bookmarks(tmp_path: Path) -> None:
    pdf_path = tmp_path / "book.pdf"
    make_pdf(pdf_path)

    assert inspect_page_count(pdf_path)["page_count"] == 2
    text_result = inspect_text(pdf_path, [1, 2])
    assert [page["pdf_page"] for page in text_result["pages"]] == [1, 2]
    assert text_result["pages"][1]["text"] == "Second page text\n"
    bookmarks_result = inspect_bookmarks(pdf_path)
    assert bookmarks_result["bookmark_count"] == 2
    assert bookmarks_result["bookmarks"][1]["pdf_page"] == 2


def test_inspect_text_rejects_out_of_range_page(tmp_path: Path) -> None:
    pdf_path = tmp_path / "book.pdf"
    make_pdf(pdf_path)

    try:
        inspect_text(pdf_path, [3])
    except ValueError as error:
        assert "page_count=2" in str(error)
    else:
        raise AssertionError("범위를 벗어난 page를 거절해야 한다.")


def test_inspect_ocr_artifact_reports_partial_progress_and_duplicates(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "book.pdf"
    artifact_dir = tmp_path / "artifacts"
    make_pdf(pdf_path)
    write_json(
        artifact_dir / "ocr_overlay_config.json",
        {"input_pdf": str(pdf_path), "output_pdf": str(tmp_path / "book_ocr.pdf")},
    )
    write_json(
        artifact_dir / "ocr_progress.json",
        {"total_pages": 2, "completed_pages": 1, "current_page": 2},
    )
    write_json(artifact_dir / "document_parse_cache" / "raw" / "first.json", {})
    write_json(
        artifact_dir / "document_parse_cache" / "insertable" / "first.json",
        {"pdf_page": 1},
    )
    write_json(
        artifact_dir / "document_parse_cache" / "insertable" / "stale.json",
        {"pdf_page": 1},
    )
    (artifact_dir / "ocr_log.jsonl").write_text(
        json.dumps({"event": "page_done", "pdf_page": 1, "message": "완료"}) + "\n",
        encoding="utf-8",
    )

    result = inspect_ocr_artifact(artifact_dir)

    assert result["status"] == "partial"
    assert result["raw_cache_count"] == 1
    assert result["duplicate_insertable_pages"] == [1]
    assert result["missing_completed_pages"] == []
    assert result["first_unprocessed_page"] == 2
    assert result["last_log_event"]["event"] == "page_done"
    assert result["warnings"]


def test_inspect_plan_artifact_summarizes_validation_and_markdown(
    tmp_path: Path,
) -> None:
    write_json(
        tmp_path / "bookmark_plan.json",
        [
            {"title": "Chapter 1", "level": 1, "pdf_page": 1},
            {"title": "Section 1.1", "level": 2, "pdf_page": 2},
        ],
    )
    write_json(
        tmp_path / "bookmark_plan_validation.json",
        {"valid": True, "item_count": 2, "warnings": []},
    )
    write_json(
        tmp_path / "book_report.json",
        {"markdown_export": {"file_count": 2, "constraint_satisfied": True}},
    )

    result = inspect_plan_artifact(tmp_path)

    assert result["status"] == "available"
    assert result["bookmark_plan_item_count"] == 2
    assert result["bookmark_levels"] == [1, 2]
    assert result["validation"]["valid"] is True
    assert result["markdown_export"]["file_count"] == 2


def test_inspect_cli_emits_json_for_page_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "book.pdf"
    make_pdf(pdf_path)

    result = CliRunner().invoke(
        app,
        ["inspect", "text", str(pdf_path), "--pages", "1-2", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [page["pdf_page"] for page in payload["pages"]] == [1, 2]
