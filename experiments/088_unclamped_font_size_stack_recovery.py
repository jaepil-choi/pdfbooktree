"""experiment 088: overlay font_size 상한 clamp를 없애면 BPE stack 계층이 회복되는지 본다.

showcase 015에서 수리통계학(개정판) merged OCR PDF에 Processor(BPE 계층 추론)를
돌리면 bookmark 552개가 전부 level 1인 flat 목록이 나왔다. 원인을 추적해보니
`insertion.py`의 `MAX_FONT_SIZE_PT=18.0pt` 절대 상한이 문제였다: 실제 overlay PDF의
font_size 분포에서 18.0pt가 단일 최빈값(20,233줄 중 1,347줄)이었고, 그 18.0pt
버킷에 몰리는 대다수는 heading이 아니라 equation(79.3%)/chart(93.3%)/figure(100%)
카테고리였다(수식/차트/그림을 element 통째로 하나의 "line"으로 심다 보니 bbox
높이가 비정상적으로 커서 상한에 부딪힘). 그 결과 실제 heading tier와 equation
tier가 정확히 같은 font_size(18.0)로 뭉개져서, `infer_bpe_outline`의 stack
알고리즘이 모든 heading을 구분 불가능한 tier 1 하나로만 인식했다.

사용자 가설: 이 clamp 자체가 문제고, category 기반 우회는 OCR engine 의존성을
만들어서 안 된다. `infer_bpe_outline`은 font tier가 stack에서 반복되고 tree
구조(중첩)를 이루는지만 보는 stack algorithm이므로, equation의 font tier가
chapter tier보다 커도(tier 번호가 더 작아도) 이론적으로는 문제가 없어야 한다.
즉 clamp만 없애면(각 line이 자기 bbox 높이 그대로의 고유한 font_size를 갖게
하면) 진짜 heading이 자기만의 recurring tier를 되찾을 수 있다는 것이다.

이 실험은 라이브 OCR 호출 없이 기존 insertable cache(637쪽, showcase 014/015
산출물)를 재사용해서 두 arm을 비교한다.
  - arm_a(baseline): 현재 src와 동일한 clamp([MIN,MAX]=[3.0, 18.0]pt, page 비례).
  - arm_b(unclamped): MAX_FONT_SIZE_PT를 사실상 무제한으로 풀고(MIN은 유지),
    나머지 zero-loss wrap 로직(experiments/087, 현재 src와 동일)은 그대로 둔다.
그 다음 각 arm의 overlay PDF에 Processor와 완전히 동일한 함수
(extract_typography_lines -> exclude_margin_artifacts -> compute_tier_set ->
extract_bpe_headings -> infer_bpe_outline -> normalize_bookmark_plan)를 그대로
호출해서 level 분포, tier 개수, 그리고 알려진 실제 heading("1장", "1.1", "정리")이
계층을 회복하는지 직접 확인한다. 가설이 틀렸다면(예: equation이 진짜 chapter보다
큰 tier가 되어 stack을 계속 top-level로 리셋시키는 경우) 그 실패 양상도 그대로
기록한다.

실행:
    uv run python experiments/088_unclamped_font_size_stack_recovery.py
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import fitz

from pdfbooktree.config import TypographyConfig
from pdfbooktree.ocr.cache import insertable_page_from_json
from pdfbooktree.ocr.insertion import (
    _load_overlay_font,
    _page_relative_font_size_bounds,
    _scale_rect,
    _strip_text_objects,
    write_overlay_pdf,
)
from pdfbooktree.ocr.models import InsertableOcrPage
from pdfbooktree.outline.plan import normalize_bookmark_plan
from pdfbooktree.typography.bpe import extract_bpe_headings, infer_bpe_outline
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts
from pdfbooktree.typography.tiers import compute_tier_set

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "088_unclamped_font_size_stack_recovery"
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
BASELINE_PDF = (
    ROOT_DIR
    / "showcase"
    / "outputs"
    / "014_ocr_overlay_math_statistics"
    / "pdfs"
    / "수리통계학(개정판)-김우철_upocr_merged_ocr.pdf"
)

# heading tree 회복 여부를 눈으로 확인할 실제 목차 anchor(육안 확인, 011/013 등에서
# 반복적으로 쓰인 방식과 동일하게 정규화된 title 부분 문자열로 찾는다).
KNOWN_HEADING_ANCHORS = ["1장", "1.1", "1.2", "1.3", "머리말", "차례"]

# unclamped arm에서 쓸 사실상 무제한 상한이다. MIN은 그대로 두고(작은 bbox 방어),
# MAX만 없애서 equation/chart/figure의 자연 bbox 높이가 그대로 font_size가 되게 한다.
UNCLAMPED_MAX_FONT_SIZE_PT = 100_000.0


# ---------------------------------------------------------------------------
# cache 로딩 (081/086/087과 동일 패턴)
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
# unclamped 삽입: 087/현재 src의 zero-loss wrap과 동일하되 MAX_FONT_SIZE_PT만 뺀다.
# ---------------------------------------------------------------------------

LINE_SPACING_FACTOR = 1.15
MIN_WRAP_WIDTH_PT = 20.0
FIT_MIN_FONT_SIZE_PT = 0.05
BINARY_SEARCH_ITER = 30


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


def _fit_line_text_unclamped(
    font: fitz.Font,
    text: str,
    rect: fitz.Rect,
    safe_bounds: fitz.Rect,
    min_font_size: float,
    max_font_size: float,
) -> tuple[list[str], float]:
    """src `_fit_line_text`와 동일하나, max_font_size로 사실상 무제한 값을 받는다."""

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


def _insert_invisible_lines_unclamped(
    document: fitz.Document,
    insertable_pages: list[InsertableOcrPage],
) -> None:
    font = _load_overlay_font()
    for page_model in insertable_pages:
        if page_model.pdf_page < 1 or page_model.pdf_page > document.page_count:
            continue

        page = document[page_model.pdf_page - 1]
        writer = fitz.TextWriter(page.rect)
        min_font_size, _ = _page_relative_font_size_bounds(page.rect.height)
        max_font_size = UNCLAMPED_MAX_FONT_SIZE_PT
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

                wrapped_lines, font_size = _fit_line_text_unclamped(
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


def write_overlay_pdf_unclamped(
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
        _insert_invisible_lines_unclamped(document, insertable_pages)
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
# BPE 계층 추론(Processor.run()과 동일한 함수 호출 순서)
# ---------------------------------------------------------------------------


def run_bpe_pipeline(pdf_path: Path) -> dict[str, object]:
    config = TypographyConfig()
    raw_lines = extract_typography_lines(pdf_path, config)
    lines = exclude_margin_artifacts(raw_lines, config)
    font_tiers = compute_tier_set(lines, "font_size", config)
    candidates = extract_bpe_headings(lines, font_tiers, config)
    plan = normalize_bookmark_plan(infer_bpe_outline(candidates, config))

    font_size_counts = Counter(round(line.font_size, 1) for line in lines)
    top_font_sizes = font_size_counts.most_common(10)
    level_counts = dict(sorted(Counter(item.level for item in plan).items()))

    anchor_hits = []
    for anchor in KNOWN_HEADING_ANCHORS:
        matches = [item for item in plan if anchor in item.title]
        if matches:
            first = matches[0]
            anchor_hits.append(
                {
                    "anchor": anchor,
                    "match_count": len(matches),
                    "first_title": first.title,
                    "first_level": first.level,
                    "first_pdf_page": first.pdf_page,
                }
            )
        else:
            anchor_hits.append({"anchor": anchor, "match_count": 0})

    tree_lines = [
        f"{'  ' * (item.level - 1)}[L{item.level}, p.{item.pdf_page}] {item.title}"
        for item in plan
    ]

    return {
        "line_count": len(lines),
        "raw_line_count": len(raw_lines),
        "font_tier_count": font_tiers.final_tier_count,
        "top_font_sizes": [
            {"font_size": size, "count": count} for size, count in top_font_sizes
        ],
        "bookmark_count": len(plan),
        "level_counts": level_counts,
        "max_level": max(level_counts) if level_counts else 0,
        "anchor_hits": anchor_hits,
        "tree_preview": tree_lines[:40],
    }


def record_experiment(summary: dict[str, object]) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "insertion.py의 MAX_FONT_SIZE_PT=18.0pt 절대 clamp가 진짜 heading tier와 "
            "equation/chart/table/figure tier를 같은 값으로 뭉개서 BPE stack이 "
            "hierarchy를 전혀 구분 못 하는지, clamp를 없애면(각 line이 고유 bbox "
            "높이의 font_size를 그대로 갖게 하면) stack algorithm이 equation tier가 "
            "chapter tier보다 커도 이론상 문제없이 진짜 heading 계층을 복원하는지 "
            "확인한다. category(OCR engine 의존) 우회는 쓰지 않는다."
        ),
        "inputs": [
            str(SOURCE_PDF.relative_to(ROOT_DIR)),
            str(ARTIFACT_DIR.relative_to(ROOT_DIR)),
        ],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "showcase 014/015의 insertable cache(637쪽)를 재사용해 arm_a(baseline, "
            "현재 src와 동일한 clamp)와 arm_b(unclamped, MAX_FONT_SIZE_PT만 사실상 "
            "무제한)를 만들고, 둘 다 Processor와 동일한 함수 순서(extract_typography_"
            "lines -> exclude_margin_artifacts -> compute_tier_set -> "
            "extract_bpe_headings -> infer_bpe_outline -> normalize_bookmark_plan, "
            "config는 모두 기본값)로 BPE bookmark plan을 만들어 level 분포와 "
            "1장/1.1/1.2/1.3/머리말/차례 anchor의 계층 위치를 비교했다."
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

    # arm_a: baseline. 이미 showcase 014/015 산출물로 존재하지만, 재현성을 위해
    # 같은 cache에서 현재 src 함수로 직접 다시 만든다(라이브 API 호출 없음).
    output_pdf_a = OUTPUT_DIR / "arm_a_baseline.pdf"
    started_a = time.monotonic()
    write_overlay_pdf(
        insertable_pages, SOURCE_PDF, output_pdf_a, OUTPUT_DIR / "_overlay_pages_a"
    )
    elapsed_a = time.monotonic() - started_a

    output_pdf_b = OUTPUT_DIR / "arm_b_unclamped.pdf"
    started_b = time.monotonic()
    write_overlay_pdf_unclamped(
        insertable_pages, SOURCE_PDF, output_pdf_b, OUTPUT_DIR / "_overlay_pages_b"
    )
    elapsed_b = time.monotonic() - started_b

    result_a = run_bpe_pipeline(output_pdf_a)
    result_a["elapsed_sec"] = round(elapsed_a, 2)
    result_b = run_bpe_pipeline(output_pdf_b)
    result_b["elapsed_sec"] = round(elapsed_b, 2)

    hierarchy_recovered = result_b["max_level"] >= 3 and any(
        hit["match_count"] > 0 and hit["first_level"] <= 2
        for hit in result_b["anchor_hits"]
        if hit["anchor"] in {"1장", "1.1"}
    )

    finding = (
        f"baseline: font_tier={result_a['font_tier_count']}, "
        f"top_font_size={result_a['top_font_sizes'][0] if result_a['top_font_sizes'] else None}, "
        f"level_counts={result_a['level_counts']} (max_level={result_a['max_level']}). "
        f"unclamped: font_tier={result_b['font_tier_count']}, "
        f"top_font_size={result_b['top_font_sizes'][0] if result_b['top_font_sizes'] else None}, "
        f"level_counts={result_b['level_counts']} (max_level={result_b['max_level']}). "
        + (
            "clamp만 없애도 stack algorithm이 진짜 heading 다단 계층을 복원했다: "
            "가설이 검증됐다."
            if hierarchy_recovered
            else "clamp를 없애도 여전히 다단 계층이 복원되지 않았다: 가설이 예상과 "
            "다르게 동작했다(추가 원인 조사 필요)."
        )
    )

    summary = {
        "arm_a_baseline": result_a,
        "arm_b_unclamped": result_b,
        "hierarchy_recovered": hierarchy_recovered,
        "finding": finding,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_experiment(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
