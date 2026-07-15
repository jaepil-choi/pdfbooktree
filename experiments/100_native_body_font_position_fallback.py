"""experiment 100: native PDF에서 body-font position fallback을 검증한다.

font 기반 plan을 기본 골격으로 두고, font evidence가 body로 분류했지만 position
반복 evidence가 있는 chunk를 page 구간상 가장 깊은 font parent 아래에 삽입한다.
position은 level을 직접 추론하지 않는다. Embedded outline을 gold로 사용해 fallback
precision과 parent 배치 정확도를 측정한다.

실행:
    uv run python experiments/100_native_body_font_position_fallback.py
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
EXPERIMENT_ID = "100_native_body_font_position_fallback"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
INPUT_PDFS = [
    ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf",
    ROOT_DIR / "data" / "native-pdf-indexed" / "퀀트의 세계 - 홍창수.pdf",
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


def normalize_title(text: str) -> str:
    """한글과 영숫자를 보존해 제목 비교용 문자열을 만든다."""

    return re.sub(r"[^\w]+", " ", text.casefold(), flags=re.UNICODE).strip()


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
    token_overlap = (
        2.0 * len(left_tokens & right_tokens) / (len(left_tokens) + len(right_tokens))
        if left_tokens and right_tokens
        else 0.0
    )
    return max(sequence, token_overlap)


def load_gold(pdf_path: Path) -> list[dict[str, Any]]:
    """embedded outline과 각 항목의 실제 parent index를 읽는다."""

    with fitz.open(pdf_path) as document:
        toc = document.get_toc()
    gold = [
        {
            "index": index,
            "level": level,
            "title": title.replace("\n", " "),
            "pdf_page": page,
            "parent_index": None,
        }
        for index, (level, title, page) in enumerate(toc)
        if page > 0
    ]
    stack: list[dict[str, Any]] = []
    for item in gold:
        while stack and stack[-1]["level"] >= item["level"]:
            stack.pop()
        item["parent_index"] = stack[-1]["index"] if stack else None
        stack.append(item)
    return gold


def best_gold_match(
    title: str, pdf_page: int, gold_by_page: dict[int, list[dict[str, Any]]]
) -> dict[str, Any] | None:
    """같은 page의 gold bookmark 중 제목이 가장 가까운 항목을 반환한다."""

    scored = [
        (title_score(item["title"], title), item)
        for item in gold_by_page.get(pdf_page, [])
    ]
    if not scored:
        return None
    score, item = max(scored, key=lambda row: row[0])
    return {**item, "score": score} if score >= TITLE_MATCH_THRESHOLD else None


def cluster_statistics(clusters: list[list[Any]]) -> list[dict[str, Any]]:
    """position cluster의 support와 최근접 cluster isolation을 계산한다."""

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
    radii = np.asarray([stat["radius"] for stat in stats], dtype=float)
    for index, stat in enumerate(stats):
        if len(stats) <= 1:
            stat["isolation_ratio"] = 0.0
            continue
        distances = np.max(np.abs(centers - centers[index]), axis=1)
        distances[index] = math.inf
        nearest = int(np.argmin(distances))
        nearest_distance = float(distances[nearest])
        stat["separation_margin"] = nearest_distance - radii[index] - radii[nearest]
        stat["isolation_ratio"] = nearest_distance / max(float(stat["diameter"]), 0.05)
    return stats


def plan_ranges(plan: list[Any], total_pages: int) -> list[dict[str, Any]]:
    """font plan 각 항목이 지배하는 page 구간을 계산한다."""

    ranges = []
    for index, item in enumerate(plan):
        end_page = total_pages
        for following in plan[index + 1 :]:
            if following.level <= item.level:
                end_page = max(item.pdf_page, following.pdf_page - 1)
                break
        ranges.append(
            {
                "index": index,
                "item": item,
                "start_page": item.pdf_page,
                "end_page": end_page,
            }
        )
    return ranges


def deepest_parent(
    pdf_page: int, ranges: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """후보 page를 포함하는 가장 깊고 가까운 font bookmark를 고른다."""

    eligible = [
        row for row in ranges if row["start_page"] <= pdf_page <= row["end_page"]
    ]
    return max(
        eligible,
        key=lambda row: (
            row["item"].level,
            row["start_page"],
            row["index"],
        ),
        default=None,
    )


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


def is_duplicate_of_font(title: str, pdf_page: int, font_plan: list[Any]) -> bool:
    """같은 page에서 font plan이 이미 잡은 제목은 fallback에서 제외한다."""

    return any(
        item.pdf_page == pdf_page and title_score(item.title, title) >= 0.8
        for item in font_plan
    )


def evaluate_plan(
    name: str,
    items: list[dict[str, Any]],
    gold: list[dict[str, Any]],
) -> dict[str, Any]:
    """plan 또는 fallback 후보의 bookmark precision을 계산한다."""

    gold_by_page: dict[int, list[dict[str, Any]]] = {}
    for item in gold:
        gold_by_page.setdefault(item["pdf_page"], []).append(item)
    evaluated = []
    for item in items:
        match = best_gold_match(item["title"], item["pdf_page"], gold_by_page)
        evaluated.append({**item, "gold_match": match})
    hits = sum(row["gold_match"] is not None for row in evaluated)
    return {
        "name": name,
        "candidate_count": len(evaluated),
        "bookmark_hits": hits,
        "precision": round(hits / len(evaluated), 4) if evaluated else 0.0,
        "evaluated": evaluated,
    }


def evaluate_fallback_parents(
    evaluated: list[dict[str, Any]], gold: list[dict[str, Any]]
) -> dict[str, Any]:
    """정답 fallback의 page parent가 gold parent와 같은지 평가한다."""

    gold_by_index = {item["index"]: item for item in gold}
    comparable = []
    for row in evaluated:
        match = row["gold_match"]
        if match is None or match["parent_index"] is None:
            continue
        expected = gold_by_index[match["parent_index"]]
        parent = row["parent"]
        correct = (
            parent is not None
            and parent["pdf_page"] == expected["pdf_page"]
            and title_score(parent["title"], expected["title"]) >= TITLE_MATCH_THRESHOLD
        )
        comparable.append(
            {
                "fallback_title": row["title"],
                "fallback_page": row["pdf_page"],
                "expected_parent": expected["title"],
                "predicted_parent": parent["title"] if parent else None,
                "correct": correct,
            }
        )
    correct_count = sum(row["correct"] for row in comparable)
    return {
        "comparable_true_fallback_count": len(comparable),
        "correct_parent_count": correct_count,
        "parent_accuracy": (
            round(correct_count / len(comparable), 4) if comparable else None
        ),
        "details": comparable,
    }


def build_fallback_items(
    chunks: list[Any],
    stats: list[dict[str, Any]],
    font_tiers: Any,
    profile: Any,
    font_plan: list[Any],
    ranges: list[dict[str, Any]],
    y_gap_metrics: dict[int, dict[str, Any]],
    *,
    require_isolation: bool,
    strict_body_size: bool,
) -> tuple[list[dict[str, Any]], int]:
    """body-font position 후보를 font parent 아래 삽입할 항목으로 만든다."""

    stat_by_chunk = {
        pattern.current.chunk_id: stat for stat in stats for pattern in stat["cluster"]
    }
    items = []
    unparented_count = 0
    for chunk in chunks:
        if len(chunk.lines) != 1:
            continue
        stat = stat_by_chunk.get(chunk.chunk_id)
        if stat is None or stat["support_pages"] < POSITION_MIN_PAGES:
            continue
        if require_isolation and stat["isolation_ratio"] < 1.0:
            continue
        tier = _tier_for_size(chunk.font_size, font_tiers)
        if tier not in profile.body_tiers:
            continue
        ratio = chunk.font_size / profile.representative_body_font_size
        if (
            strict_body_size
            and not STRICT_BODY_RATIO_LOW <= ratio <= STRICT_BODY_RATIO_HIGH
        ):
            continue
        if is_duplicate_of_font(chunk.text, chunk.pdf_page, font_plan):
            continue
        parent_range = deepest_parent(chunk.pdf_page, ranges)
        if parent_range is None:
            unparented_count += 1
            continue
        parent = parent_range["item"]
        items.append(
            {
                "title": chunk.text,
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
                    "title": parent.title,
                    "pdf_page": parent.pdf_page,
                    "level": parent.level,
                },
            }
        )
    return items, unparented_count


def compact_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    """registry에는 상세 후보 목록을 제외한 precision만 기록한다."""

    return {key: value for key, value in evaluation.items() if key != "evaluated"}


def build_larger_font_plan(
    chunks: list[Any], font_tiers: Any, profile: Any, config: TypographyConfig
) -> list[Any]:
    """20 words 이하인 larger-than-body chunk로 font 골격을 만든다."""

    headings = [
        BpeHeading(
            title=chunk.text,
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


def analyze_pdf(pdf_path: Path) -> dict[str, Any]:
    """한 native PDF의 font baseline과 두 position fallback을 비교한다."""

    config = TypographyConfig(
        heading_candidate_mode="font",
        body_font_text_coverage=BODY_TEXT_COVERAGE,
        position_min_repeated_pages=POSITION_MIN_PAGES,
    )
    raw_lines = extract_typography_lines(pdf_path, config)
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
    production_stats = cluster_statistics(
        _cluster_patterns(production_patterns, tolerance=1.0)
    )
    current_stats = cluster_statistics(
        _cluster_patterns(current_patterns, tolerance=2.0)
    )
    font_plan = build_larger_font_plan(chunks, font_tiers, profile, config)
    with fitz.open(pdf_path) as document:
        total_pages = document.page_count
    ranges = plan_ranges(font_plan, total_pages)
    y_gap_metrics = chunk_y_gap_metrics(chunks, body_spacing)
    gold = load_gold(pdf_path)
    font_items = [
        {
            "title": item.title,
            "pdf_page": item.pdf_page,
            "level": item.level,
            "line_count": next(
                len(chunk.lines)
                for chunk in chunks
                if chunk.pdf_page == item.pdf_page and chunk.text == item.title
            ),
            "word_count": len(item.title.split()),
        }
        for item in font_plan
    ]
    baseline = evaluate_plan("font_baseline", font_items, gold)

    configurations = [
        ("production_4d_body_tier_support_5", production_stats, False, False),
        ("current_2d_body_tier_support_5_isolation_1", current_stats, True, False),
        (
            "current_2d_strict_body_size_support_5_isolation_1",
            current_stats,
            True,
            True,
        ),
    ]
    fallback_results = []
    for name, stats, require_isolation, strict_body_size in configurations:
        items, unparented = build_fallback_items(
            chunks,
            stats,
            font_tiers,
            profile,
            font_plan,
            ranges,
            y_gap_metrics,
            require_isolation=require_isolation,
            strict_body_size=strict_body_size,
        )
        evaluation = evaluate_plan(name, items, gold)
        y_gap_evaluation = evaluate_plan(
            f"{name}_y_gap_over_body_spacing",
            [item for item in items if item["y_gap_exceeds_body_spacing"]],
            gold,
        )
        parent_evaluation = evaluate_fallback_parents(evaluation["evaluated"], gold)
        hybrid_count = baseline["candidate_count"] + evaluation["candidate_count"]
        hybrid_hits = baseline["bookmark_hits"] + evaluation["bookmark_hits"]
        fallback_results.append(
            {
                "name": name,
                "items": items,
                "unparented_count": unparented,
                "evaluation": evaluation,
                "y_gap_evaluation": y_gap_evaluation,
                "parent_evaluation": parent_evaluation,
                "hybrid_candidate_count": hybrid_count,
                "hybrid_bookmark_hits": hybrid_hits,
                "hybrid_precision": (
                    round(hybrid_hits / hybrid_count, 4) if hybrid_count else 0.0
                ),
            }
        )

    return {
        "pdf": str(pdf_path.relative_to(ROOT_DIR)),
        "page_count": total_pages,
        "gold_bookmark_count": len(gold),
        "raw_line_count": len(raw_lines),
        "line_count": len(lines),
        "chunk_count": len(chunks),
        "body_font_size": round(profile.representative_body_font_size, 4),
        "body_tiers": sorted(profile.body_tiers),
        "body_line_spacing": round(body_spacing, 4),
        "font_baseline": baseline,
        "font_items": font_items,
        "fallback_results": fallback_results,
    }


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


def record_experiment(summary: dict[str, Any]) -> None:
    """native fallback precision 결과를 experiments registry에 기록한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    compact_results = []
    for result in summary["results"]:
        compact_results.append(
            {
                **{
                    key: value
                    for key, value in result.items()
                    if key not in ("font_baseline", "font_items", "fallback_results")
                },
                "font_baseline": compact_evaluation(result["font_baseline"]),
                "fallback_results": [
                    {
                        "name": row["name"],
                        "tree_txt": row["tree_txt"],
                        "unparented_count": row["unparented_count"],
                        "evaluation": compact_evaluation(row["evaluation"]),
                        "y_gap_evaluation": compact_evaluation(row["y_gap_evaluation"]),
                        "parent_evaluation": {
                            key: value
                            for key, value in row["parent_evaluation"].items()
                            if key != "details"
                        },
                        "hybrid_candidate_count": row["hybrid_candidate_count"],
                        "hybrid_bookmark_hits": row["hybrid_bookmark_hits"],
                        "hybrid_precision": row["hybrid_precision"],
                    }
                    for row in result["fallback_results"]
                ],
            }
        )
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "clean native PDF에서 font plan을 기본 hierarchy로 유지하고, font가 body로 "
            "판정한 position heading을 page 구간상 font parent 아래 삽입하는 fallback의 "
            "precision과 parent 정확도를 검증한다."
        ),
        "inputs": [str(path.relative_to(ROOT_DIR)) for path in INPUT_PDFS],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "geometry가 병합한 larger-than-body chunk 중 20 words 이하를 font plan으로 만들고 "
            "infer_bpe_outline으로 hierarchy를 정했다. font plan은 multi-line을 허용한다. position은 production "
            "4D와 current-anchor 2D를 비교하고, body tier 또는 대표 body font ±3%인 "
            "후보 중 물리 line 1개인 chunk만 선택했다. 후보는 page를 포함하는 가장 깊은 font plan range의 "
            "자식으로 삽입했다. embedded outline과 같은-page 한글/영문 title match로 "
            "fallback precision, hybrid precision, gold parent accuracy를 계산했다. "
            "가장 가까운 chunk bbox y 간격이 body line spacing보다 큰 subset의 precision도 supplementary로 기록했다."
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
    results = [analyze_pdf(path) for path in INPUT_PDFS]
    finding_parts = []
    for result in results:
        stem = "investments" if "Investments" in result["pdf"] else "quant_world"
        for fallback in result["fallback_results"]:
            suffix = (
                "strict_body_size"
                if "strict_body_size" in fallback["name"]
                else "body_tier"
                if "current_2d" in fallback["name"]
                else "production_4d_body_tier"
            )
            tree_path = OUTPUT_DIR / f"{stem}_{suffix}_tree.txt"
            write_tree(
                tree_path,
                f"{Path(result['pdf']).stem} / {fallback['name']}",
                result["font_items"],
                fallback["items"],
            )
            fallback["tree_txt"] = str(tree_path.relative_to(ROOT_DIR))
        strict = next(
            row
            for row in result["fallback_results"]
            if row["name"] == "current_2d_strict_body_size_support_5_isolation_1"
        )
        evaluation = strict["evaluation"]
        y_gap_evaluation = strict["y_gap_evaluation"]
        finding_parts.append(
            f"{Path(result['pdf']).stem}: font baseline precision="
            f"{result['font_baseline']['precision']}, one-line strict fallback candidates="
            f"{evaluation['candidate_count']}, fallback precision="
            f"{evaluation['precision']}, y-gap>spacing candidates="
            f"{y_gap_evaluation['candidate_count']}, supplementary precision="
            f"{y_gap_evaluation['precision']}, hybrid precision={strict['hybrid_precision']}"
        )
    finding = "; ".join(finding_parts) + (
        ". page-range parent 삽입은 level 결정 방식일 뿐, body-font position 후보의 "
        "precision을 올리는 gate는 아니다."
    )
    summary = {"results": results, "finding": finding}
    serializable = {
        "finding": finding,
        "results": [
            {
                **result,
                "font_baseline": compact_evaluation(result["font_baseline"]),
                "font_items": result["font_items"][:30],
                "fallback_results": [
                    {
                        **{key: value for key, value in row.items() if key != "items"},
                        "evaluation": {
                            **compact_evaluation(row["evaluation"]),
                            "candidate_preview": row["evaluation"]["evaluated"][:30],
                        },
                    }
                    for row in result["fallback_results"]
                ],
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
