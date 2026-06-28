from __future__ import annotations

import json
from typing import Any

from pdfbooktree.models import TocVisualLine
from pdfbooktree.toc.staged_llm_extract import (
    SizeAwareStagedTocExtractor,
    annotate_page,
    assign_tier,
    cluster_height_cut_points,
    content_tier_to_level,
)


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


def test_height_tier_mapping_excludes_toc_heading() -> None:
    """목차 머리말은 level 매핑에서 제외하고 content tier만 level로 쓴다."""

    lines = [
        TocVisualLine(pdf_page=3, height=24.0, text="목차"),
        TocVisualLine(pdf_page=3, height=18.0, text="1장 선택의 기술"),
        TocVisualLine(pdf_page=3, height=8.0, text="비서 문제 12"),
        TocVisualLine(pdf_page=3, height=8.1, text="37퍼센트 규칙 18"),
    ]

    cuts = [22.0, 12.0]
    tiers = content_tier_to_level(lines, cuts)

    assert assign_tier(18.0, cuts) in tiers
    assert assign_tier(8.0, cuts) in tiers
    assert assign_tier(24.0, cuts) not in tiers
    assert sorted(tiers.values()) == [1, 2]


def test_height_clustering_finds_boundary_between_large_and_small_text() -> None:
    cuts = cluster_height_cut_points([17.8, 18.0, 18.2, 7.8, 8.0, 8.2])

    assert len(cuts) == 1
    assert 8.2 < cuts[0] < 17.8


def test_annotate_page_adds_tier_markers() -> None:
    lines = [
        TocVisualLine(pdf_page=7, height=18.0, text="1장 큰 제목"),
        TocVisualLine(pdf_page=7, height=8.0, text="작은 항목 10"),
    ]

    annotated = annotate_page(lines, 7, [12.0])

    assert "[T1] 1장 큰 제목" in annotated
    assert "[T2] 작은 항목 10" in annotated


def test_staged_extractor_uses_schema_then_page_extraction() -> None:
    """schema 결정 뒤 page별 추출을 호출하고 level은 tier 매핑으로 부여한다."""

    schema_response = json.dumps(
        {
            "levels": [
                {"level": 1, "name": "장", "cues": "T1", "examples": ["1장"]},
                {"level": 2, "name": "항목", "cues": "T2", "examples": ["비서 문제"]},
            ]
        }
    )
    page_response = json.dumps(
        {
            "items": [
                {"tier": 1, "title": "1장 선택의 기술", "printed_page": 1},
                {"tier": 2, "title": "비서 문제", "printed_page": 12},
                {"tier": 99, "title": "알 수 없는 tier", "printed_page": None},
                {"tier": 2, "title": "2장 순서의 기술", "printed_page": 30},
                {"tier": 2, "title": "치", "printed_page": None},
            ]
        }
    )
    fake = _FakeClient([schema_response, page_response])
    extractor = SizeAwareStagedTocExtractor(chat_client=fake)
    lines = [
        TocVisualLine(pdf_page=3, height=24.0, text="목차"),
        TocVisualLine(pdf_page=3, height=18.0, text="1장 선택의 기술"),
        TocVisualLine(pdf_page=3, height=17.8, text="2장 순서의 기술"),
        TocVisualLine(pdf_page=3, height=18.2, text="3장 예측의 기술"),
        TocVisualLine(pdf_page=3, height=8.0, text="비서 문제 12"),
        TocVisualLine(pdf_page=3, height=8.2, text="37퍼센트 규칙 16"),
        TocVisualLine(pdf_page=3, height=7.8, text="탐색과 이용 20"),
    ]

    items = extractor.extract_from_lines(lines, [3])

    assert [item.title for item in items] == [
        "1장 선택의 기술",
        "비서 문제",
        "알 수 없는 tier",
        "2장 순서의 기술",
    ]
    assert [item.level for item in items] == [1, 2, 2, 1]
    assert [item.printed_page for item in items] == [1, 12, None, 30]
    assert all(item.source_pdf_page == 3 for item in items)
    assert fake.calls[0]["response_format"]["json_schema"]["name"] == "hierarchy_schema"
    assert fake.calls[1]["response_format"]["json_schema"]["name"] == (
        "toc_page_extraction"
    )
    assert "T1=level 1" in fake.calls[0]["messages"][1]["content"]
