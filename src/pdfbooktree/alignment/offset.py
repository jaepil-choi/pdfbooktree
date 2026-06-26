"""printed page number와 PDF page 사이의 offset을 추정한다.

experiment 015에서 검증한 로직을 그대로 옮긴다. 본문 page 상/하위 band의
page number 후보에서 `offset = pdf_page - book_page`를 모아 band별 최빈값을
구하고, 연속 run이 가장 긴 band를 고른다. clean(최빈 우세) 기준을 통과하지
못하면 fast-fail로 예외를 던지며, fallback은 두지 않는다.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from pdfbooktree.config import OffsetEstimationConfig
from pdfbooktree.models import BandPageNumber, OffsetEstimate
from pdfbooktree.pdf.page_numbers import extract_band_page_numbers


class OffsetEstimationError(Exception):
    """offset이 정해지지 않거나 결과가 clean하지 않을 때 던지는 예외다."""


def summarize_offsets(offsets: list[int]) -> dict[str, Any]:
    """offset 리스트에서 최빈값과 우세도 지표를 만든다."""

    if not offsets:
        return {
            "estimated_offset": None,
            "modal_count": 0,
            "second_count": 0,
            "total": 0,
            "modal_share": 0.0,
            "dominance_ratio": 0.0,
            "top_offsets": [],
        }
    counter = Counter(offsets)
    ranked = counter.most_common()
    estimated_offset, modal_count = ranked[0]
    second_count = ranked[1][1] if len(ranked) > 1 else 0
    total = len(offsets)
    # 2위가 없으면(단일 offset) 우세도는 무한대로 본다.
    dominance_ratio = float("inf") if second_count == 0 else modal_count / second_count
    return {
        "estimated_offset": estimated_offset,
        "modal_count": modal_count,
        "second_count": second_count,
        "total": total,
        "modal_share": round(modal_count / total, 3),
        "dominance_ratio": dominance_ratio,
        "top_offsets": [
            {"offset": offset, "count": count} for offset, count in ranked[:5]
        ],
    }


def longest_consecutive_run(offset: int, pages_with_offset: set[int]) -> int:
    """추정 offset과 일치하는 page가 연속으로 이어지는 최장 길이를 센다.

    page number는 1씩 증가하므로 같은 offset을 지지하는 연속 page run이 길수록
    실제 page number sequence일 가능성이 높다.
    """

    if not pages_with_offset:
        return 0
    best = 0
    current = 0
    previous: int | None = None
    for page in sorted(pages_with_offset):
        if previous is not None and page == previous + 1:
            current += 1
        else:
            current = 1
        best = max(best, current)
        previous = page
    return best


def _band_offsets(candidates: list[BandPageNumber], band: str) -> list[tuple[int, int]]:
    """band 후보에서 (pdf_page, offset) 쌍을 만든다."""

    pairs: list[tuple[int, int]] = []
    for candidate in candidates:
        if band != "all" and candidate.band != band:
            continue
        pairs.append((candidate.pdf_page, candidate.pdf_page - candidate.number))
    return pairs


def estimate_page_offset(
    pdf_path: Path | str,
    config: OffsetEstimationConfig | None = None,
) -> OffsetEstimate:
    """본문 page number로 printed-to-PDF offset을 추정한다.

    clean(최빈 우세) 기준을 통과하지 못하면 `OffsetEstimationError`를 던진다.
    fallback(LLM, 기본 offset 등)은 두지 않는다.
    """

    config = config or OffsetEstimationConfig()
    candidates = extract_band_page_numbers(pdf_path, config)
    if not candidates:
        raise OffsetEstimationError(
            f"page number 후보를 찾지 못해 offset을 추정할 수 없다: {pdf_path}"
        )

    # band별로 (pdf_page, offset) 쌍을 만들고 summarize + 최장 연속 run을 구한다.
    bands: dict[str, dict[str, Any]] = {}
    for band in ("all", "bottom", "top"):
        pairs = _band_offsets(candidates, band)
        summary = summarize_offsets([offset for _, offset in pairs])
        estimated = summary["estimated_offset"]
        pages_with_offset = {
            pdf_page for pdf_page, offset in pairs if offset == estimated
        }
        run = (
            longest_consecutive_run(estimated, pages_with_offset)
            if estimated is not None
            else 0
        )
        bands[band] = {
            "summary": summary,
            "run": run,
            "pages_with_offset": pages_with_offset,
        }

    # best band = (연속 run, 최빈 등장수)가 가장 큰 band. modal_share는 noise가
    # 분모를 키워 신뢰도를 왜곡하므로 선택 기준에서 뺀다(experiment 015와 동일).
    best_band = max(
        bands,
        key=lambda band: (bands[band]["run"], bands[band]["summary"]["modal_count"]),
    )
    best = bands[best_band]
    summary = best["summary"]
    estimated_offset = summary["estimated_offset"]
    modal_count = summary["modal_count"]
    dominance_ratio = summary["dominance_ratio"]

    # clean 게이트(최빈 우세). 통과 못 하면 fast-fail, fallback 없음.
    if (
        estimated_offset is None
        or modal_count < config.min_modal_count
        or dominance_ratio < config.min_dominance_ratio
    ):
        raise OffsetEstimationError(
            "offset 결과가 clean하지 않다: "
            f"band={best_band}, offset={estimated_offset}, "
            f"modal_count={modal_count}(min {config.min_modal_count}), "
            f"dominance_ratio={dominance_ratio}(min {config.min_dominance_ratio}), "
            f"run={best['run']}, candidates={len(candidates)}"
        )

    pages_with_offset = best["pages_with_offset"]
    consistent_evidence = [
        {
            "pdf_page": candidate.pdf_page,
            "number": candidate.number,
            "text": candidate.text,
            "band": candidate.band,
        }
        for candidate in candidates
        if (best_band == "all" or candidate.band == best_band)
        and candidate.pdf_page - candidate.number == estimated_offset
    ][:15]

    evidence: list[dict[str, Any]] = [
        {
            "best_band": best_band,
            "modal_count": modal_count,
            "second_count": summary["second_count"],
            "dominance_ratio": (
                dominance_ratio if dominance_ratio != float("inf") else None
            ),
            "max_consecutive_run": best["run"],
            "consistent_page_count": len(pages_with_offset),
            "candidate_count": len(candidates),
            "top_offsets": summary["top_offsets"],
            "printed_page_1_estimated_pdf_page": estimated_offset + 1,
        },
        *consistent_evidence,
    ]

    return OffsetEstimate(
        offset=estimated_offset,
        confidence=summary["modal_share"],
        evidence=evidence,
    )
