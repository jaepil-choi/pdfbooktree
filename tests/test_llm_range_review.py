"""LLM 3단계 TOC range fallback을 검증한다.

live 호출 대신 page 번호로 스크립트된 fake chat client를 주입한다. 합성 PDF의 실제
텍스트 내용은 판정에 쓰이지 않고, fake client가 prompt의 page 번호만 보고 결정한다.
experiment 016에서 확인한 3단계 동작(accept / backtrack / sequential)과 brief
contents backward merge, contiguous end expansion을 격리 검증한다.
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


def _toc(start: bool = False) -> dict[str, object]:
    return {"is_toc_page": True, "is_toc_start": start, "reason": "toc"}


def _non() -> dict[str, object]:
    return {"is_toc_page": False, "is_toc_start": False, "reason": "non"}


class _FakeCompletions:
    def __init__(self, script: dict[int, dict[str, object]]) -> None:
        self.script = script
        self.asked_pages: list[int] = []

    def create(self, *, model, temperature, messages, response_format):
        content = messages[1]["content"]
        page = int(re.search(r"PDF의 (\d+)번째", content).group(1))
        self.asked_pages.append(page)
        decision = self.script.get(page, _non())
        message = SimpleNamespace(content=json.dumps(decision))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeChatClient:
    def __init__(self, script: dict[int, dict[str, object]]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(script))


def _reviewer(script: dict[int, dict[str, object]]) -> LlmTocRangeReviewer:
    config = LlmRangeReviewConfig(scan_pages=PAGE_COUNT, max_sequential=PAGE_COUNT)
    return LlmTocRangeReviewer(config, chat_client=_FakeChatClient(script))


def _detection(start: int | None) -> TocDetectionResult:
    pages = [start] if start is not None else []
    return TocDetectionResult(
        pages=pages,
        start_page=start,
        end_page=start,
        confidence=0.5,
        method="feature_vote_segment",
        candidates=[],
    )


def test_stage1_accept_with_brief_contents_merge(tmp_path: Path) -> None:
    """detector_start가 TOC 첫 page여도 backward merge로 brief contents를 흡수한다."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    # page 6이 상세 목차 시작, page 5는 brief contents, page 7-16 목차, 17은 비-TOC.
    script = {5: _toc(False), 6: _toc(True), 17: _non()}
    script.update({p: _toc(False) for p in range(7, 17)})
    script[4] = _non()

    review = _reviewer(script).review(pdf, _detection(6), PAGE_COUNT)

    assert review.stage == "stage1_accept"
    assert review.start_page == 5
    assert review.end_page == 16
    assert review.pages == list(range(5, 17))


def test_stage2_backtrack_recovers_full_range(tmp_path: Path) -> None:
    """detector가 TOC 중간 page만 잡으면 backtrack으로 시작 경계를 복구한다."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    # detector_start=10(TOC지만 첫 page 아님). 실제 TOC 7-11.
    script = {10: _toc(False), 9: _toc(False), 8: _toc(False), 7: _toc(True)}
    script.update({6: _non(), 11: _toc(False), 12: _non()})

    review = _reviewer(script).review(pdf, _detection(10), PAGE_COUNT)

    assert review.stage == "stage2_backtrack"
    assert review.start_page == 7
    assert review.end_page == 11
    assert review.pages == [7, 8, 9, 10, 11]


def test_stage3_sequential_recovery_on_wrong_segment(tmp_path: Path) -> None:
    """detector_start가 TOC가 아니면 page 1부터 순차 검토해 복구한다."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    # detector_start=3은 비-TOC. 실제 TOC 5-6.
    script = {3: _non(), 5: _toc(True), 6: _toc(False), 7: _non(), 4: _non()}

    review = _reviewer(script).review(pdf, _detection(3), PAGE_COUNT)

    assert review.stage == "stage3_sequential_recovery"
    assert review.pages == [5, 6]


def test_no_detector_candidate_goes_straight_to_sequential(tmp_path: Path) -> None:
    """detector 후보가 없으면 바로 sequential recovery로 간다."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    script = {8: _toc(True), 9: _non()}

    review = _reviewer(script).review(pdf, _detection(None), PAGE_COUNT)

    assert review.stage == "stage3_sequential_recovery"
    assert review.pages == [8]
    assert review.start_page == 8


def test_probe_results_are_cached(tmp_path: Path) -> None:
    """같은 page는 한 번만 LLM에 묻는다(캐시)."""

    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    script = {6: _toc(True), 5: _non(), 7: _non()}
    reviewer = _reviewer(script)

    review = reviewer.review(pdf, _detection(6), PAGE_COUNT)
    asked = reviewer.chat_client.chat.completions.asked_pages

    assert review.llm_calls == len(set(asked))
    assert len(asked) == len(set(asked))
