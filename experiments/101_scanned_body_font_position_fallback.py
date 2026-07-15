"""experiment 101: scanned PDF에서 body-font position fallback을 검증한다.

experiment 100과 같은 조립 규칙을 OCR/scanned 책에 적용한다. 세 책 모두
신뢰할 embedded gold가 없으므로 precision을 계산하지 않고, font 골격과 position
fallback을 합친 들여쓰기 TXT를 만들어 사람이 직접 eye check하도록 한다.

실행:
    uv run python experiments/101_scanned_body_font_position_fallback.py
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import fitz
import numpy as np

from pdfbooktree.config import TypographyConfig
from pdfbooktree.outline.plan import normalize_bookmark_plan
from pdfbooktree.typography.bpe import BpeHeading, infer_bpe_outline
from pdfbooktree.typography.geometry import (
    _body_spacing_band,
    _build_anchor_patterns,
    _build_chunks,
    _cluster_patterns,
    _merge_adjacent_non_body_chunks,
    _merge_printed_line_fragments,
    _tier_for_size,
    classify_font_tiers_by_text_coverage,
    compute_geometry_font_tier_set,
)
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "101_scanned_body_font_position_fallback"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
INTEREST_DIR = ROOT_DIR / "showcase" / "outputs" / "017_interest_economics_ocr_overlay"
STATISTICS_DIR = (
    ROOT_DIR / "showcase" / "outputs" / "018_statistics_principles_ocr_overlay"
)
DATASETS = [
    {
        "key": "interest_economics",
        "pdf": INTEREST_DIR / "interest_economics_ocr.pdf",
    },
    {
        "key": "statistics_principles",
        "pdf": STATISTICS_DIR / "statistics_principles_ocr.pdf",
    },
    {
        "key": "hankyung_reading",
        "pdf": ROOT_DIR
        / "data"
        / "scanned-pdf-not-indexed"
        / "한경_읽는법_-_한국경제신문-compressed[econ macro book].pdf",
    },
]

BODY_TEXT_COVERAGE = 0.95
POSITION_MIN_PAGES = 5
FONT_MAX_WORDS = 20
TITLE_MATCH_THRESHOLD = 0.55
STRICT_BODY_RATIO_LOW = 0.97
STRICT_BODY_RATIO_HIGH = 1.03


@dataclass(frozen=True)
class CurrentAnchor:
    """following layout을 제외한 현재 chunk의 2D anchor다."""

    current: Any
    values: tuple[float, float]


def display_text(text: str) -> str:
    """OCR overlay의 CP949 mojibake를 가능할 때 복원한다."""

    try:
        return text.encode("latin1").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def normalize_title(text: str) -> str:
    """한글과 영숫자를 보존해 제목을 정규화한다."""

    return re.sub(r"[^\w]+", " ", display_text(text).casefold()).strip()


def title_score(left: str, right: str) -> float:
    """포함 관계, 문자 순서, token 중복 중 가장 강한 제목 유사도를 반환한다."""

    left_norm = normalize_title(left)
    right_norm = normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if min(len(left_norm), len(right_norm)) >= 4 and (
        left_norm in right_norm or right_norm in left_norm
    ):
        return 1.0
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    overlap = (
        2.0 * len(left_tokens & right_tokens) / (len(left_tokens) + len(right_tokens))
        if left_tokens and right_tokens
        else 0.0
    )
    return max(sequence, overlap)


def cluster_statistics(clusters: list[list[Any]]) -> list[dict[str, Any]]:
    """position cluster support와 isolation을 계산한다."""

    stats = []
    for cluster_id, cluster in enumerate(clusters, start=1):
        values = np.asarray([pattern.values for pattern in cluster], dtype=float)
        center = np.median(values, axis=0)
        radius = float(np.max(np.abs(values - center)))
        stats.append(
            {
                "cluster_id": cluster_id,
                "cluster": cluster,
                "center": center,
                "radius": radius,
                "diameter": float(np.max(np.ptp(values, axis=0))),
                "support_pages": len({pattern.current.pdf_page for pattern in cluster}),
            }
        )
    centers = np.asarray([stat["center"] for stat in stats], dtype=float)
    for index, stat in enumerate(stats):
        if len(stats) <= 1:
            stat["isolation_ratio"] = 0.0
            continue
        distances = np.max(np.abs(centers - centers[index]), axis=1)
        distances[index] = math.inf
        nearest = float(np.min(distances))
        stat["isolation_ratio"] = nearest / max(float(stat["diameter"]), 0.05)
    return stats


def plan_ranges(plan: list[Any], total_pages: int) -> list[dict[str, Any]]:
    """font plan 각 항목의 page 구간을 계산한다."""

    ranges = []
    for index, item in enumerate(plan):
        end = total_pages
        for following in plan[index + 1 :]:
            if following.level <= item.level:
                end = max(item.pdf_page, following.pdf_page - 1)
                break
        ranges.append(
            {"index": index, "item": item, "start": item.pdf_page, "end": end}
        )
    return ranges


def deepest_parent(pdf_page: int, ranges: list[dict[str, Any]]) -> Any | None:
    """후보 page를 포함하는 가장 깊고 가까운 font parent를 반환한다."""

    eligible = [row for row in ranges if row["start"] <= pdf_page <= row["end"]]
    chosen = max(
        eligible,
        key=lambda row: (row["item"].level, row["start"], row["index"]),
        default=None,
    )
    return chosen["item"] if chosen else None


def chunk_y_gap_metrics(
    chunks: list[Any], body_spacing: float
) -> dict[int, dict[str, Any]]:
    """같은 page의 다른 chunk까지 가장 짧은 bbox y 간격을 계산한다."""

    by_page: dict[int, list[Any]] = {}
    for chunk in chunks:
        by_page.setdefault(chunk.pdf_page, []).append(chunk)
    metrics = {}
    for page_chunks in by_page.values():
        for chunk in page_chunks:
            gaps = [
                gap
                for other in page_chunks
                if other.chunk_id != chunk.chunk_id
                for gap in (
                    chunk.y0 - other.y1 if other.y1 <= chunk.y0 else None,
                    other.y0 - chunk.y1 if other.y0 >= chunk.y1 else None,
                )
                if gap is not None
            ]
            nearest = min(gaps) if gaps else 0.0
            ratio = nearest / body_spacing if body_spacing else 0.0
            metrics[chunk.chunk_id] = {
                "nearest_y_gap": round(float(nearest), 4),
                "nearest_y_gap_over_body_spacing": round(float(ratio), 4),
                "y_gap_exceeds_body_spacing": nearest > body_spacing,
            }
    return metrics


def fallback_items(
    chunks: list[Any],
    stats: list[dict[str, Any]],
    font_tiers: Any,
    profile: Any,
    font_plan: list[Any],
    ranges: list[dict[str, Any]],
    y_gap_metrics: dict[int, dict[str, Any]],
    *,
    strict_size: bool,
) -> list[dict[str, Any]]:
    """body-tier position 후보를 page-range font parent 아래 삽입한다."""

    stat_by_chunk = {
        pattern.current.chunk_id: stat for stat in stats for pattern in stat["cluster"]
    }
    items = []
    for chunk in chunks:
        if len(chunk.lines) != 1:
            continue
        stat = stat_by_chunk.get(chunk.chunk_id)
        if (
            stat is None
            or stat["support_pages"] < POSITION_MIN_PAGES
            or stat["isolation_ratio"] < 1.0
        ):
            continue
        tier = _tier_for_size(chunk.font_size, font_tiers)
        if tier not in profile.body_tiers:
            continue
        ratio = chunk.font_size / profile.representative_body_font_size
        if strict_size and not STRICT_BODY_RATIO_LOW <= ratio <= STRICT_BODY_RATIO_HIGH:
            continue
        if any(
            item.pdf_page == chunk.pdf_page
            and title_score(item.title, chunk.text) >= 0.8
            for item in font_plan
        ):
            continue
        parent = deepest_parent(chunk.pdf_page, ranges)
        if parent is None:
            continue
        items.append(
            {
                "title": display_text(chunk.text),
                "pdf_page": chunk.pdf_page,
                "level": parent.level + 1,
                "font_size": round(float(chunk.font_size), 4),
                "font_ratio": round(float(ratio), 4),
                "font_tier": tier,
                "line_count": len(chunk.lines),
                "support_pages": int(stat["support_pages"]),
                "isolation_ratio": round(float(stat["isolation_ratio"]), 4),
                **y_gap_metrics[chunk.chunk_id],
                "parent": {
                    "title": display_text(parent.title),
                    "pdf_page": parent.pdf_page,
                    "level": parent.level,
                },
            }
        )
    return items


def build_larger_font_plan(
    chunks: list[Any], font_tiers: Any, profile: Any, config: TypographyConfig
) -> list[Any]:
    """20 words 이하인 larger-than-body chunk로 font 골격을 만든다."""

    headings = [
        BpeHeading(
            title=display_text(chunk.text),
            pdf_page=chunk.pdf_page,
            tier=_tier_for_size(chunk.font_size, font_tiers),
            y0=chunk.y0,
            y1=chunk.y1,
            merged_line_count=len(chunk.lines),
            evidence=("larger_than_body_font", "font_text_coverage_candidate"),
        )
        for chunk in chunks
        if _tier_for_size(chunk.font_size, font_tiers) in profile.candidate_tiers
        and chunk.font_size > profile.representative_body_font_size
        and len(chunk.text.split()) <= FONT_MAX_WORDS
    ]
    return normalize_bookmark_plan(infer_bpe_outline(headings, config))


def analyze_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    """scanned/OCR 한 권의 font 골격과 fallback tree를 수동 감사용으로 만든다."""

    config = TypographyConfig(
        heading_candidate_mode="font",
        body_font_text_coverage=BODY_TEXT_COVERAGE,
        position_min_repeated_pages=POSITION_MIN_PAGES,
    )
    raw_lines = extract_typography_lines(dataset["pdf"], config)
    lines = exclude_margin_artifacts(raw_lines, config)
    font_tiers = compute_geometry_font_tier_set(lines)
    profile = classify_font_tiers_by_text_coverage(
        lines, font_tiers, BODY_TEXT_COVERAGE
    )
    restored = _merge_printed_line_fragments(lines)
    body_spacing, continuation_upper = _body_spacing_band(restored, font_tiers, profile)
    chunks = _merge_adjacent_non_body_chunks(
        _build_chunks(restored, continuation_upper),
        font_tiers,
        profile,
        body_spacing,
    )
    production_patterns = _build_anchor_patterns(chunks, body_spacing)
    current_patterns = [
        CurrentAnchor(pattern.current, pattern.values[:2])
        for pattern in production_patterns
    ]
    stats = cluster_statistics(_cluster_patterns(current_patterns, tolerance=2.0))
    font_plan = build_larger_font_plan(chunks, font_tiers, profile, config)
    with fitz.open(dataset["pdf"]) as document:
        total_pages = document.page_count
    ranges = plan_ranges(font_plan, total_pages)
    y_gap_metrics = chunk_y_gap_metrics(chunks, body_spacing)
    font_items = [
        {
            "title": display_text(item.title),
            "pdf_page": item.pdf_page,
            "level": item.level,
            "line_count": next(
                len(chunk.lines)
                for chunk in chunks
                if chunk.pdf_page == item.pdf_page
                and display_text(chunk.text) == display_text(item.title)
            ),
            "word_count": len(item.title.split()),
        }
        for item in font_plan
    ]
    body_tier_items = fallback_items(
        chunks,
        stats,
        font_tiers,
        profile,
        font_plan,
        ranges,
        y_gap_metrics,
        strict_size=False,
    )
    strict_items = fallback_items(
        chunks,
        stats,
        font_tiers,
        profile,
        font_plan,
        ranges,
        y_gap_metrics,
        strict_size=True,
    )
    return {
        "key": dataset["key"],
        "pdf": str(dataset["pdf"].relative_to(ROOT_DIR)),
        "evaluation": "manual_eye_check_only",
        "page_count": total_pages,
        "line_count": len(lines),
        "chunk_count": len(chunks),
        "body_font_size": round(profile.representative_body_font_size, 4),
        "body_tiers": sorted(profile.body_tiers),
        "body_line_spacing": round(body_spacing, 4),
        "font_baseline": {
            "candidate_count": len(font_items),
            "items": font_items,
        },
        "body_tier_fallback": {
            "name": "current_2d_body_tier_support_5_isolation_1",
            "candidate_count": len(body_tier_items),
            "y_gap_exceeds_body_spacing_count": sum(
                item["y_gap_exceeds_body_spacing"] for item in body_tier_items
            ),
            "items": body_tier_items,
        },
        "strict_body_size_fallback": {
            "name": "current_2d_strict_body_size_support_5_isolation_1",
            "candidate_count": len(strict_items),
            "y_gap_exceeds_body_spacing_count": sum(
                item["y_gap_exceeds_body_spacing"] for item in strict_items
            ),
            "items": strict_items,
        },
    }


def compact(evaluation: dict[str, Any]) -> dict[str, Any]:
    """registry에는 후보 수와 TXT 경로만 남긴다."""

    return {key: value for key, value in evaluation.items() if key != "items"}


def write_tree(
    path: Path,
    title: str,
    font_items: list[dict[str, Any]],
    fallback_items: list[dict[str, Any]],
) -> None:
    """font 골격과 position fallback을 level 들여쓰기 TXT로 저장한다."""

    rows = [
        {
            **item,
            "source": "FONT",
            "details": f" lines={item['line_count']} words={item['word_count']}",
        }
        for item in font_items
    ] + [
        {
            **item,
            "source": "POSITION",
            "details": (
                f" support={item['support_pages']} isolation="
                f"{item['isolation_ratio']} font_ratio={item['font_ratio']}"
                f" lines={item['line_count']} y_gap_ratio="
                f"{item['nearest_y_gap_over_body_spacing']}"
            ),
        }
        for item in fallback_items
    ]
    rows.sort(key=lambda item: (item["pdf_page"], item["level"], item["source"]))
    lines = [
        f"# {title}",
        "",
        "수동 eye check 전용: precision 정답으로 사용하지 않음",
        "[FONT] larger-than-body font hierarchy",
        f"[FONT] word limit: <= {FONT_MAX_WORDS}; multi-line allowed",
        "[POSITION] body-font position fallback",
        "y_gap_ratio = nearest bbox y-gap / body line spacing (supplementary only)",
        "",
    ]
    for item in rows:
        indent = "  " * max(0, int(item["level"]) - 1)
        lines.append(
            f"{indent}[L{item['level']}] [p.{item['pdf_page']}] "
            f"[{item['source']}] {item['title']}{item['details']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_trees(results: list[dict[str, Any]]) -> None:
    """dataset별 body-tier/strict fallback tree TXT를 저장한다."""

    for result in results:
        for key, suffix in [
            ("body_tier_fallback", "body_tier"),
            ("strict_body_size_fallback", "strict_body_size"),
        ]:
            fallback = result[key]
            path = OUTPUT_DIR / f"{result['key']}_{suffix}_tree.txt"
            write_tree(
                path,
                f"{result['key']} / {fallback['name']}",
                result["font_baseline"]["items"],
                fallback["items"],
            )
            fallback["tree_txt"] = str(path.relative_to(ROOT_DIR))


def record_experiment(summary: dict[str, Any]) -> None:
    """scanned fallback 결과를 experiments registry에 기록한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    compact_results = [
        {
            **{
                key: value
                for key, value in result.items()
                if key
                not in (
                    "font_baseline",
                    "body_tier_fallback",
                    "strict_body_size_fallback",
                )
            },
            "font_baseline": compact(result["font_baseline"]),
            "body_tier_fallback": compact(result["body_tier_fallback"]),
            "strict_body_size_fallback": compact(result["strict_body_size_fallback"]),
        }
        for result in summary["results"]
    ]
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "scanned/OCR PDF에서 larger-than-body font plan을 유지하고 body-font "
            "position 후보를 page 구간상 parent 아래 삽입한 tree를 수동 검사한다."
        ),
        "inputs": [str(row["pdf"].relative_to(ROOT_DIR)) for row in DATASETS],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "geometry가 병합한 larger-than-body chunk 중 20 words 이하를 multi-line 허용 font plan으로 만들었다. "
            "current-anchor 2D tolerance 2.0, support>=5, isolation>=1 position "
            "cluster에서 body tier와 대표 body font ±3% fallback을 나누고, 물리 line 1개인 chunk만 남겼다. 후보 level은 "
            "page를 포함하는 가장 깊은 font parent+1로만 정했다. 세 scanned/OCR 책은 "
            "embedded gold가 없으므로 precision을 계산하지 않고 들여쓰기 TXT로 저장했다. "
            "가장 가까운 chunk bbox y 간격/body line spacing은 supplementary 지표로만 표시했다."
        ),
        "summary": {"results": compact_results, "finding": summary["finding"]},
        "finding": summary["finding"],
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    experiments = data["experiments"]
    for index, existing in enumerate(experiments):
        if existing.get("id") == EXPERIMENT_ID:
            experiments[index] = entry
            break
    else:
        experiments.append(entry)
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = [analyze_dataset(dataset) for dataset in DATASETS]
    findings = []
    for result in results:
        fallback = result["body_tier_fallback"]
        strict = result["strict_body_size_fallback"]
        findings.append(
            f"{result['key']}: one-line body-tier candidates={fallback['candidate_count']} "
            f"(y-gap>spacing={fallback['y_gap_exceeds_body_spacing_count']}), "
            f"strict candidates={strict['candidate_count']} "
            f"(y-gap>spacing={strict['y_gap_exceeds_body_spacing_count']}), manual eye check only"
        )
    finding = "; ".join(findings)
    write_trees(results)
    summary = {"results": results, "finding": finding}
    serializable = {
        "finding": finding,
        "results": [
            {
                **result,
                "font_baseline": {
                    **compact(result["font_baseline"]),
                    "candidate_preview": result["font_baseline"]["items"][:20],
                },
                "body_tier_fallback": {
                    **compact(result["body_tier_fallback"]),
                    "candidate_preview": result["body_tier_fallback"]["items"][:40],
                },
                "strict_body_size_fallback": {
                    **compact(result["strict_body_size_fallback"]),
                    "candidate_preview": result["strict_body_size_fallback"]["items"][
                        :40
                    ],
                },
            }
            for result in results
        ],
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record_experiment(summary)
    print(json.dumps({"finding": finding}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
