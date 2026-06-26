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
from pdfbooktree.models import TocItem
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


def test_processor_skips_any_pdf_with_existing_bookmark(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """runtime Processor는 bookmark가 있으면 PDF 본문을 열기 전에 제외한다."""

    def fake_extract_existing_bookmarks(_: Path) -> list[dict[str, object]]:
        return [
            {
                "order": 1,
                "level": 1,
                "title": "1",
                "pdf_page": 1,
            }
        ]

    monkeypatch.setattr(
        "pdfbooktree.processor.extract_existing_bookmarks",
        fake_extract_existing_bookmarks,
    )

    result = Processor(tmp_path / "bookmarked.pdf", tmp_path / "out").run()

    assert result.status == "skipped"
    assert result.output_pdf is None
    assert result.output_markdown_dir is None
    assert result.toc_pages == []
    assert result.warnings == [
        "기존 bookmark 1개가 있어서 runtime 자동 처리를 건너뛰었다."
    ]
    assert result.report_path is not None
    assert result.report_path.exists()


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


def test_processor_raises_when_offset_unclean(tmp_path: Path) -> None:
    """offset이 clean하지 않으면 OffsetEstimationError를 그대로 전파한다(기본 정책)."""

    specs = [[(72.0, 400.0, "본문 텍스트 줄입니다")] for _ in range(6)]
    pdf_path = tmp_path / "no_page_numbers.pdf"
    _make_pdf(pdf_path, specs)

    with pytest.raises(OffsetEstimationError):
        Processor(pdf_path, tmp_path / "out").run()
