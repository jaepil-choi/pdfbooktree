"""experiment 087: 모든 overlay_mode에 적용되는 zero-loss wrap을 검증한다.

086에서는 overlay_mode="element" line만 bbox 폭 기준 word-wrap해서 전체 커버리지를
44.3% -> 79.5%로 올렸지만, 277개 page가 여전히 80% 미만이었다. 원인을 나눠보면
(1) element 모드의 wrap+shrink가 bbox 높이만 fitting 대상으로 삼아서 텍스트가
아주 많으면 bbox 아래로도 못 담고, (2) word/row 모드는 애초에 wrap을 전혀 안 해서
substitute font(malgun.ttf)의 글자폭이 원본 OCR bbox 폭보다 넓게 렌더링되면 그
차이만큼 page 경계를 넘어 잘리는 경우가 있었다.

이 실험은 두 가지를 일반화한다.
1. overlay_mode와 무관하게, 자연 font_size(rect.height*0.88)로 한 줄에 다 들어가면
   기존과 동일하게 한 줄만 쓴다(정상 line은 변화 없음).
2. 안 들어가면 (a) wrap_width는 bbox 폭, (b) 세로 여유는 bbox 높이가 아니라 "그
   line의 top부터 page 하단까지" 전체를 쓰고, 그 안에 들어가는 가장 큰 font_size를
   이분 탐색으로 찾는다. word 폭은 font_size에 선형 비례하므로, wrap_width>0과
   available_height>0만 있으면 font_size를 충분히 줄여 항상 들어갈 수 있다
   (단일 토큰이 wrap_width보다 넓어도 마찬가지로 폭 체크에 포함해 font_size를
   줄이면 해결된다).

성공 기준: aggregate coverage뿐 아니라 book 전체 637쪽 각각의 coverage가 100%에
근접하는지(최소 커버리지)를 확인한다. API 재호출 없이 086과 같은 insertable
cache를 재사용한다.

실행:
    uv run python experiments/087_zero_loss_overlay_wrap.py
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
EXPERIMENT_ID = "087_zero_loss_overlay_wrap"
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
FIT_MIN_FONT_SIZE_PT = 0.05
BINARY_SEARCH_ITER = 30


# ---------------------------------------------------------------------------
# cache 로딩 (081/086과 동일 패턴)
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
# 모든 overlay_mode에 적용되는 zero-loss wrap
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


def _fits(
    font: fitz.Font,
    lines: list[str],
    font_size: float,
    wrap_width: float,
    available_height: float,
) -> bool:
    if not lines:
        return True
    required_height = len(lines) * font_size * LINE_SPACING_FACTOR
    if required_height > available_height + 1e-6:
        return False
    max_line_width = max(font.text_length(line, fontsize=font_size) for line in lines)
    return max_line_width <= wrap_width + 0.5


def _fit_line_text(
    font: fitz.Font,
    text: str,
    rect: fitz.Rect,
    safe_bounds: fitz.Rect,
    min_font_size: float,
    max_font_size: float,
) -> tuple[list[str], float]:
    """line을 wrap_width/available_height 안에 반드시 들어가는 font_size로 맞춘다.

    word 폭은 font_size에 선형 비례하므로, wrap_width>0과 available_height>0만
    있으면 font_size를 충분히 줄여 항상 들어갈 수 있다(단일 초과 토큰도 동일 원리로
    해결된다). 자연 font_size로 한 줄에 이미 들어가면(정상 케이스) 그대로 쓴다.

    safe_bounds는 get_text() 추출이 실제로 clip하는 영역이다. 90/270도 회전된
    page는 TextWriter/page.rect가 회전된(표시) 좌표계를 쓰지만, get_text()는 원본
    MediaBox 크기로 clip한다(회전 미반영). 그래서 page.rect가 아니라 MediaBox 기반
    safe_bounds를 넘지 않게 해야 한다(실측: 페이지 519/520/521, experiments/087).
    """

    words = text.split()
    if not words:
        return [], min_font_size

    x0 = min(max(rect.x0, 0.0), safe_bounds.width - MIN_WRAP_WIDTH_PT)
    y0 = min(rect.y0, safe_bounds.height - 1.0)
    wrap_width = max(MIN_WRAP_WIDTH_PT, min(rect.width, safe_bounds.width - x0 - 2.0))
    available_height = max(1.0, safe_bounds.height - y0 - 2.0)

    natural_font_size = max(min_font_size, min(max_font_size, rect.height * 0.88))
    single_line = " ".join(words)
    if font.text_length(single_line, fontsize=natural_font_size) <= wrap_width:
        return [single_line], natural_font_size

    lo, hi = FIT_MIN_FONT_SIZE_PT, natural_font_size
    best_font_size = lo
    best_lines = _wrap_words_to_width(font, words, wrap_width, lo)
    for _ in range(BINARY_SEARCH_ITER):
        mid = (lo + hi) / 2
        lines = _wrap_words_to_width(font, words, wrap_width, mid)
        if _fits(font, lines, mid, wrap_width, available_height):
            best_font_size = mid
            best_lines = lines
            lo = mid
        else:
            hi = mid
    return best_lines, best_font_size


def _insert_invisible_lines_zero_loss(
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
        # get_text() 추출은 회전(rotation) 여부와 무관하게 MediaBox 원본 크기로
        # clip한다. 0/180도 회전이면 mediabox == page.rect라 차이가 없지만,
        # 90/270도 회전(width/height가 서로 바뀜)에서는 page.rect보다 훨씬 좁은
        # 영역만 안전하다(실측: experiments/087, 페이지 519/520/521).
        safe_bounds = fitz.Rect(0.0, 0.0, page.mediabox.width, page.mediabox.height)
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

                wrapped_lines, font_size = _fit_line_text(
                    font, text, rect, safe_bounds, min_font_size, max_font_size
                )
                line_height = font_size * LINE_SPACING_FACTOR
                origin_y0 = min(rect.y0, safe_bounds.height - 1.0)
                for index, wrapped_text in enumerate(wrapped_lines):
                    baseline_y = origin_y0 + (index + 1) * line_height
                    origin_x0 = min(
                        max(rect.x0, 0.0), safe_bounds.width - MIN_WRAP_WIDTH_PT
                    )
                    writer.append(
                        (origin_x0, baseline_y),
                        wrapped_text,
                        font=font,
                        fontsize=font_size,
                    )
                    inserted_on_page += 1

        if inserted_on_page:
            writer.write_text(page, overlay=True, render_mode=3)


def write_overlay_pdf_zero_loss(
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
        _insert_invisible_lines_zero_loss(document, insertable_pages)
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
        if reported[page] > 0
    }
    below_999 = sorted(
        (page, cov) for page, cov in per_page_coverage.items() if cov < 0.999
    )
    below_80 = sum(1 for cov in per_page_coverage.values() if cov < 0.8)
    below_50 = sum(1 for cov in per_page_coverage.values() if cov < 0.5)
    over_extract = sum(
        1
        for page in page_numbers
        if reported[page] > 0 and extracted[page] > reported[page] * 1.5
    )
    min_coverage_page = min(per_page_coverage, key=per_page_coverage.get)

    return {
        "arm": name,
        "output_pdf": str(output_pdf.relative_to(ROOT_DIR)),
        "elapsed_sec": round(elapsed_sec, 2),
        "output_bytes": output_pdf.stat().st_size,
        "total_reported_chars": total_reported,
        "total_extracted_chars": total_extracted,
        "overall_coverage": round(total_extracted / total_reported, 6)
        if total_reported
        else None,
        "min_page_coverage": round(per_page_coverage[min_coverage_page], 6),
        "min_page_coverage_page": min_coverage_page,
        "pages_below_99_9pct": len(below_999),
        "pages_below_80pct": below_80,
        "pages_below_50pct": below_50,
        "pages_with_suspected_duplication": over_extract,
        "sample_below_99_9pct": [
            {"pdf_page": page, "coverage": round(cov, 4)}
            for page, cov in below_999[:15]
        ],
        "known_worst_pages": {
            page: {
                "reported_chars": reported[page],
                "extracted_chars": extracted[page],
                "coverage": round(per_page_coverage.get(page, 1.0), 4),
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
            "086에서 남은 277개 80% 미만 page를 없애고 모든 page가 100% 커버리지를 "
            "reserve하도록, overlay_mode 구분 없이 모든 line에 page-bounded 이분 탐색 "
            "font_size fitting을 적용해 zero-loss를 구조적으로 보장할 수 있는지 검증한다."
        ),
        "inputs": [
            str(SOURCE_PDF.relative_to(ROOT_DIR)),
            str(ARTIFACT_DIR.relative_to(ROOT_DIR)),
        ],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "086과 같은 insertable cache(637쪽)를 재사용해 baseline과 zero-loss wrap "
            "(write_overlay_pdf_zero_loss)을 비교했다. zero-loss wrap은 자연 font_size로 "
            "한 줄에 들어가면 그대로 두고, 안 들어가면 line 상단부터 page 하단까지를 "
            "가용 높이로 써서 이분 탐색으로 font_size를 줄인다(word 폭이 font_size에 "
            "선형 비례하므로 항상 수렴이 보장된다). aggregate coverage뿐 아니라 "
            "page별 최소 coverage를 확인했다."
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

    output_pdf_c = OUTPUT_DIR / "arm_c_zero_loss.pdf"
    started_c = time.monotonic()
    write_overlay_pdf_zero_loss(
        insertable_pages, SOURCE_PDF, output_pdf_c, OUTPUT_DIR / "_overlay_pages_c"
    )
    elapsed_c = time.monotonic() - started_c
    arm_c = summarize_arm("zero_loss", output_pdf_c, reported, elapsed_c)

    after_hashes_c = {
        page: render_hash(output_pdf_c, page) for page in sample_visual_pages
    }
    visual_regression = {
        page: before_hashes[page] == after_hashes_c[page]
        for page in sample_visual_pages
    }

    finding_ok = (
        arm_c["overall_coverage"] is not None
        and arm_c["overall_coverage"] >= 0.999
        and arm_c["min_page_coverage"] >= 0.99
        and all(visual_regression.values())
    )
    finding = (
        f"zero-loss wrap으로 전체 커버리지가 {arm_a['overall_coverage']:.1%}(baseline)에서 "
        f"{arm_c['overall_coverage']:.1%}로 개선됐고, page별 최소 커버리지는 "
        f"{arm_c['min_page_coverage']:.1%}(page {arm_c['min_page_coverage_page']}), "
        f"99.9% 미만 page {arm_c['pages_below_99_9pct']}개, 시각 회귀 없음={all(visual_regression.values())}, "
        f"처리 시간 {arm_c['elapsed_sec']}초. "
        + (
            "모든 page가 사실상 100% 커버리지에 도달해 zero-loss 가설이 검증됐다."
            if finding_ok
            else "일부 page가 여전히 100%에 못 미쳐 추가 원인 조사가 필요하다."
        )
    )

    summary = {
        "source_page_count": source_page_count,
        "insertable_page_count": len(insertable_pages),
        "arm_a_baseline": arm_a,
        "arm_c_zero_loss": arm_c,
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
