"""bookmark review summary와 item evidence 계약을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

from pdfbooktree.artifacts import write_inference_artifacts
from pdfbooktree.models import (
    BookmarkInferenceResult,
    BookmarkPlanItem,
    BookmarkPlanValidation,
    TierSet,
    TypographyLine,
)
from pdfbooktree.review import (
    BOOKMARK_REVIEW_PREVIEW_CHAR_LIMIT,
    build_bookmark_review,
)
from pdfbooktree.typography.bpe import BpeHeading
from pdfbooktree.typography.position_fallback import PositionFallbackCandidate


def _line(pdf_page: int, text: str, y0: float) -> TypographyLine:
    return TypographyLine(
        pdf_page=pdf_page,
        text=text,
        x0=72.0,
        y0=y0,
        x1=520.0,
        y1=y0 + 12.0,
        page_width=595.0,
        page_height=842.0,
        font_size=12.0,
        height=12.0,
        is_bold=False,
    )


def _inference(
    *, long_text: bool = False, duplicate_heading: bool = False
) -> BookmarkInferenceResult:
    title = "Chapter 1"
    heading = BpeHeading(
        title=title,
        pdf_page=1,
        tier=1,
        y0=70.0,
        y1=90.0,
        merged_line_count=1,
        source="geometry_typography",
        evidence=("font_text_coverage_candidate",),
    )
    fallback = PositionFallbackCandidate(
        title="123",
        pdf_page=2,
        y0=100.0,
        y1=112.0,
        support_pages=5,
        isolation_ratio=1.2,
        font_ratio=1.0,
        confidence=0.6,
        evidence=("repeated_body_tier_position",),
    )
    page_one_text = "word " * 300 if long_text else title
    return BookmarkInferenceResult(
        lines=[
            _line(1, page_one_text, 70.0),
            _line(1, "Body text", 120.0),
            _line(2, "123", 100.0),
        ],
        font_tiers=TierSet("font_size", [], [], 0, 0, 0),
        height_tiers=TierSet("height", [], [], 0, 0, 0),
        heading_candidates=[
            heading,
            *(
                [
                    BpeHeading(
                        title=title,
                        pdf_page=1,
                        tier=2,
                        y0=75.0,
                        y1=95.0,
                        merged_line_count=1,
                        source="geometry_typography",
                        evidence=("duplicate_candidate",),
                    )
                ]
                if duplicate_heading
                else []
            ),
        ],
        fallback_candidates=[fallback],
        plan=[
            BookmarkPlanItem(
                title=title,
                level=1,
                pdf_page=1,
                source="geometry_typography",
                confidence=0.8,
                evidence=["font_text_coverage_candidate"],
            ),
            BookmarkPlanItem(
                title="123",
                level=2,
                pdf_page=2,
                source="geometry_position_fallback",
                confidence=0.6,
                evidence=["repeated_body_tier_position"],
            ),
        ],
        validation=BookmarkPlanValidation(valid=True, item_count=2),
    )


def test_build_bookmark_review_preserves_plan_and_candidate_evidence() -> None:
    summary, items = build_bookmark_review(
        _inference(),
        input_pdf=Path("book.pdf"),
        total_pages=3,
    )

    assert summary["plan_item_count"] == 2
    assert summary["source_counts"] == {
        "geometry_position_fallback": 1,
        "geometry_typography": 1,
    }
    assert summary["source_ratios"] == {
        "geometry_position_fallback": 0.5,
        "geometry_typography": 0.5,
    }
    assert summary["candidate_mapping"] == {
        "matched_count": 2,
        "missing_count": 0,
        "ambiguous_count": 0,
        "duplicate_candidates_collapsed_item_count": 0,
    }
    assert summary["review_policy"].endswith("판정이 아니다")
    assert summary["input"] == {"pdf_path": "book.pdf", "page_count": 3}
    assert items[0]["node_id"] == "n0001"
    assert items[0]["next_node_id"] == "n0002"
    assert items[0]["candidate_ref"] == {
        "artifact": "heading_candidates.json",
        "index": 0,
        "kind": "heading_candidate",
    }
    assert items[0]["candidate_geometry"]["tier"] == 1
    assert items[0]["candidate_geometry"]["font_tier"] == 1
    assert items[0]["candidate_geometry"]["height_tier"] == 1
    assert items[0]["source"] == "geometry_typography"
    assert items[0]["confidence"] == 0.8
    assert items[0]["evidence"] == ["font_text_coverage_candidate"]
    assert "quality" not in items[0]
    assert items[1]["candidate_geometry"]["support_pages"] == 5
    assert "position_fallback_source" in items[1]["attention_signals"]
    assert "numeric_only_title" in items[1]["attention_signals"]


def test_build_bookmark_review_keeps_duplicate_candidate_alternatives() -> None:
    summary, items = build_bookmark_review(_inference(duplicate_heading=True))

    assert items[0]["candidate_match_status"] == "matched"
    assert items[0]["candidate_ref"]["index"] == 0
    assert items[0]["candidate_alternative_refs"] == [
        {
            "artifact": "heading_candidates.json",
            "index": 1,
            "kind": "heading_candidate",
        }
    ]
    assert "duplicate_candidates_collapsed" in items[0]["attention_signals"]
    assert summary["candidate_mapping"] == {
        "matched_count": 2,
        "missing_count": 0,
        "ambiguous_count": 0,
        "duplicate_candidates_collapsed_item_count": 1,
    }


def test_build_bookmark_review_bounds_preview_and_records_empty_page_stats() -> None:
    summary, items = build_bookmark_review(_inference(long_text=True), total_pages=3)

    assert len(items[0]["page_text_preview"]) <= (
        BOOKMARK_REVIEW_PREVIEW_CHAR_LIMIT + 1
    )
    assert items[0]["page_text_preview_truncated"] is True
    assert summary["text_statistics"]["page_with_no_typography_text_count"] == 1


def test_write_inference_artifacts_writes_review_paths(tmp_path: Path) -> None:
    artifacts = write_inference_artifacts(
        tmp_path,
        _inference(),
        input_pdf=Path("book.pdf"),
        total_pages=3,
    )

    summary_path = artifacts["bookmark_review_summary"]
    items_path = artifacts["bookmark_review_items"]
    assert summary_path == tmp_path / "bookmark_review_summary.json"
    assert items_path == tmp_path / "bookmark_review_items.jsonl"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = [
        json.loads(line) for line in items_path.read_text(encoding="utf-8").splitlines()
    ]
    assert summary["plan_item_count"] == 2
    assert len(rows) == 2
    assert rows[1]["node_id"] == "n0002"


def test_build_bookmark_review_surfaces_reuse_rejected_reason() -> None:
    summary, _items = build_bookmark_review(
        _inference(),
        reuse_rejected_reason="invalid_structure",
    )

    assert summary["existing_outline"]["reuse_rejected_reason"] == "invalid_structure"


def test_build_bookmark_review_reuse_rejected_reason_defaults_to_none() -> None:
    summary, _items = build_bookmark_review(_inference())

    assert summary["existing_outline"]["reuse_rejected_reason"] is None


def test_build_bookmark_review_next_commands_include_markdown_only_when_available() -> (
    None
):
    without_markdown, _ = build_bookmark_review(
        _inference(), input_pdf=Path("book.pdf")
    )
    with_markdown, _ = build_bookmark_review(
        _inference(),
        input_pdf=Path("book.pdf"),
        markdown_manifest_available=True,
    )

    assert not any(
        "inspect markdown" in command for command in without_markdown["next_commands"]
    )
    assert any(
        "inspect markdown" in command for command in with_markdown["next_commands"]
    )


def test_write_inference_artifacts_detects_existing_markdown_manifest(
    tmp_path: Path,
) -> None:
    manifest_dir = tmp_path / "book_markdown_split"
    manifest_dir.mkdir()
    (manifest_dir / "markdown_manifest.json").write_text("{}", encoding="utf-8")

    artifacts = write_inference_artifacts(
        tmp_path,
        _inference(),
        input_pdf=Path("book.pdf"),
        total_pages=3,
    )

    summary = json.loads(
        artifacts["bookmark_review_summary"].read_text(encoding="utf-8")
    )
    assert any("inspect markdown" in command for command in summary["next_commands"])
