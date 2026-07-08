from __future__ import annotations

from pathlib import Path

import httpx

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

    assert [element.overlay_mode for element in page.elements] == [
        "word",
        "row",
        "element",
    ]
    assert page.elements[0].lines[0].words[0].bbox.x0 == 100.0
    assert page.elements[1].lines[0].text == "| A | B |"
    assert (
        page.elements[2].lines[0].text == "\\operatorname*{lim}_{m\\rightarrow\\infty}"
    )


def test_upstage_engine_loads_api_key_from_dotenv(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"elements": []}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured["client_kwargs"] = kwargs

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, **kwargs: object) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = kwargs["headers"]
            return FakeResponse()

    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("UPSTAGE_API_KEY=dotenv-key\n", encoding="utf-8")
    monkeypatch.setattr("pdfbooktree.ocr.engines.upstage.httpx.Client", FakeClient)

    response = UpstageOcrEngine().recognize_page(rendered_page())

    assert response == {"elements": []}
    assert captured["headers"] == {"Authorization": "Bearer dotenv-key"}


def test_upstage_engine_retries_transport_errors_with_exponential_wait(
    monkeypatch,
) -> None:
    attempts = {"count": 0}
    sleeps: list[float] = []

    class FakeResponse:
        status_code = 200
        headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"elements": [{"id": "ok"}]}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, **kwargs: object) -> FakeResponse:
            attempts["count"] += 1
            if attempts["count"] <= 3:
                raise httpx.RemoteProtocolError(
                    "Server disconnected without sending a response."
                )
            return FakeResponse()

    monkeypatch.setenv("UPSTAGE_API_KEY", "test-key")
    monkeypatch.setattr("pdfbooktree.ocr.engines.upstage.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "pdfbooktree.ocr.engines.upstage.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    response = UpstageOcrEngine({"max_retries": 3}).recognize_page(rendered_page())

    assert response == {"elements": [{"id": "ok"}]}
    assert attempts["count"] == 4
    assert sleeps == [2.0, 4.0, 8.0]
