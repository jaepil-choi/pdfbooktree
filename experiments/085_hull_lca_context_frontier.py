"""experiment 085: Hull adaptive frontier의 LCA 문맥 병합을 검증한다.

084의 page/min-words 병합이 서로 다른 top-level node를 섞는 문제를 고친다.
실제 plan node만 포함하고, 같은 top-level 실제 root 안에서만 인접 frontier를
합치며 page 불변식을 만족하지 못하는 경우를 숨기지 않고 측정한다.

실행:
    uv run python experiments/085_hull_lca_context_frontier.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "085_hull_lca_context_frontier"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
SOURCE_EXPERIMENT = (
    ROOT_DIR / "experiments" / "084_hull_adaptive_frontier_page_invariants.py"
)
MIN_PAGE_SPAN = 2
MIN_WORDS = 1_000


@dataclass
class Group:
    """실제 plan node들을 포함하는 하나의 Markdown file 후보다."""

    start_page: int
    plan_indices: list[int]
    top_root: int
    end_page: int = 0
    word_count: int = 0


def load_source_experiment() -> Any:
    """084의 production BPE plan 생성과 adaptive entry 선택을 재사용한다."""

    spec = importlib.util.spec_from_file_location("experiment_084", SOURCE_EXPERIMENT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"실험 084를 불러올 수 없다: {SOURCE_EXPERIMENT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_parent_maps(plan: list[Any]) -> tuple[list[int | None], list[int]]:
    """preorder plan의 실제 parent와 top-level root index를 계산한다."""

    parents: list[int | None] = []
    roots: list[int] = []
    stack: list[int] = []
    for index, item in enumerate(plan):
        while stack and plan[stack[-1]].level >= item.level:
            stack.pop()
        parent = stack[-1] if stack else None
        parents.append(parent)
        roots.append(roots[parent] if parent is not None else index)
        stack.append(index)
    return parents, roots


def lca(indices: list[int], parents: list[int | None]) -> int | None:
    """실제 plan index들의 가장 가까운 공통 조상을 구한다."""

    if not indices:
        return None
    ancestor_sets: list[set[int]] = []
    for index in indices:
        ancestors = {index}
        parent = parents[index]
        while parent is not None:
            ancestors.add(parent)
            parent = parents[parent]
        ancestor_sets.append(ancestors)
    common = set.intersection(*ancestor_sets)
    if not common:
        return None
    return max(common)


def make_groups(entries: list[Any], roots: list[int]) -> tuple[list[Group], int]:
    """같은 page entry를 같은 top-level root 안에서만 합친다."""

    groups: list[Group] = []
    blocked_same_page_count = 0
    for entry in entries:
        top_root = roots[entry.plan_indices[0]]
        if groups and groups[-1].start_page == entry.start_page:
            if groups[-1].top_root == top_root:
                groups[-1].plan_indices.extend(entry.plan_indices)
            else:
                blocked_same_page_count += 1
                groups.append(
                    Group(entry.start_page, list(entry.plan_indices), top_root)
                )
        else:
            groups.append(Group(entry.start_page, list(entry.plan_indices), top_root))
    return groups, blocked_same_page_count


def refresh(groups: list[Group], page_words: dict[int, int], page_count: int) -> None:
    """현재 group boundary로 page range와 body word 수를 계산한다."""

    for position, group in enumerate(groups):
        next_start = (
            groups[position + 1].start_page
            if position + 1 < len(groups)
            else page_count + 1
        )
        group.end_page = next_start - 1
        group.word_count = sum(
            page_words.get(page, 0) for page in range(group.start_page, next_start)
        )


def merge(groups: list[Group], left_index: int) -> None:
    """같은 top-level root의 인접 existing-node group을 합친다."""

    left = groups[left_index]
    right = groups[left_index + 1]
    if left.top_root != right.top_root:
        raise RuntimeError("top-level root가 다른 group은 병합할 수 없다.")
    left.plan_indices.extend(right.plan_indices)
    del groups[left_index + 1]


def nearest_merge_index(groups: list[Group], index: int) -> int | None:
    """직전 우선으로 같은 top-level root의 병합 가능한 인접 group을 찾는다."""

    group = groups[index]
    if index > 0 and groups[index - 1].top_root == group.top_root:
        return index - 1
    if index + 1 < len(groups) and groups[index + 1].top_root == group.top_root:
        return index
    return None


def normalize(
    groups: list[Group], page_words: dict[int, int], page_count: int
) -> tuple[int, int, int, int]:
    """같은 문맥 안에서 page span과 min words를 만족하도록 병합한다."""

    page_span_merges = 0
    min_word_merges = 0
    blocked_page_span = 0
    blocked_min_words = 0
    while True:
        refresh(groups, page_words, page_count)
        short_index = next(
            (
                index
                for index, group in enumerate(groups)
                if group.end_page - group.start_page + 1 < MIN_PAGE_SPAN
            ),
            None,
        )
        if short_index is None:
            break
        merge_index = nearest_merge_index(groups, short_index)
        if merge_index is None:
            blocked_page_span += 1
            break
        merge(groups, merge_index)
        page_span_merges += 1
    while True:
        refresh(groups, page_words, page_count)
        small_index = next(
            (
                index
                for index, group in enumerate(groups)
                if group.word_count < MIN_WORDS
            ),
            None,
        )
        if small_index is None:
            break
        merge_index = nearest_merge_index(groups, small_index)
        if merge_index is None:
            blocked_min_words += 1
            break
        merge(groups, merge_index)
        min_word_merges += 1
    refresh(groups, page_words, page_count)
    return page_span_merges, min_word_merges, blocked_page_span, blocked_min_words


def main() -> None:
    """Hull BPE tree에서 LCA 문맥 병합 결과를 기록한다."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source = load_source_experiment()
    plan, page_words, page_count = source.build_plan()
    roots = source.build_tree(plan)
    entries = source.choose_adaptive_entries(roots, page_words, page_count)
    parents, top_roots = build_parent_maps(plan)
    groups, blocked_same_page = make_groups(entries, top_roots)
    page_span_merges, min_word_merges, blocked_page_span, blocked_min_words = normalize(
        groups, page_words, page_count
    )
    starts = [group.start_page for group in groups]
    all_indices = [index for group in groups for index in group.plan_indices]
    span_violations = [
        group
        for group in groups
        if group.end_page - group.start_page + 1 < MIN_PAGE_SPAN
    ]
    summary = {
        "page_count": page_count,
        "bookmark_plan_count": len(plan),
        "raw_adaptive_entry_count": len(entries),
        "final_group_count": len(groups),
        "blocked_same_page_merge_count": blocked_same_page,
        "page_span_merge_count": page_span_merges,
        "min_word_merge_count": min_word_merges,
        "blocked_page_span_merge_count": blocked_page_span,
        "blocked_min_word_merge_count": blocked_min_words,
        "same_page_start_count": len(starts) - len(set(starts)),
        "page_span_violation_count": len(span_violations),
        "small_group_count": sum(group.word_count < MIN_WORDS for group in groups),
        "large_group_count": sum(
            group.word_count > source.MAX_WORDS for group in groups
        ),
        "all_plan_nodes_accounted": set(all_indices) == set(range(len(plan))),
        "duplicated_plan_node_count": len(all_indices) - len(set(all_indices)),
        "synthetic_node_count": 0,
        "samples": [
            {
                "start_page": group.start_page,
                "end_page": group.end_page,
                "page_span": group.end_page - group.start_page + 1,
                "word_count": group.word_count,
                "top_root_title": plan[group.top_root].title,
                "lca_title": plan[lca(group.plan_indices, parents)].title
                if lca(group.plan_indices, parents) is not None
                else None,
                "member_titles": [
                    plan[index].title for index in group.plan_indices[:8]
                ],
            }
            for group in groups[:25]
        ],
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "Hull production BPE bookmark tree에서 adaptive frontier의 min_words/page span "
            "병합을 같은 top-level 실제 root 안으로 제한해, 084의 의미적으로 무관한 "
            "병합을 막으면서 page 불변식을 만족할 수 있는지 검증한다."
        ),
        "inputs": [str(source.BOOK_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "084의 실제-node adaptive entry를 출발점으로 쓰고, 같은 page·1-page·min_words "
            "미달 group을 직전 우선으로 합치되 top-level root가 다르면 병합하지 않는다. "
            "각 group의 LCA와 막힌 병합을 기록한다."
        ),
        "summary": summary,
        "finding": (
            f"raw={summary['raw_adaptive_entry_count']} final={summary['final_group_count']} "
            f"blocked_same_page={summary['blocked_same_page_merge_count']} "
            f"same_page_starts={summary['same_page_start_count']} "
            f"span_violations={summary['page_span_violation_count']} "
            f"small={summary['small_group_count']} large={summary['large_group_count']}"
        ),
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"] = [
        item for item in data["experiments"] if item.get("id") != EXPERIMENT_ID
    ] + [entry]
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
