"""본문 separator BPE와 coverage Markdown split을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import yaml

from pdfbooktree.config import MarkdownSplitConfig, TypographyConfig
from pdfbooktree.export.fallback import choose_deepest_available_level
from pdfbooktree.export.markdown import export_markdown_split
from pdfbooktree.models import BookmarkPlanItem, Tier, TierSet, TypographyLine
from pdfbooktree.typography.bpe import (
    BpeHeading,
    extract_bpe_headings,
    infer_bpe_outline,
)
from pdfbooktree.typography.tiers import compute_tier_set


def _line(text: str, font_size: float, y0: float) -> TypographyLine:
    return TypographyLine(
        pdf_page=1,
        text=text,
        x0=72.0,
        y0=y0,
        x1=300.0,
        y1=y0 + 10.0,
        page_width=595.0,
        page_height=842.0,
        font_size=font_size,
        height=10.0,
        is_bold=False,
    )


def _tiers() -> TierSet:
    return TierSet(
        signal="font_size",
        cut_points=[15.0],
        tiers=[
            Tier(tier=1, lower_bound=15.0, upper_bound=None, peak=20.0, count=2),
            Tier(tier=2, lower_bound=None, upper_bound=15.0, peak=10.0, count=3),
        ],
        raw_tier_count=2,
        gap_merged_tier_count=2,
        final_tier_count=2,
    )


def test_body_token_blocks_bpe_pair_across_body_text() -> None:
    lines = [
        _line("First Heading", 20.0, 10.0),
        _line("body separator", 10.0, 20.0),
        _line("Second Heading", 20.0, 30.0),
        _line("body line one", 10.0, 40.0),
        _line("body line two", 10.0, 50.0),
    ]

    headings = extract_bpe_headings(
        lines, _tiers(), TypographyConfig(bpe_min_pair_count=1)
    )

    assert [heading.title for heading in headings] == [
        "First Heading",
        "Second Heading",
    ]


def test_bpe_merges_narrow_direct_heading_lines() -> None:
    lines = [
        _line("CHAPTER", 20.0, 10.0),
        _line("One", 20.0, 20.0),
        _line("body line one", 10.0, 40.0),
        _line("body line two", 10.0, 50.0),
        _line("body line three", 10.0, 60.0),
    ]

    headings = extract_bpe_headings(
        lines, _tiers(), TypographyConfig(bpe_min_pair_count=1)
    )

    assert [heading.title for heading in headings] == ["CHAPTER One"]


def test_bpe_does_not_merge_broad_direct_heading_lines() -> None:
    lines = [
        _line("CHAPTER", 20.0, 10.0),
        _line("One", 20.0, 40.0),
        _line("body line one", 10.0, 60.0),
        _line("body line two", 10.0, 70.0),
        _line("body line three", 10.0, 80.0),
    ]

    headings = extract_bpe_headings(
        lines, _tiers(), TypographyConfig(bpe_min_pair_count=1)
    )

    assert [heading.title for heading in headings] == ["CHAPTER", "One"]


def test_tier_set_keeps_close_frequent_peaks_for_body_separator() -> None:
    lines = [
        *[_line(f"section {index}", 12.0, float(index * 20)) for index in range(5)],
        *[_line(f"body {index}", 11.0, float(200 + index * 20)) for index in range(5)],
    ]

    tiers = compute_tier_set(
        lines,
        "font_size",
        TypographyConfig(min_tier_count=1, min_tier_gap=2.0),
    )

    assert tiers.final_tier_count == 2


def test_bpe_demotes_long_node_by_one_font_tier() -> None:
    lines = [
        _line(" ".join(["long"] * 31), 20.0, 10.0),
        _line("body one", 10.0, 30.0),
        _line("short one", 20.0, 50.0),
        _line("body two", 10.0, 70.0),
        _line("short two", 20.0, 90.0),
        _line("body three", 10.0, 110.0),
        _line("short three", 20.0, 130.0),
        _line("body four", 10.0, 150.0),
    ]

    headings = extract_bpe_headings(lines, _tiers())

    assert [heading.is_pollution for heading in headings] == [True, False, False, False]
    assert [
        item.level
        for item in infer_bpe_outline(
            headings, TypographyConfig(bpe_level_pollution_ratio=1.0)
        )
    ] == [2, 1, 1, 1]


def test_bpe_excludes_bookmark_level_when_pollution_exceeds_ratio() -> None:
    headings = [
        BpeHeading("Chapter", 1, 1, 10.0, 20.0, 1),
        BpeHeading("Section", 1, 2, 30.0, 40.0, 1),
        BpeHeading("Subsection", 1, 3, 50.0, 60.0, 1),
        BpeHeading("Long body", 1, 2, 70.0, 80.0, 1, is_pollution=True),
    ]

    plan = infer_bpe_outline(headings, TypographyConfig(bpe_level_pollution_ratio=0.3))

    assert [item.title for item in plan] == ["Chapter", "Section"]


def test_split_export_selects_coarsest_level_that_meets_coverage(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    document = fitz.open()
    try:
        for _ in range(3):
            page = document.new_page()
            page.insert_text((72, 72), "one two three four five", fontsize=12)
        document.save(pdf)
    finally:
        document.close()
    plan = [
        BookmarkPlanItem(title="Chapter", level=1, pdf_page=1),
        BookmarkPlanItem(
            title="Section",
            level=2,
            pdf_page=2,
            source="position_fallback",
            confidence=0.61,
            evidence=["page_top_repetition"],
        ),
        BookmarkPlanItem(title="Topic", level=3, pdf_page=3),
    ]

    result = export_markdown_split(
        pdf,
        tmp_path / "out",
        plan,
        total_pages=3,
        config=MarkdownSplitConfig(max_words=16, max_words_coverage=1.0),
    )

    assert result.constraint_satisfied is True
    assert result.fallback_used is False
    assert result.fallback_reason is None
    assert result.chosen_level == 2
    assert result.file_count == 2
    assert result.manifest_path is not None and result.manifest_path.exists()
    assert result.manifest_path.name == "markdown_manifest.json"
    assert result.export_mode == "split"
    assert result.overflow_files == []
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["export_mode"] == "split"
    assert manifest["content_mode"] == "bounded"
    assert manifest["validation"]["valid"] is True
    assert [node["node_id"] for node in manifest["nodes"]] == ["n0001", "n0002"]
    assert manifest["nodes"][1]["contained_plan_node_ids"] == ["n0002", "n0003"]
    assert (result.output_dir / "toc.md").is_file()
    node_path = result.output_dir / manifest["nodes"][1]["relative_path"]
    lines = node_path.read_text(encoding="utf-8").splitlines()
    end = lines.index("---", 1)
    front_matter = yaml.safe_load("\n".join(lines[1:end]))
    assert front_matter["node_id"] == "n0002"
    assert front_matter["source"] == "position_fallback"
    assert front_matter["confidence"] == 0.61
    assert front_matter["evidence_count"] == 1
    assert front_matter["evidence_ref"] == "../bookmark_plan.json#n0002"


def test_split_graph는_same_page_boundary에서_마지막_node만_page를_소유한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "same-page.pdf"
    document = fitz.open()
    try:
        for text in ("first page body", "second page body"):
            page = document.new_page()
            page.insert_text((72, 72), text, fontsize=12)
        document.save(pdf)
    finally:
        document.close()
    plan = [
        BookmarkPlanItem(title="Chapter", level=1, pdf_page=1),
        BookmarkPlanItem(title="Section", level=2, pdf_page=1),
        BookmarkPlanItem(title="Next", level=1, pdf_page=2),
    ]

    result = export_markdown_split(
        pdf,
        tmp_path / "out",
        plan,
        total_pages=2,
        config=MarkdownSplitConfig(max_words=1, max_words_coverage=1.0),
    )

    assert result.fallback_used is True
    assert result.chosen_level == 2
    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["coverage"]["duplicated_page_count"] == 0
    assert manifest["coverage"]["navigation_only_node_count"] == 1
    assert manifest["warnings"]["same_page_boundary_count"] == 1
    assert manifest["validation"]["valid"] is True


def test_deepest_level_fallback은_문서가_있는_가장_깊은_level을_고른다():
    decision = choose_deepest_available_level({1: [object()], 2: [object()], 3: []})

    assert decision.chosen_level == 2
    assert decision.used is True
    assert decision.reason == "coverage_target_unsatisfied"


def test_deepest_level_fallback은_문서가_없으면_level을_고르지_않는다():
    decision = choose_deepest_available_level({1: [], 2: []})

    assert decision.chosen_level is None
    assert decision.used is False
    assert decision.reason == "no_documents_at_any_level"


def test_split_export는_constraint_실패시_가장_깊은_level을_export한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "one two three four five", fontsize=12)
        document.save(pdf)
    finally:
        document.close()

    result = export_markdown_split(
        pdf,
        tmp_path / "out",
        [BookmarkPlanItem(title="Chapter", level=1, pdf_page=1)],
        total_pages=1,
        config=MarkdownSplitConfig(max_words=1, max_words_coverage=1.0),
    )

    assert result.constraint_satisfied is False
    assert result.fallback_used is True
    assert result.fallback_reason == "coverage_target_unsatisfied"
    assert result.chosen_level == 1
    assert result.file_count == 1
    assert len(result.overflow_files) == 1
    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["fallback_used"] is True
    assert manifest["chosen_level"] == 1
    assert manifest["statistics"]["coverage"] == 0.0
