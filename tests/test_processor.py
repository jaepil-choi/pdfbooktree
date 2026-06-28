"""단일 PDF 처리 파이프라인을 검증한다.

offset 추정은 data/ 실제 PDF 대신 fitz 합성 PDF의 footer page number로 결정적으로
검증한다. TOC item 파싱은 detect/parse heuristic에 묶이지 않도록 monkeypatch로 주입해
offset → alignment → ranges 연결 자체를 격리 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from pdfbooktree.alignment.offset import OffsetEstimationError
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.models import TocItem, TocRangeReview
from pdfbooktree.processor import Processor

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
FOOTER_Y = 810.0  # 하위 10% band(>= 757.8) 안
HEADING_Y = 60.0  # 상위 10% band 안, page 첫 줄로 잡힌다


def _make_pdf(path: Path, page_specs: list[list[tuple[float, float, str]]]) -> None:
    """page_specs대로 텍스트를 배치한 bookmark 없는 합성 PDF를 만든다."""

    document = fitz.open()
    try:
        for spec in page_specs:
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            for x, y, text in spec:
                page.insert_text((x, y), text, fontsize=12)
        document.save(str(path))
    finally:
        document.close()


def test_processor_exports_markdown_for_pdf_with_existing_bookmark(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """기본 config에서 bookmark가 있으면 skip 대신 markdown tree를 export한다."""

    bookmarks = [
        {"order": 1, "level": 1, "title": "Chapter 1", "pdf_page": 1},
        {"order": 2, "level": 2, "title": "1.1", "pdf_page": 2},
    ]

    monkeypatch.setattr(
        "pdfbooktree.processor.extract_existing_bookmarks",
        lambda _: bookmarks,
    )

    captured: dict[str, object] = {}
    fake_dir = tmp_path / "out" / "bookmarked_markdown"

    def fake_export(input_pdf, output_dir, passed_bookmarks):
        captured["bookmarks"] = passed_bookmarks
        return (len(passed_bookmarks), fake_dir)

    monkeypatch.setattr(
        "pdfbooktree.processor.export_bookmark_markdown_tree",
        fake_export,
    )

    result = Processor(tmp_path / "bookmarked.pdf", tmp_path / "out").run()

    assert result.status == "processed"
    assert result.output_pdf is None
    assert result.output_markdown_dir == fake_dir
    assert result.bookmark_count == 2
    assert captured["bookmarks"] == bookmarks
    # embedding을 건너뛰었고 markdown을 export했다는 사실이 경고에 남는다.
    assert len(result.warnings) == 1
    assert "embedding" in result.warnings[0]
    assert "markdown" in result.warnings[0]
    assert result.report_path is not None
    assert result.report_path.exists()


def test_processor_forced_reprocess_skips_bookmark_export(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """--no-skip(강제 재처리)면 bookmark export를 건너뛰고 TOC 파이프라인으로 내려간다."""

    monkeypatch.setattr(
        "pdfbooktree.processor.extract_existing_bookmarks",
        lambda _: [{"order": 1, "level": 1, "title": "Chapter 1", "pdf_page": 1}],
    )

    def fail_export(*_args, **_kwargs):
        raise AssertionError("강제 재처리에서는 bookmark export를 호출하면 안 된다.")

    monkeypatch.setattr(
        "pdfbooktree.processor.export_bookmark_markdown_tree",
        fail_export,
    )

    pdf_path = tmp_path / "no_page_numbers.pdf"
    _make_pdf(pdf_path, [[(72.0, 400.0, "본문 텍스트 줄입니다")] for _ in range(6)])

    # bookmark export를 안 타고 기존 파이프라인으로 내려가다 offset에서 fast-fail한다.
    with pytest.raises(OffsetEstimationError):
        Processor(
            pdf_path,
            tmp_path / "out",
            ProcessingConfig(skip_existing_bookmarks=False),
        ).run()


def test_processor_wires_offset_alignment_and_ranges(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """offset → heading alignment → content range가 연결되고 산출물이 남는다."""

    headings = {5: "Chapter 1 Introduction", 14: "Chapter 2 Methods"}
    specs: list[list[tuple[float, float, str]]] = []
    for pdf_page in range(1, 26):
        spec: list[tuple[float, float, str]] = []
        if pdf_page in headings:
            spec.append((72.0, HEADING_Y, headings[pdf_page]))
        printed = pdf_page - 4  # offset 4: printed 1 ≈ PDF page 5
        if printed >= 1:
            spec.append((300.0, FOOTER_Y, str(printed)))
        specs.append(spec)
    pdf_path = tmp_path / "no_bookmark.pdf"
    _make_pdf(pdf_path, specs)

    def fake_parse_toc_items(_pages, _toc_pages) -> list[TocItem]:
        return [
            TocItem(
                title="Chapter 1 Introduction",
                level=1,
                printed_page=1,
                raw_text="Chapter 1 Introduction 1",
                source_pdf_page=2,
                confidence=0.8,
            ),
            TocItem(
                title="Chapter 2 Methods",
                level=1,
                printed_page=10,
                raw_text="Chapter 2 Methods 10",
                source_pdf_page=2,
                confidence=0.8,
            ),
        ]

    monkeypatch.setattr(
        "pdfbooktree.processor.parse_toc_items",
        fake_parse_toc_items,
    )

    output_dir = tmp_path / "out"
    result = Processor(pdf_path, output_dir).run()

    # offset/alignment confidence가 채워진다.
    assert result.confidence_summary.offset is not None
    assert result.confidence_summary.offset > 0.0
    assert result.confidence_summary.alignment is not None
    assert result.confidence_summary.alignment > 0.0

    # 경고는 남은 stub(bookmark 삽입/markdown)만 언급하고 offset은 빼야 한다.
    assert "PDF bookmark 삽입" in result.warnings[0]
    assert "offset" not in result.warnings[0]

    # 중간 산출물이 저장된다.
    assert (output_dir / "page_offset.json").exists()
    assert (output_dir / "toc_aligned.json").exists()
    assert (output_dir / "ranges.json").exists()

    # offset 4로 printed 1/10 → PDF page 5/14에 heading match된다.
    offset_payload = json.loads((output_dir / "page_offset.json").read_text("utf-8"))
    assert offset_payload["offset"] == 4

    ranges_payload = json.loads((output_dir / "ranges.json").read_text("utf-8"))
    assert len(ranges_payload) == 2
    assert [entry["start_pdf_page"] for entry in ranges_payload] == [5, 14]
    assert ranges_payload[0]["end_pdf_page"] == 13
    assert ranges_payload[1]["end_pdf_page"] == 25


def _make_offset_pdf(path: Path) -> None:
    """offset 4(printed 1 ≈ PDF page 5)와 heading을 가진 bookmark 없는 PDF를 만든다."""

    headings = {5: "Chapter 1 Introduction", 14: "Chapter 2 Methods"}
    specs: list[list[tuple[float, float, str]]] = []
    for pdf_page in range(1, 26):
        spec: list[tuple[float, float, str]] = []
        if pdf_page in headings:
            spec.append((72.0, HEADING_Y, headings[pdf_page]))
        printed = pdf_page - 4
        if printed >= 1:
            spec.append((300.0, FOOTER_Y, str(printed)))
        specs.append(spec)
    _make_pdf(path, specs)


class _StubReviewer:
    def __init__(self, pages: list[int]) -> None:
        self.pages = pages
        self.called = False

    def review(self, pdf_path, detection, total_pages) -> TocRangeReview:
        self.called = True
        return TocRangeReview(
            pages=self.pages,
            start_page=self.pages[0],
            end_page=self.pages[-1],
            anchor_page=self.pages[0],
            stage="stage1_accept",
            method="llm_3stage_fallback",
            llm_calls=3,
        )


class _StubExtractor:
    def __init__(self, items: list[TocItem]) -> None:
        self.items = items
        self.called_with: list[int] | None = None

    def extract(self, pdf_path, toc_pages) -> list[TocItem]:
        self.called_with = list(toc_pages)
        return self.items


def test_processor_uses_llm_range_review_and_item_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """use_llm일 때 range reviewer가 toc_pages를 정하고, regex가 0개면 LLM item으로 채운다."""

    pdf_path = tmp_path / "no_bookmark.pdf"
    _make_offset_pdf(pdf_path)

    # 결정적 파서가 0개를 뽑은 상황을 만든다(한국어/OCR 목차 가정).
    monkeypatch.setattr(
        "pdfbooktree.processor.parse_toc_items",
        lambda _pages, _toc_pages: [],
    )

    items = [
        TocItem(
            title="Chapter 1 Introduction",
            level=1,
            printed_page=1,
            raw_text="Chapter 1 Introduction 1",
            source_pdf_page=5,
            confidence=0.8,
        ),
        TocItem(
            title="Chapter 2 Methods",
            level=1,
            printed_page=10,
            raw_text="Chapter 2 Methods 10",
            source_pdf_page=5,
            confidence=0.8,
        ),
    ]
    reviewer = _StubReviewer([5, 6])
    extractor = _StubExtractor(items)

    output_dir = tmp_path / "out"
    result = Processor(
        pdf_path,
        output_dir,
        ProcessingConfig(use_llm=True),
        range_reviewer=reviewer,
        item_extractor=extractor,
    ).run()

    # reviewer가 정한 toc_pages를 그대로 쓴다.
    assert reviewer.called is True
    assert result.toc_pages == [5, 6]
    assert (output_dir / "toc_range_review.json").exists()

    # 결정적 파서 0개 → LLM item extractor가 같은 toc_pages로 호출된다.
    assert extractor.called_with == [5, 6]

    # LLM item이 offset/alignment/ranges로 흘러 산출물이 만들어진다.
    ranges_payload = json.loads((output_dir / "ranges.json").read_text("utf-8"))
    assert [entry["start_pdf_page"] for entry in ranges_payload] == [5, 14]


def test_processor_skips_llm_when_use_llm_false(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """use_llm=False면 range reviewer를 호출하지 않고 결정적 경로만 쓴다."""

    pdf_path = tmp_path / "no_bookmark.pdf"
    _make_offset_pdf(pdf_path)

    monkeypatch.setattr(
        "pdfbooktree.processor.parse_toc_items",
        lambda _pages, _toc_pages: [],
    )
    reviewer = _StubReviewer([5, 6])
    extractor = _StubExtractor([])

    result = Processor(
        pdf_path,
        tmp_path / "out",
        ProcessingConfig(use_llm=False),
        range_reviewer=reviewer,
        item_extractor=extractor,
    ).run()

    assert reviewer.called is False
    assert extractor.called_with is None
    assert not (tmp_path / "out" / "toc_range_review.json").exists()
    _ = result


def test_processor_raises_when_offset_unclean(tmp_path: Path) -> None:
    """offset이 clean하지 않으면 OffsetEstimationError를 그대로 전파한다(기본 정책)."""

    specs = [[(72.0, 400.0, "본문 텍스트 줄입니다")] for _ in range(6)]
    pdf_path = tmp_path / "no_page_numbers.pdf"
    _make_pdf(pdf_path, specs)

    with pytest.raises(OffsetEstimationError):
        Processor(pdf_path, tmp_path / "out").run()
