"""공개 결과 직렬화 계약을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdfbooktree import (
    ConfidenceSummary,
    ProcessingResult,
    to_json,
    to_jsonable,
)


def test_to_jsonable은_공개_result와_path를_json_value로_변환한다() -> None:
    result = ProcessingResult(
        status="processed",
        input_pdf=Path("책.pdf"),
        output_pdf=Path("결과.pdf"),
        bookmark_count=3,
        confidence_summary=ConfidenceSummary(outline=0.8),
        artifact_paths={"bookmark_plan": Path("bookmark_plan.json")},
    )

    payload = to_jsonable(result)

    assert payload["status"] == "processed"
    assert payload["input_pdf"] == "책.pdf"
    assert payload["confidence_summary"] == {
        "line_extraction": None,
        "tiering": None,
        "heading_candidates": None,
        "outline": 0.8,
    }
    assert payload["artifact_paths"] == {"bookmark_plan": "bookmark_plan.json"}


def test_to_json은_unicode와_tuple을_표준_json으로_직렬화한다() -> None:
    encoded = to_json(
        {"title": "제1장", "pages": (1, 2)},
        ensure_ascii=False,
        indent=2,
    )

    assert json.loads(encoded) == {"title": "제1장", "pages": [1, 2]}
    assert "제1장" in encoded


def test_to_jsonable은_지원하지_않는_객체를_거부한다() -> None:
    with pytest.raises(TypeError, match="JSON으로 변환할 수 없는 타입"):
        to_jsonable(object())


def test_to_jsonable은_non_finite_float를_거부한다() -> None:
    with pytest.raises(ValueError, match="NaN과 Infinity"):
        to_jsonable(float("nan"))
