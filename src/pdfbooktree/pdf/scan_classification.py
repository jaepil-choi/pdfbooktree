"""문서 전체 단위로 native/scanned를 판정한다.

핵심 정의: scanned pdf는 표본 page 전부가 사실상 image이고
(scanned_page_fraction == 1.0), 그 위에 실제로 화면에 그려지는(visible) 문자가
전혀 없는(total_visible_chars_sampled == 0) 문서다. 문자가 추출되더라도
invisible render mode(OCR 검색용 overlay)라면 이 조건을 깨지 않는다.

두 조건 중 하나라도 어긋나면 native로 보고, 어떤 조건이 어떤 값 때문에
실패했는지 reject_reasons에 남긴다. 이 값은 batch 실행 시 CSV/JSONL report에
그대로 옮겨져서, 왜 특정 PDF가 scanned로 분류되지 않았는지 바로 확인할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from pdfbooktree.pdf.scan_signals import (
    DEFAULT_MAX_SAMPLE_PAGES,
    PageScanSignal,
    analyze_page,
    sample_page_indices,
)


@dataclass(frozen=True)
class ScanClassification:
    """문서 단위 native/scanned 판정 결과다."""

    page_count: int
    sampled_page_count: int
    scanned_page_fraction: float
    total_visible_chars_sampled: int
    total_invisible_chars_sampled: int
    is_scanned: bool
    reject_reasons: tuple[str, ...] = ()
    page_features: tuple[PageScanSignal, ...] = ()


def classify_scan(
    pdf_path: Path, max_sample_pages: int = DEFAULT_MAX_SAMPLE_PAGES
) -> ScanClassification:
    """PDF 전체를 sampling해 scanned 여부를 판정한다."""

    with fitz.open(pdf_path) as document:
        page_count = document.page_count
        indices = sample_page_indices(page_count, max_sample_pages)
        page_features = tuple(
            analyze_page(document.load_page(index)) for index in indices
        )

    scan_like_count = sum(1 for feature in page_features if feature.is_scan_like_page)
    scanned_page_fraction = (
        scan_like_count / len(page_features) if page_features else 0.0
    )
    total_visible_chars = sum(feature.visible_char_count for feature in page_features)
    total_invisible_chars = sum(
        feature.invisible_char_count for feature in page_features
    )

    fraction_ok = scanned_page_fraction == 1.0
    visible_chars_ok = total_visible_chars == 0
    is_scanned = fraction_ok and visible_chars_ok

    reject_reasons: list[str] = []
    if not fraction_ok:
        non_scan_like_count = len(page_features) - scan_like_count
        reject_reasons.append(
            f"scanned_page_fraction={scanned_page_fraction:.4f} != 1.0 "
            f"(non_scan_like_page_count={non_scan_like_count}/{len(page_features)})"
        )
    if not visible_chars_ok:
        pages_with_visible_text = sum(
            1 for feature in page_features if feature.visible_char_count > 0
        )
        reject_reasons.append(
            f"total_visible_chars_sampled={total_visible_chars} != 0 "
            f"(pages_with_visible_text_count={pages_with_visible_text})"
        )

    return ScanClassification(
        page_count=page_count,
        sampled_page_count=len(page_features),
        scanned_page_fraction=scanned_page_fraction,
        total_visible_chars_sampled=total_visible_chars,
        total_invisible_chars_sampled=total_invisible_chars,
        is_scanned=is_scanned,
        reject_reasons=tuple(reject_reasons),
        page_features=page_features,
    )
