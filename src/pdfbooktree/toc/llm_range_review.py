"""LLM per-page 판정으로 TOC page range를 검증/복구한다.

experiment 038에서 검증한 흐름을 패키지 코드로 옮긴 것이다. experiment 016의
3단계 fallback(start accept / backtrack / sequential)을 단순화해, LLM은 page별로
"이 한 page가 목차인가"만 판정하고 범위를 어디서 멈출지는 코드가 결정한다.

- anchor 탐색: detector start(seed)부터 앞으로 `max_anchor_scan` page까지 스캔해
  첫 목차 page를 anchor로 잡는다(seed가 없으면 page 1부터).
- 양방향 확장: anchor에서 forward/backward로 page를 한 칸씩 넓힌다.
  - forward는 스캔 OCR 책의 중간 오판을 건너뛰도록 `forward_gap_tolerance`만큼
    연속 non-TOC page를 관용한다.
  - backward는 brief contents 오염을 막으려고 관용 없이 첫 non-TOC에서 멈춘다.
- 수락 조건은 항상 `is_toc_page AND has_page_numbers`다. 페이지 번호 없이 제목·
  주소·메모만 나열한 목록은(예: 본문 페이지 번호 없는 Brief Contents) 목차로
  인정하지 않는다.

LLM은 Upstage Solar chat(solar-pro3) 텍스트 경로만 쓴다(IE는 과금이라 금지).
테스트나 재현을 위해 `chat_client`를 주입할 수 있다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pdfbooktree.config import LlmRangeReviewConfig
from pdfbooktree.models import TocDetectionResult, TocRangeReview
from pdfbooktree.pdf.text import extract_page_texts

if TYPE_CHECKING:
    from openai import OpenAI


def build_decision_schema() -> dict[str, Any]:
    """page별 TOC 판정용 json_schema response_format을 만든다."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "is_toc_page",
            "schema": {
                "type": "object",
                "properties": {
                    "is_toc_page": {
                        "type": "boolean",
                        "description": (
                            "이 페이지가 책의 목차(Table of Contents / 차례 / Contents)"
                            "또는 간략 목차(Brief Contents)의 일부이면 true."
                        ),
                    },
                    "has_page_numbers": {
                        "type": "boolean",
                        "description": (
                            "대부분의 줄에 본문 페이지 번호가 동반되면 true. "
                            "페이지 번호 없이 제목/주소/메모만 나열되면 false."
                        ),
                    },
                    "confidence": {
                        "type": "number",
                        "description": "판정 신뢰도(0~1).",
                    },
                    "reason": {
                        "type": "string",
                        "description": "판정 근거를 한국어로 한두 문장.",
                    },
                },
                "required": [
                    "is_toc_page",
                    "has_page_numbers",
                    "confidence",
                    "reason",
                ],
            },
        },
    }


class LlmTocRangeReviewer:
    """LLM per-page 판정으로 TOC page range를 보정한다."""

    def __init__(
        self,
        config: LlmRangeReviewConfig | None = None,
        *,
        chat_client: "OpenAI | None" = None,
    ) -> None:
        self.config = config or LlmRangeReviewConfig()
        self._chat_client = chat_client

    # ------------------------------------------------------------------ #
    # client
    # ------------------------------------------------------------------ #
    @property
    def chat_client(self) -> "OpenAI":
        if self._chat_client is None:
            import os

            from openai import OpenAI

            api_key = os.environ.get(self.config.api_key_env)
            if not api_key:
                raise RuntimeError(
                    f"환경변수 {self.config.api_key_env}가 설정되지 않았다."
                )
            kwargs: dict[str, Any] = {
                "api_key": api_key,
                "base_url": self.config.base_url,
            }
            if self.config.request_timeout is not None:
                kwargs["timeout"] = self.config.request_timeout
            self._chat_client = OpenAI(**kwargs)
        return self._chat_client

    # ------------------------------------------------------------------ #
    # public
    # ------------------------------------------------------------------ #
    def review(
        self,
        pdf_path: str | Path,
        detection: TocDetectionResult,
        total_pages: int,
    ) -> TocRangeReview:
        """결정적 detector 결과를 받아 per-page 판정으로 보정한다."""

        scan = min(self.config.scan_pages, total_pages)
        page_text = {
            page.pdf_page: page.text
            for page in extract_page_texts(Path(pdf_path), max_pages=scan)
        }
        state = _ReviewState(self, page_text, total_pages)

        anchor = state.find_anchor(detection.start_page)
        if anchor is None:
            return TocRangeReview(
                pages=[],
                start_page=None,
                end_page=None,
                anchor_page=None,
                stage="no_toc_range",
                method="llm_perpage_scan",
                llm_calls=state.call_count,
                decisions=state.trace,
            )

        start, end = state.grow_block(anchor)
        return TocRangeReview(
            pages=list(range(start, end + 1)),
            start_page=start,
            end_page=end,
            anchor_page=anchor,
            stage="forward_scan",
            method="llm_perpage_scan",
            llm_calls=state.call_count,
            decisions=state.trace,
        )

    # ------------------------------------------------------------------ #
    # low-level probe (state가 사용)
    # ------------------------------------------------------------------ #
    def _probe_call(self, pdf_page: int, snippet: str) -> dict[str, Any]:
        # experiment 038에서 검증한 user prompt 형식을 그대로 쓴다. 군더더기 마커를
        # 붙이면 OCR이 심하게 깨진 경계 page 판정이 흔들린다(kim_note1 page 3 등).
        user_prompt = (
            f"PDF page {pdf_page}의 텍스트다. 이 한 페이지가 목차 페이지인지 판정하라.\n\n"
            f"{snippet}"
        )
        response = self.chat_client.chat.completions.create(
            model=self.config.model,
            temperature=self.config.temperature,
            messages=[
                {"role": "system", "content": self.config.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=build_decision_schema(),
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)


class _ReviewState:
    """단일 review 호출 동안의 page text, 캐시, trace를 들고 다닌다."""

    def __init__(
        self,
        reviewer: LlmTocRangeReviewer,
        page_text: dict[int, str],
        total_pages: int,
    ) -> None:
        self.reviewer = reviewer
        self.config = reviewer.config
        self.page_text = page_text
        self.total_pages = total_pages
        self.cache: dict[int, dict[str, Any]] = {}
        self.trace: list[dict[str, Any]] = []
        self.call_count = 0

    def probe(self, pdf_page: int) -> dict[str, Any]:
        if pdf_page in self.cache:
            return self.cache[pdf_page]
        snippet = self.page_text.get(pdf_page, "")[: self.config.prompt_max_chars]
        # 빈 page는 LLM 호출 없이 비-목차로 처리한다.
        if not snippet.strip():
            decision = {
                "is_toc_page": False,
                "has_page_numbers": False,
                "confidence": 1.0,
                "reason": "빈 페이지",
            }
        else:
            decision = self.reviewer._probe_call(pdf_page, snippet)
            self.call_count += 1
        decision["pdf_page"] = pdf_page
        self.cache[pdf_page] = decision
        self.trace.append(
            {
                "pdf_page": pdf_page,
                "is_toc_page": bool(decision.get("is_toc_page")),
                "has_page_numbers": bool(decision.get("has_page_numbers")),
                "accepted": _is_accepted(decision),
                "confidence": decision.get("confidence"),
            }
        )
        return decision

    def accepted(self, pdf_page: int) -> bool:
        """목차의 필수 요건(목차 page AND 페이지 번호 동반)을 만족하는지 본다."""

        return _is_accepted(self.probe(pdf_page))

    # anchor 탐색: seed부터 앞으로 스캔 ---------------------------------- #
    def find_anchor(self, detector_start: int | None) -> int | None:
        page = max(1, detector_start or 1)
        steps = 0
        while page <= self.total_pages and steps < self.config.max_anchor_scan:
            if self.accepted(page):
                return page
            page += 1
            steps += 1
        return None

    # 양방향 contiguous 확장 -------------------------------------------- #
    def grow_block(self, anchor: int) -> tuple[int, int]:
        # forward: gap tolerance를 둬 스캔 OCR 중간 오판을 건너뛴다.
        end = anchor
        gap = 0
        page = anchor + 1
        span_limit = min(
            anchor + self.config.max_end_expand, self.total_pages, len(self.page_text)
        )
        while page <= span_limit:
            if self.accepted(page):
                end = page
                gap = 0
            else:
                gap += 1
                if gap > self.config.forward_gap_tolerance:
                    break
            page += 1

        # backward: 관용 없이 첫 non-TOC page에서 멈춘다(brief contents 오염 방지).
        start = anchor
        page = anchor - 1
        back_limit = max(1, anchor - self.config.max_backtrack)
        while page >= back_limit:
            if self.accepted(page):
                start = page
                page -= 1
            else:
                break
        return start, end


def _is_accepted(decision: dict[str, Any]) -> bool:
    """수락 조건: 목차 page이면서 페이지 번호가 동반될 때만 True."""

    return bool(decision.get("is_toc_page")) and bool(decision.get("has_page_numbers"))
