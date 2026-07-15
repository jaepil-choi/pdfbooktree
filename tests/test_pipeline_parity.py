"""Phase 2 파이프라인 분리 리팩터링 전후 plan이 같은지 고정한다.

이 테스트의 golden 값은 리팩터링 전 ``Processor.run()``을 실제로 실행해 얻은
결과를 그대로 박제한 것이다. ``analyze_pdf``/``infer_bookmarks``/``apply_plan``
추출 이후에도 이 assertion은 수정하지 않는다 - 값이 달라지면 리팩터링이 동작을
바꾼 것이므로 테스트가 아니라 구현을 의심해야 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from pdfbooktree.config import ProcessingConfig, TypographyConfig
from pdfbooktree.processor import Processor

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0


def _make_parity_book_pdf(path: Path) -> None:
    """3단 font tier heading과 body-tier 반복 marker를 함께 담은 책이다.

    28pt/16pt heading은 font 기반 BPE 경로를, 매 page 반복되는 10pt "Note N"
    marker(본문과 같은 tier)는 position fallback 경로를 함께 노출한다.
    """

    document = fitz.open()
    try:
        for page_no in range(1, 10):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            if page_no in (1, 4, 7):
                chapter_number = {1: 1, 4: 2, 7: 3}[page_no]
                page.insert_text(
                    (72, 90), f"Chapter {chapter_number} Title", fontsize=28
                )
                page.insert_text((72, 155), f"{chapter_number}.1 Section", fontsize=16)
            page.insert_text((72, 200), f"Note {page_no}", fontsize=10)
            for row in range(15):
                page.insert_text(
                    (72, 260 + row * 15),
                    "This is ordinary body text for the chapter.",
                    fontsize=10,
                )
        document.save(path)
    finally:
        document.close()


def test_processor_run_plan_matches_pinned_golden_plan(tmp_path: Path) -> None:
    pdf = tmp_path / "parity_book.pdf"
    output_dir = tmp_path / "out"
    _make_parity_book_pdf(pdf)
    config = ProcessingConfig(
        typography=TypographyConfig(
            min_tier_count=1,
            max_heading_tier=2,
            position_min_repeated_pages=5,
        )
    )

    result = Processor(pdf, output_dir, config).run()

    plan = json.loads((output_dir / "bookmark_plan.json").read_text("utf-8"))
    observed = [
        (item["title"], item["pdf_page"], item["level"], item["source"])
        for item in plan
    ]

    # GOLDEN VALUES: 리팩터링 전 Processor.run()을 이 fixture로 실제 실행해 얻은
    # 결과다. 손으로 유도한 값이 아니다.
    assert observed == [
        ("Chapter 1 Title", 1, 1, "geometry_typography"),
        ("1.1 Section", 1, 2, "geometry_typography"),
        ("Note 1", 1, 3, "geometry_position_fallback"),
        ("Note 2", 2, 3, "geometry_position_fallback"),
        ("Note 3", 3, 3, "geometry_position_fallback"),
        ("Chapter 2 Title", 4, 1, "geometry_typography"),
        ("2.1 Section", 4, 2, "geometry_typography"),
        ("Note 4", 4, 3, "geometry_position_fallback"),
        ("Note 5", 5, 3, "geometry_position_fallback"),
        ("Note 6", 6, 3, "geometry_position_fallback"),
        ("Chapter 3 Title", 7, 1, "geometry_typography"),
        ("3.1 Section", 7, 2, "geometry_typography"),
        ("Note 7", 7, 3, "geometry_position_fallback"),
        ("Note 8", 8, 3, "geometry_position_fallback"),
        ("Note 9", 9, 3, "geometry_position_fallback"),
    ]
    assert result.status == "processed"
    assert result.bookmark_count == len(plan)


def test_processor_existing_outline_fast_path_skips_typography_extraction(
    tmp_path: Path, monkeypatch
) -> None:
    pdf = tmp_path / "bookmarked.pdf"
    document = fitz.open()
    try:
        for index in range(3):
            page = document.new_page()
            page.insert_text((72, 72), f"Page {index + 1}", fontsize=12)
        document.set_toc([[1, "Chapter 1", 1], [2, "1.1 Topic", 2]])
        document.save(pdf)
    finally:
        document.close()

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "existing outline이 있으면 typography extraction을 호출하면 안 된다."
        )

    monkeypatch.setattr("pdfbooktree.pipeline.extract_typography_lines", _fail)

    result = Processor(pdf, tmp_path / "out").run()

    assert result.status == "processed"
