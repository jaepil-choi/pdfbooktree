"""analyze_pdf/infer_bookmarks/apply_plan 개별 public 함수를 검증한다."""

from __future__ import annotations

from dataclasses import is_dataclass
import json
from pathlib import Path

import fitz

from pdfbooktree.config import MarkdownSplitConfig, TypographyConfig
from pdfbooktree.models import (
    BookmarkPlanItem,
    HeadingCandidate,
    PdfAnalysis,
    TypographyLine,
)
from pdfbooktree.artifacts import write_inference_artifacts
from pdfbooktree.outline.validate import validate_bookmark_plan
from pdfbooktree.pipeline import analyze_pdf, apply_plan, infer_bookmarks, validate_plan
from pdfbooktree.review import build_bookmark_review
from pdfbooktree.typography.bpe import BpeHeading
from pdfbooktree.utils.hashing import file_sha256

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0


def _make_simple_pdf(path: Path, page_count: int = 3) -> None:
    document = fitz.open()
    try:
        for page_no in range(1, page_count + 1):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            page.insert_text((72, 90), f"Page {page_no} body text", fontsize=10)
        document.save(path)
    finally:
        document.close()


def _make_ocr_style_book_pdf(path: Path, chapter_pages: int = 7) -> None:
    document = fitz.open()
    try:
        for page_no in range(1, chapter_pages + 1):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            if page_no == 1:
                page.insert_text((72, 90), "Book Title", fontsize=24)
            page.insert_text((72, 150), f"Chapter {page_no}", fontsize=10)
            for row in range(10):
                page.insert_text(
                    (72, 200 + row * 14),
                    "This is ordinary OCR body text repeated across the page.",
                    fontsize=10,
                )
        document.save(path)
    finally:
        document.close()


def test_analyze_pdf_returns_plain_dataclass_lines(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    _make_simple_pdf(pdf)

    analysis = analyze_pdf(pdf)

    assert analysis.input_pdf == pdf
    assert analysis.total_pages == 3
    assert analysis.lines
    assert all(
        is_dataclass(line) and isinstance(line, TypographyLine)
        for line in analysis.lines
    )
    assert analysis.extraction_config_hash


def test_analyze_pdf_extraction_config_hash_tracks_config(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    _make_simple_pdf(pdf)

    same_a = analyze_pdf(pdf, TypographyConfig(line_y_tolerance_ratio=0.5))
    same_b = analyze_pdf(pdf, TypographyConfig(line_y_tolerance_ratio=0.5))
    different = analyze_pdf(pdf, TypographyConfig(line_y_tolerance_ratio=0.7))

    assert same_a.extraction_config_hash == same_b.extraction_config_hash
    assert same_a.extraction_config_hash != different.extraction_config_hash


def test_infer_bookmarks_excludes_margin_lines_before_tiering() -> None:
    lines = []
    for pdf_page in range(3, 7):
        lines.extend(
            [
                TypographyLine(
                    pdf_page=pdf_page,
                    text=f"CHAPTER {pdf_page - 2}. Example {pdf_page - 2}",
                    x0=72.0,
                    y0=12.0,
                    x1=450.0,
                    y1=22.0,
                    page_width=PAGE_WIDTH,
                    page_height=PAGE_HEIGHT,
                    font_size=10.0,
                    height=10.0,
                    is_bold=False,
                ),
                TypographyLine(
                    pdf_page=pdf_page,
                    text="Course Notes",
                    x0=72.0,
                    y0=32.0,
                    x1=150.0,
                    y1=42.0,
                    page_width=PAGE_WIDTH,
                    page_height=PAGE_HEIGHT,
                    font_size=8.0,
                    height=10.0,
                    is_bold=False,
                ),
                TypographyLine(
                    pdf_page=pdf_page,
                    text=f"Body page {pdf_page}",
                    x0=72.0,
                    y0=300.0,
                    x1=200.0,
                    y1=312.0,
                    page_width=PAGE_WIDTH,
                    page_height=PAGE_HEIGHT,
                    font_size=10.0,
                    height=12.0,
                    is_bold=False,
                ),
            ]
        )
    analysis = PdfAnalysis(input_pdf=Path("dummy.pdf"), total_pages=7, lines=lines)

    inference = infer_bookmarks(
        analysis, TypographyConfig(margin_min_consecutive_pages=3)
    )

    kept_texts = {line.text for line in inference.lines}
    assert "Course Notes" not in kept_texts
    assert all(not text.startswith("CHAPTER") for text in kept_texts)
    assert {f"Body page {page}" for page in range(3, 7)} <= kept_texts


def test_infer_bookmarks_respects_position_fallback_enabled(tmp_path: Path) -> None:
    pdf = tmp_path / "ocr_style_book.pdf"
    _make_ocr_style_book_pdf(pdf)
    analysis = analyze_pdf(pdf)

    enabled = infer_bookmarks(
        analysis,
        TypographyConfig(position_min_repeated_pages=5, position_fallback_enabled=True),
    )
    disabled = infer_bookmarks(
        analysis,
        TypographyConfig(
            position_min_repeated_pages=5, position_fallback_enabled=False
        ),
    )

    assert enabled.fallback_candidates
    assert disabled.fallback_candidates == []


def test_infer_bookmarks_validation_matches_standalone_validate_call(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_simple_pdf(pdf)
    analysis = analyze_pdf(pdf)

    inference = infer_bookmarks(analysis)

    assert inference.validation == validate_bookmark_plan(
        inference.plan, analysis.total_pages
    )


def test_infer_bookmarks_keeps_strict_geometry_candidates(
    monkeypatch,
) -> None:
    strict_candidate = BpeHeading(
        title="Strict Chapter",
        pdf_page=1,
        tier=1,
        y0=72.0,
        y1=90.0,
        merged_line_count=1,
        source="strict_geometry",
        evidence=("strict_geometry",),
    )
    monkeypatch.setattr(
        "pdfbooktree.pipeline.select_geometry_headings",
        lambda _context, _config: [strict_candidate],
    )

    def fail_legacy(*_args: object) -> list[HeadingCandidate]:
        raise AssertionError(
            "strict geometry 후보가 있으면 legacy 후보를 추출하면 안 된다."
        )

    monkeypatch.setattr("pdfbooktree.pipeline.extract_heading_candidates", fail_legacy)

    inference = infer_bookmarks(
        PdfAnalysis(input_pdf=Path("dummy.pdf"), total_pages=1, lines=[]),
        TypographyConfig(position_fallback_enabled=False),
    )

    assert inference.heading_candidates == [strict_candidate]
    assert [(item.title, item.source) for item in inference.plan] == [
        ("Strict Chapter", "strict_geometry")
    ]


def test_infer_bookmarks_uses_page_strongest_legacy_candidates(
    monkeypatch,
) -> None:
    legacy_candidates = [
        HeadingCandidate(
            title="Unnumbered Heading",
            pdf_page=1,
            font_tier=1,
            height_tier=1,
            y0=40.0,
            y1=52.0,
            numbering_depth=None,
            confidence=0.99,
            evidence=["large_font_tier", "top_page_position", "bold"],
        ),
        HeadingCandidate(
            title="1. Numbered Chapter",
            pdf_page=1,
            font_tier=1,
            height_tier=1,
            y0=60.0,
            y1=72.0,
            numbering_depth=1,
            confidence=0.70,
            evidence=["large_font_tier"],
        ),
        HeadingCandidate(
            title="1.1 First Section",
            pdf_page=2,
            font_tier=2,
            height_tier=2,
            y0=80.0,
            y1=92.0,
            numbering_depth=2,
            confidence=0.80,
            evidence=["large_height_tier", "top_page_position"],
        ),
        HeadingCandidate(
            title="2. Next Chapter",
            pdf_page=3,
            font_tier=1,
            height_tier=1,
            y0=50.0,
            y1=62.0,
            numbering_depth=1,
            confidence=0.85,
            evidence=["large_font_tier", "bold"],
        ),
    ]
    monkeypatch.setattr(
        "pdfbooktree.pipeline.select_geometry_headings",
        lambda _context, _config: [],
    )
    monkeypatch.setattr(
        "pdfbooktree.pipeline.extract_heading_candidates",
        lambda _lines, _font_tiers, _height_tiers, _config: legacy_candidates,
    )

    inference = infer_bookmarks(
        PdfAnalysis(input_pdf=Path("dummy.pdf"), total_pages=3, lines=[]),
        TypographyConfig(position_fallback_enabled=False),
    )

    assert [
        (candidate.title, candidate.pdf_page, candidate.tier, candidate.source)
        for candidate in inference.heading_candidates
    ] == [
        ("1. Numbered Chapter", 1, 1, "typography"),
        ("1.1 First Section", 2, 2, "typography"),
        ("2. Next Chapter", 3, 1, "typography"),
    ]
    assert [
        (item.title, item.level, item.pdf_page, item.confidence, item.evidence)
        for item in inference.plan
    ] == [
        ("1. Numbered Chapter", 1, 1, 0.70, ["large_font_tier"]),
        (
            "1.1 First Section",
            2,
            2,
            0.80,
            ["large_height_tier", "top_page_position"],
        ),
        ("2. Next Chapter", 1, 3, 0.85, ["large_font_tier", "bold"]),
    ]
    assert all(item.source == "typography" for item in inference.plan)
    assert inference.validation.valid


def test_infer_bookmarks_legacy_fallback_candidates_survive_artifact_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """P0 회귀: strict geometry가 비어 legacy fallback이 동작하는 입력에서도
    write_artifacts=True 경로(artifact 저장 -> review 생성)가 예외 없이 끝나야
    한다. HeadingCandidate가 변환 없이 heading_candidates에 들어가면
    build_bookmark_review()가 candidate.source에서 AttributeError로 죽는다.
    """

    legacy_candidates = [
        HeadingCandidate(
            title="1. Numbered Chapter",
            pdf_page=1,
            font_tier=1,
            height_tier=1,
            y0=60.0,
            y1=72.0,
            numbering_depth=1,
            confidence=0.70,
            evidence=["large_font_tier"],
        ),
    ]
    monkeypatch.setattr(
        "pdfbooktree.pipeline.select_geometry_headings",
        lambda _context, _config: [],
    )
    monkeypatch.setattr(
        "pdfbooktree.pipeline.extract_heading_candidates",
        lambda _lines, _font_tiers, _height_tiers, _config: legacy_candidates,
    )

    analysis = PdfAnalysis(input_pdf=Path("dummy.pdf"), total_pages=3, lines=[])
    inference = infer_bookmarks(
        analysis, TypographyConfig(position_fallback_enabled=False)
    )

    assert inference.heading_candidates
    assert all(
        candidate.source == "typography" for candidate in inference.heading_candidates
    )

    output_dir = tmp_path / "artifacts"
    output_dir.mkdir()
    artifacts = write_inference_artifacts(
        output_dir,
        inference,
        input_pdf=analysis.input_pdf,
        total_pages=analysis.total_pages,
    )

    assert (output_dir / "heading_candidates.json").is_file()
    assert (output_dir / "bookmark_review_summary.json").is_file()
    assert "bookmark_review_items" in artifacts

    summary, items = build_bookmark_review(
        inference, input_pdf=analysis.input_pdf, total_pages=analysis.total_pages
    )
    assert items
    assert summary["candidate_counts"]["heading"] == len(inference.heading_candidates)


def test_infer_bookmarks_keeps_empty_plan_without_legacy_evidence(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "pdfbooktree.pipeline.select_geometry_headings",
        lambda _context, _config: [],
    )
    monkeypatch.setattr(
        "pdfbooktree.pipeline.extract_heading_candidates",
        lambda _lines, _font_tiers, _height_tiers, _config: [],
    )

    inference = infer_bookmarks(
        PdfAnalysis(input_pdf=Path("dummy.pdf"), total_pages=3, lines=[]),
        TypographyConfig(position_fallback_enabled=False),
    )

    assert inference.heading_candidates == []
    assert inference.plan == []
    assert not inference.validation.valid


def test_apply_plan_writes_pdf_and_markdown_for_valid_plan(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_simple_pdf(pdf)
    plan = [
        BookmarkPlanItem(title="Chapter 1", level=1, pdf_page=1),
        BookmarkPlanItem(title="Chapter 2", level=1, pdf_page=2),
    ]

    result = apply_plan(pdf, output_dir, plan, total_pages=3)

    assert result.validation.valid
    assert result.output_pdf is not None and result.output_pdf.exists()
    assert (
        result.output_markdown_dir is not None
        and (result.output_markdown_dir / "toc.md").exists()
    )
    assert result.markdown_export is not None
    assert result.markdown_export.export_mode == "tree_graph"
    assert result.markdown_export.manifest_path is not None
    assert result.markdown_export.manifest_path.is_file()


def test_apply_plan_skips_writing_for_invalid_plan(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_simple_pdf(pdf)
    plan = [BookmarkPlanItem(title="Out of range", level=1, pdf_page=99)]

    result = apply_plan(pdf, output_dir, plan, total_pages=3)

    assert not result.validation.valid
    assert result.output_pdf is None
    assert result.output_markdown_dir is None
    assert not list(output_dir.glob("*_bookmarked.pdf"))


def test_apply_plan_does_not_reextract_typography(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_simple_pdf(pdf)
    plan = [BookmarkPlanItem(title="Chapter 1", level=1, pdf_page=1)]

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("apply_plan은 typography extraction을 다시 하면 안 된다.")

    monkeypatch.setattr("pdfbooktree.pipeline.extract_typography_lines", _fail)

    result = apply_plan(pdf, output_dir, plan, total_pages=3)

    assert result.validation.valid


def test_apply_plan_uses_markdown_split_when_configured(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "out"
    _make_simple_pdf(pdf)
    plan = [BookmarkPlanItem(title="Chapter 1", level=1, pdf_page=1)]

    result = apply_plan(
        pdf,
        output_dir,
        plan,
        total_pages=3,
        markdown_split=MarkdownSplitConfig(max_words=1000, max_words_coverage=1.0),
    )

    assert result.markdown_export is not None
    assert result.output_markdown_dir == result.markdown_export.output_dir


def test_apply_plan_syncs_in_place_outline_to_markdown_chosen_level(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "ocr-overlay.pdf"
    document = fitz.open()
    try:
        for _ in range(3):
            page = document.new_page()
            page.insert_text((72, 72), "one two three four five", fontsize=12)
        document.save(pdf)
    finally:
        document.close()
    original_hash = file_sha256(pdf)
    plan = [
        BookmarkPlanItem(title="Chapter", level=1, pdf_page=1),
        BookmarkPlanItem(title="Section", level=2, pdf_page=2),
        BookmarkPlanItem(title="Topic", level=3, pdf_page=3),
    ]

    result = apply_plan(
        pdf,
        tmp_path / "runs",
        plan,
        total_pages=3,
        markdown_split=MarkdownSplitConfig(
            max_words=16,
            max_words_coverage=1.0,
        ),
        in_place=True,
    )

    assert result.validation.valid
    assert result.in_place is True
    assert result.output_pdf == pdf.resolve()
    assert result.source_bookmark_count == 3
    assert [item.title for item in result.applied_plan] == ["Chapter", "Section"]
    assert result.markdown_export is not None
    assert result.markdown_export.chosen_level == 2
    assert result.original_pdf_sha256 == original_hash
    assert result.final_pdf_sha256 == file_sha256(pdf)
    assert result.final_pdf_sha256 != original_hash
    assert not list(tmp_path.rglob("*_bookmarked.pdf"))
    with fitz.open(pdf) as updated:
        assert updated.page_count == 3
        assert updated.get_toc() == [[1, "Chapter", 1], [2, "Section", 2]]
        assert "one two three four five" in updated[2].get_text()
    manifest = json.loads(
        result.markdown_export.manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["chosen_level"] == 2
    assert manifest["input"]["sha256"] == result.final_pdf_sha256


def test_in_place_outline_failure_preserves_original_pdf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "ocr-overlay.pdf"
    _make_simple_pdf(pdf)
    original_hash = file_sha256(pdf)

    def fail_validation(*_args, **_kwargs) -> None:
        raise RuntimeError("candidate validation failed")

    monkeypatch.setattr(
        "pdfbooktree.pdf.outline._validate_written_outline",
        fail_validation,
    )

    try:
        apply_plan(
            pdf,
            tmp_path / "runs",
            [BookmarkPlanItem(title="Chapter", level=1, pdf_page=1)],
            total_pages=3,
            markdown_split=MarkdownSplitConfig(max_words=1000),
            in_place=True,
        )
    except RuntimeError as error:
        assert str(error) == "candidate validation failed"
    else:
        raise AssertionError("in-place validation failure가 전파되어야 한다")

    assert file_sha256(pdf) == original_hash
    assert not list(tmp_path.glob(".*.bookmarks.*.pdf"))


def test_validate_plan_reads_page_count_without_writing(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    _make_simple_pdf(pdf)
    before = sorted(path.name for path in tmp_path.iterdir())

    valid = validate_plan(
        pdf, [BookmarkPlanItem(title="Chapter 1", level=1, pdf_page=1)]
    )
    invalid = validate_plan(
        pdf, [BookmarkPlanItem(title="Outside", level=1, pdf_page=99)]
    )

    assert valid.valid is True
    assert invalid.valid is False
    assert sorted(path.name for path in tmp_path.iterdir()) == before
