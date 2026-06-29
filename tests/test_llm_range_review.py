"""LLM per-page TOC range 보정을 검증한다.

live 호출 대신 page 번호로 스크립트된 fake chat client를 주입한다. 합성 PDF의 실제
텍스트 내용은 판정에 쓰이지 않고, fake client가 prompt의 page 번호만 보고 결정한다.
experiment 038에서 확인한 per-page 동작(seed forward 스캔 anchor, 양방향 확장,
has_page_numbers gate, forward gap tolerance, backward 엄격 stop)을 격리 검증한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import fitz

from pdfbooktree.config import LlmRangeReviewConfig
from pdfbooktree.models import TocDetectionResult
from pdfbooktree.toc.llm_range_review import LlmTocRangeReviewer

PAGE_COUNT = 22


def _make_pdf(path: Path, page_count: int = PAGE_COUNT) -> None:
    document = fitz.open()
    try:
        for index in range(page_count):
            page = document.new_page(width=595.0, height=842.0)
            page.insert_text((72.0, 72.0), f"page {index + 1} body text", fontsize=12)
        document.save(str(path))
    finally:
        document.close()


def _toc() -> dict[str, object]:
    """목차 page이면서 페이지 번호 동반 → 수락된다."""

    return {
        "is_toc_page": True,
        "has_page_numbers": True,
        "confidence": 0.9,
        "reason": "toc",
    }


def _toc_no_pagenum() -> dict[str, object]:
    """목차처럼 보이지만 페이지 번호가 없어 수락되지 않는다."""

    return {
        "is_toc_page": True,
        "has_page_numbers": False,
        "confidence": 0.8,
        "reason": "no page numbers",
    }


def _non() -> dict[str, object]:
    return {
        "is_toc_page": False,
        "has_page_numbers": False,
        "confidence": 0.9,
        "reason": "non",
    }


class _FakeCompletions:
    def __init__(self, script: dict[int, dict[str, object]]) -> None:
        self.script = script
        self.asked_pages: list[int] = []

    def create(self, *, model, temperature, messages, response_format):
        content = messages[1]["content"]
        page = int(re.search(r"PDF page (\d+)", content).group(1))
        self.asked_pages.append(page)
        decision = self.script.get(page, _non())
        message = SimpleNamespace(content=json.dumps(decision))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeChatClient:
    def __init__(self, script: dict[int, dict[str, object]]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(script))


def _reviewer(script: dict[int, dict[str, object]]) -> LlmTocRangeReviewer:
    config = LlmRangeReviewConfig(scan_pages=PAGE_COUNT, max_anchor_scan=PAGE_COUNT)
    return LlmTocRangeReviewer(config, chat_client=_FakeChatClient(script))


def _detection(start: int | None) -> TocDetectionResult:
    pages = [start] if start is not None else []
    return TocDetectionResult(
        pages=pages,
        start_page=start,
        end_page=start,
        confidence=0.5,
        method="ml_toc_page_classifier",
        candidates=[],
    )


def test_anchor_at_seed_with_brief_contents_merge(tmp_path: Path) -> None:
    """seed가 목차 page면 anchor로 잡고 backward merge로 brief contents를 흡수한다."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    # page 6이 상세 목차 시작, page 5는 brief contents(번호 동반), page 7-16 목차.
    script = {5: _toc(), 6: _toc(), 17: _non()}
    script.update({p: _toc() for p in range(7, 17)})
    script[4] = _non()

    review = _reviewer(script).review(pdf, _detection(6), PAGE_COUNT)

    assert review.stage == "forward_scan"
    assert review.anchor_page == 6
    assert review.start_page == 5
    assert review.end_page == 16
    assert review.pages == list(range(5, 17))


def test_anchor_found_by_forward_scan(tmp_path: Path) -> None:
    """detector start가 비-목차면 앞으로 스캔해 첫 목차 page를 anchor로 잡는다."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    # detector_start=3은 비-TOC. 실제 TOC 5-6.
    script = {3: _non(), 4: _non(), 5: _toc(), 6: _toc(), 7: _non()}

    review = _reviewer(script).review(pdf, _detection(3), PAGE_COUNT)

    assert review.stage == "forward_scan"
    assert review.anchor_page == 5
    assert review.pages == [5, 6]


def test_no_detector_candidate_starts_from_page_one(tmp_path: Path) -> None:
    """detector 후보가 없으면 page 1부터 forward 스캔한다."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    script = {8: _toc(), 9: _non()}

    review = _reviewer(script).review(pdf, _detection(None), PAGE_COUNT)

    assert review.stage == "forward_scan"
    assert review.pages == [8]
    assert review.start_page == 8


def test_page_without_page_numbers_is_rejected(tmp_path: Path) -> None:
    """is_toc_page=true여도 has_page_numbers=false면 목차로 인정하지 않는다."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    # page 6은 목차처럼 보이나 페이지 번호 없음 → 제외. 실제 목차는 7-9.
    script = {6: _toc_no_pagenum(), 7: _toc(), 8: _toc(), 9: _toc(), 10: _non()}

    review = _reviewer(script).review(pdf, _detection(6), PAGE_COUNT)

    assert review.anchor_page == 7
    assert review.start_page == 7  # backward가 page 6에서 엄격 stop
    assert review.pages == [7, 8, 9]


def test_forward_gap_tolerance_bridges_single_misjudgment(tmp_path: Path) -> None:
    """forward 확장은 스캔 OCR 중간 한 page 오판을 건너뛰어 이어 붙인다."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    # anchor=5, page 7만 오판으로 non, 양옆은 목차. page 9~ 연속 non이면 멈춘다.
    script = {5: _toc(), 6: _toc(), 7: _non(), 8: _toc(), 9: _non(), 10: _non()}
    script[4] = _non()

    review = _reviewer(script).review(pdf, _detection(5), PAGE_COUNT)

    assert review.start_page == 5
    assert review.end_page == 8  # page 7을 건너뛰고 8까지 포함
    assert review.pages == [5, 6, 7, 8]


def test_backward_expansion_stops_strictly(tmp_path: Path) -> None:
    """backward 확장은 관용 없이 첫 비-목차 page에서 멈춘다."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    # anchor=10. page 9는 non(엄격 stop), page 8은 목차지만 흡수하지 않는다.
    script = {10: _toc(), 9: _non(), 8: _toc(), 11: _non()}

    review = _reviewer(script).review(pdf, _detection(10), PAGE_COUNT)

    assert review.anchor_page == 10
    assert review.start_page == 10
    assert review.pages == [10]


def test_no_toc_range_when_nothing_accepted(tmp_path: Path) -> None:
    """스캔 범위 안에 수락되는 page가 없으면 빈 range를 돌려준다."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    script: dict[int, dict[str, object]] = {}  # 전부 default _non()

    review = _reviewer(script).review(pdf, _detection(3), PAGE_COUNT)

    assert review.stage == "no_toc_range"
    assert review.pages == []
    assert review.start_page is None
    assert review.anchor_page is None


def test_probe_results_are_cached(tmp_path: Path) -> None:
    """같은 page는 한 번만 LLM에 묻는다(캐시)."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    script = {6: _toc(), 5: _non(), 7: _non()}
    reviewer = _reviewer(script)

    review = reviewer.review(pdf, _detection(6), PAGE_COUNT)
    asked = reviewer.chat_client.chat.completions.asked_pages

    assert review.llm_calls == len(set(asked))
    assert len(asked) == len(set(asked))
