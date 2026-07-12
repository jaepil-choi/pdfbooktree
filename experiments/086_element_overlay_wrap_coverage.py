"""experiment 086: element overlay_mode 텍스트 손실을 폭 기반 wrap으로 고칠 수 있는지 검증한다.

showcase 014에서 확인된 문제: overlay_mode="element" fallback은 문단/표 전체를
단 하나의 InsertableOcrLine으로 만들고, insertion.py는 이를 폭 제한 없이 한 줄로
써서 element bbox 폭을 크게 넘어선다. PyMuPDF get_text()는 page rect 밖 glyph를
추출하지 않으므로 넘친 부분이 통째로 사라진다(실측 커버리지 44.3%).

이 실험은 이미 완료된 showcase 014의 insertable cache(API 재호출 없음)를 그대로 써서
1) baseline(현재 write_overlay_pdf)과
2) element 모드 line만 bbox 폭에 맞춰 word-wrap하는 변형
을 같은 원본 PDF에 적용하고, get_text() 커버리지·시각적 회귀·중복 추출 여부를 비교한다.

실행:
    uv run python experiments/086_element_overlay_wrap_coverage.py
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

import fitz

from pdfbooktree.ocr.cache import insertable_page_from_json
from pdfbooktree.ocr.insertion import (
    _load_overlay_font,
    _page_relative_font_size_bounds,
    _scale_rect,
    _strip_text_objects,
    write_overlay_pdf,
)
from pdfbooktree.ocr.models import InsertableOcrPage

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "086_element_overlay_wrap_coverage"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID

SOURCE_PDF = (
    ROOT_DIR
    / "data"
    / "scanned-pdf-not-indexed"
    / "수리통계학(개정판)-김우철_upocr_merged.pdf"
)
ARTIFACT_DIR = (
    ROOT_DIR / "showcase" / "outputs" / "014_ocr_overlay_math_statistics" / "artifacts"
)

KNOWN_WORST_PAGES = [1, 122, 123, 124, 126, 457]
LINE_SPACING_FACTOR = 1.15
MIN_WRAP_WIDTH_PT = 20.0
MAX_WRAP_ITER = 8


# ---------------------------------------------------------------------------
# cache 로딩 (081과 동일 패턴, page당 중복 cache는 최신 mtime을 채택)
# ---------------------------------------------------------------------------


def load_insertable_pages_deduped(artifact_dir: Path) -> list[InsertableOcrPage]:
    cache_dir = artifact_dir / "document_parse_cache" / "insertable"
    by_page: dict[int, tuple[float, InsertableOcrPage]] = {}
    for path in cache_dir.glob("*.json"):
        page = insertable_page_from_json(json.loads(path.read_text(encoding="utf-8")))
        mtime = path.stat().st_mtime
        existing = by_page.get(page.pdf_page)
        if existing is None or mtime > existing[0]:
            by_page[page.pdf_page] = (mtime, page)
    return [by_page[key][1] for key in sorted(by_page)]


# ---------------------------------------------------------------------------
# Arm B: element 모드 line만 bbox 폭 기준 word-wrap
# ---------------------------------------------------------------------------


def _wrap_words_to_width(
    font: fitz.Font, words: list[str], wrap_width: float, font_size: float
) -> list[str]:
    space_width = font.text_length(" ", fontsize=font_size) or font_size * 0.25
    lines: list[list[str]] = []
    current: list[str] = []
    current_width = 0.0
    for word in words:
        word_width = font.text_length(word, fontsize=font_size)
        candidate_width = (
            word_width if not current else current_width + space_width + word_width
        )
        if current and candidate_width > wrap_width:
            lines.append(current)
            current = [word]
            current_width = word_width
        else:
            current.append(word)
            current_width = candidate_width
    if current:
        lines.append(current)
    return [" ".join(line) for line in lines]


def _fit_element_text(
    font: fitz.Font,
    text: str,
    rect: fitz.Rect,
    page_rect: fitz.Rect,
    min_font_size: float,
    max_font_size: float,
) -> tuple[list[str], float]:
    words = text.split()
    if not words:
        return [], min_font_size

    wrap_width = max(
        MIN_WRAP_WIDTH_PT, min(rect.width, page_rect.width - rect.x0 - 2.0)
    )
    font_size = max(min_font_size, min(max_font_size, rect.height * 0.88))
    lines = _wrap_words_to_width(font, words, wrap_width, font_size)
    for _ in range(MAX_WRAP_ITER):
        required_height = len(lines) * font_size * LINE_SPACING_FACTOR
        if required_height <= rect.height or font_size <= min_font_size:
            break
        # 폭 wrap 결과가 bbox 높이를 넘으면 font_size를 단조 감소시켜 재수렴한다.
        # rect.height/len(lines)*0.88처럼 매 반복 재계산하면 line 수가 font_size에
        # 따라 크게 튀어 진동(oscillation)할 수 있어, 항상 줄어드는 방향으로만 조정한다.
        shrunk_font_size = max(
            min_font_size, font_size * (rect.height / required_height)
        )
        if shrunk_font_size >= font_size:
            break
        font_size = shrunk_font_size
        lines = _wrap_words_to_width(font, words, wrap_width, font_size)
    return lines, font_size


def _insert_invisible_lines_wrapped(
    document: fitz.Document,
    insertable_pages: list[InsertableOcrPage],
) -> None:
    font = _load_overlay_font()
    for page_model in insertable_pages:
        if page_model.pdf_page < 1 or page_model.pdf_page > document.page_count:
            continue

        page = document[page_model.pdf_page - 1]
        writer = fitz.TextWriter(page.rect)
        min_font_size, max_font_size = _page_relative_font_size_bounds(page.rect.height)
        inserted_on_page = 0

        for element in page_model.elements:
            for line in element.lines:
                text = " ".join(line.text.split())
                if not text:
                    continue

                rect = _scale_rect(
                    line.bbox,
                    page_rect=page.rect,
                    width_px=page_model.width_px,
                    height_px=page_model.height_px,
                )

                if element.overlay_mode != "element":
                    font_size = max(
                        min_font_size, min(max_font_size, rect.height * 0.88)
                    )
                    writer.append(
                        (rect.x0, rect.y1), text, font=font, fontsize=font_size
                    )
                    inserted_on_page += 1
                    continue

                wrapped_lines, font_size = _fit_element_text(
                    font, text, rect, page.rect, min_font_size, max_font_size
                )
                line_height = font_size * LINE_SPACING_FACTOR
                for index, wrapped_text in enumerate(wrapped_lines):
                    baseline_y = rect.y0 + (index + 1) * line_height
                    writer.append(
                        (rect.x0, baseline_y),
                        wrapped_text,
                        font=font,
                        fontsize=font_size,
                    )
                    inserted_on_page += 1

        if inserted_on_page:
            writer.write_text(page, overlay=True, render_mode=3)


def write_overlay_pdf_wrapped(
    insertable_pages: list[InsertableOcrPage],
    source_pdf: Path,
    output_pdf: Path,
    temp_dir: Path,
) -> None:
    if output_pdf.exists():
        output_pdf.unlink()
    temp_dir.mkdir(parents=True, exist_ok=True)
    stripped_pdf = temp_dir / "source_text_stripped.pdf"

    target_pages = {page.pdf_page for page in insertable_pages}
    _strip_text_objects(source_pdf, stripped_pdf, target_pages)
    document = fitz.open(stripped_pdf)
    try:
        _insert_invisible_lines_wrapped(document, insertable_pages)
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        document.save(
            output_pdf,
            garbage=4,
            deflate=True,
            deflate_fonts=True,
            use_objstms=1,
            compression_effort=100,
        )
    finally:
        document.close()


# ---------------------------------------------------------------------------
# 측정
# ---------------------------------------------------------------------------


def ocr_reported_char_counts(pages: list[InsertableOcrPage]) -> dict[int, int]:
    return {
        page.pdf_page: sum(
            len(line.text) for element in page.elements for line in element.lines
        )
        for page in pages
    }


def extracted_char_counts(pdf_path: Path, page_numbers: list[int]) -> dict[int, int]:
    counts: dict[int, int] = {}
    with fitz.open(pdf_path) as document:
        for pdf_page in page_numbers:
            counts[pdf_page] = len(document[pdf_page - 1].get_text())
    return counts


def render_hash(pdf_path: Path, pdf_page: int) -> str:
    with fitz.open(pdf_path) as document:
        png = document[pdf_page - 1].get_pixmap(dpi=144, alpha=False).tobytes("png")
    return hashlib.sha256(png).hexdigest()


def summarize_arm(
    name: str,
    output_pdf: Path,
    reported: dict[int, int],
    elapsed_sec: float,
) -> dict[str, object]:
    page_numbers = sorted(reported)
    extracted = extracted_char_counts(output_pdf, page_numbers)

    total_reported = sum(reported.values())
    total_extracted = sum(extracted.values())

    per_page_coverage = {
        page: (extracted[page] / reported[page] if reported[page] else 1.0)
        for page in page_numbers
    }
    below_80 = sum(1 for cov in per_page_coverage.values() if cov < 0.8)
    below_50 = sum(1 for cov in per_page_coverage.values() if cov < 0.5)
    over_extract = sum(
        1
        for page in page_numbers
        if reported[page] > 0 and extracted[page] > reported[page] * 1.5
    )

    return {
        "arm": name,
        "output_pdf": str(output_pdf.relative_to(ROOT_DIR)),
        "elapsed_sec": round(elapsed_sec, 2),
        "output_bytes": output_pdf.stat().st_size,
        "total_reported_chars": total_reported,
        "total_extracted_chars": total_extracted,
        "overall_coverage": round(total_extracted / total_reported, 4)
        if total_reported
        else None,
        "pages_below_80pct": below_80,
        "pages_below_50pct": below_50,
        "pages_with_suspected_duplication": over_extract,
        "known_worst_pages": {
            page: {
                "reported_chars": reported[page],
                "extracted_chars": extracted[page],
                "coverage": round(per_page_coverage[page], 4),
            }
            for page in KNOWN_WORST_PAGES
            if page in reported
        },
    }


def record_experiment(summary: dict[str, object]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "showcase 014에서 확인된 overlay_mode='element' fallback의 텍스트 커버리지 손실"
            "(44.3%)을 element line만 bbox 폭 기준 word-wrap하는 방식으로 고칠 수 있는지, "
            "API 재호출 없이 기존 insertable cache로 baseline과 비교 검증한다."
        ),
        "inputs": [
            str(SOURCE_PDF.relative_to(ROOT_DIR)),
            str(ARTIFACT_DIR.relative_to(ROOT_DIR)),
        ],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "showcase 014 insertable cache(pdf_page 중복은 최신 mtime 채택, 637쪽)를 그대로 "
            "불러와 baseline(write_overlay_pdf)과 element line word-wrap 변형"
            "(write_overlay_pdf_wrapped)에 각각 적용한 뒤, get_text() 문자수 대비 OCR 보고 "
            "문자수 커버리지, 시각 회귀(pixel hash), 중복 추출 의심 page 수를 비교했다."
        ),
        "summary": summary,
        "finding": summary["finding"],
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"] = [
        item for item in data["experiments"] if item.get("id") != EXPERIMENT_ID
    ] + [entry]
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    insertable_pages = load_insertable_pages_deduped(ARTIFACT_DIR)
    with fitz.open(SOURCE_PDF) as document:
        source_page_count = document.page_count

    page_numbers = [page.pdf_page for page in insertable_pages]
    expected_pages = list(range(1, source_page_count + 1))
    if page_numbers != expected_pages:
        raise RuntimeError(
            f"insertable cache가 source 전체와 일치하지 않는다: "
            f"loaded={len(page_numbers)}, source={source_page_count}"
        )

    reported = ocr_reported_char_counts(insertable_pages)

    sample_visual_pages = [1, 2, 457, source_page_count]
    before_hashes = {
        page: render_hash(SOURCE_PDF, page) for page in sample_visual_pages
    }

    output_pdf_a = OUTPUT_DIR / "arm_a_baseline.pdf"
    started_a = time.monotonic()
    write_overlay_pdf(
        insertable_pages, SOURCE_PDF, output_pdf_a, OUTPUT_DIR / "_overlay_pages_a"
    )
    elapsed_a = time.monotonic() - started_a
    arm_a = summarize_arm("baseline", output_pdf_a, reported, elapsed_a)

    output_pdf_b = OUTPUT_DIR / "arm_b_wrapped.pdf"
    started_b = time.monotonic()
    write_overlay_pdf_wrapped(
        insertable_pages, SOURCE_PDF, output_pdf_b, OUTPUT_DIR / "_overlay_pages_b"
    )
    elapsed_b = time.monotonic() - started_b
    arm_b = summarize_arm("wrapped", output_pdf_b, reported, elapsed_b)

    after_hashes_b = {
        page: render_hash(output_pdf_b, page) for page in sample_visual_pages
    }
    visual_regression = {
        page: before_hashes[page] == after_hashes_b[page]
        for page in sample_visual_pages
    }

    coverage_gain = None
    if arm_a["overall_coverage"] and arm_b["overall_coverage"] is not None:
        coverage_gain = round(arm_b["overall_coverage"] - arm_a["overall_coverage"], 4)

    finding_ok = (
        arm_b["overall_coverage"] is not None
        and arm_a["overall_coverage"] is not None
        and arm_b["overall_coverage"] > arm_a["overall_coverage"]
        and all(visual_regression.values())
    )
    finding = (
        f"element line word-wrap로 전체 커버리지가 {arm_a['overall_coverage']:.1%}에서 "
        f"{arm_b['overall_coverage']:.1%}로 개선됐고(gain={coverage_gain}), "
        f"80% 미만 page {arm_a['pages_below_80pct']}->{arm_b['pages_below_80pct']}, "
        f"50% 미만 page {arm_a['pages_below_50pct']}->{arm_b['pages_below_50pct']}, "
        f"시각 회귀 없음={all(visual_regression.values())}. "
        + (
            "src/insertion.py로 이식할 수 있는 가설이 검증됐다."
            if finding_ok
            else "가설이 완전히 검증되지 않았다: 개선폭이나 시각 회귀를 재확인해야 한다."
        )
    )

    summary = {
        "source_page_count": source_page_count,
        "insertable_page_count": len(insertable_pages),
        "arm_a_baseline": arm_a,
        "arm_b_wrapped": arm_b,
        "coverage_gain": coverage_gain,
        "visual_regression_check": visual_regression,
        "finding": finding,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_experiment(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
