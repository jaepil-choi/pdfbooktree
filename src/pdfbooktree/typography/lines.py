"""PDF span을 책 전체 visual line으로 재군집화한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Callable

import fitz

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import TypographyLine
from pdfbooktree.utils.text_normalize import normalize_text

_WORDISH = re.compile(r"[A-Za-z가-힣0-9]")


@dataclass(frozen=True)
class _Span:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    font: str
    flags: int

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)


def extract_typography_lines(
    pdf_path: Path,
    config: TypographyConfig | None = None,
    page_callback: Callable[[int, int], None] | None = None,
) -> list[TypographyLine]:
    """PDF 전체를 읽어 visual line 목록을 만든다."""

    resolved = config or TypographyConfig()
    lines: list[TypographyLine] = []
    with fitz.open(pdf_path) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            page_spans = _extract_page_spans(page)
            for group in _cluster_spans_by_y(
                page_spans, resolved.line_y_tolerance_ratio
            ):
                line = _build_line(page_index + 1, page.rect, group)
                if line is not None:
                    lines.append(line)
            if page_callback is not None:
                page_callback(page_index + 1, document.page_count)
    return lines


def _extract_page_spans(page: fitz.Page) -> list[_Span]:
    spans: list[_Span] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = normalize_text(str(span.get("text", "")))
                if not _is_content_text(text):
                    continue
                x0, y0, x1, y1 = [float(value) for value in span["bbox"]]
                spans.append(
                    _Span(
                        text=text,
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                        size=float(span.get("size", y1 - y0)),
                        font=str(span.get("font", "")),
                        flags=int(span.get("flags", 0)),
                    )
                )
    return spans


def _is_content_text(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped and _WORDISH.search(stripped))


def _cluster_spans_by_y(
    spans: list[_Span], tolerance_ratio: float
) -> list[list[_Span]]:
    if not spans:
        return []
    ordered = sorted(spans, key=lambda span: (span.center_y, span.x0))
    groups: list[list[_Span]] = []
    for span in ordered:
        if not groups:
            groups.append([span])
            continue
        current = groups[-1]
        current_center = median(item.center_y for item in current)
        current_height = max(median(item.height for item in current), 1.0)
        tolerance = max(1.5, current_height * tolerance_ratio)
        if abs(span.center_y - current_center) <= tolerance:
            current.append(span)
        else:
            groups.append([span])
    return groups


def _build_line(
    pdf_page: int, rect: fitz.Rect, spans: list[_Span]
) -> TypographyLine | None:
    content = sorted(spans, key=lambda span: span.x0)
    text = normalize_text(" ".join(span.text for span in content))
    if not text:
        return None
    return TypographyLine(
        pdf_page=pdf_page,
        text=text,
        x0=round(min(span.x0 for span in content), 2),
        y0=round(min(span.y0 for span in content), 2),
        x1=round(max(span.x1 for span in content), 2),
        y1=round(max(span.y1 for span in content), 2),
        page_width=round(float(rect.width), 2),
        page_height=round(float(rect.height), 2),
        font_size=round(float(median(span.size for span in content)), 2),
        height=round(float(median(span.height for span in content)), 2),
        is_bold=any(_span_is_bold(span) for span in content),
        font_names=tuple(sorted({span.font for span in content if span.font})),
    )


def _span_is_bold(span: _Span) -> bool:
    return bool(span.flags & 2**4) or "bold" in span.font.lower()
