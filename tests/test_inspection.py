from __future__ import annotations

import json
from pathlib import Path

import fitz
from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.inspection import (
    inspect_bookmarks,
    inspect_compare_plans,
    inspect_ocr_artifact,
    inspect_page_count,
    inspect_plan_artifact,
    inspect_text,
)


def json_result(result, command: str) -> dict[str, object]:
    """schema v1 success envelope에서 inspection result를 꺼낸다."""

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    envelope = json.loads(result.stdout)
    assert set(envelope) == {"schema_version", "command", "ok", "result"}
    assert envelope["schema_version"] == 1
    assert envelope["command"] == command
    assert envelope["ok"] is True
    return envelope["result"]


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


def write_review_artifacts(path: Path) -> None:
    """inspection filter 검사용 review summary와 JSONL을 쓴다."""

    write_json(
        path / "bookmark_review_summary.json",
        {
            "schema_version": 1,
            "plan_item_count": 3,
            "attention": {"item_count": 2},
        },
    )
    rows = [
        {
            "schema_version": 1,
            "node_id": "n0001",
            "title": "Chapter 1",
            "level": 1,
            "pdf_page": 1,
            "source": "geometry_typography",
            "attention_signals": [],
        },
        {
            "schema_version": 1,
            "node_id": "n0002",
            "title": "Fallback",
            "level": 2,
            "pdf_page": 2,
            "source": "geometry_position_fallback",
            "attention_signals": ["position_fallback_source"],
        },
        {
            "schema_version": 1,
            "node_id": "n0003",
            "title": "Repeated – title",
            "level": 2,
            "pdf_page": 3,
            "source": "geometry_typography",
            "attention_signals": ["repeated_title"],
        },
    ]
    (path / "bookmark_review_items.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


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
        {
            "markdown_export": {
                "file_count": 2,
                "constraint_satisfied": True,
                "manifest_path": "book_markdown/markdown_manifest.json",
            }
        },
    )
    write_json(
        tmp_path / "book_markdown" / "markdown_manifest.json",
        {
            "schema_version": 1,
            "export_mode": "tree_graph",
            "content_mode": "direct",
            "node_count": 2,
            "root_count": 1,
            "constraint_satisfied": True,
            "validation": {"valid": True, "dangling_link_count": 0},
            "coverage": {
                "assigned_page_count": 2,
                "unassigned_page_count": 0,
            },
            "warnings": {"same_page_boundary_count": 0},
        },
    )

    result = inspect_plan_artifact(tmp_path)

    assert result["status"] == "available"
    assert result["bookmark_plan_item_count"] == 2
    assert result["bookmark_levels"] == [1, 2]
    assert result["validation"]["valid"] is True
    assert result["markdown_export"]["file_count"] == 2
    assert result["markdown_manifest_path"].endswith("markdown_manifest.json")
    assert result["markdown_manifest"] == {
        "schema_version": 1,
        "export_mode": "tree_graph",
        "content_mode": "direct",
        "node_count": 2,
        "root_count": 1,
        "chosen_level": None,
        "constraint_satisfied": True,
        "fallback_used": None,
        "validation": {"valid": True, "dangling_link_count": 0},
        "coverage": {"assigned_page_count": 2, "unassigned_page_count": 0},
        "manifest_warnings": {"same_page_boundary_count": 0},
    }


def test_inspect_plan_artifact는_run_manifest의_markdown_manifest를_따른다(
    tmp_path: Path,
) -> None:
    write_json(
        tmp_path / "bookmark_plan.json",
        [{"title": "Chapter", "level": 1, "pdf_page": 1}],
    )
    manifest_path = tmp_path / "artifacts" / "markdown_manifest.json"
    write_json(
        manifest_path,
        {
            "schema_version": 1,
            "export_mode": "split",
            "content_mode": "bounded",
            "node_count": 1,
            "root_count": 1,
            "chosen_level": 1,
            "constraint_satisfied": False,
            "fallback_used": True,
            "validation": {"valid": True},
            "coverage": {"duplicated_page_count": 0},
            "warnings": {},
        },
    )
    write_json(
        tmp_path / "run_manifest.json",
        {"artifact_paths": {"markdown_manifest": str(manifest_path)}},
    )

    result = inspect_plan_artifact(tmp_path)

    assert result["markdown_manifest_path"] == str(manifest_path)
    assert result["markdown_manifest"]["export_mode"] == "split"
    assert result["markdown_manifest"]["chosen_level"] == 1
    assert result["markdown_manifest"]["fallback_used"] is True


def test_inspect_plan_artifact_filters_review_items(tmp_path: Path) -> None:
    write_json(
        tmp_path / "bookmark_plan.json",
        [{"title": "Chapter", "level": 1, "pdf_page": 1}],
    )
    write_review_artifacts(tmp_path)

    result = inspect_plan_artifact(
        tmp_path,
        include_items=True,
        page_range=(2, 3),
        level=2,
        attention_only=True,
        limit=1,
    )

    assert result["bookmark_review_summary"]["plan_item_count"] == 3
    assert result["review_query"] == {
        "item_id": None,
        "page_range": [2, 3],
        "level": 2,
        "source": None,
        "attention_only": True,
        "limit": 1,
        "matched_item_count": 2,
        "returned_item_count": 1,
        "truncated": True,
    }
    assert result["bookmark_review_items"][0]["node_id"] == "n0002"


def test_inspect_plan_artifact_selects_single_review_item(tmp_path: Path) -> None:
    write_json(
        tmp_path / "bookmark_plan.json",
        [{"title": "Chapter", "level": 1, "pdf_page": 1}],
    )
    write_review_artifacts(tmp_path)

    result = inspect_plan_artifact(tmp_path, item_id="n0003")

    assert result["review_query"]["matched_item_count"] == 1
    assert result["bookmark_review_items"][0]["title"] == "Repeated – title"


def test_inspect_compare_plans_reports_added_removed_and_moved(
    tmp_path: Path,
) -> None:
    plan_a = tmp_path / "before.json"
    plan_b = tmp_path / "after.json"
    write_json(
        plan_a,
        [
            {"title": "Chapter 1", "level": 1, "pdf_page": 10},
            {"title": "Chapter 2", "level": 1, "pdf_page": 40},
        ],
    )
    write_json(
        plan_b,
        [
            {"title": "Chapter 1", "level": 1, "pdf_page": 12},
            {"title": "Chapter 3", "level": 1, "pdf_page": 70},
        ],
    )

    result = inspect_compare_plans(plan_a, plan_b, page_tolerance=2)

    assert result["plan_a_item_count"] == 2
    assert result["plan_b_item_count"] == 2
    assert result["moved_count"] == 1
    assert result["added_count"] == 1
    assert result["removed_count"] == 1
    statuses = {entry["status"] for entry in result["entries"]}
    assert statuses == {"matched", "added", "removed"}


def test_inspect_cli_emits_json_for_page_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "book.pdf"
    make_pdf(pdf_path)

    result = CliRunner().invoke(
        app,
        ["inspect", "text", str(pdf_path), "--pages", "1-2", "--json"],
    )

    payload = json_result(result, "inspect.text")
    assert [page["pdf_page"] for page in payload["pages"]] == [1, 2]


def test_inspect_cli_format_json은_모든_command를_envelope로_출력한다(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "book.pdf"
    artifact_dir = tmp_path / "ocr_artifacts"
    plan_dir = tmp_path / "plan_artifacts"
    make_pdf(pdf_path)
    artifact_dir.mkdir()
    write_json(
        plan_dir / "bookmark_plan.json",
        [{"title": "Chapter 1", "level": 1, "pdf_page": 1}],
    )

    runner = CliRunner()
    page_count = runner.invoke(
        app,
        ["inspect", "page-count", str(pdf_path), "--format", "json"],
    )
    text = runner.invoke(
        app,
        [
            "inspect",
            "text",
            str(pdf_path),
            "--pages",
            "1",
            "--format",
            "json",
        ],
    )
    bookmarks = runner.invoke(
        app,
        ["inspect", "bookmarks", str(pdf_path), "--format", "json"],
    )
    ocr = runner.invoke(
        app,
        ["inspect", "ocr", str(artifact_dir), "--format", "json"],
    )
    plan = runner.invoke(
        app,
        ["inspect", "plan", str(plan_dir), "--format", "json"],
    )

    assert json_result(page_count, "inspect.page-count")["page_count"] == 2
    assert json_result(text, "inspect.text")["pages"][0]["pdf_page"] == 1
    assert json_result(bookmarks, "inspect.bookmarks")["bookmark_count"] == 2
    assert json_result(ocr, "inspect.ocr")["artifact_dir"] == str(artifact_dir)
    assert json_result(plan, "inspect.plan")["bookmark_plan_item_count"] == 1


def test_inspect_cli_plan_item_and_filters_use_json_contract(tmp_path: Path) -> None:
    plan_dir = tmp_path / "plan_artifacts"
    write_json(
        plan_dir / "bookmark_plan.json",
        [{"title": "Chapter 1", "level": 1, "pdf_page": 1}],
    )
    write_review_artifacts(plan_dir)

    item_result = CliRunner().invoke(
        app,
        [
            "inspect",
            "plan",
            str(plan_dir),
            "--item-id",
            "n0002",
            "--format",
            "json",
        ],
    )
    filtered_result = CliRunner().invoke(
        app,
        [
            "inspect",
            "plan",
            str(plan_dir),
            "--items",
            "--page-range",
            "2-3",
            "--level",
            "2",
            "--source",
            "geometry_position_fallback",
            "--attention-only",
            "--limit",
            "10",
            "--format",
            "json",
        ],
    )

    item_payload = json_result(item_result, "inspect.plan")
    filtered_payload = json_result(filtered_result, "inspect.plan")
    assert item_payload["bookmark_review_items"][0]["node_id"] == "n0002"
    assert filtered_payload["review_query"]["matched_item_count"] == 1
    assert filtered_payload["bookmark_review_items"][0]["source"] == (
        "geometry_position_fallback"
    )

    unicode_result = CliRunner().invoke(
        app,
        [
            "inspect",
            "plan",
            str(plan_dir),
            "--item-id",
            "n0003",
            "--format",
            "json",
        ],
    )
    assert (
        json_result(unicode_result, "inspect.plan")["bookmark_review_items"][0]["title"]
        == "Repeated – title"
    )
    assert "\\u2013" in unicode_result.stdout


def test_inspect_cli_plan_item_without_review_artifact_is_input_error(
    tmp_path: Path,
) -> None:
    write_json(
        tmp_path / "bookmark_plan.json",
        [{"title": "Chapter 1", "level": 1, "pdf_page": 1}],
    )

    result = CliRunner().invoke(
        app,
        [
            "inspect",
            "plan",
            str(tmp_path),
            "--item-id",
            "n0001",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    envelope = json.loads(result.stderr)
    assert envelope["command"] == "inspect.plan"
    assert envelope["error"]["code"] == "invalid_input"
    assert "bookmark_review_items.jsonl" in envelope["error"]["message"]


def test_inspect_cli_compare_reports_diff_counts_as_json(tmp_path: Path) -> None:
    plan_a = tmp_path / "before.json"
    plan_b = tmp_path / "after.json"
    write_json(plan_a, [{"title": "Chapter 1", "level": 1, "pdf_page": 10}])
    write_json(plan_b, [{"title": "Chapter 1", "level": 2, "pdf_page": 10}])

    result = CliRunner().invoke(
        app,
        [
            "inspect",
            "compare",
            str(plan_a),
            str(plan_b),
            "--format",
            "json",
        ],
    )

    payload = json_result(result, "inspect.compare")
    assert payload["matched_count"] == 1
    assert payload["level_changed_count"] == 1
    assert payload["entries"][0]["level_changed"] is True


def test_inspect_cli_compare_missing_plan_uses_json_input_error(
    tmp_path: Path,
) -> None:
    plan_a = tmp_path / "before.json"
    write_json(plan_a, [{"title": "Chapter 1", "level": 1, "pdf_page": 10}])

    result = CliRunner().invoke(
        app,
        [
            "inspect",
            "compare",
            str(plan_a),
            str(tmp_path / "missing.json"),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    envelope = json.loads(result.stderr)
    assert envelope["command"] == "inspect.compare"
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_input"


def test_inspect_cli_missing_input은_json_stderr와_exit_2를_사용한다(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.pdf"

    result = CliRunner().invoke(
        app,
        ["inspect", "page-count", str(missing), "--format", "json"],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    envelope = json.loads(result.stderr)
    assert envelope["schema_version"] == 1
    assert envelope["command"] == "inspect.page-count"
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_input"
    assert envelope["error"]["type"] == "FileNotFoundError"


def test_inspect_cli_human_output은_기존_표현을_유지한다(tmp_path: Path) -> None:
    pdf_path = tmp_path / "book.pdf"
    make_pdf(pdf_path)

    result = CliRunner().invoke(app, ["inspect", "page-count", str(pdf_path)])

    assert result.exit_code == 0
    assert "page_count" in result.stdout
    assert "schema_version" not in result.stdout
