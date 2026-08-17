"""bookmark plan을 agent가 점진적으로 검토할 review evidence로 변환한다."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pdfbooktree.models import BookmarkInferenceResult, OutlineQualityAssessment
from pdfbooktree.typography.tiers import assign_tier
from pdfbooktree.utils.text_normalize import normalize_text

BOOKMARK_REVIEW_SCHEMA_VERSION = 1
BOOKMARK_REVIEW_PREVIEW_CHAR_LIMIT = 800
BOOKMARK_REVIEW_SURROUNDING_LINE_RADIUS = 2


def build_bookmark_review(
    inference: BookmarkInferenceResult,
    *,
    input_pdf: Path | None = None,
    total_pages: int | None = None,
    quality: OutlineQualityAssessment | None = None,
    existing_outline_plan_available: bool = False,
    markdown_manifest_available: bool = False,
    reuse_rejected_reason: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """추론 결과에서 review summary와 item별 근거를 만든다.

    attention signal은 내용 품질의 판정이 아니라 사람이 먼저 확인할 위치를
    나타낸다. 최종 plan의 source, confidence와 evidence는 변형하지 않는다.
    ``markdown_manifest_available``은 호출 시점에 Markdown tree manifest가
    이미 존재하는지를 나타내며, 존재할 때만 ``next_commands``에
    ``inspect markdown``을 추가 후보로 남긴다. ``reuse_rejected_reason``은
    ``resolve_existing_outline_action()``이 기존 outline을 재사용하지 않은
    이유(``invalid_structure``, ``skip_existing_bookmarks_disabled``,
    ``low_quality_replace``)를 그대로 전달받아 ``existing_outline`` 섹션에
    남긴다 - typography 추론으로 넘어온 원인이 quality가 아니라 구조 오류일
    때도 agent가 구분할 수 있게 한다.
    """

    candidate_index = _candidate_index(inference)
    lines_by_page = _ordered_lines_by_page(inference)
    resolved_total_pages = total_pages or _inferred_total_pages(
        inference, lines_by_page
    )
    items = _build_review_items(inference, candidate_index, lines_by_page)
    summary = _build_review_summary(
        inference,
        items,
        lines_by_page,
        resolved_total_pages,
        input_pdf=input_pdf,
        quality=quality,
        existing_outline_plan_available=existing_outline_plan_available,
        markdown_manifest_available=markdown_manifest_available,
        reuse_rejected_reason=reuse_rejected_reason,
    )
    return summary, items


def _candidate_key(source: str, pdf_page: int, title: str) -> tuple[str, int, str]:
    return source, pdf_page, normalize_text(title).casefold()


def _candidate_index(
    inference: BookmarkInferenceResult,
) -> dict[tuple[str, int, str], list[dict[str, Any]]]:
    index: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for position, candidate in enumerate(inference.heading_candidates):
        key = _candidate_key(candidate.source, candidate.pdf_page, candidate.title)
        index[key].append(
            {
                "artifact": "heading_candidates.json",
                "index": position,
                "kind": "heading_candidate",
                "candidate": candidate,
            }
        )
    for position, candidate in enumerate(inference.fallback_candidates):
        key = _candidate_key(
            "geometry_position_fallback",
            candidate.pdf_page,
            candidate.title,
        )
        index[key].append(
            {
                "artifact": "position_fallback_candidates.json",
                "index": position,
                "kind": "position_fallback_candidate",
                "candidate": candidate,
            }
        )
    return index


def _ordered_lines_by_page(
    inference: BookmarkInferenceResult,
) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)
    for line in inference.lines:
        grouped[line.pdf_page].append(line)
    for page_lines in grouped.values():
        page_lines.sort(key=lambda line: (line.y0, line.x0))
    return grouped


def _inferred_total_pages(
    inference: BookmarkInferenceResult,
    lines_by_page: dict[int, list[Any]],
) -> int:
    pages = [item.pdf_page for item in inference.plan]
    pages.extend(lines_by_page)
    return max(pages, default=0)


def _build_review_items(
    inference: BookmarkInferenceResult,
    candidate_index: dict[tuple[str, int, str], list[dict[str, Any]]],
    lines_by_page: dict[int, list[Any]],
) -> list[dict[str, Any]]:
    title_counts = Counter(
        normalize_text(item.title).casefold() for item in inference.plan
    )
    page_counts = Counter(item.pdf_page for item in inference.plan)
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(inference.plan):
        order = index + 1
        key = _candidate_key(item.source, item.pdf_page, item.title)
        matches = candidate_index.get(key, [])
        # normalize_bookmark_plan()은 같은 page/title의 첫 후보를 보존하므로
        # candidate artifact의 원래 순서에서도 첫 항목을 canonical 근거로 쓴다.
        match = matches[0] if matches else None
        candidate = match["candidate"] if match is not None else None
        page_lines = lines_by_page.get(item.pdf_page, [])
        preview, preview_truncated = _page_preview(page_lines)
        signals = _attention_signals(
            item.title,
            item.source,
            item.pdf_page,
            title_count=title_counts[key[2]],
            page_item_count=page_counts[item.pdf_page],
            page_line_count=len(page_lines),
            candidate_match_count=len(matches),
            previous_page=inference.plan[index - 1].pdf_page if index else None,
        )
        rows.append(
            {
                "schema_version": BOOKMARK_REVIEW_SCHEMA_VERSION,
                "node_id": f"n{order:04d}",
                "order": order,
                "title": item.title,
                "level": item.level,
                "pdf_page": item.pdf_page,
                "source": item.source,
                "confidence": item.confidence,
                "confidence_semantics": (
                    "pipeline evidence 값이며 bookmark 내용 품질의 합격 확률이 아니다"
                ),
                "evidence": list(item.evidence),
                "previous_node_id": f"n{order - 1:04d}" if order > 1 else None,
                "next_node_id": (
                    f"n{order + 1:04d}" if order < len(inference.plan) else None
                ),
                "candidate_match_status": _candidate_match_status(len(matches)),
                "candidate_ref": _candidate_ref(match),
                "candidate_alternative_refs": [
                    _candidate_ref(alternative) for alternative in matches[1:]
                ],
                "candidate_geometry": _candidate_geometry(
                    candidate,
                    page_lines,
                    inference.font_tiers.cut_points,
                    inference.height_tiers.cut_points,
                ),
                "page_line_count": len(page_lines),
                "page_text_preview": preview,
                "page_text_preview_truncated": preview_truncated,
                "surrounding_lines": _surrounding_lines(page_lines, candidate),
                "source_artifacts": {
                    "whole_book_lines": "whole_book_lines.jsonl",
                    "bookmark_plan": "bookmark_plan.json",
                },
                "attention_signals": signals,
            }
        )
    return rows


def _candidate_match_status(match_count: int) -> str:
    return "matched" if match_count >= 1 else "missing"


def _candidate_ref(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if match is None:
        return None
    return {
        "artifact": match["artifact"],
        "index": match["index"],
        "kind": match["kind"],
    }


def _candidate_geometry(
    candidate: Any | None,
    page_lines: list[Any],
    font_cut_points: list[float],
    height_cut_points: list[float],
) -> dict[str, Any] | None:
    if candidate is None:
        return None
    fields = (
        "tier",
        "y0",
        "y1",
        "merged_line_count",
        "support_pages",
        "isolation_ratio",
        "font_ratio",
    )
    geometry = {
        name: getattr(candidate, name) for name in fields if hasattr(candidate, name)
    }
    closest_line = _closest_line(page_lines, candidate)
    geometry["font_tier"] = (
        getattr(candidate, "tier")
        if hasattr(candidate, "tier")
        else assign_tier(closest_line.font_size, font_cut_points)
        if closest_line is not None
        else None
    )
    geometry["height_tier"] = (
        assign_tier(closest_line.height, height_cut_points)
        if closest_line is not None
        else None
    )
    return geometry


def _closest_line(page_lines: list[Any], candidate: Any | None) -> Any | None:
    if not page_lines:
        return None
    candidate_y = float(getattr(candidate, "y0", 0.0))
    return min(page_lines, key=lambda line: abs(line.y0 - candidate_y))


def _page_preview(page_lines: list[Any]) -> tuple[str, bool]:
    text = normalize_text(" ".join(line.text for line in page_lines))
    if len(text) <= BOOKMARK_REVIEW_PREVIEW_CHAR_LIMIT:
        return text, False
    return text[:BOOKMARK_REVIEW_PREVIEW_CHAR_LIMIT].rstrip() + "…", True


def _surrounding_lines(
    page_lines: list[Any], candidate: Any | None
) -> list[dict[str, Any]]:
    if not page_lines:
        return []
    closest_line = _closest_line(page_lines, candidate)
    center = page_lines.index(closest_line)
    start = max(0, center - BOOKMARK_REVIEW_SURROUNDING_LINE_RADIUS)
    end = min(len(page_lines), center + BOOKMARK_REVIEW_SURROUNDING_LINE_RADIUS + 1)
    return [
        {
            "text": line.text,
            "y0": line.y0,
            "y1": line.y1,
            "font_size": line.font_size,
            "height": line.height,
            "is_bold": line.is_bold,
        }
        for line in page_lines[start:end]
    ]


def _attention_signals(
    title: str,
    source: str,
    pdf_page: int,
    *,
    title_count: int,
    page_item_count: int,
    page_line_count: int,
    candidate_match_count: int,
    previous_page: int | None,
) -> list[str]:
    signals: list[str] = []
    normalized_title = normalize_text(title)
    if source == "geometry_position_fallback":
        signals.append("position_fallback_source")
    if re.fullmatch(r"[\d\W_]+", normalized_title, flags=re.UNICODE):
        signals.append("numeric_only_title")
    if title_count > 1:
        signals.append("repeated_title")
    if len(normalized_title) > 100:
        signals.append("long_title")
    if page_item_count > 1:
        signals.append("same_page_bookmarks")
    if page_line_count == 0:
        signals.append("no_typography_text_on_page")
    elif page_line_count <= 2:
        signals.append("low_typography_line_count")
    if candidate_match_count == 0:
        signals.append("candidate_match_missing")
    elif candidate_match_count > 1:
        signals.append("duplicate_candidates_collapsed")
    if previous_page is not None and pdf_page - previous_page > 20:
        signals.append("long_page_gap_from_previous")
    return signals


def _build_review_summary(
    inference: BookmarkInferenceResult,
    items: list[dict[str, Any]],
    lines_by_page: dict[int, list[Any]],
    total_pages: int,
    *,
    input_pdf: Path | None,
    quality: OutlineQualityAssessment | None,
    existing_outline_plan_available: bool,
    markdown_manifest_available: bool = False,
    reuse_rejected_reason: str | None = None,
) -> dict[str, Any]:
    signal_counts = Counter(
        signal for item in items for signal in item["attention_signals"]
    )
    title_counts = Counter(
        normalize_text(item.title).casefold() for item in inference.plan
    )
    priority_items = sorted(
        (item for item in items if item["attention_signals"]),
        key=lambda item: (-len(item["attention_signals"]), item["order"]),
    )
    mapping = Counter(item["candidate_match_status"] for item in items)
    warnings = []
    duplicate_candidate_item_count = sum(
        bool(item["candidate_alternative_refs"]) for item in items
    )
    if mapping["missing"]:
        warnings.append(
            "일부 plan item을 candidate artifact와 연결하지 못했다: "
            f"missing={mapping['missing']}"
        )
    source_counts = Counter(item.source for item in inference.plan)
    plan_count = len(inference.plan)
    return {
        "schema_version": BOOKMARK_REVIEW_SCHEMA_VERSION,
        "review_policy": (
            "attention signal은 검토 순서를 위한 정보이며 품질 합격/불합격 판정이 아니다"
        ),
        "confidence_semantics": (
            "pipeline evidence 값이며 bookmark 내용 품질의 합격 확률이 아니다"
        ),
        "input": {
            "pdf_path": str(input_pdf) if input_pdf is not None else None,
            "page_count": total_pages,
        },
        "plan_item_count": plan_count,
        "level_counts": dict(
            sorted(Counter(item.level for item in inference.plan).items())
        ),
        "source_counts": dict(sorted(source_counts.items())),
        "source_ratios": {
            source: round(count / plan_count, 6) if plan_count else 0.0
            for source, count in sorted(source_counts.items())
        },
        "candidate_counts": {
            "heading": len(inference.heading_candidates),
            "position_fallback": len(inference.fallback_candidates),
            "final_plan": len(inference.plan),
        },
        "candidate_mapping": {
            "matched_count": mapping["matched"],
            "missing_count": mapping["missing"],
            "ambiguous_count": 0,
            "duplicate_candidates_collapsed_item_count": (
                duplicate_candidate_item_count
            ),
        },
        "page_density_windows": _density_windows(inference, total_pages),
        "title_statistics": {
            "numeric_only_count": sum(
                "numeric_only_title" in item["attention_signals"] for item in items
            ),
            "long_title_count": sum(
                "long_title" in item["attention_signals"] for item in items
            ),
            "repeated_title_value_count": sum(
                count > 1 for count in title_counts.values()
            ),
        },
        "text_statistics": {
            "page_with_no_typography_text_count": sum(
                page not in lines_by_page for page in range(1, total_pages + 1)
            ),
            "page_with_at_most_two_lines_count": sum(
                len(lines_by_page.get(page, [])) <= 2
                for page in range(1, total_pages + 1)
            ),
        },
        "existing_outline": {
            "present": quality is not None or existing_outline_plan_available,
            "is_low_quality": quality.is_low_quality if quality is not None else None,
            "reasons": list(quality.reasons) if quality is not None else [],
            "quality_artifact": (
                "existing_outline_quality.json" if quality is not None else None
            ),
            "plan_artifact": (
                "existing_outline_plan.json"
                if existing_outline_plan_available
                else None
            ),
            "reuse_rejected_reason": reuse_rejected_reason,
        },
        "attention": {
            "item_count": len(priority_items),
            "signal_counts": dict(sorted(signal_counts.items())),
            "priority_items": [
                {
                    "node_id": item["node_id"],
                    "title": item["title"],
                    "pdf_page": item["pdf_page"],
                    "signals": item["attention_signals"],
                }
                for item in priority_items[:20]
            ],
        },
        "artifacts": {
            "items": "bookmark_review_items.jsonl",
            "bookmark_plan": "bookmark_plan.json",
            "whole_book_lines": "whole_book_lines.jsonl",
            "heading_candidates": "heading_candidates.json",
            "position_fallback_candidates": "position_fallback_candidates.json",
        },
        "next_commands": _next_commands(input_pdf, markdown_manifest_available),
        "warnings": warnings,
    }


def _density_windows(
    inference: BookmarkInferenceResult, total_pages: int
) -> list[dict[str, int]]:
    windows: list[dict[str, int]] = []
    for start in range(1, total_pages + 1, 50):
        end = min(total_pages, start + 49)
        windows.append(
            {
                "start_pdf_page": start,
                "end_pdf_page": end,
                "bookmark_count": sum(
                    start <= item.pdf_page <= end for item in inference.plan
                ),
            }
        )
    return windows


def _next_commands(
    input_pdf: Path | None, markdown_manifest_available: bool = False
) -> list[str]:
    pdf = str(input_pdf) if input_pdf is not None else "<PDF>"
    commands = [
        "uv run pdfbooktree inspect plan <RUN> --attention-only --limit 20 --format json",
        "uv run pdfbooktree inspect plan <RUN> --item-id n0001 --format json",
        f'uv run pdfbooktree inspect text "{pdf}" --pages 1 --format json',
    ]
    if markdown_manifest_available:
        commands.append("uv run pdfbooktree inspect markdown <RUN> --format json")
    return commands
