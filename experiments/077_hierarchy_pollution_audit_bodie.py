"""experiment 077: hierarchy 안의 본문 오염을 bookmark ground truth로 감사한다.

076의 길이 분할을 더 세밀한 규칙으로 보완하지 않는다. 대신 후보 tree 자체에서
bookmark에 매칭되지 않은 후보가 실제 heading의 조상으로 들어가 hierarchy를 얼마나
오염시키는지 측정한다. 후보의 단어 수는 제거 임계값이 아니라 오염 분포를 설명하는
관측값으로만 쓴다.

실행:
    uv run python experiments/077_hierarchy_pollution_audit_bodie.py
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

import fitz
import numpy as np
from rapidfuzz import fuzz

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "077_hierarchy_pollution_audit_bodie"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
SOURCE_EXPERIMENT = ROOT_DIR / "experiments" / "075_length_based_level_selection_bodie.py"
BOOK_PDF = (
    ROOT_DIR
    / "data"
    / "300STUDY"
    / "textbooks"
    / "Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf"
)
TITLE_MATCH_THRESHOLD = 70
_NORM_STRIP = re.compile(r"[^a-z0-9가-힣 ]")
_MULTI_SPACE = re.compile(r"\s+")
_WORD_SPLIT = re.compile(r"\S+")


def load_source_experiment() -> Any:
    spec = importlib.util.spec_from_file_location("experiment_075_for_077", SOURCE_EXPERIMENT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"실험 075를 불러올 수 없습니다: {SOURCE_EXPERIMENT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def normalize_for_match(text: str) -> str:
    return _MULTI_SPACE.sub(" ", _NORM_STRIP.sub(" ", text.lower())).strip()


def load_ground_truth(pdf_path: Path) -> list[dict[str, Any]]:
    with fitz.open(pdf_path) as document:
        toc = document.get_toc(simple=False)
    return [
        {"truth_idx": index, "level": level, "title": title, "page": page}
        for index, (level, title, page, _destination) in enumerate(toc)
        if page > 0
    ]


def match_bookmarks(candidates: list[Any], truth: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """기존 072~074와 같은 page-local fuzzy title 매칭을 사용한다.

    이 결과의 미매칭은 "본문"이라는 확정 판정이 아니다. PDF bookmark에 없는 후보를
    뜻하며, hierarchy에 실제 구조가 아닌 노드가 끼어든 정도를 볼 수 있는 proxy다.
    """

    by_page: dict[int, list[Any]] = defaultdict(list)
    for candidate in candidates:
        by_page[candidate.pdf_page].append(candidate)

    matches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for entry in truth:
        best: Any | None = None
        best_score = -1.0
        truth_norm = normalize_for_match(entry["title"])
        for candidate in by_page.get(entry["page"], []):
            score = fuzz.token_set_ratio(truth_norm, normalize_for_match(candidate.text))
            if score > best_score:
                best = candidate
                best_score = score
        if best is not None and best_score >= TITLE_MATCH_THRESHOLD:
            matches[best.idx].append(
                {
                    "truth_idx": entry["truth_idx"],
                    "truth_title": entry["title"],
                    "truth_level": entry["level"],
                    "match_score": round(best_score, 1),
                }
            )
    return matches


def word_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = [item["title_word_count"] for item in items]
    if not counts:
        return {"count": 0, "median": None, "p90": None, "max": None}
    return {
        "count": len(counts),
        "median": int(median(counts)),
        "p90": int(np.percentile(counts, 90)),
        "max": max(counts),
    }


def audit_hierarchy(candidates: list[Any], matches: dict[int, list[dict[str, Any]]]) -> dict[str, Any]:
    by_idx = {candidate.idx: candidate for candidate in candidates}
    children: dict[int | None, list[int]] = defaultdict(list)
    for candidate in candidates:
        children[candidate.parent_idx].append(candidate.idx)
    for sibling_ids in children.values():
        sibling_ids.sort()

    matched_ids = set(matches)
    subtree_matched_count: dict[int, int] = {}
    subtree_node_count: dict[int, int] = {}

    def count_subtree(node_id: int) -> tuple[int, int]:
        matched_count = int(node_id in matched_ids)
        node_count = 1
        for child_id in children.get(node_id, []):
            child_matched, child_nodes = count_subtree(child_id)
            matched_count += child_matched
            node_count += child_nodes
        subtree_matched_count[node_id] = matched_count
        subtree_node_count[node_id] = node_count
        return matched_count, node_count

    for root_id in children.get(None, []):
        count_subtree(root_id)

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        unmatched_ancestor_ids: list[int] = []
        parent_id = candidate.parent_idx
        while parent_id is not None:
            if parent_id not in matched_ids:
                unmatched_ancestor_ids.append(parent_id)
            parent_id = by_idx[parent_id].parent_idx
        rows.append(
            {
                "idx": candidate.idx,
                "pdf_page": candidate.pdf_page,
                "level": candidate.level,
                "title": candidate.text,
                "title_word_count": len(_WORD_SPLIT.findall(candidate.text)),
                "parent_idx": candidate.parent_idx,
                "bookmark_match_count": len(matches.get(candidate.idx, [])),
                "bookmark_matches": matches.get(candidate.idx, []),
                "is_bookmark_matched": candidate.idx in matched_ids,
                "unmatched_ancestor_ids": unmatched_ancestor_ids,
                "subtree_node_count": subtree_node_count[candidate.idx],
                "subtree_matched_heading_count": subtree_matched_count[candidate.idx],
            }
        )

    unmatched_rows = [row for row in rows if not row["is_bookmark_matched"]]
    matched_rows = [row for row in rows if row["is_bookmark_matched"]]
    bridge_rows = [
        row for row in unmatched_rows if row["subtree_matched_heading_count"] > 0
    ]
    contaminated_matched = [row for row in matched_rows if row["unmatched_ancestor_ids"]]

    by_level: dict[int, dict[str, Any]] = {}
    for level in sorted({row["level"] for row in rows}):
        level_rows = [row for row in rows if row["level"] == level]
        level_unmatched = [row for row in level_rows if not row["is_bookmark_matched"]]
        level_bridge = [row for row in level_unmatched if row["subtree_matched_heading_count"] > 0]
        by_level[level] = {
            "candidate_count": len(level_rows),
            "bookmark_matched_count": len(level_rows) - len(level_unmatched),
            "bookmark_unmatched_count": len(level_unmatched),
            "bookmark_unmatched_fraction": round(len(level_unmatched) / len(level_rows), 4),
            "unmatched_word_count": word_stats(level_unmatched),
            "bridge_candidate_count": len(level_bridge),
            "bridge_descendant_matched_heading_count": sum(
                row["subtree_matched_heading_count"] for row in level_bridge
            ),
        }

    bridge_samples = sorted(
        bridge_rows,
        key=lambda row: (row["subtree_matched_heading_count"], row["title_word_count"]),
        reverse=True,
    )[:30]
    long_unmatched_samples = sorted(
        unmatched_rows, key=lambda row: row["title_word_count"], reverse=True
    )[:30]
    return {
        "candidate_rows": rows,
        "summary": {
            "candidate_count": len(rows),
            "bookmark_matched_candidate_count": len(matched_rows),
            "bookmark_unmatched_candidate_count": len(unmatched_rows),
            "bookmark_unmatched_fraction": round(len(unmatched_rows) / len(rows), 4),
            "matched_heading_with_unmatched_ancestor_count": len(contaminated_matched),
            "matched_heading_with_unmatched_ancestor_fraction": round(
                len(contaminated_matched) / len(matched_rows), 4
            )
            if matched_rows
            else 0.0,
            "unmatched_bridge_candidate_count": len(bridge_rows),
            "unmatched_bridge_descendant_matched_heading_count": sum(
                row["subtree_matched_heading_count"] for row in bridge_rows
            ),
            "matched_title_word_count": word_stats(matched_rows),
            "unmatched_title_word_count": word_stats(unmatched_rows),
        },
        "per_level": {str(level): result for level, result in by_level.items()},
        "bridge_samples": bridge_samples,
        "long_unmatched_samples": long_unmatched_samples,
    }


def record_experiment(truth_count: int, audit: dict[str, Any]) -> None:
    summary = audit["summary"]
    per_level = audit["per_level"]
    finding = (
        f"candidates={summary['candidate_count']} bookmark_matched="
        f"{summary['bookmark_matched_candidate_count']} unmatched="
        f"{summary['bookmark_unmatched_candidate_count']}"
        f"({summary['bookmark_unmatched_fraction']:.4f}) | matched headings with unmatched "
        f"ancestor={summary['matched_heading_with_unmatched_ancestor_count']}"
        f"({summary['matched_heading_with_unmatched_ancestor_fraction']:.4f}) | unmatched bridge "
        f"candidates={summary['unmatched_bridge_candidate_count']} descendant matched headings="
        f"{summary['unmatched_bridge_descendant_matched_heading_count']} | "
        + " | ".join(
            f"L{level}: unmatched={result['bookmark_unmatched_count']}/{result['candidate_count']}"
            f"({result['bookmark_unmatched_fraction']:.4f}) bridge={result['bridge_candidate_count']}"
            for level, result in per_level.items()
        )
    )
    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "규칙 기반 제거 없이 raw candidate hierarchy를 bookmark ground truth와 page-local "
            "fuzzy title 매칭해, bookmark에 없는 후보가 실제 heading의 조상으로 들어가는 "
            "오염(bridge) 규모를 측정한다. title 단어 수는 필터 조건이 아니라 매칭/미매칭 "
            "후보 분포를 설명하는 관측값으로만 기록한다."
        ),
        "inputs": [str(BOOK_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "source_experiments": ["074_bpe_style_page_local_tier_merge", "075_length_based_level_selection_bodie", "076_adaptive_frontier_length_selection_bodie"],
        "candidate_pipeline": "075와 동일하되 title 길이로 후보를 제거하지 않음",
        "title_match_threshold": TITLE_MATCH_THRESHOLD,
        "ground_truth_bookmark_count": truth_count,
        "hierarchy_pollution": {key: value for key, value in audit.items() if key != "candidate_rows"},
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
    source = load_source_experiment()
    source.BOOK_PDF = BOOK_PDF
    print(f"... raw 후보 tree 생성 중: {BOOK_PDF.name}")
    # title 길이를 어떤 판정에도 쓰지 않기 위해 충분히 큰 값으로 모든 후보를 유지한다.
    candidates, _page_word_counts, _page_count, removed_nodes = source.build_candidate_tree(
        BOOK_PDF, max_title_words=1_000_000
    )
    truth = load_ground_truth(BOOK_PDF)
    matches = match_bookmarks(candidates, truth)
    audit = audit_hierarchy(candidates, matches)
    summary = audit["summary"]
    print(
        f"candidates={summary['candidate_count']} truth={len(truth)} "
        f"bookmark_unmatched={summary['bookmark_unmatched_candidate_count']} "
        f"bridge={summary['unmatched_bridge_candidate_count']} "
        f"contaminated_matched={summary['matched_heading_with_unmatched_ancestor_count']} "
        f"removed_by_title_filter={len(removed_nodes)}"
    )
    for level, result in audit["per_level"].items():
        print(
            f"L{level}: unmatched={result['bookmark_unmatched_count']}/{result['candidate_count']} "
            f"bridge={result['bridge_candidate_count']} "
            f"unmatched_words={result['unmatched_word_count']}"
        )

    (OUTPUT_DIR / "hierarchy_pollution_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record_experiment(len(truth), audit)
    print(f"summary: {OUTPUT_DIR / 'hierarchy_pollution_audit.json'}")


if __name__ == "__main__":
    main()
