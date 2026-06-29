from __future__ import annotations

import json
from typing import Any

from pdfbooktree.config import LlmTocExtractionConfig
from pdfbooktree.models import PdfPageText
from pdfbooktree.toc.llm_extract import LlmTocExtractor, build_toc_schema


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, parent: "_FakeClient") -> None:
        self._parent = parent

    def create(self, **kwargs: Any) -> _FakeCompletion:
        self._parent.calls.append(kwargs)
        content = self._parent.responses[self._parent.index]
        self._parent.index += 1
        return _FakeCompletion(content)


class _FakeChat:
    def __init__(self, parent: "_FakeClient") -> None:
        self.completions = _FakeCompletions(parent)


class _FakeClient:
    """openai client를 흉내내 호출 kwargs를 기록하고 정해진 응답을 돌려준다."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.index = 0
        self.calls: list[dict[str, Any]] = []
        self.chat = _FakeChat(self)


def _page(pdf_page: int, lines: list[str]) -> PdfPageText:
    text = "\n".join(lines)
    return PdfPageText(pdf_page=pdf_page, text=text, lines=lines, char_count=len(text))


def test_extract_from_pages_builds_toc_items() -> None:
    response = json.dumps(
        {
            "is_toc_page": True,
            "items": [
                {
                    "title": "Chapter 1 Introduction",
                    "level": 1,
                    "printed_page": 3,
                    "source_pdf_page": 5,
                },
                {
                    "title": "1.1 Motivation",
                    "level": 2,
                    "printed_page": 7,
                    "source_pdf_page": 5,
                },
            ]
        }
    )
    extractor = LlmTocExtractor(chat_client=_FakeClient([response]))
    pages = [_page(5, ["Chapter 1 Introduction 3", "1.1 Motivation 7"])]

    items = extractor.extract_from_pages(pages)

    assert [it.title for it in items] == ["Chapter 1 Introduction", "1.1 Motivation"]
    assert [it.level for it in items] == [1, 2]
    assert [it.printed_page for it in items] == [3, 7]
    assert all(it.source_pdf_page == 5 for it in items)
    assert all(it.confidence == 0.8 for it in items)


def test_null_printed_page_becomes_none() -> None:
    response = json.dumps(
        {
            "is_toc_page": True,
            "items": [{"title": "찾아보기", "level": 1, "printed_page": None}],
        }
    )
    extractor = LlmTocExtractor(chat_client=_FakeClient([response]))

    items = extractor.extract_from_pages([_page(5, ["찾아보기"])])

    assert len(items) == 1
    assert items[0].printed_page is None


def test_invalid_source_page_falls_back_to_first_toc_page() -> None:
    response = json.dumps(
        {
            "is_toc_page": True,
            "items": [
                {
                    "title": "Preface",
                    "level": 1,
                    "printed_page": 1,
                    "source_pdf_page": 999,
                }
            ]
        }
    )
    extractor = LlmTocExtractor(chat_client=_FakeClient([response]))

    items = extractor.extract_from_pages([_page(6, ["Preface"]), _page(7, ["x"])])

    # source_pdf_page 999는 입력 page에 없으므로 가장 앞 TOC page(6)로 보정한다.
    assert items[0].source_pdf_page == 6


def test_items_without_title_are_dropped() -> None:
    response = json.dumps(
        {
            "is_toc_page": True,
            "items": [
                {"title": "", "level": 1, "printed_page": 1},
                {"title": "Real", "level": 1, "printed_page": 2},
            ]
        }
    )
    extractor = LlmTocExtractor(chat_client=_FakeClient([response]))

    items = extractor.extract_from_pages([_page(5, ["x"])])

    assert [it.title for it in items] == ["Real"]


def test_non_toc_page_response_is_skipped() -> None:
    response = json.dumps({"is_toc_page": False, "items": [{"title": "Noise"}]})
    extractor = LlmTocExtractor(chat_client=_FakeClient([response]))

    items = extractor.extract_from_pages([_page(5, ["List of Pages", "x"])])

    assert items == []


def test_config_controls_model_and_hyperparameters() -> None:
    response = json.dumps({"is_toc_page": True, "items": []})
    fake = _FakeClient([response])
    config = LlmTocExtractionConfig(
        text_model="solar-pro3",
        temperature=0.4,
        max_completion_tokens=2048,
    )
    extractor = LlmTocExtractor(config, chat_client=fake)

    extractor.extract_from_pages([_page(5, ["x"])])

    call = fake.calls[0]
    assert call["model"] == "solar-pro3"
    assert call["temperature"] == 0.4
    assert call["max_tokens"] == 2048
    assert call["response_format"]["json_schema"]["name"] == "toc_extraction"


def test_text_schema_allows_null_page_image_schema_does_not() -> None:
    text_schema = build_toc_schema(nullable_page=True, include_source_page=True)
    image_schema = build_toc_schema(nullable_page=False, include_source_page=False)

    text_props = text_schema["json_schema"]["schema"]["properties"]["items"]["items"][
        "properties"
    ]
    text_top_props = text_schema["json_schema"]["schema"]["properties"]
    image_props = image_schema["json_schema"]["schema"]["properties"]["items"]["items"][
        "properties"
    ]

    assert text_top_props["is_toc_page"]["type"] == "boolean"
    assert "is_toc_page" in text_schema["json_schema"]["schema"]["required"]
    assert text_props["printed_page"]["type"] == ["integer", "null"]
    assert image_props["printed_page"]["type"] == "integer"
    assert "source_pdf_page" in text_props
    assert "source_pdf_page" not in image_props
