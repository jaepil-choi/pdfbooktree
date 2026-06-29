from __future__ import annotations

import json
from typing import Any

from pdfbooktree.models import TocVisualLine
from pdfbooktree.toc.staged_llm_extract import (
    ClusteredTocLine,
    SizeAwareStagedTocExtractor,
    annotate_page,
    assign_tier,
    build_clusters,
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
        TocVisualLine(pdf_page=7, height=18.0, text="1장 큰 제목", x1=72.0),
        TocVisualLine(pdf_page=7, height=8.0, text="작은 <항목> '10'", x1=96.5),
    ]

    annotated = annotate_page(lines, 7, [12.0])

    assert '<T1 x1="72.0">1장 큰 제목</T1>' in annotated
    assert "<T2 x1=\"96.5\">작은 &lt;항목&gt; '10'</T2>" in annotated


def test_build_clusters_keeps_visual_signals_separate() -> None:
    """height와 indent column을 함께 써서 content 줄을 signature cluster로 묶는다."""

    lines = [
        ClusteredTocLine(
            pdf_page=3,
            text="Chapter 1 Introduction",
            height=18.0,
            title_x=72.0,
            page_width=600.0,
            is_bold=True,
            font_type="times",
            trailing_page=1,
        ),
        ClusteredTocLine(
            pdf_page=3,
            text="1.1 Motivation",
            height=9.0,
            title_x=96.0,
            page_width=600.0,
            is_bold=False,
            font_type="times",
            trailing_page=3,
        ),
        ClusteredTocLine(
            pdf_page=3,
            text="1.2 Scope",
            height=9.1,
            title_x=96.5,
            page_width=600.0,
            is_bold=False,
            font_type="times",
            trailing_page=4,
        ),
    ]

    line_cluster, clusters, debug = build_clusters(lines)

    assert len(clusters) == 2
    assert line_cluster[1] == line_cluster[2]
    assert line_cluster[0] != line_cluster[1]
    assert debug["n_clusters"] == 2


def test_staged_extractor_uses_cluster_order_split_then_correction() -> None:
    """클러스터 순서 결정 뒤 level marker 추출과 제목 교정을 순서대로 호출한다."""

    cluster_response = json.dumps(
        {
            "clusters": [
                {"cluster_id": 0, "level": 1},
                {"cluster_id": 1, "level": 2},
            ]
        }
    )
    split_response = json.dumps(
        {
            "items": [
                {"level": 1, "title": "1장선택의기술", "printed_page": 1},
                {"level": 2, "title": "비서 문제", "printed_page": 12},
                {"level": 2, "title": "치", "printed_page": None},
            ]
        }
    )
    correction_response = json.dumps({"titles": ["1장 선택의 기술", "비서 문제"]})
    fake = _FakeClient([cluster_response, split_response, correction_response])
    extractor = SizeAwareStagedTocExtractor(chat_client=fake)
    lines = [
        ClusteredTocLine(
            pdf_page=3,
            text="목차",
            height=24.0,
            title_x=72.0,
            page_width=600.0,
            is_bold=True,
            font_type="gothic",
            trailing_page=None,
        ),
        ClusteredTocLine(
            pdf_page=3,
            text="1장선택의기술 1",
            height=18.0,
            title_x=72.0,
            page_width=600.0,
            is_bold=True,
            font_type="gothic",
            trailing_page=1,
        ),
        ClusteredTocLine(
            pdf_page=3,
            text="비서 문제 12",
            height=8.0,
            title_x=96.0,
            page_width=600.0,
            is_bold=False,
            font_type="gothic",
            trailing_page=12,
        ),
    ]

    items = extractor.extract_from_clustered_lines(lines, [3])

    assert [item.title for item in items] == ["1장 선택의 기술", "비서 문제"]
    assert [item.level for item in items] == [1, 2]
    assert [item.printed_page for item in items] == [1, 12]
    assert all(item.source_pdf_page == 3 for item in items)
    assert fake.calls[0]["response_format"]["json_schema"]["name"] == "cluster_levels"
    assert fake.calls[1]["response_format"]["json_schema"]["name"] == "toc_split"
    assert fake.calls[2]["response_format"]["json_schema"]["name"] == (
        "toc_title_correction"
    )
    assert "클러스터 목록" in fake.calls[0]["messages"][1]["content"]
    assert "[L1]" in fake.calls[1]["messages"][1]["content"]


def test_staged_extractor_returns_empty_when_page_extraction_has_no_items() -> None:
    """page별 추출 결과가 비면 제목 교정을 호출하지 않고 빈 결과를 반환한다."""

    cluster_response = json.dumps({"clusters": [{"cluster_id": 0, "level": 1}]})
    split_response = json.dumps({"items": []})
    fake = _FakeClient([cluster_response, split_response])
    extractor = SizeAwareStagedTocExtractor(chat_client=fake)
    lines = [
        TocVisualLine(pdf_page=3, height=18.0, text="광고 문구", x1=72.0),
    ]

    items = extractor.extract_from_lines(lines, [3])

    assert items == []
    assert len(fake.calls) == 2
