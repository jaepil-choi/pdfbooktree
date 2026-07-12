"""experiment 079: 본문 제거 뒤 page-local tier로 BPE 병합을 수행한다.

078은 남은 heading 글자를 책 전체에서 다시 군집화해 tier가 둘로 붕괴했다. 이번에는
최빈 body tier와 더 작은 tier를 먼저 제외한 뒤, 각 페이지의 남은 글자만으로 BPE용
tier를 산정한다. stack hierarchy의 크기 순서는 원래 전역 font tier를 유지한다.

실행:
    uv run python experiments/079_page_local_tiers_after_body_exclusion_bodie.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "079_page_local_tiers_after_body_exclusion_bodie"
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


def build_page_local_tier_tree(source: Any) -> tuple[list[Any], dict[str, Any]]:
    """전역 body cutoff 뒤, 페이지 안에서만 heading tier를 만든다.

    page-local tier는 BPE가 같은 역할의 인접 line을 병합하는 데만 쓴다. 페이지마다
    tier 번호가 독립적이므로, 책 전체 stack hierarchy에는 원래 전역 tier의 font-size
    peak를 계속 사용해 페이지 경계를 넘어도 크기 순서가 일관되게 유지되게 한다.
    """

    lines, _page_word_counts, _page_count = source.extract_book_lines_and_page_word_counts(BOOK_PDF)
    all_sizes = [line["font_size"] for line in lines]
    global_tiers = source.compute_tiers(all_sizes, source.MIN_TIER_COUNT)
    global_assignments = [source.assign_tier(size, global_tiers["final_cuts"]) for size in all_sizes]
    global_counts = Counter(global_assignments)
    body_tier = max(global_counts, key=global_counts.get)
    body_and_smaller = set(range(body_tier, global_tiers["final_tier_count"] + 1))
    heading_lines = [
        line for line, tier in zip(lines, global_assignments) if tier not in body_and_smaller
    ]

    lines_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for line in heading_lines:
        lines_by_page[line["pdf_page"]].append(line)

    locally_tiered: list[tuple[dict[str, Any], int]] = []
    local_tier_count_histogram: Counter[int] = Counter()
    for page in sorted(lines_by_page):
        page_lines = lines_by_page[page]
        local_tiers = source.compute_tiers(
            [line["font_size"] for line in page_lines], source.MIN_TIER_COUNT
        )
        local_tier_count_histogram[local_tiers["final_tier_count"]] += 1
        local_assignments = [
            source.assign_tier(line["font_size"], local_tiers["final_cuts"]) for line in page_lines
        ]
        locally_tiered.extend(zip(page_lines, local_assignments))

    bpe_nodes = source.bpe_merge_page_local(
        locally_tiered,
        gap_ratio=source.MERGE_GAP_RATIO,
        min_pair_count=source.MIN_PAIR_COUNT,
    )
    candidates = []
    for index, node in enumerate(bpe_nodes):
        global_tier = source.assign_tier(node["font_size"], global_tiers["final_cuts"])
        candidates.append(
            source.HeadingCandidate(
                idx=index,
                pdf_page=node["pdf_page"],
                text=node["text"],
                font_size=node["font_size"],
                tier_value=global_tiers["final_peaks"][global_tier - 1],
                tier=global_tier,
            )
        )
    source.assign_levels_by_stack(candidates)
    return candidates, {
        "input_line_count": len(lines),
        "body_tier": body_tier,
        "body_and_smaller_tiers": sorted(body_and_smaller),
        "body_and_smaller_line_count": len(lines) - len(heading_lines),
        "heading_line_count": len(heading_lines),
        "global_tiers": global_tiers,
        "pages_with_heading_lines": len(lines_by_page),
        "page_local_tier_count_histogram": {
            str(tier_count): count for tier_count, count in sorted(local_tier_count_histogram.items())
        },
        "bpe_node_count": len(bpe_nodes),
    }


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
    baseline = results["baseline_global_tiers"]
    page_local = results["page_local_tiers_after_body_exclusion"]
    base_eval, new_eval = baseline["evaluation"], page_local["evaluation"]
    base_pollution = baseline["pollution_audit"]["summary"]
    new_pollution = page_local["pollution_audit"]["summary"]
    finding = (
        f"baseline: candidates={baseline['candidate_count']} recall={base_eval['recall']} "
        f"level_accuracy={base_eval['level_accuracy']} parent_accuracy={base_eval['parent_accuracy']} "
        f"unmatched={base_pollution['bookmark_unmatched_candidate_count']} bridge={base_pollution['unmatched_bridge_candidate_count']} | "
        f"page_local: candidates={page_local['candidate_count']} recall={new_eval['recall']} "
        f"level_accuracy={new_eval['level_accuracy']} parent_accuracy={new_eval['parent_accuracy']} "
        f"unmatched={new_pollution['bookmark_unmatched_candidate_count']} bridge={new_pollution['unmatched_bridge_candidate_count']} | "
        f"body_tier=L{metadata['body_tier']} excluded_lines={metadata['body_and_smaller_line_count']}"
    )
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "전체 책 최빈 body tier와 더 작은 tier를 먼저 제외하고, 남은 line만으로 "
            "페이지별 BPE용 tier를 산정한다. hierarchy stack의 전역 크기 순서는 기존 "
            "global tier를 유지해, body 제거 뒤 page-local tier가 병합 품질과 hierarchy "
            "오염에 주는 영향을 baseline과 비교한다."
        ),
        "inputs": [str(BOOK_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": ["074_bpe_style_page_local_tier_merge", "075_length_based_level_selection_bodie", "077_hierarchy_pollution_audit_bodie", "078_recluster_heading_tiers_after_body_exclusion_bodie"],
        "body_rule": "전체 책의 최빈 tier와 그보다 작은 모든 tier를 본문/주석으로 제외",
        "page_local_metadata": metadata,
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
    source = load_module("experiment_075_for_079", SOURCE_075)
    source.BOOK_PDF = BOOK_PDF
    eval_module = load_module("experiment_074_for_079", SOURCE_074)
    audit_module = load_module("experiment_077_for_079", SOURCE_077)
    truth = audit_module.load_ground_truth(BOOK_PDF)

    print("... baseline(global BPE tier) 생성 중")
    baseline_candidates, _page_counts, _page_count, removed = source.build_candidate_tree(
        BOOK_PDF, max_title_words=NO_TITLE_FILTER
    )
    if removed:
        raise RuntimeError("title filter가 적용되면 안 됩니다")
    print("... body 제외 후 page-local BPE tier 생성 중")
    page_local_candidates, metadata = build_page_local_tier_tree(source)
    results = {
        "baseline_global_tiers": run_variant(
            "baseline", baseline_candidates, eval_module, audit_module, truth
        ),
        "page_local_tiers_after_body_exclusion": run_variant(
            "page_local", page_local_candidates, eval_module, audit_module, truth
        ),
    }
    (OUTPUT_DIR / "page_local_tier_comparison.json").write_text(
        json.dumps({"page_local_metadata": metadata, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_experiment(results, metadata)
    print(f"summary: {OUTPUT_DIR / 'page_local_tier_comparison.json'}")


if __name__ == "__main__":
    main()
