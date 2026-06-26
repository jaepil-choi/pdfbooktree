"""LLM 3단계 fallback으로 TOC page range를 검증/복구한다.

experiment 016에서 검증한 흐름을 패키지 코드로 옮긴 것이다. PRD §7.8~7.11(15.1)의
3단계 구조를 따른다.

- 1단계 start page accept: 결정적 detector의 시작 page S가 TOC 첫 page이면 accept.
- 2단계 backtrack_start: S가 TOC이지만 첫 page가 아니면 anchor로 삼고 backward merge한다.
- 3단계 sequential recovery: S가 TOC가 아니면(또는 detector 후보가 없으면) page 1부터
  순차 검토해 첫 TOC page를 anchor로 잡는다.

anchor를 정한 뒤 양방향 contiguous 확장(`grow_block`)으로 start/end를 정한다.
backward 확장은 brief contents 같은 인접 TOC segment를 merge한다.

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
            "name": "toc_page_decision",
            "schema": {
                "type": "object",
                "properties": {
                    "is_toc_page": {
                        "type": "boolean",
                        "description": (
                            "이 페이지가 책의 목차(Table of Contents / 차례 / Contents)"
                            "또는 간략 목차(Contents in brief)의 일부이면 true."
                        ),
                    },
                    "is_toc_start": {
                        "type": "boolean",
                        "description": (
                            "이 페이지가 목차가 시작되는 첫 페이지이면 true. "
                            "바로 앞 페이지는 목차가 아니어야 한다."
                        ),
                    },
                    "reason": {
                        "type": "string",
                        "description": "판정 근거를 한국어로 한두 문장.",
                    },
                },
                "required": ["is_toc_page", "is_toc_start", "reason"],
            },
        },
    }


class LlmTocRangeReviewer:
    """LLM 3단계 fallback으로 TOC page range를 보정한다."""

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

            from openai import OpenAI  # optional dependency라 호출 시점에 import

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
        """결정적 detector 결과를 받아 3단계 fallback으로 보정한다."""

        scan = min(self.config.scan_pages, total_pages)
        page_text = {
            page.pdf_page: page.text
            for page in extract_page_texts(Path(pdf_path), max_pages=scan)
        }
        state = _ReviewState(self, page_text, total_pages)

        anchor, stage = state.find_anchor(detection.start_page)
        if anchor is None:
            return TocRangeReview(
                pages=[],
                start_page=None,
                end_page=None,
                anchor_page=None,
                stage=stage,
                method="llm_3stage_fallback",
                llm_calls=state.call_count,
                decisions=state.trace,
            )

        start, end = state.grow_block(anchor)
        return TocRangeReview(
            pages=list(range(start, end + 1)),
            start_page=start,
            end_page=end,
            anchor_page=anchor,
            stage=stage,
            method="llm_3stage_fallback",
            llm_calls=state.call_count,
            decisions=state.trace,
        )

    # ------------------------------------------------------------------ #
    # low-level probe (state가 사용)
    # ------------------------------------------------------------------ #
    def _probe_call(self, pdf_page: int, snippet: str) -> dict[str, Any]:
        user_prompt = (
            f"다음은 PDF의 {pdf_page}번째 페이지(1-based) 텍스트다.\n"
            f"이 페이지가 목차 페이지인지 판정하라.\n\n"
            f"---PAGE {pdf_page} TEXT START---\n{snippet}\n---PAGE TEXT END---"
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
        decision = self.reviewer._probe_call(pdf_page, snippet)
        self.call_count += 1
        decision["pdf_page"] = pdf_page
        self.cache[pdf_page] = decision
        return decision

    # 3단계 anchor 탐색 -------------------------------------------------- #
    def find_anchor(self, detector_start: int | None) -> tuple[int | None, str]:
        scan_limit = min(self.config.max_sequential, self.total_pages)

        if detector_start is None:
            return self._sequential_recovery(scan_limit)

        s = self.probe(detector_start)
        self.trace.append({"stage": "probe_detector_start", **s})

        # 1단계: start page accept
        if s["is_toc_page"] and s["is_toc_start"]:
            return detector_start, "stage1_accept"
        # 2단계: S가 TOC이지만 첫 page가 아님 → anchor = S (backward merge가 경계 처리)
        if s["is_toc_page"]:
            return detector_start, "stage2_backtrack"
        # 3단계: sequential recovery
        return self._sequential_recovery(scan_limit)

    def _sequential_recovery(self, scan_limit: int) -> tuple[int | None, str]:
        for page in range(1, scan_limit + 1):
            d = self.probe(page)
            self.trace.append({"stage": "sequential", **d})
            if d["is_toc_page"]:
                return page, "stage3_sequential_recovery"
        return None, "stage3_failed"

    # 양방향 contiguous 확장 -------------------------------------------- #
    def grow_block(self, anchor: int) -> tuple[int, int]:
        start = anchor
        gap = 0
        page = anchor - 1
        while page >= 1 and page >= anchor - self.config.max_backtrack:
            d = self.probe(page)
            if d["is_toc_page"]:
                start = page
                gap = 0
            else:
                gap += 1
                if gap > self.config.end_gap_tolerance:
                    break
            page -= 1

        end = anchor
        gap = 0
        page = anchor + 1
        span_limit = min(
            anchor + self.config.max_end_expand, self.total_pages, len(self.page_text)
        )
        while page <= span_limit:
            d = self.probe(page)
            if d["is_toc_page"]:
                end = page
                gap = 0
            else:
                gap += 1
                if gap > self.config.end_gap_tolerance:
                    break
            page += 1
        return start, end
