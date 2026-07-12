"""experiment 084: Hull에서 실제 node만 쓰는 adaptive frontier를 검증한다.

가짜 page/paragraph node 없이 production BPE bookmark plan의 실제 node만 선택한다.
같은 PDF page에서 두 Markdown frontier가 시작하지 않고, 각 frontier가 최소 두
PDF page를 차지하도록 작은 node를 인접한 기존 node와 묶을 수 있는지 측정한다.

실행:
    uv run python experiments/084_hull_adaptive_frontier_page_invariants.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import fitz

from pdfbooktree.config import TypographyConfig
from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.outline.plan import normalize_bookmark_plan
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.typography.bpe import extract_bpe_headings, infer_bpe_outline
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts
from pdfbooktree.typography.tiers import compute_tier_set
from pdfbooktree.utils.text_normalize import normalize_text


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "084_hull_adaptive_frontier_page_invariants"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
BOOK_PDF = (
    ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf"
)
MIN_PAGE_SPAN = 2
MAX_WORDS = 10_000
MIN_WORDS_OPTIONS = (500, 1_000)


@dataclass
class TreeNode:
    """실제 bookmark plan의 한 node와 preorder subtree 범위를 보관한다."""

    index: int
    item: BookmarkPlanItem
    subtree_end_index: int
    children: list["TreeNode"] = field(default_factory=list)


@dataclass
class FrontierEntry:
    """실제 node들만 포함하는 adaptive frontier의 초기 항목이다."""

    start_page: int
    end_page_exclusive: int
    plan_indices: list[int]


@dataclass
class FrontierGroup:
    """여러 기존 node를 한 Markdown 파일에 연속 기록하는 경계 묶음이다."""

    start_page: int
    plan_indices: list[int]
    end_page: int = 0
    word_count: int = 0


def build_plan() -> tuple[list[BookmarkPlanItem], dict[int, int], int]:
    """현재 production BPE pipeline으로 Hull bookmark plan과 page word 수를 만든다."""

    config = TypographyConfig()
    with fitz.open(BOOK_PDF) as document:
        page_count = document.page_count
    raw_lines = extract_typography_lines(BOOK_PDF, config)
    lines = exclude_margin_artifacts(raw_lines, config)
    font_tiers = compute_tier_set(lines, "font_size", config)
    candidates = extract_bpe_headings(lines, font_tiers, config)
    plan = normalize_bookmark_plan(infer_bpe_outline(candidates, config))
    page_words = {
        page.pdf_page: len(normalize_text(page.text).split())
        for page in extract_page_texts(BOOK_PDF, max_pages=page_count)
    }
    return plan, page_words, page_count


def build_tree(plan: list[BookmarkPlanItem]) -> list[TreeNode]:
    """정규화된 preorder plan을 실제 parent-child tree로 바꾼다."""

    nodes = [TreeNode(index, item, len(plan)) for index, item in enumerate(plan)]
    stack: list[TreeNode] = []
    roots: list[TreeNode] = []
    for node in nodes:
        while stack and stack[-1].item.level >= node.item.level:
            stack.pop().subtree_end_index = node.index
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)
    while stack:
        stack.pop().subtree_end_index = len(plan)
    return roots


def word_count(
    page_words: dict[int, int], start_page: int, end_page_exclusive: int
) -> int:
    """PDF page 범위의 중복 없는 body word 수를 센다."""

    return sum(
        page_words.get(page, 0) for page in range(start_page, end_page_exclusive)
    )


def choose_adaptive_entries(
    roots: list[TreeNode],
    page_words: dict[int, int],
    page_count: int,
) -> list[FrontierEntry]:
    """과대 subtree만 실제 child node로 내려가며 frontier를 고른다.

    부모가 child로 치환될 때 부모 제목과 첫 child 사이의 본문을 잃지 않도록 부모
    plan index는 첫 child entry에 포함하고 시작 page도 부모 page를 유지한다. 이는
    새 node를 만드는 것이 아니라 실제 부모 node를 같은 Markdown 파일에 기록하는
    방식이다.
    """

    entries: list[FrontierEntry] = []

    def visit(
        node: TreeNode,
        start_page: int,
        end_page_exclusive: int,
        inherited_indices: list[int],
    ) -> None:
        if (
            word_count(page_words, start_page, end_page_exclusive) > MAX_WORDS
            and node.children
        ):
            for position, child in enumerate(node.children):
                child_start = start_page if position == 0 else child.item.pdf_page
                child_end = (
                    node.children[position + 1].item.pdf_page
                    if position + 1 < len(node.children)
                    else end_page_exclusive
                )
                visit(
                    child,
                    child_start,
                    child_end,
                    [*inherited_indices, node.index] if position == 0 else [],
                )
            return
        entries.append(
            FrontierEntry(
                start_page=start_page,
                end_page_exclusive=end_page_exclusive,
                plan_indices=[
                    *inherited_indices,
                    *range(node.index, node.subtree_end_index),
                ],
            )
        )

    for position, root in enumerate(roots):
        root_end = (
            roots[position + 1].item.pdf_page
            if position + 1 < len(roots)
            else page_count + 1
        )
        visit(root, root.item.pdf_page, root_end, [])
    return entries


def initial_groups(entries: list[FrontierEntry]) -> list[FrontierGroup]:
    """같은 page에 시작하는 실제 frontier entry를 하나의 파일 후보로 묶는다."""

    groups: list[FrontierGroup] = []
    for entry in entries:
        if groups and groups[-1].start_page == entry.start_page:
            groups[-1].plan_indices.extend(entry.plan_indices)
        else:
            groups.append(FrontierGroup(entry.start_page, list(entry.plan_indices)))
    return groups


def refresh_groups(
    groups: list[FrontierGroup], page_words: dict[int, int], page_count: int
) -> None:
    """최종 boundary만으로 page range와 word 수를 다시 계산한다."""

    for position, group in enumerate(groups):
        next_start = (
            groups[position + 1].start_page
            if position + 1 < len(groups)
            else page_count + 1
        )
        group.end_page = next_start - 1
        group.word_count = word_count(page_words, group.start_page, next_start)


def merge_groups(groups: list[FrontierGroup], left_index: int) -> None:
    """인접한 두 기존-node 묶음을 하나의 Markdown 파일 후보로 합친다."""

    left = groups[left_index]
    right = groups[left_index + 1]
    left.plan_indices.extend(right.plan_indices)
    del groups[left_index + 1]


def enforce_page_span(
    groups: list[FrontierGroup], page_words: dict[int, int], page_count: int
) -> int:
    """모든 frontier가 최소 두 PDF page를 갖도록 인접 기존 node를 병합한다."""

    merge_count = 0
    while len(groups) > 1:
        refresh_groups(groups, page_words, page_count)
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
        merge_groups(
            groups, short_index if short_index + 1 < len(groups) else short_index - 1
        )
        merge_count += 1
    refresh_groups(groups, page_words, page_count)
    return merge_count


def enforce_min_words(
    groups: list[FrontierGroup],
    page_words: dict[int, int],
    page_count: int,
    min_words: int,
) -> int:
    """작은 frontier를 우선 직전 실제-node 파일에 이어 붙인다."""

    merge_count = 0
    while len(groups) > 1:
        refresh_groups(groups, page_words, page_count)
        small_index = next(
            (
                index
                for index, group in enumerate(groups)
                if group.word_count < min_words
            ),
            None,
        )
        if small_index is None:
            break
        merge_groups(groups, small_index - 1 if small_index else 0)
        merge_count += 1
    refresh_groups(groups, page_words, page_count)
    return merge_count


def evaluate(
    entries: list[FrontierEntry],
    plan: list[BookmarkPlanItem],
    page_words: dict[int, int],
    page_count: int,
    min_words: int,
) -> dict[str, object]:
    """page·node·word 불변식을 검사하고 사람이 볼 sample을 만든다."""

    groups = initial_groups(entries)
    same_page_merge_count = len(entries) - len(groups)
    page_span_merge_count = enforce_page_span(groups, page_words, page_count)
    min_word_merge_count = enforce_min_words(groups, page_words, page_count, min_words)
    refresh_groups(groups, page_words, page_count)
    starts = [group.start_page for group in groups]
    all_indices = [index for group in groups for index in group.plan_indices]
    span_violations = [
        group
        for group in groups
        if group.end_page - group.start_page + 1 < MIN_PAGE_SPAN
    ]
    samples = [
        {
            "start_page": group.start_page,
            "end_page": group.end_page,
            "page_span": group.end_page - group.start_page + 1,
            "word_count": group.word_count,
            "member_count": len(group.plan_indices),
            "member_titles": [plan[index].title for index in group.plan_indices[:8]],
        }
        for group in groups[:20]
    ]
    return {
        "min_words": min_words,
        "max_words": MAX_WORDS,
        "raw_adaptive_entry_count": len(entries),
        "final_group_count": len(groups),
        "same_page_merge_count": same_page_merge_count,
        "page_span_merge_count": page_span_merge_count,
        "min_word_merge_count": min_word_merge_count,
        "small_group_count": sum(group.word_count < min_words for group in groups),
        "large_group_count": sum(group.word_count > MAX_WORDS for group in groups),
        "strictly_increasing_start_pages": all(
            left < right for left, right in zip(starts, starts[1:], strict=False)
        ),
        "same_page_start_count": len(starts) - len(set(starts)),
        "page_span_violation_count": len(span_violations),
        "all_plan_nodes_accounted": set(all_indices) == set(range(len(plan))),
        "duplicated_plan_node_count": len(all_indices) - len(set(all_indices)),
        "synthetic_node_count": 0,
        "samples": samples,
    }


def record_experiment(summary: dict[str, object]) -> None:
    """실험 결과를 registry에 기록한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entries = {
        name: result
        for name, result in summary["configurations"].items()  # type: ignore[union-attr]
    }
    finding = " | ".join(
        (
            f"{name}: raw={result['raw_adaptive_entry_count']} final={result['final_group_count']} "
            f"same_page_merge={result['same_page_merge_count']} "
            f"span_merge={result['page_span_merge_count']} min_merge={result['min_word_merge_count']} "
            f"small={result['small_group_count']} large={result['large_group_count']} "
            f"page_ok={result['same_page_start_count'] == 0 and result['page_span_violation_count'] == 0}"
        )
        for name, result in entries.items()
    )
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "현재 production BPE bookmark plan을 실제 Hull PDF에서 만들고, synthetic node 없이 "
            "실제 node만 쓰는 adaptive frontier가 같은 PDF page의 복수 시작 경계 금지, "
            "최소 2-page span, min_words 병합을 만족할 수 있는지 검증한다."
        ),
        "inputs": [str(BOOK_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "과대 subtree만 실제 child로 재귀 분할한 뒤 같은 page 시작 entry를 합치고, "
            "1-page group과 min_words 미달 group을 인접한 기존 node group에 병합한다. "
            "최종 page range는 병합 뒤의 다음 boundary로 계산한다."
        ),
        "summary": summary,
        "finding": finding,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"] = [
        item for item in data["experiments"] if item.get("id") != EXPERIMENT_ID
    ] + [entry]
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    """Hull production plan에서 strict frontier prototype을 실행한다."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plan, page_words, page_count = build_plan()
    roots = build_tree(plan)
    entries = choose_adaptive_entries(roots, page_words, page_count)
    configurations = {
        f"min{min_words}_max{MAX_WORDS}": evaluate(
            entries, plan, page_words, page_count, min_words
        )
        for min_words in MIN_WORDS_OPTIONS
    }
    summary: dict[str, object] = {
        "page_count": page_count,
        "bookmark_plan_count": len(plan),
        "raw_adaptive_entry_count": len(entries),
        "configurations": configurations,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_experiment(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
