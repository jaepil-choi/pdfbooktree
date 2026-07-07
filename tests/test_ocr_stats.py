from __future__ import annotations

import json
from pathlib import Path

from pdfbooktree.ocr.models import (
    InsertableOcrElement,
    InsertableOcrLine,
    InsertableOcrPage,
    InsertableOcrWord,
    OcrBox,
)
from pdfbooktree.ocr.stats import infer_numbering_depth, write_ocr_stats


def make_insertable_page() -> InsertableOcrPage:
    return InsertableOcrPage(
        pdf_page=1,
        width_px=1000,
        height_px=2000,
        width_pt=500.0,
        height_pt=1000.0,
        source_engine="test",
        source_model="fixture",
        elements=[
            InsertableOcrElement(
                element_id="h1",
                category="heading1",
                bbox=OcrBox(100, 100, 500, 180),
                content_text="1.2 Test Heading",
                overlay_mode="word",
                lines=[
                    InsertableOcrLine(
                        text="1.2 Test Heading",
                        bbox=OcrBox(100, 100, 500, 180),
                        words=[
                            InsertableOcrWord("1.2", OcrBox(100, 100, 160, 170)),
                            InsertableOcrWord("Test", OcrBox(180, 110, 260, 170)),
                            InsertableOcrWord("Heading", OcrBox(280, 105, 500, 175)),
                        ],
                    )
                ],
            ),
            InsertableOcrElement(
                element_id="p1",
                category="paragraph",
                bbox=OcrBox(100, 400, 700, 430),
                content_text="Body text",
                overlay_mode="word",
                lines=[
                    InsertableOcrLine(
                        text="Body text",
                        bbox=OcrBox(100, 400, 700, 430),
                        words=[
                            InsertableOcrWord("Body", OcrBox(100, 400, 180, 430)),
                            InsertableOcrWord("text", OcrBox(200, 400, 280, 430)),
                        ],
                    )
                ],
            ),
        ],
    )


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_write_ocr_stats_exports_line_and_page_height_features(tmp_path: Path) -> None:
    result = write_ocr_stats([make_insertable_page()], tmp_path, include_word_stats=True)

    line_rows = read_jsonl(result.line_stats_path)
    page_rows = read_jsonl(result.page_stats_path)
    element_rows = read_jsonl(result.element_stats_path)
    word_rows = read_jsonl(result.word_stats_path)  # type: ignore[arg-type]

    assert line_rows[0]["height_pt"] == 40.0
    assert line_rows[0]["word_height_median_pt"] == 35.0
    assert line_rows[0]["numbering_depth"] == 2
    assert line_rows[0]["inserted_font_size_median_pt"] is None
    assert page_rows[0]["category_counts"] == {"heading1": 1, "paragraph": 1}
    assert page_rows[0]["line_count"] == 2
    assert element_rows[0]["bbox_height_pt"] == 40.0
    assert len(word_rows) == 5


def test_infer_numbering_depth_keeps_numeric_only_as_separate_signal() -> None:
    assert infer_numbering_depth("3") == 0
    assert infer_numbering_depth("Chapter 4 Introduction") == 1
    assert infer_numbering_depth("2.3.1 Markov Chains") == 3
    assert infer_numbering_depth("No number") == -1
