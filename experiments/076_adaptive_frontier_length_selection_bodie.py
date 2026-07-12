"""experiment 076: 계층별 적응형 frontier로 본문 길이 경계를 선택한다.

075는 책 전체에 같은 cutoff depth를 적용하면 1,000단어 하한과 상한을 동시에
만족시키기 어렵다는 것을 보였다. 이 실험은 후보 트리의 각 노드에서만 필요한 만큼
하위 heading으로 내려가는 방식으로 그 한계를 완화할 수 있는지 검증한다.

실행:
    uv run python experiments/076_adaptive_frontier_length_selection_bodie.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "076_adaptive_frontier_length_selection_bodie"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
SOURCE_EXPERIMENT = ROOT_DIR / "experiments" / "075_length_based_level_selection_bodie.py"
BOOK_PDF = (
    ROOT_DIR
    / "data"
    / "300STUDY"
    / "textbooks"
    / "Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf"
)


def load_source_experiment() -> Any:
    """075의 검증 완료된 후보 트리 생성 파이프라인을 그대로 사용한다.

    076은 패키지 구현이 아니라 길이 선택 규칙만 바꾸는 단일 PoC다. 따라서 font
    tier, BPE 병합, stack 계층화가 달라져 결과가 섞이지 않도록 075 파일을 읽기 전용
    기준선으로 불러온다.
    """

    spec = importlib.util.spec_from_file_location("experiment_075", SOURCE_EXPERIMENT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"실험 075를 불러올 수 없습니다: {SOURCE_EXPERIMENT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_children(candidates: list[Any]) -> tuple[dict[int, Any], dict[int | None, list[Any]]]:
    by_idx = {candidate.idx: candidate for candidate in candidates}
    children: dict[int | None, list[Any]] = defaultdict(list)
    for candidate in candidates:
        children[candidate.parent_idx].append(candidate)
    for siblings in children.values():
        siblings.sort(key=lambda candidate: candidate.idx)
    return by_idx, children


def count_words(page_word_counts: dict[int, int], start_page: int, end_page_exclusive: int) -> int:
    return sum(page_word_counts.get(page, 0) for page in range(start_page, end_page_exclusive))


def choose_adaptive_frontier(
    candidates: list[Any],
    page_word_counts: dict[int, int],
    page_count: int,
    max_words: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """너무 긴 노드만 직계 자식으로 치환해 가변 깊이 frontier를 만든다.

    첫 자식의 시작 page는 부모의 시작 page로 당겨, 부모 제목과 첫 자식 제목 사이의
    본문이 출력 범위에서 빠지지 않게 한다. page 단위 길이 근사라 같은 페이지의
    인접 heading은 0단어 조각이 될 수 있으며, 이를 숨기지 않고 결과에 기록한다.
    """

    _by_idx, children = build_children(candidates)
    frontier: list[dict[str, Any]] = []
    unsplittable: list[dict[str, Any]] = []

    def visit(node: Any, start_page: int, end_page_exclusive: int, title_path: list[str]) -> None:
        words = count_words(page_word_counts, start_page, end_page_exclusive)
        direct_children = children.get(node.idx, [])
        if words > max_words and direct_children:
            for position, child in enumerate(direct_children):
                child_start = start_page if position == 0 else child.pdf_page
                child_end = (
                    direct_children[position + 1].pdf_page
                    if position + 1 < len(direct_children)
                    else end_page_exclusive
                )
                visit(child, child_start, child_end, [*title_path, child.text])
            return

        item = {
            "idx": node.idx,
            "title": node.text,
            "heading_path": title_path,
            "level": node.level,
            "start_page": start_page,
            "end_page_exclusive": end_page_exclusive,
            "word_count": words,
            "child_count": len(direct_children),
        }
        frontier.append(item)
        if words > max_words and not direct_children:
            unsplittable.append(item)

    roots = children.get(None, [])
    for position, root in enumerate(roots):
        root_end = roots[position + 1].pdf_page if position + 1 < len(roots) else page_count + 1
        visit(root, root.pdf_page, root_end, [root.text])
    return frontier, unsplittable


def summarise_frontier(
    frontier: list[dict[str, Any]],
    unsplittable: list[dict[str, Any]],
    min_words: int,
    max_words: int,
) -> dict[str, Any]:
    counts = [item["word_count"] for item in frontier]
    too_small = [item for item in frontier if item["word_count"] < min_words]
    too_large = [item for item in frontier if item["word_count"] > max_words]
    intra_page_small = [
        item for item in too_small if item["end_page_exclusive"] <= item["start_page"]
    ]
    return {
        "min_words": min_words,
        "max_words": max_words,
        "chunk_count": len(frontier),
        "min_word_count": min(counts) if counts else None,
        "max_word_count": max(counts) if counts else None,
        "median_word_count": int(np.median(counts)) if counts else None,
        "p90_word_count": int(np.percentile(counts, 90)) if counts else None,
        "within_range_count": sum(min_words <= count <= max_words for count in counts),
        "within_range_fraction": round(
            sum(min_words <= count <= max_words for count in counts) / len(counts), 4
        )
        if counts
        else 0.0,
        "min_words_fraction_ok": round(sum(count >= min_words for count in counts) / len(counts), 4)
        if counts
        else 0.0,
        "max_words_fraction_ok": round(sum(count <= max_words for count in counts) / len(counts), 4)
        if counts
        else 0.0,
        "too_small_count": len(too_small),
        "intra_page_small_count": len(intra_page_small),
        "genuine_small_count": len(too_small) - len(intra_page_small),
        "too_large_count": len(too_large),
        "unsplittable_large_count": len(unsplittable),
        "success_at_p90": (
            sum(min_words <= count <= max_words for count in counts) / len(counts) >= 0.9
            if counts
            else False
        ),
        "too_small_samples": sorted(too_small, key=lambda item: item["word_count"])[:10],
        "unsplittable_large_samples": sorted(
            unsplittable, key=lambda item: item["word_count"], reverse=True
        )[:10],
    }


def global_cutoff_comparison(source: Any, level_stats: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """075의 동일한 p90 규칙을 기준선으로 남긴다."""

    return {
        "min1000_max10000_p90": source.select_level_by_conditions(
            level_stats, cum_percentile=0.9, min_words=1000, max_words=10000
        ),
        "min1000_max2000_p90": source.select_level_by_conditions(
            level_stats, cum_percentile=0.9, min_words=1000, max_words=2000
        ),
    }


def record_experiment(
    candidate_count: int,
    global_comparison: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> None:
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    finding = " | ".join(
        (
            f"{name}: chunks={result['chunk_count']} within_range="
            f"{result['within_range_fraction']:.4f} p90={result['p90_word_count']} "
            f"small={result['too_small_count']}(intra_page={result['intra_page_small_count']}) "
            f"large={result['too_large_count']}(unsplittable={result['unsplittable_large_count']}) "
            f"success_at_p90={result['success_at_p90']}"
        )
        for name, result in results.items()
    )
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "075에서 확인된 전역 cutoff depth의 길이 제약 충돌을 해결하기 위해, "
            "L1 root에서 시작해 max_words를 넘는 노드만 직계 자식으로 재귀 분할하는 "
            "적응형 frontier를 검증한다. 각 leaf chunk가 min_words~max_words 범위에 "
            "드는 비율과, 분할 불가능한 과대 노드 및 page 단위 근사로 생긴 작은 "
            "조각을 분리해 측정한다."
        ),
        "inputs": [str(BOOK_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": ["074_bpe_style_page_local_tier_merge", "075_length_based_level_selection_bodie"],
        "candidate_pipeline": "075와 동일: mode_and_smaller, bpe_min15, title>20단어 후보 제거",
        "candidate_count": candidate_count,
        "global_cutoff_comparison": global_comparison,
        "adaptive_frontier_results": results,
        "finding": finding,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    experiments = data["experiments"]
    data["experiments"] = [item for item in experiments if item.get("id") != EXPERIMENT_ID] + [entry]
    EXPERIMENTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source = load_source_experiment()
    # 075 당시의 indexed 사본은 현재 없고, 같은 실제 PDF가 원본 데이터 폴더에 있다.
    # 후보 생성 파이프라인만 동일하게 유지하고 입력 위치만 현재 실재하는 파일로 바꾼다.
    source.BOOK_PDF = BOOK_PDF
    if not BOOK_PDF.exists():
        print(f"PDF 없음: {BOOK_PDF}")
        return

    print(f"... 후보 트리 생성 중: {source.BOOK_PDF.name}")
    candidates, page_word_counts, page_count, removed_nodes = source.build_candidate_tree(
        source.BOOK_PDF, max_title_words=20
    )
    level_stats = source.compute_level_length_stats(candidates, page_word_counts, page_count)
    global_comparison = global_cutoff_comparison(source, level_stats)
    print(f"    candidates={len(candidates)} pages={page_count} removed_polluted={len(removed_nodes)}")

    configurations = {"min1000_max10000": (1000, 10000), "min1000_max2000": (1000, 2000)}
    results: dict[str, dict[str, Any]] = {}
    output: dict[str, Any] = {"global_cutoff_comparison": global_comparison, "adaptive": {}}
    for name, (min_words, max_words) in configurations.items():
        frontier, unsplittable = choose_adaptive_frontier(
            candidates, page_word_counts, page_count, max_words
        )
        summary = summarise_frontier(frontier, unsplittable, min_words, max_words)
        results[name] = summary
        output["adaptive"][name] = {"summary": summary, "frontier": frontier}
        print(
            f"{name}: chunks={summary['chunk_count']} within={summary['within_range_fraction']:.4f} "
            f"p90={summary['p90_word_count']} small={summary['too_small_count']} "
            f"(same_page={summary['intra_page_small_count']}) large={summary['too_large_count']} "
            f"unsplittable={summary['unsplittable_large_count']} p90_success={summary['success_at_p90']}"
        )

    (OUTPUT_DIR / "adaptive_frontier.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record_experiment(len(candidates), global_comparison, results)
    print(f"summary: {OUTPUT_DIR / 'adaptive_frontier.json'}")


if __name__ == "__main__":
    main()
