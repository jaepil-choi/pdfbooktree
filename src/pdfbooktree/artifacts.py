"""중간 산출물 저장 helper다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pdfbooktree.models import (
    BookmarkInferenceResult,
    ExistingOutlineItem,
    OutlineQualityAssessment,
)
from pdfbooktree.pdf.outline import outline_to_plan
from pdfbooktree.review import build_bookmark_review
from pdfbooktree.utils.jsonio import to_jsonable, write_json


def write_artifact(output_dir: Path, name: str, data: Any) -> Path:
    """JSON artifact를 저장하고 경로를 반환한다."""

    path = output_dir / f"{name}.json"
    write_json(path, data)
    return path


def write_jsonl_artifact(output_dir: Path, name: str, rows: list[Any]) -> Path:
    """JSONL artifact를 저장하고 경로를 반환한다."""

    path = output_dir / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(to_jsonable(row), ensure_ascii=False) + "\n")
    return path


def write_inference_artifacts(
    output_dir: Path,
    inference: BookmarkInferenceResult,
    quality: OutlineQualityAssessment | None = None,
    *,
    input_pdf: Path | None = None,
    total_pages: int | None = None,
    existing_outline: list[ExistingOutlineItem] | None = None,
) -> dict[str, Path]:
    """``infer_bookmarks()`` 결과와 review 근거 artifact를 저장한다.

    ``Processor``와 ``infer`` CLI가 같은 artifact 이름/파일로 저장하도록
    이 함수를 공유한다. bookmarked PDF/Markdown은 여기서 만들지 않는다.
    """

    artifacts = {
        "whole_book_lines": write_jsonl_artifact(
            output_dir, "whole_book_lines", inference.lines
        ),
        "font_size_tiers": write_artifact(
            output_dir, "font_size_tiers", inference.font_tiers
        ),
        "height_tiers": write_artifact(
            output_dir, "height_tiers", inference.height_tiers
        ),
        "heading_candidates": write_artifact(
            output_dir, "heading_candidates", inference.heading_candidates
        ),
        "position_fallback_candidates": write_artifact(
            output_dir,
            "position_fallback_candidates",
            inference.fallback_candidates,
        ),
        "bookmark_plan": write_artifact(output_dir, "bookmark_plan", inference.plan),
        "bookmark_plan_validation": write_artifact(
            output_dir, "bookmark_plan_validation", inference.validation
        ),
    }
    if quality is not None:
        artifacts["existing_outline_quality"] = write_artifact(
            output_dir, "existing_outline_quality", quality
        )
    if existing_outline:
        artifacts["existing_outline_plan"] = write_artifact(
            output_dir,
            "existing_outline_plan",
            outline_to_plan(existing_outline),
        )
    review_summary, review_items = build_bookmark_review(
        inference,
        input_pdf=input_pdf,
        total_pages=total_pages,
        quality=quality,
        existing_outline_plan_available="existing_outline_plan" in artifacts,
    )
    artifacts["bookmark_review_summary"] = write_artifact(
        output_dir,
        "bookmark_review_summary",
        review_summary,
    )
    artifacts["bookmark_review_items"] = write_jsonl_artifact(
        output_dir,
        "bookmark_review_items",
        review_items,
    )
    return artifacts
