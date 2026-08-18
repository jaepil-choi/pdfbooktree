"""AI agent가 PDF와 처리 artifact를 작은 단위로 조사하는 읽기 전용 API다."""

from __future__ import annotations

import json
import math
import re
import shlex
import statistics
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import fields as dataclass_fields, replace
from pathlib import Path
from typing import Any

import fitz

from pdfbooktree.config import MarkdownSplitConfig, TypographyConfig
from pdfbooktree.evaluation import PlanDiffEntry, compare_bookmark_plans
from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.outline.plan_io import load_bookmark_plan_json
from pdfbooktree.pdf.bookmarks import extract_existing_bookmarks
from pdfbooktree.pipeline import analyze_pdf
from pdfbooktree.typography.geometry import (
    build_geometry_context,
    compute_geometry_font_tier_set,
    select_geometry_headings,
)
from pdfbooktree.typography.margins import exclude_margin_artifacts

# ---------------------------------------------------------------------------
# Markdown tree finding 상수
#
# 아래 임계값은 고정 corpus(PDF 356권, markdown_manifest.json export에 성공한
# 335권)의 실측 분포를 percentile로 보정한 값이다. 특정 책 제목, 파일명,
# 출판사를 가정하지 않는 general 문턱값이다.
# ---------------------------------------------------------------------------

# uncovered: 실측 unassigned_ratio p90=0.03, p95=0.048. 두 percentile보다
# 확연히 큰 여유를 둔 blocking 문턱값이다.
UNASSIGNED_RATIO_BLOCKING_THRESHOLD = 0.10

# thin: 실측 pages_per_node.mean median=10.0, p75=15.7. 그 3배 이상 여유를 둔
# advisory 문턱값이다.
THIN_MEAN_PAGES_PER_NODE_THRESHOLD = 50.0
THIN_MIN_PAGE_COUNT = 20
THIN_MAX_NODE_COUNT = 2

# over_split: node 수가 page 수보다 많거나(평균 1 page 미만) 본문 word 수가
# heading에 가까울 정도로 짧은 node가 절반을 넘는 경우를 잡는 절대 문턱값이다.
# word_count 신호가 없는 export(예: tree_graph)에서는 word 기반 조건을 평가하지
# 않고 page 기반 조건만으로 판정한다.
OVER_SPLIT_MEAN_PAGES_PER_NODE_THRESHOLD = 1.0
OVER_SPLIT_WORDS_PER_NODE_MEDIAN_THRESHOLD = 50

# fragmented: 실측 fragment_ratio median=0.167, p75=0.317. p75 부근의 advisory
# 문턱값이다.
FRAGMENTED_RATIO_THRESHOLD = 0.30

FINDING_SEVERITY_ORDER = (
    "invalid_graph",
    "uncovered",
    "duplicated",
    "thin",
    "over_split",
    "fragmented",
)
FINDING_SEVERITY = {
    "invalid_graph": "blocking",
    "uncovered": "blocking",
    "duplicated": "advisory",
    "thin": "advisory",
    "over_split": "advisory",
    "fragmented": "advisory",
}


# reused_existing_outline retry 실측(고정 corpus의 thin reused 37권 전체 재추론):
# processing.skip_existing_bookmarks=false로 재추론하면 37/37 모두 node 수가
# 늘었다(2 node → median 38 node, 최소 12). 강하게 뒷받침되는 후보이지만 여전히
# 보장이 아니라 재시도 후보로 표시한다.
_REUSED_OUTLINE_RETRY_REASON = (
    "실측(thin reused 37권 재추론)에서 이 override는 37/37 모두 node 수가 "
    "증가했다(2 node → median 38 node, 최소 12). 강하게 뒷받침되는 후보이지만 "
    "여전히 보장이 아니라 재시도 후보다."
)

# non_heading_text_selected retry 실측(고정 corpus 5권 재추론, 대상은 재추론 전
# fragment_ratio>=0.5인 책):
# - typography.max_heading_tier 감소는 효과가 없거나 오히려 악화됐다(3/5는
#   동일, 2/5는 악화: 0.645→0.708, 0.242→0.46). 그래서 이 override는 후보로
#   제시하지 않는다.
# - typography.body_font_max_words, typography.body_font_text_coverage 조정도
#   거의 변화가 없었다.
# - typography.heading_candidate_mode=position_and_font만 일부 개선했다
#   (0.441→0.309, 0.674→0.655). 5권 중 2권만 감소했고 나머지 3권은 변화가
#   없었다.
# - fragment는 level1(0.33)에서 가장 많고 level2(0.296), level3(0.23) 순이라
#   markdown.max_words로 split level을 낮춰도 fragment가 줄지 않는다.
_NON_HEADING_TEXT_RETRY_REASON = (
    "실측(5권 재추론, 재추론 전 fragment_ratio>=0.5 대상)에서 이 override는 "
    "2/5권만 fragment_ratio가 감소했고(0.441→0.309, 0.674→0.655) 나머지 3권은 "
    "변화가 없었다. 개선을 보장하지 않으며, 현재 parameter로는 신뢰성 있게 "
    "교정되지 않는 알려진 한계다."
)
_FRAGMENT_LEVEL_NOTE = (
    "실측상 fragment는 최상위 level(level1)에도 하위 level과 비슷하거나 더 "
    "높은 비율로 나타난다. markdown.max_words를 올려 split level을 낮추는 "
    "방식으로는 fragment가 줄지 않을 수 있다."
)

# sparse_heading_candidates retry 실측(고정 corpus의 thin inferred 2권 재추론):
# typography.heading_candidate_mode=position은 heading 후보를 크게 늘려 thin은
# 확실히 해소되지만, 대개 반대편인 over_split으로 뒤집힌다(376p/1 node → plan
# 2350건, 301p/5 node → plan 746건). position_fallback_enabled=true는 이미
# 기본값이라 재실행해도 변화가 없어 후보에서 제외한다.
_SPARSE_HEADING_RETRY_REASON = (
    "실측(thin inferred 2권 재추론, 표본 크기 2)에서 이 override는 heading "
    "후보를 크게 늘렸다(1 node → plan item 2350건, 5 node → plan item 746건). "
    "앞 수치는 재추론 전 tree node 수, 뒤 수치는 재추론 후 bookmark plan item "
    "수로 서로 다른 단위이며 직접 비교할 수 없다. 두 사례 모두 thin에서 "
    "over_split 쪽으로 방향이 뒤집혔다는 것만 근거가 있는 후보이지 thin 해소를 "
    "보장하지 않는다. 재실행 후 다시 `inspect markdown`으로 확인하라."
)
_SPARSE_HEADING_OVER_SPLIT_FOLLOWUP = (
    " over_split이 나오면 markdown.enabled=true인 split export에서만 "
    "markdown.max_words 조정으로 이어가라(tree_graph export에서는 "
    "markdown.max_words가 효과가 없다)."
)

_WORD_RE = re.compile(r"[A-Za-z\uac00-\ud7a3]+")

# ---------------------------------------------------------------------------
# heading candidate sweep 상수 (실험 118 heading_knob_steerability 재현)
#
# 여기 sweep하는 knob은 전부 책 내부 상대값이다. 절대 font size나 tier
# 번호는 OCR overlay가 책마다 다른 지점에서 clamp해 책 사이에서 의미가
# 달라지므로(실험 117) sweep 대상에 넣지 않는다.
# ---------------------------------------------------------------------------

HEADING_SWEEP_DEFAULT_SIZE_CLASS_DEPTHS: tuple[int, ...] = (1, 2, 3)
HEADING_SWEEP_DEFAULT_MAX_HEADINGS_PER_PAGE: tuple[int, ...] = (1, 2, 3, 5, 8, 999)
HEADING_SWEEP_DEFAULT_MIN_WORD_COUNTS: tuple[int, ...] = (1, 2)

# agent가 훑어보고 "말이 되는" 장 간격이라고 볼 범위다. 정답이 아니라 조작
# 가능성을 판정하기 위한 눈금이며, 책마다 실제 장 수는 다를 수 있다.
HEADING_SWEEP_SENSIBLE_PAGES_PER_CANDIDATE = (5.0, 40.0)

_HEADING_SWEEP_REQUIRED_TYPOGRAPHY_FIELDS = (
    "size_class_depth",
    "max_headings_per_page",
)


def inspect_page_count(pdf_path: Path | str) -> dict[str, Any]:
    """PDF 총 page 수를 1-based convention과 함께 반환한다."""

    path = _require_file(pdf_path, "PDF")
    with fitz.open(path) as document:
        return {"pdf_path": str(path), "page_count": document.page_count}


def inspect_text(
    pdf_path: Path | str,
    pages: list[int],
) -> dict[str, Any]:
    """지정한 1-based page들의 text를 page별로 반환한다."""

    path = _require_file(pdf_path, "PDF")
    if not pages:
        raise ValueError("확인할 PDF page를 하나 이상 지정해야 한다.")
    if any(page < 1 for page in pages):
        raise ValueError("PDF page는 1 이상이어야 한다.")

    with fitz.open(path) as document:
        page_count = document.page_count
        invalid_pages = [page for page in pages if page > page_count]
        if invalid_pages:
            raise ValueError(
                f"PDF page 범위를 벗어났다: pages={invalid_pages}, page_count={page_count}"
            )
        page_rows = []
        for page in pages:
            text = document[page - 1].get_text()
            page_rows.append({"pdf_page": page, "text": text, "char_count": len(text)})
    return {"pdf_path": str(path), "page_count": page_count, "pages": page_rows}


def inspect_bookmarks(pdf_path: Path | str) -> dict[str, Any]:
    """PDF 기존 bookmark와 target page를 반환한다."""

    path = _require_file(pdf_path, "PDF")
    with fitz.open(path) as document:
        page_count = document.page_count
    bookmarks = extract_existing_bookmarks(path)
    return {
        "pdf_path": str(path),
        "page_count": page_count,
        "bookmark_count": len(bookmarks),
        "bookmarks": bookmarks,
    }


def inspect_heading_sweep(
    pdf_path: Path | str,
    *,
    size_class_depths: Sequence[int] = HEADING_SWEEP_DEFAULT_SIZE_CLASS_DEPTHS,
    max_headings_per_page_values: Sequence[
        int
    ] = HEADING_SWEEP_DEFAULT_MAX_HEADINGS_PER_PAGE,
    min_word_counts: Sequence[int] = HEADING_SWEEP_DEFAULT_MIN_WORD_COUNTS,
    base_config: TypographyConfig | None = None,
) -> dict[str, Any]:
    """PDF typography를 한 번만 분석하고 heading knob 조합을 메모리에서 sweep한다.

    agent가 ``process``를 설정마다 반복 실행하지 않고도 ``typography.
    size_class_depth``, ``typography.max_headings_per_page``, 최소 단어 수
    조합이 candidate 수/page 분포를 어느 방향으로 움직이는지 한 번에 훑어볼 수
    있게 한다. typography 추출(``analyze_pdf``)은 이 함수 안에서 정확히 한 번만
    실행하고, 이후 sweep은 이미 추출한 line에 대해서만 메모리 안에서 반복한다.
    process가 만드는 최종 bookmark/Markdown output은 만들지 않는다.

    ``size_class_depth``/``max_headings_per_page``는 ``TypographyConfig``
    필드로 존재해야 한다. 없으면 다른 lane의 작업이 아직 반영되지 않은 것이므로
    후보를 조용히 건너뛰지 않고 명확한 메시지로 실패한다.
    """

    path = _require_file(pdf_path, "PDF")
    _require_typography_sweep_fields()
    depths = _positive_int_sequence(size_class_depths, "size_class_depths")
    max_per_page_values = _positive_int_sequence(
        max_headings_per_page_values, "max_headings_per_page_values"
    )
    min_word_values = _positive_int_sequence(min_word_counts, "min_word_counts")

    resolved_base = base_config or TypographyConfig()
    analysis = analyze_pdf(path, resolved_base)
    lines = exclude_margin_artifacts(analysis.lines, resolved_base)

    settings: list[dict[str, Any]] = []
    for depth in depths:
        for max_per_page in max_per_page_values:
            for min_words in min_word_values:
                settings.append(
                    _evaluate_heading_sweep_setting(
                        lines,
                        resolved_base,
                        analysis.total_pages,
                        size_class_depth=depth,
                        max_headings_per_page=max_per_page,
                        min_words=min_words,
                    )
                )

    summary = _heading_sweep_summary(settings)
    return {
        "pdf_path": str(path),
        "page_count": analysis.total_pages,
        "body_line_count": len(lines),
        "settings_tried": len(settings),
        "settings": settings,
        "summary": summary,
    }


def _require_typography_sweep_fields() -> None:
    """sweep이 참조하는 book-relative knob이 config에 없으면 조용히 넘어가지 않는다."""

    field_names = {field.name for field in dataclass_fields(TypographyConfig)}
    missing = [
        name
        for name in _HEADING_SWEEP_REQUIRED_TYPOGRAPHY_FIELDS
        if name not in field_names
    ]
    if missing:
        raise ValueError(
            "TypographyConfig에 heading sweep이 요구하는 field가 없다: "
            f"missing={missing}. 이 field를 추가하는 lane의 변경을 먼저 반영해야 한다."
        )


def _positive_int_sequence(values: Sequence[int], label: str) -> list[int]:
    resolved = list(values)
    if not resolved:
        raise ValueError(f"{label}은 하나 이상의 값을 가져야 한다.")
    if any(not isinstance(value, int) or isinstance(value, bool) for value in resolved):
        raise ValueError(f"{label}은 정수 목록이어야 한다: value={resolved!r}")
    if any(value < 1 for value in resolved):
        raise ValueError(f"{label}의 모든 값은 1 이상이어야 한다: value={resolved!r}")
    return resolved


def _evaluate_heading_sweep_setting(
    lines: list[Any],
    base_config: TypographyConfig,
    total_pages: int,
    *,
    size_class_depth: int,
    max_headings_per_page: int,
    min_words: int,
) -> dict[str, Any]:
    """이미 추출한 line에 대해 단일 knob 조합의 candidate 결과를 계산한다."""

    setting_config = replace(
        base_config,
        size_class_depth=size_class_depth,
        max_headings_per_page=max_headings_per_page,
    )
    font_tiers = compute_geometry_font_tier_set(lines)
    context = build_geometry_context(lines, font_tiers, setting_config)
    candidates = [
        heading
        for heading in select_geometry_headings(context, setting_config)
        if len(_WORD_RE.findall(heading.title)) >= min_words
    ]
    pages_with_candidate = {candidate.pdf_page for candidate in candidates}
    candidate_count = len(candidates)
    pages_per_candidate = (
        round(total_pages / candidate_count, 2) if candidate_count else None
    )
    return {
        "size_class_depth": size_class_depth,
        "max_headings_per_page": max_headings_per_page,
        "min_words": min_words,
        "candidate_count": candidate_count,
        "pages_with_candidate_count": len(pages_with_candidate),
        "pages_per_candidate": pages_per_candidate,
    }


def _heading_sweep_summary(settings: list[dict[str, Any]]) -> dict[str, Any]:
    """sweep 결과를 훑어 plausible한 setting과 knob 방향을 한 번에 알려준다."""

    low, high = HEADING_SWEEP_SENSIBLE_PAGES_PER_CANDIDATE
    plausible = [
        setting
        for setting in settings
        if setting["pages_per_candidate"] is not None
        and low <= setting["pages_per_candidate"] <= high
    ]
    return {
        "sensible_pages_per_candidate_range": [low, high],
        "plausible_setting_count": len(plausible),
        "plausible_settings": plausible,
        "size_class_depth_direction": _heading_sweep_knob_direction(
            settings, "size_class_depth"
        ),
        "max_headings_per_page_direction": _heading_sweep_knob_direction(
            settings, "max_headings_per_page"
        ),
        "min_words_direction": _heading_sweep_knob_direction(settings, "min_words"),
    }


def _heading_sweep_knob_direction(settings: list[dict[str, Any]], knob: str) -> str:
    """knob을 키울 때 candidate 수가 늘거나 줄거나 섞이는지 한 단어로 요약한다.

    다른 knob 값은 고정한 채 짝지어 비교해, agent가 다음에 어느 방향으로 knob을
    움직여야 candidate가 늘거나 줄지 결과를 다시 읽지 않고 바로 판단하게 한다.
    """

    other_keys = [
        key
        for key in ("size_class_depth", "max_headings_per_page", "min_words")
        if key != knob
    ]
    groups: dict[tuple[Any, ...], list[tuple[int, int]]] = {}
    for setting in settings:
        group_key = tuple(setting[key] for key in other_keys)
        groups.setdefault(group_key, []).append(
            (setting[knob], setting["candidate_count"])
        )
    increasing = 0
    decreasing = 0
    flat = 0
    for series in groups.values():
        series.sort()
        for (_, before), (_, after) in zip(series, series[1:]):
            if after > before:
                increasing += 1
            elif after < before:
                decreasing += 1
            else:
                flat += 1
    total = increasing + decreasing + flat
    if total == 0:
        return "unknown"
    if increasing and not decreasing:
        return "increases_candidates" if flat == 0 else "mostly_increases_candidates"
    if decreasing and not increasing:
        return "decreases_candidates" if flat == 0 else "mostly_decreases_candidates"
    if not increasing and not decreasing:
        return "no_effect"
    return "mixed"


def inspect_ocr_artifact(artifact_dir: Path | str) -> dict[str, Any]:
    """OCR artifact의 진행 상태, cache page, stats와 마지막 로그를 요약한다."""

    root = _require_directory(artifact_dir, "OCR artifact directory")
    warnings: list[str] = []
    config_value = _read_optional_json(root / "ocr_overlay_config.json", warnings)
    progress_value = _read_optional_json(root / "ocr_progress.json", warnings)
    if not isinstance(config_value, dict):
        if config_value is not None:
            warnings.append("OCR config artifact 형식이 JSON object가 아니다.")
        config = {}
    else:
        config = config_value
    if not isinstance(progress_value, dict):
        if progress_value is not None:
            warnings.append("OCR progress artifact 형식이 JSON object가 아니다.")
        progress = {}
    else:
        progress = progress_value

    input_pdf = _path_from_config(config.get("input_pdf"))
    output_pdf = _path_from_config(config.get("output_pdf"))
    total_pages = _pdf_page_count(input_pdf, warnings)
    progress_total_pages = _as_int(progress.get("total_pages"))
    if total_pages is None:
        total_pages = progress_total_pages
    target_pages = _target_pages(config, total_pages, warnings)
    completed_pages = _as_int(progress.get("completed_pages")) or 0

    cache_root = root / "document_parse_cache"
    raw_count = _json_file_count(cache_root / "raw")
    insertable_pages, invalid_insertable_count = _read_insertable_pages(
        cache_root / "insertable"
    )
    if invalid_insertable_count:
        warnings.append(
            f"읽을 수 없는 insertable cache 파일이 {invalid_insertable_count}개 있다."
        )
    page_counts = Counter(insertable_pages)
    unique_pages = set(insertable_pages)
    duplicate_pages = sorted(page for page, count in page_counts.items() if count > 1)
    if duplicate_pages:
        warnings.append(
            "중복 pdf_page를 가진 insertable cache가 있다. 이전 cache key 형식의 "
            f"잔재일 수 있다: pages={duplicate_pages}"
        )

    expected_completed = set(target_pages[:completed_pages])
    missing_completed_pages = sorted(expected_completed - unique_pages)
    if missing_completed_pages:
        warnings.append(
            f"progress에서 완료로 기록한 page의 insertable cache가 없다: {missing_completed_pages}"
        )
    unprocessed_pages = [page for page in target_pages if page not in unique_pages]

    stats = _inspect_ocr_stats(root)
    last_log_event = _read_last_log_event(root / "ocr_log.jsonl", warnings)
    output_exists = output_pdf is not None and output_pdf.is_file()
    status = _ocr_status(
        root,
        total_pages,
        target_pages,
        unique_pages,
        output_exists,
    )
    if raw_count != len(unique_pages):
        warnings.append(
            "raw cache 수와 고유 insertable page 수가 다르다: "
            f"raw={raw_count}, unique_insertable={len(unique_pages)}"
        )

    return {
        "status": status,
        "artifact_dir": str(root),
        "input_pdf": str(input_pdf) if input_pdf is not None else None,
        "output_pdf": str(output_pdf) if output_pdf is not None else None,
        "output_pdf_exists": output_exists,
        "total_pages": total_pages,
        "target_page_count": len(target_pages),
        "progress_completed_pages": completed_pages,
        "progress_current_page": _as_int(progress.get("current_page")),
        "raw_cache_count": raw_count,
        "insertable_cache_count": len(insertable_pages),
        "unique_insertable_page_count": len(unique_pages),
        "duplicate_insertable_pages": duplicate_pages,
        "missing_completed_pages": missing_completed_pages,
        "unprocessed_page_count": len(unprocessed_pages),
        "first_unprocessed_page": unprocessed_pages[0] if unprocessed_pages else None,
        "stats": stats,
        "last_log_event": last_log_event,
        "warnings": warnings,
    }


def inspect_plan_artifact(
    output_dir: Path | str,
    *,
    include_items: bool = False,
    limit: int = 20,
    item_id: str | None = None,
    page_range: tuple[int, int] | None = None,
    level: int | None = None,
    source: str | None = None,
    attention_only: bool = False,
) -> dict[str, Any]:
    """bookmark plan과 review/Markdown artifact를 점진적으로 조사한다."""

    root = _require_directory(output_dir, "처리 output directory")
    if limit < 1:
        raise ValueError("limit은 1 이상이어야 한다.")
    if level is not None and level < 1:
        raise ValueError("level은 1 이상이어야 한다.")
    if page_range is not None:
        start_page, end_page = page_range
        if start_page < 1 or end_page < start_page:
            raise ValueError(
                "page range는 1 이상의 오름차순 범위여야 한다: "
                f"start={start_page}, end={end_page}"
            )
    warnings: list[str] = []
    plan_path = _first_existing_path(
        root / "bookmark_plan.json", root / "existing_outline_plan.json"
    )
    validation_path = root / "bookmark_plan_validation.json"
    plan = _read_optional_json(plan_path, warnings) if plan_path else None
    validation = _read_optional_json(validation_path, warnings)
    report_path = _find_processing_report(root)
    report = _read_optional_json(report_path, warnings) if report_path else None
    run_manifest_path = root / "run_manifest.json"
    run_manifest = _read_optional_json(run_manifest_path, warnings)

    if plan is None:
        warnings.append("bookmark plan artifact가 없다.")
        plan_items: list[Any] = []
    elif not isinstance(plan, list):
        warnings.append("bookmark plan artifact 형식이 list가 아니다.")
        plan_items = []
    else:
        plan_items = plan

    levels = sorted(
        {
            int(item["level"])
            for item in plan_items
            if isinstance(item, dict) and isinstance(item.get("level"), int)
        }
    )
    markdown_export = (
        report.get("markdown_export") if isinstance(report, dict) else None
    )
    markdown_manifest_path = _find_markdown_manifest(
        root,
        markdown_export,
        run_manifest,
        warnings,
    )
    markdown_manifest = _read_optional_json(markdown_manifest_path, warnings)
    markdown_manifest_summary = _summarize_markdown_manifest(
        markdown_manifest,
        warnings,
    )
    review_summary_path, review_items_path = _find_review_artifacts(
        root,
        run_manifest,
    )
    review_summary = _read_optional_json(review_summary_path, warnings)
    if review_summary is not None and not isinstance(review_summary, dict):
        warnings.append("bookmark review summary 형식이 JSON object가 아니다.")
        review_summary = None

    result = {
        "status": "available" if plan_path else "missing",
        "output_dir": str(root),
        "plan_path": str(plan_path) if plan_path else None,
        "bookmark_plan_item_count": len(plan_items),
        "bookmark_levels": levels,
        "validation_path": str(validation_path) if validation_path.is_file() else None,
        "validation": validation,
        "report_path": str(report_path) if report_path else None,
        "markdown_export": markdown_export,
        "markdown_manifest_path": (
            str(markdown_manifest_path) if markdown_manifest_path else None
        ),
        "markdown_manifest": markdown_manifest_summary,
        "bookmark_review_summary_path": (
            str(review_summary_path) if review_summary_path else None
        ),
        "bookmark_review_items_path": (
            str(review_items_path) if review_items_path else None
        ),
        "bookmark_review_summary": review_summary,
        "warnings": warnings,
    }
    query_requested = any(
        (
            include_items,
            item_id is not None,
            page_range is not None,
            level is not None,
            source is not None,
            attention_only,
        )
    )
    if not query_requested:
        return result
    if review_items_path is None:
        raise FileNotFoundError(
            "bookmark review item artifact가 없다. typography infer를 다시 실행해 "
            "bookmark_review_items.jsonl을 생성해야 한다."
        )

    review_items = _read_review_items(review_items_path)
    filtered = _filter_review_items(
        review_items,
        item_id=item_id,
        page_range=page_range,
        level=level,
        source=source,
        attention_only=attention_only,
    )
    if item_id is not None and not filtered:
        raise ValueError(f"bookmark review item ID를 찾지 못했다: {item_id}")
    selected = filtered[:limit]
    result["review_query"] = {
        "item_id": item_id,
        "page_range": list(page_range) if page_range is not None else None,
        "level": level,
        "source": source,
        "attention_only": attention_only,
        "limit": limit,
        "matched_item_count": len(filtered),
        "returned_item_count": len(selected),
        "truncated": len(filtered) > len(selected),
    }
    result["bookmark_review_items"] = selected
    return result


def inspect_compare_plans(
    plan_a: Path | str,
    plan_b: Path | str,
    *,
    page_tolerance: int | None = None,
    title_similarity_threshold: float | None = None,
) -> dict[str, Any]:
    """두 bookmark plan JSON을 title+page 매칭으로 비교한다."""

    path_a = _require_file(plan_a, "plan A")
    path_b = _require_file(plan_b, "plan B")
    before = load_bookmark_plan_json(path_a)
    after = load_bookmark_plan_json(path_b)
    kwargs: dict[str, Any] = {}
    if page_tolerance is not None:
        kwargs["page_tolerance"] = page_tolerance
    if title_similarity_threshold is not None:
        kwargs["title_similarity_threshold"] = title_similarity_threshold
    diff = compare_bookmark_plans(before, after, **kwargs)

    return {
        "plan_a_path": str(path_a),
        "plan_b_path": str(path_b),
        "plan_a_item_count": len(before),
        "plan_b_item_count": len(after),
        "added_count": diff.added_count,
        "removed_count": diff.removed_count,
        "matched_count": diff.matched_count,
        "unchanged_count": diff.unchanged_count,
        "moved_count": diff.moved_count,
        "level_changed_count": diff.level_changed_count,
        "source_changed_count": diff.source_changed_count,
        "entries": [_diff_entry_to_dict(entry) for entry in diff.entries],
    }


def inspect_markdown_tree(
    target: Path | str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Markdown tree manifest를 조사해 verdict, finding, 재시도 후보를 낸다.

    ``target``은 process output directory 또는 ``markdown_manifest.json``
    경로다. node 본문 파일은 읽지 않고 manifest만 사용한다.
    """

    if limit < 1:
        raise ValueError("limit은 1 이상이어야 한다.")
    warnings: list[str] = []
    manifest_path = _resolve_markdown_manifest_path(target, warnings)
    manifest = _load_markdown_manifest_json(manifest_path)

    source_info = (
        manifest.get("input") if isinstance(manifest.get("input"), dict) else {}
    )
    pdf_path = source_info.get("pdf_path")
    page_count = source_info.get("page_count")
    if not isinstance(page_count, int) or page_count < 1:
        raise ValueError(
            f"Markdown manifest의 page_count가 유효하지 않다: path={manifest_path}"
        )

    nodes = manifest.get("nodes")
    nodes = nodes if isinstance(nodes, list) else []
    node_count = manifest.get("node_count")
    node_count = node_count if isinstance(node_count, int) else len(nodes)

    graph = {
        "export_mode": manifest.get("export_mode"),
        "content_mode": manifest.get("content_mode"),
        "chosen_level": manifest.get("chosen_level"),
        "node_count": node_count,
        "root_count": manifest.get("root_count"),
        "constraint_satisfied": manifest.get("constraint_satisfied"),
        "fallback_used": manifest.get("fallback_used"),
        "fallback_reason": manifest.get("fallback_reason"),
    }

    levels = _levels_from_nodes(nodes)
    words_per_node = _words_per_node_stats(nodes)
    pages_per_node = _pages_per_node_stats(nodes, page_count, node_count)

    coverage_raw = manifest.get("coverage")
    coverage_raw = coverage_raw if isinstance(coverage_raw, dict) else {}
    coverage = _coverage_summary(coverage_raw, page_count)

    sources = dict(
        sorted(
            Counter(
                node.get("source") for node in nodes if isinstance(node, dict)
            ).items(),
            key=lambda item: (item[0] is None, str(item[0])),
        )
    )

    titles = _titles_summary(nodes, limit)

    validation_raw = manifest.get("validation")
    validation_raw = validation_raw if isinstance(validation_raw, dict) else {}
    validation = _validation_summary(validation_raw)

    findings = _markdown_findings(
        validation_raw=validation_raw,
        coverage=coverage,
        node_count=node_count,
        page_count=page_count,
        pages_per_node=pages_per_node,
        words_per_node=words_per_node,
        titles=titles,
        nodes=nodes,
        sources=sources,
        content_mode=graph["content_mode"],
    )
    verdict = findings[0]["code"] if findings else "ok"
    retry = _markdown_retry_candidates(findings, manifest, sources)

    return {
        "manifest_path": str(manifest_path),
        "source": {"pdf_path": pdf_path, "page_count": page_count},
        "graph": graph,
        "levels": levels,
        "words_per_node": words_per_node,
        "pages_per_node": pages_per_node,
        "coverage": coverage,
        "sources": sources,
        "titles": titles,
        "validation": validation,
        "findings": findings,
        "verdict": verdict,
        "retry": retry,
        "warnings": warnings,
    }


def _resolve_markdown_manifest_path(target: Path | str, warnings: list[str]) -> Path:
    """output directory 또는 manifest 경로에서 실제 manifest 경로를 찾는다.

    directory 아래 manifest가 여러 개 발견되면 그 경고를 버리지 않고
    ``warnings``에 담는다.
    """

    path = Path(target)
    if path.is_file():
        return path
    if path.is_dir():
        found = _find_markdown_manifest(path, None, None, warnings)
        if found is not None:
            return found
        raise FileNotFoundError(
            "Markdown manifest를 찾지 못했다: "
            f"directory={path}, checked={path / 'markdown_manifest.json'} "
            f"and {path}/**/markdown_manifest.json"
        )
    raise FileNotFoundError(
        f"Markdown manifest 또는 process output directory가 없다: {path}"
    )


def _load_markdown_manifest_json(path: Path) -> dict[str, Any]:
    """markdown manifest JSON을 읽고 실패 원인을 보존한 채로 검증한다.

    ``_read_optional_json``은 오류를 삼키고 None을 반환하므로 여기서는
    재사용하지 않고, 손상된 JSON/권한 오류/non-object를 서로 구분되는
    메시지로 낸다.
    """

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"Markdown manifest를 읽지 못했다(파일 접근 오류): path={path}, reason={exc}"
        ) from exc
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Markdown manifest가 유효한 JSON이 아니다: path={path}, reason={exc}"
        ) from exc
    if not isinstance(manifest, dict):
        raise ValueError(
            "Markdown manifest 형식이 JSON object가 아니다: "
            f"path={path}, actual_type={type(manifest).__name__}"
        )
    return manifest


def _levels_from_nodes(nodes: list[Any]) -> dict[int, int]:
    counts = Counter(
        node["level"]
        for node in nodes
        if isinstance(node, dict) and isinstance(node.get("level"), int)
    )
    return dict(sorted(counts.items()))


def _quantile(values: list[float], q: float) -> float:
    """linear interpolation quantile이다 (0<=q<=1)."""

    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _words_per_node_stats(nodes: list[Any]) -> dict[str, float | int | bool]:
    """node word_count 분포를 낸다.

    tree_graph export는 node.word_count를 채우지 않는다(항상 null). 이 경우
    ``has_data=False``로 signal 부재를 명시하고, 호출측은 word 기반 조건을
    평가하지 말아야 한다.
    """

    counts = [
        node["word_count"]
        for node in nodes
        if isinstance(node, dict) and isinstance(node.get("word_count"), int)
    ]
    if not counts:
        return {"min": 0, "median": 0, "p90": 0, "max": 0, "has_data": False}
    return {
        "min": min(counts),
        "median": statistics.median(counts),
        "p90": _quantile([float(value) for value in counts], 0.9),
        "max": max(counts),
        "has_data": True,
    }


def _pages_per_node_stats(
    nodes: list[Any], page_count: int, node_count: int
) -> dict[str, float]:
    spans = [
        node["pdf_end_page"] - node["pdf_start_page"] + 1
        for node in nodes
        if isinstance(node, dict)
        and isinstance(node.get("pdf_start_page"), int)
        and isinstance(node.get("pdf_end_page"), int)
    ]
    mean = page_count / node_count if node_count else 0.0
    if not spans:
        return {"median": 0.0, "max": 0.0, "mean": mean}
    return {
        "median": statistics.median(spans),
        "max": max(spans),
        "mean": mean,
    }


def _coverage_summary(coverage_raw: dict[str, Any], page_count: int) -> dict[str, Any]:
    assigned = coverage_raw.get("assigned_page_count") or 0
    unassigned = coverage_raw.get("unassigned_page_count") or 0
    duplicated = coverage_raw.get("duplicated_page_count") or 0
    empty_text = coverage_raw.get("empty_text_page_count") or 0
    unassigned_ratio = round(unassigned / page_count, 4) if page_count else 0.0
    return {
        "assigned_page_count": assigned,
        "unassigned_page_count": unassigned,
        "duplicated_page_count": duplicated,
        "empty_text_page_count": empty_text,
        "unassigned_ratio": unassigned_ratio,
    }


def _title_fragment_reasons(title: object) -> list[str]:
    """제목 문자열만으로 fragment 여부를 판정한다 (책/파일/출판사 무관)."""

    text = title if isinstance(title, str) else ""
    stripped = text.strip()
    reasons: list[str] = []
    if not stripped:
        reasons.append("empty")
        return reasons
    words = _WORD_RE.findall(stripped)
    if not words:
        reasons.append("no_word")
    elif len(words) <= 1:
        reasons.append("single_token")
    if stripped.count("|") >= 2:
        reasons.append("table_like")
    if "![image](" in stripped:
        reasons.append("image_placeholder")
    return reasons


def _titles_summary(nodes: list[Any], limit: int) -> dict[str, Any]:
    dict_nodes = [node for node in nodes if isinstance(node, dict)]
    total = len(dict_nodes)
    samples: list[dict[str, Any]] = []
    fragment_count = 0
    for node in dict_nodes:
        reasons = _title_fragment_reasons(node.get("title"))
        if not reasons:
            continue
        fragment_count += 1
        if len(samples) < limit:
            samples.append(
                {
                    "node_id": node.get("node_id"),
                    "level": node.get("level"),
                    "pdf_start_page": node.get("pdf_start_page"),
                    "title": node.get("title"),
                    "reasons": reasons,
                }
            )
    fragment_ratio = round(fragment_count / total, 4) if total else 0.0
    return {
        "total": total,
        "fragment_count": fragment_count,
        "fragment_ratio": fragment_ratio,
        "samples": samples,
    }


_INVALID_GRAPH_DETAIL_LIST_LIMIT = 5

_INVALID_GRAPH_COUNT_KEYS = (
    "yaml_parse_error_count",
    "duplicate_node_id_count",
    "duplicate_output_path_count",
    "dangling_link_count",
    "parent_child_asymmetry_count",
    "previous_next_asymmetry_count",
    "unreachable_node_count",
    "toc_unlinked_node_count",
)

_INVALID_GRAPH_OFFENDER_LIST_KEYS = ("yaml_errors", "dangling_links")


def _invalid_graph_detail(validation_raw: dict[str, Any]) -> str:
    # validation 실패의 counts와 첫 offender 목록만 남긴다.
    # 전체 validation dict의 Python repr은 parse할 수 없고, node 수가 많으면
    # 잘려서 완전하지도 않다. 대신 구조화한 count와 bounded된 offender list를
    # 낸다.
    counts = {
        key: validation_raw[key]
        for key in _INVALID_GRAPH_COUNT_KEYS
        if key in validation_raw
    }
    count_parts = ", ".join(f"{key}={value}" for key, value in counts.items())
    offender_parts = []
    for key in _INVALID_GRAPH_OFFENDER_LIST_KEYS:
        offenders = validation_raw.get(key)
        if not isinstance(offenders, list) or not offenders:
            continue
        first = offenders[:_INVALID_GRAPH_DETAIL_LIST_LIMIT]
        offender_parts.append(f"{key}(first {len(first)}/{len(offenders)})={first!r}")
    parts = ["validation.valid=False"]
    if count_parts:
        parts.append(count_parts)
    parts.extend(offender_parts)
    return ", ".join(parts)


def _validation_summary(validation_raw: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "valid" in validation_raw:
        result["valid"] = validation_raw["valid"]
    for key, value in validation_raw.items():
        if key == "valid":
            continue
        if (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and value != 0
        ):
            result[key] = value
    return result


def _fragment_level_detail(nodes: list[Any], titles: dict[str, Any]) -> str:
    """level별 fragment 비율을 관측 사실로 detail에 남긴다.

    fragment는 split level을 낮춰도 줄지 않을 수 있으므로, 어느 level에
    몰려 있는지를 detail에 남겨야 사용자가 level 조정으로 해결되는
    문제인지 스스로 판단할 수 있다.
    """

    per_level_total: Counter[int] = Counter()
    per_level_fragment: Counter[int] = Counter()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        level = node.get("level")
        if not isinstance(level, int):
            continue
        per_level_total[level] += 1
        if _title_fragment_reasons(node.get("title")):
            per_level_fragment[level] += 1
    parts = []
    for level in sorted(per_level_total):
        total = per_level_total[level]
        fragment = per_level_fragment[level]
        ratio = round(fragment / total, 3) if total else 0.0
        parts.append(f"level{level}={ratio}")
    level_detail = ", ".join(parts) if parts else "level별 분포 없음"
    return (
        f"fragment_ratio={titles['fragment_ratio']} "
        f"(threshold={FRAGMENTED_RATIO_THRESHOLD}, "
        f"fragment_count={titles['fragment_count']}/{titles['total']}). "
        f"level별 fragment 비율: {level_detail}. " + _FRAGMENT_LEVEL_NOTE
    )


def _markdown_findings(
    *,
    validation_raw: dict[str, Any],
    coverage: dict[str, Any],
    node_count: int,
    page_count: int,
    pages_per_node: dict[str, float],
    words_per_node: dict[str, float | int | bool],
    titles: dict[str, Any],
    nodes: list[Any],
    sources: dict[Any, int],
    content_mode: str | None,
) -> list[dict[str, Any]]:
    findings: dict[str, dict[str, Any]] = {}

    if validation_raw.get("valid") is False:
        findings["invalid_graph"] = {
            "code": "invalid_graph",
            "severity": FINDING_SEVERITY["invalid_graph"],
            "detail": _invalid_graph_detail(validation_raw),
            "cause": "graph_contract_violation",
        }

    unassigned_ratio = coverage["unassigned_ratio"]
    if unassigned_ratio >= UNASSIGNED_RATIO_BLOCKING_THRESHOLD:
        findings["uncovered"] = {
            "code": "uncovered",
            "severity": FINDING_SEVERITY["uncovered"],
            "detail": (
                f"unassigned_ratio={unassigned_ratio} "
                f"(threshold={UNASSIGNED_RATIO_BLOCKING_THRESHOLD})"
            ),
            "cause": "pages_outside_any_node",
        }

    # content_mode=inclusive는 부모/자식 page 중복을 설계상 허용한다. 그
    # 경우에는 duplicated_page_count가 정상 신호이므로 발화하지 않는다.
    duplicated_page_count = coverage["duplicated_page_count"]
    if duplicated_page_count > 0 and content_mode != "inclusive":
        findings["duplicated"] = {
            "code": "duplicated",
            "severity": FINDING_SEVERITY["duplicated"],
            "detail": (
                f"duplicated_page_count={duplicated_page_count}, "
                f"content_mode={content_mode}"
            ),
            "cause": "pages_owned_by_multiple_nodes",
        }

    mean_pages = pages_per_node["mean"]
    thin_triggered = (
        node_count <= THIN_MAX_NODE_COUNT and page_count >= THIN_MIN_PAGE_COUNT
    ) or mean_pages > THIN_MEAN_PAGES_PER_NODE_THRESHOLD
    if thin_triggered:
        only_existing_outline = bool(sources) and set(sources) == {"existing_outline"}
        cause = (
            "reused_existing_outline"
            if only_existing_outline
            else "sparse_heading_candidates"
        )
        findings["thin"] = {
            "code": "thin",
            "severity": FINDING_SEVERITY["thin"],
            "detail": (
                f"node_count={node_count}, page_count={page_count}, "
                f"pages_per_node.mean={mean_pages} "
                f"(threshold={THIN_MEAN_PAGES_PER_NODE_THRESHOLD})"
            ),
            "cause": cause,
        }

    # word_count는 tree_graph export에서 항상 null이라 신호가 없다. 신호가
    # 없으면 word 기반 조건은 평가하지 않고, page 기반 조건만으로 판정한다.
    has_word_data = bool(words_per_node.get("has_data"))
    words_median = words_per_node["median"]
    over_split_triggered = mean_pages < OVER_SPLIT_MEAN_PAGES_PER_NODE_THRESHOLD or (
        has_word_data and words_median < OVER_SPLIT_WORDS_PER_NODE_MEDIAN_THRESHOLD
    )
    # thin과 over_split은 반대 방향(node를 늘려라 vs 줄여라) retry를 요구한다.
    # 동시에 발화하면 severity 순서상 먼저 오는 thin만 남기고 over_split은
    # 내지 않는다.
    if over_split_triggered and not thin_triggered:
        word_detail = (
            f"words_per_node.median={words_median} "
            f"(threshold={OVER_SPLIT_WORDS_PER_NODE_MEDIAN_THRESHOLD})"
            if has_word_data
            else "words_per_node에 signal이 없다(word_count가 모두 null. "
            "tree_graph export의 알려진 한계다). page 기반 조건만 평가했다."
        )
        findings["over_split"] = {
            "code": "over_split",
            "severity": FINDING_SEVERITY["over_split"],
            "detail": (
                f"pages_per_node.mean={mean_pages} "
                f"(threshold={OVER_SPLIT_MEAN_PAGES_PER_NODE_THRESHOLD}), "
                + word_detail
            ),
            "cause": "heading_candidates_too_permissive",
        }

    if titles["fragment_ratio"] >= FRAGMENTED_RATIO_THRESHOLD:
        findings["fragmented"] = {
            "code": "fragmented",
            "severity": FINDING_SEVERITY["fragmented"],
            "detail": _fragment_level_detail(nodes, titles),
            "cause": "non_heading_text_selected",
        }

    return [findings[code] for code in FINDING_SEVERITY_ORDER if code in findings]


def _markdown_retry_candidates(
    findings: list[dict[str, Any]],
    manifest: dict[str, Any],
    sources: dict[Any, int],
) -> list[dict[str, Any]]:
    pdf_path = None
    input_info = manifest.get("input")
    if isinstance(input_info, dict):
        pdf_path = input_info.get("pdf_path")
    max_words_raw = manifest.get("max_words")
    max_words = (
        max_words_raw
        if isinstance(max_words_raw, int)
        else MarkdownSplitConfig().max_words
    )
    has_max_words = isinstance(max_words_raw, int)
    export_mode = manifest.get("export_mode")

    # thin과 over_split은 반대 방향(node를 늘려라 vs 줄여라) retry를 요구한다.
    # 두 finding이 동시에 성립할 수 있는 경우는 _markdown_findings가 이미
    # thin만 남기고 over_split을 걸러내므로(단일 exclusivity 지점), 여기서는
    # 중복으로 다시 강제하지 않는다.
    candidates: list[dict[str, Any]] = []
    seen_causes: set[str] = set()
    for finding in findings:
        cause = finding["cause"]
        if cause in seen_causes:
            continue
        seen_causes.add(cause)
        candidates.extend(
            _retry_candidates_for_cause(
                cause, pdf_path, max_words, has_max_words, export_mode
            )
        )
    return candidates


def _retry_command(pdf_path: str | None, overrides: list[str]) -> str | None:
    """사람이 읽을 human-facing command string이다.

    POSIX single-quoting(``shlex.quote``)을 쓰므로 bash/zsh와(값이 우연히
    맞아떨어지는 대부분의 경우) PowerShell에서는 그대로 실행 가능하지만,
    cmd.exe는 작은따옴표를 quoting으로 취급하지 않아 이 문자열을 그대로
    실행하면 공백/괄호가 섞인 경로에서 exit 2로 실패할 수 있다. shell 없이
    실행해야 하는 agent는 이 문자열이 아니라 ``command_argv``를 써야 한다.
    """

    if pdf_path is None or not overrides:
        return None
    quoted_path = shlex.quote(str(pdf_path))
    set_parts = " ".join(f"--set {shlex.quote(override)}" for override in overrides)
    return f"pdfbooktree process {quoted_path} {set_parts}"


def _retry_command_argv(pdf_path: str | None, overrides: list[str]) -> list[str] | None:
    """shell 없이(subprocess argv로) 그대로 실행 가능한 토큰 목록이다.

    quoting이 필요 없어 cmd.exe/PowerShell/POSIX shell 어디서도 argv로 직접
    실행하면 동일하게 동작한다. override가 없는 candidate는 ``command``와
    마찬가지로 ``None``이다.
    """

    if pdf_path is None or not overrides:
        return None
    argv = ["pdfbooktree", "process", str(pdf_path)]
    for override in overrides:
        argv.extend(["--set", override])
    return argv


def _retry_candidates_for_cause(
    cause: str,
    pdf_path: str | None,
    max_words: int,
    has_max_words: bool,
    export_mode: object,
) -> list[dict[str, Any]]:
    if cause == "reused_existing_outline":
        overrides = ["processing.skip_existing_bookmarks=false"]
        return [
            {
                "cause": cause,
                "overrides": overrides,
                "command": _retry_command(pdf_path, overrides),
                "command_argv": _retry_command_argv(pdf_path, overrides),
                "reason": _REUSED_OUTLINE_RETRY_REASON,
            }
        ]
    if cause == "sparse_heading_candidates":
        overrides = ["typography.heading_candidate_mode=position"]
        reason = _SPARSE_HEADING_RETRY_REASON
        if export_mode != "tree_graph":
            reason += _SPARSE_HEADING_OVER_SPLIT_FOLLOWUP
        return [
            {
                "cause": cause,
                "overrides": overrides,
                "command": _retry_command(pdf_path, overrides),
                "command_argv": _retry_command_argv(pdf_path, overrides),
                "reason": reason,
            }
        ]
    if cause == "heading_candidates_too_permissive":
        if export_mode == "tree_graph":
            # markdown.enabled=false인 tree_graph 경로에서는 markdown.max_words
            # override가 export 결과에 아무 영향을 주지 못한다. 효과 없는
            # override를 후보로 내지 않는다.
            return [
                {
                    "cause": cause,
                    "overrides": [],
                    "command": None,
                    "command_argv": None,
                    "reason": (
                        "export_mode=tree_graph는 markdown.enabled=false다. 이 "
                        "경로에서는 markdown.max_words override가 export 결과에 "
                        "아무 영향을 주지 못해 후보로 제시하지 않는다. node를 "
                        "더 큰 단위로 합치려면 markdown.enabled=true로 "
                        "length-limited split export를 사용해야 한다."
                    ),
                }
            ]
        if has_max_words:
            doubled_max_words = max_words * 2
            reason = (
                f"manifest에 기록된 현재 max_words={max_words}의 2배로 늘리면 "
                "over_split의 node가 더 큰 단위로 합쳐질 수 있다는 후보다. "
                "보장이 아니라 재시도 후보이며 재실행 후 다시 확인해야 한다."
            )
        else:
            doubled_max_words = MarkdownSplitConfig().max_words * 2
            reason = (
                "manifest에 max_words가 기록되어 있지 않아 현재 값을 알 수 "
                f"없다. 현재 값의 2배라고 말할 수 없으므로 config 기본값"
                f"({MarkdownSplitConfig().max_words})의 2배인 {doubled_max_words}를 "
                "시작점으로만 제시한다. 실제 현재 값을 먼저 확인하고 조정하라."
            )
        overrides = [f"markdown.max_words={doubled_max_words}"]
        return [
            {
                "cause": cause,
                "overrides": overrides,
                "command": _retry_command(pdf_path, overrides),
                "command_argv": _retry_command_argv(pdf_path, overrides),
                "reason": reason,
            }
        ]
    if cause == "non_heading_text_selected":
        overrides = ["typography.heading_candidate_mode=position_and_font"]
        return [
            {
                "cause": cause,
                "overrides": overrides,
                "command": _retry_command(pdf_path, overrides),
                "command_argv": _retry_command_argv(pdf_path, overrides),
                "reason": _NON_HEADING_TEXT_RETRY_REASON,
            }
        ]
    if cause == "pages_owned_by_multiple_nodes":
        return [
            {
                "cause": cause,
                "overrides": [],
                "command": None,
                "command_argv": None,
                "reason": (
                    "이 원인은 현재 config parameter로 직접 교정할 수 있는 "
                    "재시도 후보가 없다. manifest의 coverage.duplicated_pages, "
                    "validation 상세를 먼저 조사해야 한다."
                ),
            }
        ]
    if cause in ("pages_outside_any_node", "graph_contract_violation"):
        return [
            {
                "cause": cause,
                "overrides": [],
                "command": None,
                "command_argv": None,
                "reason": (
                    "이 원인은 현재 config parameter로 직접 교정할 수 있는 "
                    "재시도 후보가 없다. manifest의 coverage.unassigned_pages, "
                    "validation 상세를 먼저 조사해야 한다."
                ),
            }
        ]
    return []


def inspect_compare_markdown(
    manifest_a: Path | str,
    manifest_b: Path | str,
) -> dict[str, Any]:
    """두 Markdown manifest를 (level, page, normalized title) 기준으로 비교한다."""

    path_a = _require_file(manifest_a, "markdown manifest A")
    path_b = _require_file(manifest_b, "markdown manifest B")
    before_manifest = _load_markdown_manifest_for_compare(path_a)
    after_manifest = _load_markdown_manifest_for_compare(path_b)

    before_summary = _markdown_compare_summary(before_manifest)
    after_summary = _markdown_compare_summary(after_manifest)

    before_keys = _markdown_node_keys(before_manifest)
    after_keys = _markdown_node_keys(after_manifest)
    added = after_keys - before_keys
    removed = before_keys - after_keys

    delta: dict[str, Any] = {
        "node_count": after_summary["node_count"] - before_summary["node_count"],
        "chosen_level": _optional_int_delta(
            before_summary["chosen_level"], after_summary["chosen_level"]
        ),
        "words_per_node_median": _optional_float_delta(
            before_summary["words_per_node"],
            after_summary["words_per_node"],
        ),
        "pages_per_node_mean": (
            after_summary["pages_per_node"]["mean"]
            - before_summary["pages_per_node"]["mean"]
        ),
        "unassigned_ratio": (
            after_summary["coverage"]["unassigned_ratio"]
            - before_summary["coverage"]["unassigned_ratio"]
        ),
        "fragment_ratio": (
            after_summary["titles"]["fragment_ratio"]
            - before_summary["titles"]["fragment_ratio"]
        ),
        "verdict_changed": before_summary["verdict"] != after_summary["verdict"],
        "added_node_count": len(added),
        "removed_node_count": len(removed),
    }

    return {
        "before": _markdown_compare_view(before_summary),
        "after": _markdown_compare_view(after_summary),
        "delta": delta,
    }


def _optional_int_delta(before: int | None, after: int | None) -> int | None:
    if before is None or after is None:
        return None
    return after - before


def _optional_float_delta(
    before_stats: dict[str, float | int | bool],
    after_stats: dict[str, float | int | bool],
) -> float | None:
    # 양쪽 다 word_count signal이 있을 때만 median 차이를 낸다. 한쪽이라도
    # has_data=False(예: tree_graph export)면 "0 word"로 읽히는 거짓 delta를
    # 만들지 않고 signal 부재를 그대로 None으로 전파한다.
    if not before_stats.get("has_data") or not after_stats.get("has_data"):
        return None
    return float(after_stats["median"]) - float(before_stats["median"])


def _load_markdown_manifest_for_compare(path: Path) -> dict[str, Any]:
    manifest = _load_markdown_manifest_json(path)
    if "nodes" not in manifest:
        raise ValueError(f"Markdown manifest 형식이 아니다(nodes 없음): path={path}")
    return manifest


def _markdown_compare_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    source_info = (
        manifest.get("input") if isinstance(manifest.get("input"), dict) else {}
    )
    page_count = source_info.get("page_count")
    page_count = page_count if isinstance(page_count, int) else 0
    nodes = manifest.get("nodes")
    nodes = nodes if isinstance(nodes, list) else []
    node_count = manifest.get("node_count")
    node_count = node_count if isinstance(node_count, int) else len(nodes)

    words_per_node = _words_per_node_stats(nodes)
    pages_per_node = _pages_per_node_stats(nodes, page_count, node_count)
    coverage_raw = manifest.get("coverage")
    coverage_raw = coverage_raw if isinstance(coverage_raw, dict) else {}
    coverage = _coverage_summary(coverage_raw, page_count)
    titles = _titles_summary(nodes, limit=0)
    validation_raw = manifest.get("validation")
    validation_raw = validation_raw if isinstance(validation_raw, dict) else {}

    sources = Counter(node.get("source") for node in nodes if isinstance(node, dict))
    findings = _markdown_findings(
        validation_raw=validation_raw,
        coverage=coverage,
        node_count=node_count,
        page_count=page_count,
        pages_per_node=pages_per_node,
        words_per_node=words_per_node,
        titles=titles,
        nodes=nodes,
        sources=dict(sources),
        content_mode=manifest.get("content_mode"),
    )
    verdict = findings[0]["code"] if findings else "ok"

    return {
        "node_count": node_count,
        "chosen_level": manifest.get("chosen_level"),
        "words_per_node": words_per_node,
        "pages_per_node": pages_per_node,
        "coverage": coverage,
        "titles": titles,
        "verdict": verdict,
    }


def _markdown_compare_view(summary: dict[str, Any]) -> dict[str, Any]:
    has_word_data = bool(summary["words_per_node"].get("has_data"))
    return {
        "node_count": summary["node_count"],
        "chosen_level": summary["chosen_level"],
        # tree_graph export는 word_count를 채우지 않는다(has_data=False). 그
        # 경우 median을 0으로 내면 "word 수가 0"으로 읽히므로, signal 부재를
        # None으로 명시한다.
        "words_per_node_median": (
            summary["words_per_node"]["median"] if has_word_data else None
        ),
        "words_per_node_has_data": has_word_data,
        "pages_per_node_mean": summary["pages_per_node"]["mean"],
        "unassigned_ratio": summary["coverage"]["unassigned_ratio"],
        "fragment_ratio": summary["titles"]["fragment_ratio"],
        "verdict": summary["verdict"],
    }


def _markdown_node_keys(manifest: dict[str, Any]) -> set[tuple[Any, Any, str]]:
    nodes = manifest.get("nodes")
    nodes = nodes if isinstance(nodes, list) else []
    keys: set[tuple[Any, Any, str]] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        keys.add(
            (
                node.get("level"),
                node.get("pdf_start_page"),
                _normalize_title(node.get("title")),
            )
        )
    return keys


def _normalize_title(title: object) -> str:
    text = title if isinstance(title, str) else ""
    normalized = unicodedata.normalize("NFKC", text).strip().casefold()
    return " ".join(normalized.split())


def _diff_entry_to_dict(entry: PlanDiffEntry) -> dict[str, Any]:
    return {
        "status": entry.status,
        "title_similarity": entry.title_similarity,
        "page_changed": entry.page_changed,
        "level_changed": entry.level_changed,
        "source_changed": entry.source_changed,
        "before": _plan_item_to_dict(entry.before),
        "after": _plan_item_to_dict(entry.after),
    }


def _plan_item_to_dict(item: BookmarkPlanItem | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "title": item.title,
        "level": item.level,
        "pdf_page": item.pdf_page,
        "source": item.source,
    }


def _require_file(path_value: Path | str, label: str) -> Path:
    path = Path(path_value)
    if not path.is_file():
        raise FileNotFoundError(f"{label} 파일이 없다: {path}")
    return path


def _require_directory(path_value: Path | str, label: str) -> Path:
    path = Path(path_value)
    if not path.is_dir():
        raise FileNotFoundError(f"{label}가 없다: {path}")
    return path


def _read_optional_json(path: Path | None, warnings: list[str]) -> Any | None:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"JSON artifact를 읽지 못했다: path={path}, reason={exc}")
        return None


def _path_from_config(value: object) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


def _pdf_page_count(path: Path | None, warnings: list[str]) -> int | None:
    if path is None:
        return None
    if not path.is_file():
        warnings.append(f"OCR config의 input PDF를 찾지 못했다: {path}")
        return None
    try:
        with fitz.open(path) as document:
            return document.page_count
    except fitz.FileDataError as exc:
        warnings.append(f"OCR config의 input PDF를 열지 못했다: {exc}")
        return None


def _target_pages(
    config: dict[str, Any], total_pages: int | None, warnings: list[str]
) -> list[int]:
    configured_pages = config.get("pages")
    if isinstance(configured_pages, list) and all(
        isinstance(page, int) and page >= 1 for page in configured_pages
    ):
        return sorted(dict.fromkeys(configured_pages))
    if total_pages is None:
        warnings.append("OCR target page 수를 알 수 없다.")
        return []
    return list(range(1, total_pages + 1))


def _json_file_count(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for _ in directory.glob("*.json"))


def _read_insertable_pages(directory: Path) -> tuple[list[int], int]:
    if not directory.is_dir():
        return [], 0
    pages: list[int] = []
    invalid_count = 0
    for path in directory.glob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("pdf_page")
            if not isinstance(value, int) or value < 1:
                raise ValueError("pdf_page가 1 이상의 정수가 아니다.")
        except (OSError, ValueError, json.JSONDecodeError):
            invalid_count += 1
        else:
            pages.append(value)
    return pages, invalid_count


def _inspect_ocr_stats(root: Path) -> dict[str, dict[str, Any]]:
    names = ("ocr_page_stats.jsonl", "ocr_element_stats.jsonl", "ocr_line_stats.jsonl")
    return {
        name: {
            "exists": (path := root / name).is_file(),
            "row_count": _line_count(path),
        }
        for name in names
    }


def _line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8") as file:
        return sum(1 for line in file if line.strip())


def _read_last_log_event(path: Path, warnings: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        if not lines:
            return None
        event = json.loads(lines[-1])
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"OCR log 마지막 event를 읽지 못했다: {exc}")
        return None
    return {
        key: event.get(key)
        for key in ("event", "level", "pdf_page", "message", "elapsed_sec")
    }


def _ocr_status(
    artifact_dir: Path,
    total_pages: int | None,
    target_pages: list[int],
    insertable_pages: set[int],
    output_exists: bool,
) -> str:
    if output_exists and target_pages and set(target_pages) <= insertable_pages:
        return "complete"
    if artifact_dir.exists() and (total_pages is not None or insertable_pages):
        return "partial"
    return "missing"


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _first_existing_path(*paths: Path) -> Path | None:
    return next((path for path in paths if path.is_file()), None)


def _find_processing_report(root: Path) -> Path | None:
    return next(iter(sorted(root.glob("*_report.json"))), None)


def _find_review_artifacts(
    root: Path,
    run_manifest: object,
) -> tuple[Path | None, Path | None]:
    """run manifest와 output root에서 review summary/items를 찾는다."""

    artifact_paths = (
        run_manifest.get("artifact_paths") if isinstance(run_manifest, dict) else None
    )

    def find(name: str, filename: str) -> Path | None:
        candidates: list[Path] = []
        if isinstance(artifact_paths, dict):
            _append_artifact_path(candidates, root, artifact_paths.get(name))
        candidates.append(root / filename)
        return next((path for path in candidates if path.is_file()), None)

    return (
        find("bookmark_review_summary", "bookmark_review_summary.json"),
        find("bookmark_review_items", "bookmark_review_items.jsonl"),
    )


def _read_review_items(path: Path) -> list[dict[str, Any]]:
    """독립 JSON object인 review JSONL을 검증하며 읽는다."""

    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        "bookmark review JSONL을 읽지 못했다: "
                        f"path={path}, line={line_number}, reason={exc}"
                    ) from exc
                if not isinstance(row, dict):
                    raise ValueError(
                        "bookmark review JSONL 행이 object가 아니다: "
                        f"path={path}, line={line_number}"
                    )
                rows.append(row)
    except OSError as exc:
        raise ValueError(
            f"bookmark review JSONL을 읽지 못했다: path={path}, reason={exc}"
        ) from exc
    return rows


def _filter_review_items(
    items: list[dict[str, Any]],
    *,
    item_id: str | None,
    page_range: tuple[int, int] | None,
    level: int | None,
    source: str | None,
    attention_only: bool,
) -> list[dict[str, Any]]:
    """review item에 CLI/Python API filter를 순서대로 적용한다."""

    result: list[dict[str, Any]] = []
    for item in items:
        if item_id is not None and item.get("node_id") != item_id:
            continue
        pdf_page = item.get("pdf_page")
        if page_range is not None and (
            not isinstance(pdf_page, int)
            or not page_range[0] <= pdf_page <= page_range[1]
        ):
            continue
        if level is not None and item.get("level") != level:
            continue
        if source is not None and item.get("source") != source:
            continue
        if attention_only and not item.get("attention_signals"):
            continue
        result.append(item)
    return result


def _find_markdown_manifest(
    root: Path,
    markdown_export: object,
    run_manifest: object,
    warnings: list[str],
) -> Path | None:
    """report, run manifest와 output tree에서 graph manifest를 찾는다."""

    candidates: list[Path] = []
    if isinstance(markdown_export, dict):
        _append_artifact_path(candidates, root, markdown_export.get("manifest_path"))
    if isinstance(run_manifest, dict):
        artifact_paths = run_manifest.get("artifact_paths")
        if isinstance(artifact_paths, dict):
            _append_artifact_path(
                candidates,
                root,
                artifact_paths.get("markdown_manifest"),
            )
    candidates.append(root / "markdown_manifest.json")
    for path in candidates:
        if path.is_file():
            return path

    discovered = sorted(root.rglob("markdown_manifest.json"))
    if len(discovered) > 1:
        warnings.append(
            f"Markdown manifest가 여러 개라 첫 경로를 사용한다: count={len(discovered)}"
        )
    return discovered[0] if discovered else None


def _append_artifact_path(candidates: list[Path], root: Path, value: object) -> None:
    """문자열 artifact path를 absolute/relative 후보로 추가한다."""

    if not isinstance(value, str) or not value:
        return
    path = Path(value)
    candidates.append(path if path.is_absolute() else root / path)


def _summarize_markdown_manifest(
    value: object,
    warnings: list[str],
) -> dict[str, Any] | None:
    """node 파일을 읽지 않고 graph 계약과 coverage 핵심값만 반환한다."""

    if value is None:
        return None
    if not isinstance(value, dict):
        warnings.append("Markdown manifest 형식이 JSON object가 아니다.")
        return None
    return {
        "schema_version": value.get("schema_version"),
        "export_mode": value.get("export_mode"),
        "content_mode": value.get("content_mode"),
        "node_count": value.get("node_count"),
        "root_count": value.get("root_count"),
        "chosen_level": value.get("chosen_level"),
        "constraint_satisfied": value.get("constraint_satisfied"),
        "fallback_used": value.get("fallback_used"),
        "validation": value.get("validation"),
        "coverage": value.get("coverage"),
        "manifest_warnings": value.get("warnings"),
    }
