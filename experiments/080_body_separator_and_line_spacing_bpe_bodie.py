"""experiment 080: body tier separator와 line-spacing으로 BPE heading 병합을 제한한다.

최빈 body tier와 더 작은 tier는 heading 후보로 내보내지 않는다. 단, 원본 line
시퀀스에서는 삭제하지 않고 separator token으로 남긴다. 따라서 L3-L4(body)-L3은
두 L3가 BPE에서 인접 pair가 될 수 없다. 직접 인접한 non-body line만, 해당 페이지의
body line-spacing보다 좁을 때 BPE 병합 후보가 된다.

실행:
    uv run python experiments/080_body_separator_and_line_spacing_bpe_bodie.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "080_body_separator_and_line_spacing_bpe_bodie"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
SOURCE_075 = ROOT_DIR / "experiments" / "075_length_based_level_selection_bodie.py"
SOURCE_074 = ROOT_DIR / "experiments" / "074_bpe_style_page_local_tier_merge.py"
SOURCE_077 = ROOT_DIR / "experiments" / "077_hierarchy_pollution_audit_bodie.py"
BOOK_PDF = (
    ROOT_DIR
    / "data"
    / "300STUDY"
    / "textbooks"
    / "Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf"
)
NO_TITLE_FILTER = 1_000_000
MAX_BPE_ITERATIONS = 50


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"실험 모듈을 불러올 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def normalized_line_spacing(upper: dict[str, Any], lower: dict[str, Any]) -> float | None:
    """두 line의 중심선 간격을 더 큰 line height로 나눈 상대 line spacing을 구한다."""

    delta = lower["y0"] - upper["y0"]
    if delta <= 0:
        return None
    return delta / max(upper["height"], lower["height"], 1e-6)


def compute_body_spacing_by_page(
    lines: list[dict[str, Any]], body_flags: list[bool]
) -> tuple[dict[int, float], float]:
    """body/주석 line의 중앙 spacing을 페이지별로 구하고 부족한 페이지용 전역값을 만든다."""

    body_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for line, is_body in zip(lines, body_flags):
        if is_body:
            body_by_page[line["pdf_page"]].append(line)

    all_spacings: list[float] = []
    page_spacings: dict[int, float] = {}
    for page, page_lines in body_by_page.items():
        ordered = sorted(page_lines, key=lambda line: line["y0"])
        spacings = [
            spacing
            for upper, lower in zip(ordered, ordered[1:])
            if (spacing := normalized_line_spacing(upper, lower)) is not None
        ]
        if spacings:
            page_spacings[page] = float(median(spacings))
            all_spacings.extend(spacings)
    if not all_spacings:
        raise RuntimeError("body line spacing을 계산할 수 없습니다")
    return page_spacings, float(median(all_spacings))


def bpe_merge_with_separators(
    tokens: list[dict[str, Any]],
    page_spacing: dict[int, float],
    fallback_spacing: float,
    min_pair_count: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """separator를 유지한 token stream에서만 BPE pair를 만든다.

    body token은 병합하지 않지만 nodes에서 제거하지도 않는다. 그래서 body를 사이에 둔
    heading token은 반복 BPE 이후에도 인접해질 수 없다.
    """

    nodes = [dict(token) for token in tokens]
    stats = Counter()
    for _iteration in range(MAX_BPE_ITERATIONS):
        pair_counter: Counter[tuple[tuple[int, ...], tuple[int, ...]]] = Counter()
        pair_positions: dict[tuple[tuple[int, ...], tuple[int, ...]], list[int]] = defaultdict(list)
        for index, (upper, lower) in enumerate(zip(nodes, nodes[1:])):
            if upper["kind"] != "heading" or lower["kind"] != "heading":
                if upper["kind"] != lower["kind"]:
                    stats["separator_barrier_adjacencies"] += 1
                continue
            if upper["pdf_page"] != lower["pdf_page"]:
                continue
            spacing = normalized_line_spacing(upper, lower)
            threshold = page_spacing.get(upper["pdf_page"], fallback_spacing)
            if spacing is None or spacing > threshold:
                stats["broad_spacing_rejections"] += 1
                continue
            pair = (upper["tier_seq"], lower["tier_seq"])
            pair_counter[pair] += 1
            pair_positions[pair].append(index)

        if not pair_counter:
            break
        best_pair, best_count = pair_counter.most_common(1)[0]
        if best_count < min_pair_count:
            break

        merge_at = set(pair_positions[best_pair])
        new_nodes: list[dict[str, Any]] = []
        index = 0
        while index < len(nodes):
            if index in merge_at and index + 1 < len(nodes):
                upper, lower = nodes[index], nodes[index + 1]
                new_nodes.append(
                    {
                        "kind": "heading",
                        "pdf_page": upper["pdf_page"],
                        "text": f"{upper['text']} {lower['text']}".strip(),
                        "font_size": float(median([upper["font_size"], lower["font_size"]])),
                        "y0": upper["y0"],
                        "height": upper["height"] + lower["height"],
                        "tier_seq": upper["tier_seq"] + lower["tier_seq"],
                        "merged_line_count": upper["merged_line_count"] + lower["merged_line_count"],
                    }
                )
                stats["merged_pairs"] += 1
                index += 2
            else:
                new_nodes.append(nodes[index])
                index += 1
        nodes = new_nodes
    return [node for node in nodes if node["kind"] == "heading"], dict(stats)


def build_separator_spacing_tree(source: Any) -> tuple[list[Any], dict[str, Any]]:
    lines, _page_word_counts, _page_count = source.extract_book_lines_and_page_word_counts(BOOK_PDF)
    all_sizes = [line["font_size"] for line in lines]
    tiers = source.compute_tiers(all_sizes, source.MIN_TIER_COUNT)
    assigned_tiers = [source.assign_tier(size, tiers["final_cuts"]) for size in all_sizes]
    tier_counts = Counter(assigned_tiers)
    body_tier = max(tier_counts, key=tier_counts.get)
    body_and_smaller = set(range(body_tier, tiers["final_tier_count"] + 1))
    body_flags = [tier in body_and_smaller for tier in assigned_tiers]
    page_spacing, fallback_spacing = compute_body_spacing_by_page(lines, body_flags)

    tokens = [
        {
            "kind": "separator" if is_body else "heading",
            "pdf_page": line["pdf_page"],
            "text": line["text"],
            "font_size": line["font_size"],
            "y0": line["y0"],
            "height": line["height"],
            "tier_seq": (tier,) if not is_body else (),
            "merged_line_count": 1,
        }
        for line, tier, is_body in zip(lines, assigned_tiers, body_flags)
    ]
    bpe_nodes, bpe_stats = bpe_merge_with_separators(
        tokens,
        page_spacing,
        fallback_spacing,
        min_pair_count=source.MIN_PAIR_COUNT,
    )
    candidates = [
        source.HeadingCandidate(
            idx=index,
            pdf_page=node["pdf_page"],
            text=node["text"],
            font_size=node["font_size"],
            tier_value=tiers["final_peaks"][min(node["tier_seq"]) - 1],
            tier=min(node["tier_seq"]),
        )
        for index, node in enumerate(bpe_nodes)
    ]
    source.assign_levels_by_stack(candidates)
    return candidates, {
        "input_line_count": len(lines),
        "body_tier": body_tier,
        "body_and_smaller_tiers": sorted(body_and_smaller),
        "body_separator_count": sum(body_flags),
        "heading_token_count": len(lines) - sum(body_flags),
        "pages_with_body_spacing": len(page_spacing),
        "fallback_normalized_body_spacing": round(fallback_spacing, 4),
        "page_spacing_p10": round(float(np.percentile(list(page_spacing.values()), 10)), 4),
        "page_spacing_p50": round(float(np.percentile(list(page_spacing.values()), 50)), 4),
        "page_spacing_p90": round(float(np.percentile(list(page_spacing.values()), 90)), 4),
        "bpe_node_count": len(bpe_nodes),
        "bpe_stats": bpe_stats,
    }


def compact_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "truth_count",
        "matched_count",
        "recall",
        "level_correct_count",
        "level_accuracy",
        "parent_correct_count",
        "parent_accuracy",
        "level_off_by_histogram",
    ]
    return {key: evaluation[key] for key in keys}


def run_variant(name: str, candidates: list[Any], eval_module: Any, audit_module: Any, truth: list[dict[str, Any]]) -> dict[str, Any]:
    evaluation = eval_module.evaluate_against_ground_truth(candidates, truth)
    matches = audit_module.match_bookmarks(candidates, truth)
    audit = audit_module.audit_hierarchy(candidates, matches)
    print(
        f"{name}: candidates={len(candidates)} recall={evaluation['recall']} "
        f"level_accuracy={evaluation['level_accuracy']} parent_accuracy={evaluation['parent_accuracy']} "
        f"unmatched={audit['summary']['bookmark_unmatched_candidate_count']} "
        f"bridge={audit['summary']['unmatched_bridge_candidate_count']}"
    )
    return {
        "candidate_count": len(candidates),
        "evaluation": compact_evaluation(evaluation),
        "pollution_audit": {key: value for key, value in audit.items() if key != "candidate_rows"},
        "candidate_tree": [
            {
                "idx": candidate.idx,
                "pdf_page": candidate.pdf_page,
                "level": candidate.level,
                "tier": candidate.tier,
                "parent_idx": candidate.parent_idx,
                "title": candidate.text,
            }
            for candidate in candidates
        ],
    }


def record_experiment(results: dict[str, dict[str, Any]], metadata: dict[str, Any]) -> None:
    baseline = results["baseline_global_bpe"]
    proposed = results["body_separator_spacing_bpe"]
    base_eval, new_eval = baseline["evaluation"], proposed["evaluation"]
    base_pollution = baseline["pollution_audit"]["summary"]
    new_pollution = proposed["pollution_audit"]["summary"]
    finding = (
        f"baseline: candidates={baseline['candidate_count']} recall={base_eval['recall']} "
        f"level_accuracy={base_eval['level_accuracy']} parent_accuracy={base_eval['parent_accuracy']} "
        f"unmatched={base_pollution['bookmark_unmatched_candidate_count']} bridge={base_pollution['unmatched_bridge_candidate_count']} | "
        f"separator_spacing: candidates={proposed['candidate_count']} recall={new_eval['recall']} "
        f"level_accuracy={new_eval['level_accuracy']} parent_accuracy={new_eval['parent_accuracy']} "
        f"unmatched={new_pollution['bookmark_unmatched_candidate_count']} bridge={new_pollution['unmatched_bridge_candidate_count']} | "
        f"body_separators={metadata['body_separator_count']} merged_pairs={metadata['bpe_stats'].get('merged_pairs', 0)} "
        f"broad_rejections={metadata['bpe_stats'].get('broad_spacing_rejections', 0)}"
    )
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "본문 tier와 더 작은 tier를 heading 후보에서는 제외하되 원본 line sequence에서는 "
            "separator token으로 유지한다. body로 분리된 non-body tier가 BPE에서 다시 인접해 "
            "병합되지 않게 하고, 직접 인접한 non-body line은 페이지별 body line-spacing 이하일 "
            "때만 BPE로 병합해 hierarchy 오염과 정확도를 baseline과 비교한다."
        ),
        "inputs": [str(BOOK_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": ["074_bpe_style_page_local_tier_merge", "075_length_based_level_selection_bodie", "077_hierarchy_pollution_audit_bodie", "079_page_local_tiers_after_body_exclusion_bodie"],
        "body_handling": "본문/주석 tier는 BPE 후보가 아닌 separator token으로 유지",
        "line_spacing_rule": "직접 인접한 non-body line의 상대 line spacing이 해당 페이지 body 중앙 spacing 이하일 때만 BPE pair 허용",
        "separator_spacing_metadata": metadata,
        "results": {
            name: {key: value for key, value in result.items() if key != "candidate_tree"}
            for name, result in results.items()
        },
        "finding": finding,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"] = [item for item in data["experiments"] if item.get("id") != EXPERIMENT_ID] + [entry]
    EXPERIMENTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not BOOK_PDF.exists():
        print(f"PDF 없음: {BOOK_PDF}")
        return
    source = load_module("experiment_075_for_080", SOURCE_075)
    source.BOOK_PDF = BOOK_PDF
    eval_module = load_module("experiment_074_for_080", SOURCE_074)
    audit_module = load_module("experiment_077_for_080", SOURCE_077)
    truth = audit_module.load_ground_truth(BOOK_PDF)

    print("... baseline(global BPE) 생성 중")
    baseline_candidates, _page_counts, _page_count, removed = source.build_candidate_tree(
        BOOK_PDF, max_title_words=NO_TITLE_FILTER
    )
    if removed:
        raise RuntimeError("title filter가 적용되면 안 됩니다")
    print("... body separator + line-spacing BPE 생성 중")
    separator_candidates, metadata = build_separator_spacing_tree(source)
    results = {
        "baseline_global_bpe": run_variant(
            "baseline", baseline_candidates, eval_module, audit_module, truth
        ),
        "body_separator_spacing_bpe": run_variant(
            "separator_spacing", separator_candidates, eval_module, audit_module, truth
        ),
    }
    (OUTPUT_DIR / "separator_spacing_comparison.json").write_text(
        json.dumps({"separator_spacing_metadata": metadata, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_experiment(results, metadata)
    print(f"summary: {OUTPUT_DIR / 'separator_spacing_comparison.json'}")


if __name__ == "__main__":
    main()
