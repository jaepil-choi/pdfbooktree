from __future__ import annotations

from pdfbooktree.ocr.engines.upstage import UpstageOcrEngine
from pdfbooktree.ocr.models import RenderedPage


def rendered_page() -> RenderedPage:
    return RenderedPage(
        pdf_page=42,
        png_bytes=b"png",
        png_sha1="abc",
        width_px=1000,
        height_px=2000,
        width_pt=500.0,
        height_pt=1000.0,
    )


def test_upstage_adapter_selects_word_row_and_element_overlay_modes() -> None:
    raw = {
        "elements": [
            {
                "id": "heading",
                "category": "heading1",
                "coordinates": [
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.4, "y": 0.1},
                    {"x": 0.4, "y": 0.14},
                    {"x": 0.1, "y": 0.14},
                ],
                "content": {"text": "Hello World"},
                "words": [
                    {
                        "text": "Hello",
                        "coordinates": [
                            {"x": 0.1, "y": 0.1},
                            {"x": 0.2, "y": 0.1},
                            {"x": 0.2, "y": 0.12},
                            {"x": 0.1, "y": 0.12},
                        ],
                    },
                    {
                        "text": "World",
                        "coordinates": [
                            {"x": 0.22, "y": 0.1},
                            {"x": 0.34, "y": 0.1},
                            {"x": 0.34, "y": 0.12},
                            {"x": 0.22, "y": 0.12},
                        ],
                    },
                ],
            },
            {
                "id": "table",
                "category": "table",
                "coordinates": [
                    {"x": 0.1, "y": 0.2},
                    {"x": 0.5, "y": 0.2},
                    {"x": 0.5, "y": 0.3},
                    {"x": 0.1, "y": 0.3},
                ],
                "content": {"text": "| A | B |\n| --- | --- |\n| 1 | 2 |"},
                "words": [
                    {
                        "text": "A",
                        "coordinates": [
                            {"x": 0.1, "y": 0.2},
                            {"x": 0.12, "y": 0.2},
                            {"x": 0.12, "y": 0.22},
                            {"x": 0.1, "y": 0.22},
                        ],
                    },
                    {
                        "text": "B",
                        "coordinates": [
                            {"x": 0.2, "y": 0.2},
                            {"x": 0.22, "y": 0.2},
                            {"x": 0.22, "y": 0.22},
                            {"x": 0.2, "y": 0.22},
                        ],
                    },
                    {
                        "text": "1",
                        "coordinates": [
                            {"x": 0.1, "y": 0.26},
                            {"x": 0.12, "y": 0.26},
                            {"x": 0.12, "y": 0.28},
                            {"x": 0.1, "y": 0.28},
                        ],
                    },
                    {
                        "text": "2",
                        "coordinates": [
                            {"x": 0.2, "y": 0.26},
                            {"x": 0.22, "y": 0.26},
                            {"x": 0.22, "y": 0.28},
                            {"x": 0.2, "y": 0.28},
                        ],
                    },
                ],
            },
            {
                "id": "equation",
                "category": "equation",
                "coordinates": [
                    {"x": 0.1, "y": 0.4},
                    {"x": 0.5, "y": 0.4},
                    {"x": 0.5, "y": 0.5},
                    {"x": 0.1, "y": 0.5},
                ],
                "content": {"text": "\\operatorname*{lim}_{m\\rightarrow\\infty}"},
                "words": [
                    {
                        "text": "lim",
                        "coordinates": [
                            {"x": 0.1, "y": 0.4},
                            {"x": 0.14, "y": 0.4},
                            {"x": 0.14, "y": 0.42},
                            {"x": 0.1, "y": 0.42},
                        ],
                    },
                    {
                        "text": "m",
                        "coordinates": [
                            {"x": 0.15, "y": 0.45},
                            {"x": 0.17, "y": 0.45},
                            {"x": 0.17, "y": 0.47},
                            {"x": 0.15, "y": 0.47},
                        ],
                    },
                ],
            },
        ]
    }

    page = UpstageOcrEngine().to_insertable_page(raw, rendered_page())

    assert [element.overlay_mode for element in page.elements] == ["word", "row", "element"]
    assert page.elements[0].lines[0].words[0].bbox.x0 == 100.0
    assert page.elements[1].lines[0].text == "| A | B |"
    assert page.elements[2].lines[0].text == "\\operatorname*{lim}_{m\\rightarrow\\infty}"
