"""experiment 078: 본문 제거 뒤 heading 전용 font tier를 다시 산정한다.

책 전체의 최빈 font tier와 그보다 작은 tier는 본문/주석으로 먼저 확정한다. 이후
남은 큰 글자만으로 font tier를 다시 만들고 page-local BPE 병합과 stack hierarchy를
수행한다. 기존처럼 본문을 포함해 만든 global tier를 그대로 쓰는 기준선과 비교한다.

실행:
    uv run python experiments/078_recluster_heading_tiers_after_body_exclusion_bodie.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "078_recluster_heading_tiers_after_body_exclusion_bodie"
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


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"실험 모듈을 불러올 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def build_reclustered_heading_tree(source: Any) -> tuple[list[Any], dict[str, Any]]:
    """본문 font tier를 제거한 뒤 남은 line만으로 tier를 다시 산정한다."""

    lines, _page_word_counts, _page_count = source.extract_book_lines_and_page_word_counts(BOOK_PDF)
    all_sizes = [line["font_size"] for line in lines]
    initial_tiers = source.compute_tiers(all_sizes, source.MIN_TIER_COUNT)
    initial_assignments = [source.assign_tier(size, initial_tiers["final_cuts"]) for size in all_sizes]
    tier_counts = Counter(initial_assignments)
    body_tier = max(tier_counts, key=tier_counts.get)
    body_and_smaller = set(range(body_tier, initial_tiers["final_tier_count"] + 1))
    heading_lines = [
        line for line, tier in zip(lines, initial_assignments) if tier not in body_and_smaller
    ]

    heading_tiers = source.compute_tiers(
        [line["font_size"] for line in heading_lines], source.MIN_TIER_COUNT
    )
    heading_assignments = [
        source.assign_tier(line["font_size"], heading_tiers["final_cuts"]) for line in heading_lines
    ]
    bpe_nodes = source.bpe_merge_page_local(
        list(zip(heading_lines, heading_assignments)),
        gap_ratio=source.MERGE_GAP_RATIO,
        min_pair_count=source.MIN_PAIR_COUNT,
    )
    candidates = [
        source.HeadingCandidate(
            idx=index,
            pdf_page=node["pdf_page"],
            text=node["text"],
            font_size=node["font_size"],
            tier_value=heading_tiers["final_peaks"][min(node["tier_seq"]) - 1],
            tier=min(node["tier_seq"]),
        )
        for index, node in enumerate(bpe_nodes)
    ]
    source.assign_levels_by_stack(candidates)
    return candidates, {
        "input_line_count": len(lines),
        "body_tier": body_tier,
        "body_and_smaller_tiers": sorted(body_and_smaller),
        "body_and_smaller_line_count": len(lines) - len(heading_lines),
        "heading_line_count": len(heading_lines),
        "initial_tiers": initial_tiers,
        "heading_only_tiers": heading_tiers,
        "bpe_node_count": len(bpe_nodes),
    }


def compact_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        key: evaluation[key]
        for key in [
            "truth_count",
            "matched_count",
            "recall",
            "level_correct_count",
            "level_accuracy",
            "parent_correct_count",
            "parent_accuracy",
            "level_off_by_histogram",
        ]
    }


def compact_audit(audit: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in audit.items() if key != "candidate_rows"}


def run_variant(name: str, candidates: list[Any], eval_module: Any, audit_module: Any, truth: list[dict[str, Any]]) -> dict[str, Any]:
    evaluation = eval_module.evaluate_against_ground_truth(candidates, truth)
    bookmark_matches = audit_module.match_bookmarks(candidates, truth)
    audit = audit_module.audit_hierarchy(candidates, bookmark_matches)
    print(
        f"{name}: candidates={len(candidates)} recall={evaluation['recall']} "
        f"level_accuracy={evaluation['level_accuracy']} parent_accuracy={evaluation['parent_accuracy']} "
        f"unmatched={audit['summary']['bookmark_unmatched_candidate_count']} "
        f"bridge={audit['summary']['unmatched_bridge_candidate_count']}"
    )
    return {
        "candidate_count": len(candidates),
        "evaluation": compact_evaluation(evaluation),
        "pollution_audit": compact_audit(audit),
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


def record_experiment(results: dict[str, dict[str, Any]], proposed_metadata: dict[str, Any]) -> None:
    baseline = results["baseline_global_tiers"]
    proposed = results["recluster_after_body_exclusion"]
    base_eval = baseline["evaluation"]
    new_eval = proposed["evaluation"]
    base_pollution = baseline["pollution_audit"]["summary"]
    new_pollution = proposed["pollution_audit"]["summary"]
    finding = (
        f"baseline: candidates={baseline['candidate_count']} recall={base_eval['recall']} "
        f"level_accuracy={base_eval['level_accuracy']} parent_accuracy={base_eval['parent_accuracy']} "
        f"unmatched={base_pollution['bookmark_unmatched_candidate_count']} "
        f"bridge={base_pollution['unmatched_bridge_candidate_count']} | "
        f"reclustered: candidates={proposed['candidate_count']} recall={new_eval['recall']} "
        f"level_accuracy={new_eval['level_accuracy']} parent_accuracy={new_eval['parent_accuracy']} "
        f"unmatched={new_pollution['bookmark_unmatched_candidate_count']} "
        f"bridge={new_pollution['unmatched_bridge_candidate_count']} | "
        f"body_tier=L{proposed_metadata['body_tier']} "
        f"excluded_lines={proposed_metadata['body_and_smaller_line_count']}"
    )
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "책 전체 최빈 font tier와 그보다 작은 tier를 본문/주석으로 먼저 제외한 뒤, "
            "남은 큰 글자만으로 heading tier를 다시 산정하는 것이 hierarchy 본문 오염과 "
            "ground truth 정확도에 주는 영향을 baseline(global tier 유지)과 비교한다."
        ),
        "inputs": [str(BOOK_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": ["074_bpe_style_page_local_tier_merge", "075_length_based_level_selection_bodie", "077_hierarchy_pollution_audit_bodie"],
        "body_rule": "전체 책의 최빈 tier와 그보다 작은 모든 tier를 본문/주석으로 제외",
        "recluster_metadata": proposed_metadata,
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
    source = load_module("experiment_075_for_078", SOURCE_075)
    source.BOOK_PDF = BOOK_PDF
    eval_module = load_module("experiment_074_for_078", SOURCE_074)
    audit_module = load_module("experiment_077_for_078", SOURCE_077)
    # 077의 truth에는 audit용 안정적인 truth_idx가 추가되어 있고, 074 평가 함수도
    # level/title/page 필드만 읽으므로 두 평가에 공통으로 쓸 수 있다.
    truth = audit_module.load_ground_truth(BOOK_PDF)

    print("... baseline(global tier 유지) 생성 중")
    baseline_candidates, _page_counts, _page_count, removed = source.build_candidate_tree(
        BOOK_PDF, max_title_words=NO_TITLE_FILTER
    )
    if removed:
        raise RuntimeError("title filter가 적용되면 안 됩니다")
    print("... body 제외 후 heading tier 재산정 생성 중")
    reclustered_candidates, recluster_metadata = build_reclustered_heading_tree(source)

    results = {
        "baseline_global_tiers": run_variant(
            "baseline", baseline_candidates, eval_module, audit_module, truth
        ),
        "recluster_after_body_exclusion": run_variant(
            "reclustered", reclustered_candidates, eval_module, audit_module, truth
        ),
    }
    (OUTPUT_DIR / "tier_recluster_comparison.json").write_text(
        json.dumps({"recluster_metadata": recluster_metadata, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_experiment(results, recluster_metadata)
    print(f"summary: {OUTPUT_DIR / 'tier_recluster_comparison.json'}")


if __name__ == "__main__":
    main()
