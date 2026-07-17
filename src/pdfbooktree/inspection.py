"""AI agent가 PDF와 처리 artifact를 작은 단위로 조사하는 읽기 전용 API다."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import fitz

from pdfbooktree.evaluation import PlanDiffEntry, compare_bookmark_plans
from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.outline.plan_io import load_bookmark_plan_json
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks


def inspect_page_count(pdf_path: Path | str) -> dict[str, Any]:
    """PDF 총 page 수를 1-based convention과 함께 반환한다."""

    path = _require_file(pdf_path, "PDF")
    with fitz.open(path) as document:
        return {"pdf_path": str(path), "page_count": document.page_count}


def inspect_text(
    pdf_path: Path | str,
    pages: list[int],
) -> dict[str, Any]:
    """지정한 1-based page들의 text를 page별로 반환한다."""

    path = _require_file(pdf_path, "PDF")
    if not pages:
        raise ValueError("확인할 PDF page를 하나 이상 지정해야 한다.")
    if any(page < 1 for page in pages):
        raise ValueError("PDF page는 1 이상이어야 한다.")

    with fitz.open(path) as document:
        page_count = document.page_count
        invalid_pages = [page for page in pages if page > page_count]
        if invalid_pages:
            raise ValueError(
                f"PDF page 범위를 벗어났다: pages={invalid_pages}, page_count={page_count}"
            )
        page_rows = []
        for page in pages:
            text = document[page - 1].get_text()
            page_rows.append({"pdf_page": page, "text": text, "char_count": len(text)})
    return {"pdf_path": str(path), "page_count": page_count, "pages": page_rows}


def inspect_bookmarks(pdf_path: Path | str) -> dict[str, Any]:
    """PDF 기존 bookmark와 target page를 반환한다."""

    path = _require_file(pdf_path, "PDF")
    with fitz.open(path) as document:
        page_count = document.page_count
    bookmarks = extract_existing_bookmarks(path)
    return {
        "pdf_path": str(path),
        "page_count": page_count,
        "bookmark_count": len(bookmarks),
        "bookmarks": bookmarks,
    }


def inspect_ocr_artifact(artifact_dir: Path | str) -> dict[str, Any]:
    """OCR artifact의 진행 상태, cache page, stats와 마지막 로그를 요약한다."""

    root = _require_directory(artifact_dir, "OCR artifact directory")
    warnings: list[str] = []
    config_value = _read_optional_json(root / "ocr_overlay_config.json", warnings)
    progress_value = _read_optional_json(root / "ocr_progress.json", warnings)
    if not isinstance(config_value, dict):
        if config_value is not None:
            warnings.append("OCR config artifact 형식이 JSON object가 아니다.")
        config = {}
    else:
        config = config_value
    if not isinstance(progress_value, dict):
        if progress_value is not None:
            warnings.append("OCR progress artifact 형식이 JSON object가 아니다.")
        progress = {}
    else:
        progress = progress_value

    input_pdf = _path_from_config(config.get("input_pdf"))
    output_pdf = _path_from_config(config.get("output_pdf"))
    total_pages = _pdf_page_count(input_pdf, warnings)
    progress_total_pages = _as_int(progress.get("total_pages"))
    if total_pages is None:
        total_pages = progress_total_pages
    target_pages = _target_pages(config, total_pages, warnings)
    completed_pages = _as_int(progress.get("completed_pages")) or 0

    cache_root = root / "document_parse_cache"
    raw_count = _json_file_count(cache_root / "raw")
    insertable_pages, invalid_insertable_count = _read_insertable_pages(
        cache_root / "insertable"
    )
    if invalid_insertable_count:
        warnings.append(
            f"읽을 수 없는 insertable cache 파일이 {invalid_insertable_count}개 있다."
        )
    page_counts = Counter(insertable_pages)
    unique_pages = set(insertable_pages)
    duplicate_pages = sorted(page for page, count in page_counts.items() if count > 1)
    if duplicate_pages:
        warnings.append(
            "중복 pdf_page를 가진 insertable cache가 있다. 이전 cache key 형식의 "
            f"잔재일 수 있다: pages={duplicate_pages}"
        )

    expected_completed = set(target_pages[:completed_pages])
    missing_completed_pages = sorted(expected_completed - unique_pages)
    if missing_completed_pages:
        warnings.append(
            f"progress에서 완료로 기록한 page의 insertable cache가 없다: {missing_completed_pages}"
        )
    unprocessed_pages = [page for page in target_pages if page not in unique_pages]

    stats = _inspect_ocr_stats(root)
    last_log_event = _read_last_log_event(root / "ocr_log.jsonl", warnings)
    output_exists = output_pdf is not None and output_pdf.is_file()
    status = _ocr_status(
        root,
        total_pages,
        target_pages,
        unique_pages,
        output_exists,
    )
    if raw_count != len(unique_pages):
        warnings.append(
            "raw cache 수와 고유 insertable page 수가 다르다: "
            f"raw={raw_count}, unique_insertable={len(unique_pages)}"
        )

    return {
        "status": status,
        "artifact_dir": str(root),
        "input_pdf": str(input_pdf) if input_pdf is not None else None,
        "output_pdf": str(output_pdf) if output_pdf is not None else None,
        "output_pdf_exists": output_exists,
        "total_pages": total_pages,
        "target_page_count": len(target_pages),
        "progress_completed_pages": completed_pages,
        "progress_current_page": _as_int(progress.get("current_page")),
        "raw_cache_count": raw_count,
        "insertable_cache_count": len(insertable_pages),
        "unique_insertable_page_count": len(unique_pages),
        "duplicate_insertable_pages": duplicate_pages,
        "missing_completed_pages": missing_completed_pages,
        "unprocessed_page_count": len(unprocessed_pages),
        "first_unprocessed_page": unprocessed_pages[0] if unprocessed_pages else None,
        "stats": stats,
        "last_log_event": last_log_event,
        "warnings": warnings,
    }


def inspect_plan_artifact(
    output_dir: Path | str,
    *,
    include_items: bool = False,
    limit: int = 20,
    item_id: str | None = None,
    page_range: tuple[int, int] | None = None,
    level: int | None = None,
    source: str | None = None,
    attention_only: bool = False,
) -> dict[str, Any]:
    """bookmark plan과 review/Markdown artifact를 점진적으로 조사한다."""

    root = _require_directory(output_dir, "처리 output directory")
    if limit < 1:
        raise ValueError("limit은 1 이상이어야 한다.")
    if level is not None and level < 1:
        raise ValueError("level은 1 이상이어야 한다.")
    if page_range is not None:
        start_page, end_page = page_range
        if start_page < 1 or end_page < start_page:
            raise ValueError(
                "page range는 1 이상의 오름차순 범위여야 한다: "
                f"start={start_page}, end={end_page}"
            )
    warnings: list[str] = []
    plan_path = _first_existing_path(
        root / "bookmark_plan.json", root / "existing_outline_plan.json"
    )
    validation_path = root / "bookmark_plan_validation.json"
    plan = _read_optional_json(plan_path, warnings) if plan_path else None
    validation = _read_optional_json(validation_path, warnings)
    report_path = _find_processing_report(root)
    report = _read_optional_json(report_path, warnings) if report_path else None
    run_manifest_path = root / "run_manifest.json"
    run_manifest = _read_optional_json(run_manifest_path, warnings)

    if plan is None:
        warnings.append("bookmark plan artifact가 없다.")
        plan_items: list[Any] = []
    elif not isinstance(plan, list):
        warnings.append("bookmark plan artifact 형식이 list가 아니다.")
        plan_items = []
    else:
        plan_items = plan

    levels = sorted(
        {
            int(item["level"])
            for item in plan_items
            if isinstance(item, dict) and isinstance(item.get("level"), int)
        }
    )
    markdown_export = (
        report.get("markdown_export") if isinstance(report, dict) else None
    )
    markdown_manifest_path = _find_markdown_manifest(
        root,
        markdown_export,
        run_manifest,
        warnings,
    )
    markdown_manifest = _read_optional_json(markdown_manifest_path, warnings)
    markdown_manifest_summary = _summarize_markdown_manifest(
        markdown_manifest,
        warnings,
    )
    review_summary_path, review_items_path = _find_review_artifacts(
        root,
        run_manifest,
    )
    review_summary = _read_optional_json(review_summary_path, warnings)
    if review_summary is not None and not isinstance(review_summary, dict):
        warnings.append("bookmark review summary 형식이 JSON object가 아니다.")
        review_summary = None

    result = {
        "status": "available" if plan_path else "missing",
        "output_dir": str(root),
        "plan_path": str(plan_path) if plan_path else None,
        "bookmark_plan_item_count": len(plan_items),
        "bookmark_levels": levels,
        "validation_path": str(validation_path) if validation_path.is_file() else None,
        "validation": validation,
        "report_path": str(report_path) if report_path else None,
        "markdown_export": markdown_export,
        "markdown_manifest_path": (
            str(markdown_manifest_path) if markdown_manifest_path else None
        ),
        "markdown_manifest": markdown_manifest_summary,
        "bookmark_review_summary_path": (
            str(review_summary_path) if review_summary_path else None
        ),
        "bookmark_review_items_path": (
            str(review_items_path) if review_items_path else None
        ),
        "bookmark_review_summary": review_summary,
        "warnings": warnings,
    }
    query_requested = any(
        (
            include_items,
            item_id is not None,
            page_range is not None,
            level is not None,
            source is not None,
            attention_only,
        )
    )
    if not query_requested:
        return result
    if review_items_path is None:
        raise FileNotFoundError(
            "bookmark review item artifact가 없다. typography infer를 다시 실행해 "
            "bookmark_review_items.jsonl을 생성해야 한다."
        )

    review_items = _read_review_items(review_items_path)
    filtered = _filter_review_items(
        review_items,
        item_id=item_id,
        page_range=page_range,
        level=level,
        source=source,
        attention_only=attention_only,
    )
    if item_id is not None and not filtered:
        raise ValueError(f"bookmark review item ID를 찾지 못했다: {item_id}")
    selected = filtered[:limit]
    result["review_query"] = {
        "item_id": item_id,
        "page_range": list(page_range) if page_range is not None else None,
        "level": level,
        "source": source,
        "attention_only": attention_only,
        "limit": limit,
        "matched_item_count": len(filtered),
        "returned_item_count": len(selected),
        "truncated": len(filtered) > len(selected),
    }
    result["bookmark_review_items"] = selected
    return result


def inspect_compare_plans(
    plan_a: Path | str,
    plan_b: Path | str,
    *,
    page_tolerance: int | None = None,
    title_similarity_threshold: float | None = None,
) -> dict[str, Any]:
    """두 bookmark plan JSON을 title+page 매칭으로 비교한다."""

    path_a = _require_file(plan_a, "plan A")
    path_b = _require_file(plan_b, "plan B")
    before = load_bookmark_plan_json(path_a)
    after = load_bookmark_plan_json(path_b)
    kwargs: dict[str, Any] = {}
    if page_tolerance is not None:
        kwargs["page_tolerance"] = page_tolerance
    if title_similarity_threshold is not None:
        kwargs["title_similarity_threshold"] = title_similarity_threshold
    diff = compare_bookmark_plans(before, after, **kwargs)

    return {
        "plan_a_path": str(path_a),
        "plan_b_path": str(path_b),
        "plan_a_item_count": len(before),
        "plan_b_item_count": len(after),
        "added_count": diff.added_count,
        "removed_count": diff.removed_count,
        "matched_count": diff.matched_count,
        "unchanged_count": diff.unchanged_count,
        "moved_count": diff.moved_count,
        "level_changed_count": diff.level_changed_count,
        "source_changed_count": diff.source_changed_count,
        "entries": [_diff_entry_to_dict(entry) for entry in diff.entries],
    }


def _diff_entry_to_dict(entry: PlanDiffEntry) -> dict[str, Any]:
    return {
        "status": entry.status,
        "title_similarity": entry.title_similarity,
        "page_changed": entry.page_changed,
        "level_changed": entry.level_changed,
        "source_changed": entry.source_changed,
        "before": _plan_item_to_dict(entry.before),
        "after": _plan_item_to_dict(entry.after),
    }


def _plan_item_to_dict(item: BookmarkPlanItem | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "title": item.title,
        "level": item.level,
        "pdf_page": item.pdf_page,
        "source": item.source,
    }


def _require_file(path_value: Path | str, label: str) -> Path:
    path = Path(path_value)
    if not path.is_file():
        raise FileNotFoundError(f"{label} 파일이 없다: {path}")
    return path


def _require_directory(path_value: Path | str, label: str) -> Path:
    path = Path(path_value)
    if not path.is_dir():
        raise FileNotFoundError(f"{label}가 없다: {path}")
    return path


def _read_optional_json(path: Path | None, warnings: list[str]) -> Any | None:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"JSON artifact를 읽지 못했다: path={path}, reason={exc}")
        return None


def _path_from_config(value: object) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


def _pdf_page_count(path: Path | None, warnings: list[str]) -> int | None:
    if path is None:
        return None
    if not path.is_file():
        warnings.append(f"OCR config의 input PDF를 찾지 못했다: {path}")
        return None
    try:
        with fitz.open(path) as document:
            return document.page_count
    except fitz.FileDataError as exc:
        warnings.append(f"OCR config의 input PDF를 열지 못했다: {exc}")
        return None


def _target_pages(
    config: dict[str, Any], total_pages: int | None, warnings: list[str]
) -> list[int]:
    configured_pages = config.get("pages")
    if isinstance(configured_pages, list) and all(
        isinstance(page, int) and page >= 1 for page in configured_pages
    ):
        return sorted(dict.fromkeys(configured_pages))
    if total_pages is None:
        warnings.append("OCR target page 수를 알 수 없다.")
        return []
    return list(range(1, total_pages + 1))


def _json_file_count(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for _ in directory.glob("*.json"))


def _read_insertable_pages(directory: Path) -> tuple[list[int], int]:
    if not directory.is_dir():
        return [], 0
    pages: list[int] = []
    invalid_count = 0
    for path in directory.glob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("pdf_page")
            if not isinstance(value, int) or value < 1:
                raise ValueError("pdf_page가 1 이상의 정수가 아니다.")
        except (OSError, ValueError, json.JSONDecodeError):
            invalid_count += 1
        else:
            pages.append(value)
    return pages, invalid_count


def _inspect_ocr_stats(root: Path) -> dict[str, dict[str, Any]]:
    names = ("ocr_page_stats.jsonl", "ocr_element_stats.jsonl", "ocr_line_stats.jsonl")
    return {
        name: {
            "exists": (path := root / name).is_file(),
            "row_count": _line_count(path),
        }
        for name in names
    }


def _line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8") as file:
        return sum(1 for line in file if line.strip())


def _read_last_log_event(path: Path, warnings: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        if not lines:
            return None
        event = json.loads(lines[-1])
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"OCR log 마지막 event를 읽지 못했다: {exc}")
        return None
    return {
        key: event.get(key)
        for key in ("event", "level", "pdf_page", "message", "elapsed_sec")
    }


def _ocr_status(
    artifact_dir: Path,
    total_pages: int | None,
    target_pages: list[int],
    insertable_pages: set[int],
    output_exists: bool,
) -> str:
    if output_exists and target_pages and set(target_pages) <= insertable_pages:
        return "complete"
    if artifact_dir.exists() and (total_pages is not None or insertable_pages):
        return "partial"
    return "missing"


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _first_existing_path(*paths: Path) -> Path | None:
    return next((path for path in paths if path.is_file()), None)


def _find_processing_report(root: Path) -> Path | None:
    return next(iter(sorted(root.glob("*_report.json"))), None)


def _find_review_artifacts(
    root: Path,
    run_manifest: object,
) -> tuple[Path | None, Path | None]:
    """run manifest와 output root에서 review summary/items를 찾는다."""

    artifact_paths = (
        run_manifest.get("artifact_paths") if isinstance(run_manifest, dict) else None
    )

    def find(name: str, filename: str) -> Path | None:
        candidates: list[Path] = []
        if isinstance(artifact_paths, dict):
            _append_artifact_path(candidates, root, artifact_paths.get(name))
        candidates.append(root / filename)
        return next((path for path in candidates if path.is_file()), None)

    return (
        find("bookmark_review_summary", "bookmark_review_summary.json"),
        find("bookmark_review_items", "bookmark_review_items.jsonl"),
    )


def _read_review_items(path: Path) -> list[dict[str, Any]]:
    """독립 JSON object인 review JSONL을 검증하며 읽는다."""

    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        "bookmark review JSONL을 읽지 못했다: "
                        f"path={path}, line={line_number}, reason={exc}"
                    ) from exc
                if not isinstance(row, dict):
                    raise ValueError(
                        "bookmark review JSONL 행이 object가 아니다: "
                        f"path={path}, line={line_number}"
                    )
                rows.append(row)
    except OSError as exc:
        raise ValueError(
            f"bookmark review JSONL을 읽지 못했다: path={path}, reason={exc}"
        ) from exc
    return rows


def _filter_review_items(
    items: list[dict[str, Any]],
    *,
    item_id: str | None,
    page_range: tuple[int, int] | None,
    level: int | None,
    source: str | None,
    attention_only: bool,
) -> list[dict[str, Any]]:
    """review item에 CLI/Python API filter를 순서대로 적용한다."""

    result: list[dict[str, Any]] = []
    for item in items:
        if item_id is not None and item.get("node_id") != item_id:
            continue
        pdf_page = item.get("pdf_page")
        if page_range is not None and (
            not isinstance(pdf_page, int)
            or not page_range[0] <= pdf_page <= page_range[1]
        ):
            continue
        if level is not None and item.get("level") != level:
            continue
        if source is not None and item.get("source") != source:
            continue
        if attention_only and not item.get("attention_signals"):
            continue
        result.append(item)
    return result


def _find_markdown_manifest(
    root: Path,
    markdown_export: object,
    run_manifest: object,
    warnings: list[str],
) -> Path | None:
    """report, run manifest와 output tree에서 graph manifest를 찾는다."""

    candidates: list[Path] = []
    if isinstance(markdown_export, dict):
        _append_artifact_path(candidates, root, markdown_export.get("manifest_path"))
    if isinstance(run_manifest, dict):
        artifact_paths = run_manifest.get("artifact_paths")
        if isinstance(artifact_paths, dict):
            _append_artifact_path(
                candidates,
                root,
                artifact_paths.get("markdown_manifest"),
            )
    candidates.append(root / "markdown_manifest.json")
    for path in candidates:
        if path.is_file():
            return path

    discovered = sorted(root.rglob("markdown_manifest.json"))
    if len(discovered) > 1:
        warnings.append(
            f"Markdown manifest가 여러 개라 첫 경로를 사용한다: count={len(discovered)}"
        )
    return discovered[0] if discovered else None


def _append_artifact_path(candidates: list[Path], root: Path, value: object) -> None:
    """문자열 artifact path를 absolute/relative 후보로 추가한다."""

    if not isinstance(value, str) or not value:
        return
    path = Path(value)
    candidates.append(path if path.is_absolute() else root / path)


def _summarize_markdown_manifest(
    value: object,
    warnings: list[str],
) -> dict[str, Any] | None:
    """node 파일을 읽지 않고 graph 계약과 coverage 핵심값만 반환한다."""

    if value is None:
        return None
    if not isinstance(value, dict):
        warnings.append("Markdown manifest 형식이 JSON object가 아니다.")
        return None
    return {
        "schema_version": value.get("schema_version"),
        "export_mode": value.get("export_mode"),
        "content_mode": value.get("content_mode"),
        "node_count": value.get("node_count"),
        "root_count": value.get("root_count"),
        "chosen_level": value.get("chosen_level"),
        "constraint_satisfied": value.get("constraint_satisfied"),
        "fallback_used": value.get("fallback_used"),
        "validation": value.get("validation"),
        "coverage": value.get("coverage"),
        "manifest_warnings": value.get("warnings"),
    }
