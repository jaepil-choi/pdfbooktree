"""OCR 결과에서 font/height hierarchy 추론용 통계를 만든다."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

import fitz

from pdfbooktree.ocr.models import InsertableOcrPage, OcrBox, OcrStatsResult
from pdfbooktree.utils.jsonio import to_jsonable


NUMBERING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\b")
CHAPTER_RE = re.compile(r"^\s*(chapter|part|appendix|제\s*\d+\s*장)\b", re.IGNORECASE)


def write_ocr_stats(
    insertable_pages: list[InsertableOcrPage],
    output_dir: Path,
    overlay_pdf: Path | None = None,
    *,
    include_word_stats: bool = False,
) -> OcrStatsResult:
    """OCR stats JSONL artifact를 저장한다."""

    output_dir.mkdir(parents=True, exist_ok=True)
    inserted_font_sizes = _extract_inserted_font_sizes(overlay_pdf, insertable_pages)
    line_rows = _build_line_rows(insertable_pages, inserted_font_sizes)
    element_rows = _build_element_rows(insertable_pages)
    page_rows = _build_page_rows(insertable_pages, line_rows)

    page_path = output_dir / "ocr_page_stats.jsonl"
    element_path = output_dir / "ocr_element_stats.jsonl"
    line_path = output_dir / "ocr_line_stats.jsonl"
    word_path = output_dir / "ocr_word_stats.jsonl" if include_word_stats else None

    _write_jsonl(page_path, page_rows)
    _write_jsonl(element_path, element_rows)
    _write_jsonl(line_path, line_rows)
    if word_path is not None:
        _write_jsonl(word_path, _build_word_rows(insertable_pages))

    return OcrStatsResult(
        page_stats_path=page_path,
        element_stats_path=element_path,
        line_stats_path=line_path,
        word_stats_path=word_path,
    )


def _build_line_rows(
    insertable_pages: list[InsertableOcrPage],
    inserted_font_sizes: dict[str, float | None],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in insertable_pages:
        sx = page.width_pt / page.width_px
        sy = page.height_pt / page.height_px
        for element in page.elements:
            for line_index, line in enumerate(element.lines):
                line_id = f"{page.pdf_page}:{element.element_id}:{line_index}"
                box_pt = _scale_box(line.bbox, sx, sy)
                word_heights = [word.bbox.height * sy for word in line.words]
                text = line.text
                rows.append(
                    {
                        "pdf_page": page.pdf_page,
                        "line_id": line_id,
                        "element_id": element.element_id,
                        "category": element.category,
                        "overlay_mode": element.overlay_mode,
                        "text": text,
                        "char_count": len(text),
                        "word_count": len(_tokens(text)),
                        "x0_pt": box_pt.x0,
                        "y0_pt": box_pt.y0,
                        "x1_pt": box_pt.x1,
                        "y1_pt": box_pt.y1,
                        "height_pt": box_pt.height,
                        "word_height_median_pt": (
                            float(median(word_heights)) if word_heights else None
                        ),
                        "word_height_max_pt": max(word_heights)
                        if word_heights
                        else None,
                        "inserted_font_size_median_pt": inserted_font_sizes.get(
                            line_id
                        ),
                        "y_center_ratio": _center_ratio(
                            box_pt.y0, box_pt.y1, page.height_pt
                        ),
                        "x_center_ratio": _center_ratio(
                            box_pt.x0, box_pt.x1, page.width_pt
                        ),
                        "numbering_depth": infer_numbering_depth(text),
                        "is_numeric_only": _is_numeric_only(text),
                    }
                )
    return rows


def _build_element_rows(
    insertable_pages: list[InsertableOcrPage],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in insertable_pages:
        sx = page.width_pt / page.width_px
        sy = page.height_pt / page.height_px
        for element in page.elements:
            box_pt = _scale_box(element.bbox, sx, sy)
            line_heights = [
                _scale_box(line.bbox, sx, sy).height for line in element.lines
            ]
            rows.append(
                {
                    "pdf_page": page.pdf_page,
                    "element_id": element.element_id,
                    "category": element.category,
                    "overlay_mode": element.overlay_mode,
                    "line_count": len(element.lines),
                    "word_count": sum(
                        len(_tokens(line.text)) for line in element.lines
                    ),
                    "char_count": len(element.content_text),
                    "bbox_height_pt": box_pt.height,
                    "bbox_width_pt": box_pt.width,
                    "line_height_median_pt": (
                        float(median(line_heights)) if line_heights else None
                    ),
                }
            )
    return rows


def _build_page_rows(
    insertable_pages: list[InsertableOcrPage],
    line_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_page: dict[int, list[dict[str, Any]]] = {}
    for row in line_rows:
        rows_by_page.setdefault(int(row["pdf_page"]), []).append(row)

    rows: list[dict[str, Any]] = []
    for page in insertable_pages:
        page_lines = rows_by_page.get(page.pdf_page, [])
        heights = [float(row["height_pt"]) for row in page_lines]
        inserted_sizes = [
            float(row["inserted_font_size_median_pt"])
            for row in page_lines
            if row["inserted_font_size_median_pt"] is not None
        ]
        category_counts = Counter(
            element.category or "unknown" for element in page.elements
        )
        large_cut = _quantile(heights, 0.9)
        rows.append(
            {
                "pdf_page": page.pdf_page,
                "line_count": len(page_lines),
                "word_count": sum(int(row["word_count"]) for row in page_lines),
                "char_count": sum(int(row["char_count"]) for row in page_lines),
                "line_height_min_pt": min(heights) if heights else None,
                "line_height_p25_pt": _quantile(heights, 0.25),
                "line_height_median_pt": _quantile(heights, 0.5),
                "line_height_p75_pt": _quantile(heights, 0.75),
                "line_height_p90_pt": large_cut,
                "line_height_max_pt": max(heights) if heights else None,
                "inserted_font_size_median_pt": (
                    float(median(inserted_sizes)) if inserted_sizes else None
                ),
                "inserted_font_size_max_pt": (
                    max(inserted_sizes) if inserted_sizes else None
                ),
                "large_line_count": (
                    sum(1 for row in page_lines if float(row["height_pt"]) >= large_cut)
                    if large_cut is not None
                    else 0
                ),
                "top_region_large_line_count": (
                    sum(
                        1
                        for row in page_lines
                        if large_cut is not None
                        and float(row["height_pt"]) >= large_cut
                        and float(row["y_center_ratio"]) <= 0.33
                    )
                ),
                "numeric_only_line_count": sum(
                    1 for row in page_lines if bool(row["is_numeric_only"])
                ),
                "category_counts": dict(sorted(category_counts.items())),
            }
        )
    return rows


def _build_word_rows(insertable_pages: list[InsertableOcrPage]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in insertable_pages:
        sx = page.width_pt / page.width_px
        sy = page.height_pt / page.height_px
        for element in page.elements:
            for line_index, line in enumerate(element.lines):
                line_id = f"{page.pdf_page}:{element.element_id}:{line_index}"
                for word in line.words:
                    box_pt = _scale_box(word.bbox, sx, sy)
                    rows.append(
                        {
                            "pdf_page": page.pdf_page,
                            "element_id": element.element_id,
                            "line_id": line_id,
                            "text": word.text,
                            "x0_pt": box_pt.x0,
                            "y0_pt": box_pt.y0,
                            "x1_pt": box_pt.x1,
                            "y1_pt": box_pt.y1,
                            "height_pt": box_pt.height,
                        }
                    )
    return rows


def _extract_inserted_font_sizes(
    overlay_pdf: Path | None,
    insertable_pages: list[InsertableOcrPage],
) -> dict[str, float | None]:
    if overlay_pdf is None or not overlay_pdf.exists():
        return {}

    sizes: dict[str, float | None] = {}
    with fitz.open(overlay_pdf) as document:
        for page_model in insertable_pages:
            if page_model.pdf_page > document.page_count:
                continue
            page = document.load_page(page_model.pdf_page - 1)
            spans = _extract_page_spans(page)
            sx = page_model.width_pt / page_model.width_px
            sy = page_model.height_pt / page_model.height_px
            for element in page_model.elements:
                for line_index, line in enumerate(element.lines):
                    line_id = f"{page_model.pdf_page}:{element.element_id}:{line_index}"
                    rect = _scale_box(line.bbox, sx, sy)
                    matched_sizes = [
                        span["size"]
                        for span in spans
                        if rect.x0 <= span["cx"] <= rect.x1
                        and rect.y0 <= span["cy"] <= rect.y1
                    ]
                    sizes[line_id] = (
                        float(median(matched_sizes)) if matched_sizes else None
                    )
    return sizes


def _extract_page_spans(page: fitz.Page) -> list[dict[str, float]]:
    spans: list[dict[str, float]] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                x0, y0, x1, y1 = span.get("bbox", (0, 0, 0, 0))
                spans.append(
                    {
                        "cx": (float(x0) + float(x1)) / 2,
                        "cy": (float(y0) + float(y1)) / 2,
                        "size": float(span.get("size", 0.0)),
                    }
                )
    return spans


def infer_numbering_depth(text: str) -> int:
    """heading 후보 feature로 쓸 간단한 numbering depth를 계산한다."""

    stripped = text.strip()
    if _is_numeric_only(stripped):
        return 0
    if CHAPTER_RE.match(stripped):
        return 1
    match = NUMBERING_RE.match(stripped)
    if not match:
        return -1
    return len(match.group(1).split("."))


def _is_numeric_only(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and bool(re.fullmatch(r"[\d\s.·-]+", stripped))


def _tokens(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def _scale_box(box: OcrBox, sx: float, sy: float) -> OcrBox:
    return OcrBox(box.x0 * sx, box.y0 * sy, box.x1 * sx, box.y1 * sy)


def _center_ratio(start: float, end: float, total: float) -> float:
    return ((start + end) / 2) / total if total else 0.0


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(to_jsonable(row), ensure_ascii=False) + "\n" for row in rows
        ),
        encoding="utf-8",
    )
