"""300STUDY 밖 sample PDF의 BPE bookmark tree만 텍스트로 저장한다."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from pdfbooktree.config import TypographyConfig
from pdfbooktree.export.markdown import _render_split_documents, _statistics
from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.outline.plan import normalize_bookmark_plan
from pdfbooktree.outline.tree import build_outline_tree
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.typography.bpe import extract_bpe_headings, infer_bpe_outline
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts
from pdfbooktree.typography.tiers import compute_tier_set
from pdfbooktree.utils.paths import safe_filename
from pdfbooktree.utils.text_normalize import normalize_text


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "013_bpe_bookmark_tree_samples"
MAX_WORDS = 10_000
MAX_WORDS_COVERAGE = 0.90
_TREE_ITEM = re.compile(r"^\s*- \[L(?P<level>\d+), p\.(?P<page>\d+)\] (?P<title>.+)$")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_paths = sorted(
        path for path in DATA_DIR.rglob("*.pdf") if "300STUDY" not in path.parts
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, help="처리할 1-based sample PDF 순번")
    parser.add_argument(
        "--select-splits",
        action="store_true",
        help="기존 tree에서 10000단어·90% coverage split level을 계산한다.",
    )
    args = parser.parse_args()
    if args.index is not None and not 1 <= args.index <= len(pdf_paths):
        raise ValueError(f"--index는 1..{len(pdf_paths)} 범위여야 한다")
    targets = [pdf_paths[args.index - 1]] if args.index is not None else pdf_paths
    result_path = OUTPUT_DIR / "result.json"
    previous = _load_previous_results(result_path)
    results_by_input = {str(item["input"]): item for item in previous}
    for pdf_path in targets:
        if args.select_splits:
            result = _write_selected_split_tree(pdf_path, results_by_input)
        else:
            try:
                result = _write_bookmark_tree(pdf_path)
            except Exception as error:  # showcase는 각 실제 파일 실패를 기록하고 다음 파일을 계속 본다.
                result = {
                    "input": str(pdf_path.relative_to(ROOT_DIR)),
                    "status": "failed",
                    "error": f"{type(error).__name__}: {error}",
                }
        results_by_input[str(result["input"])] = result
        print(json.dumps(result, ensure_ascii=False))

    payload = {
        "showcase_id": "013_bpe_bookmark_tree_samples",
        "excluded_directory": "data/300STUDY",
        "book_count": len(pdf_paths),
        "results": [
            results_by_input.get(
                str(path.relative_to(ROOT_DIR)),
                {"input": str(path.relative_to(ROOT_DIR)), "status": "pending"},
            )
            for path in pdf_paths
        ],
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_previous_results(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("results", []))


def _write_bookmark_tree(pdf_path: Path) -> dict[str, object]:
    config = TypographyConfig(bpe_min_pair_count=15)
    lines = exclude_margin_artifacts(extract_typography_lines(pdf_path, config), config)
    font_tiers = compute_tier_set(lines, "font_size", config)
    headings = extract_bpe_headings(lines, font_tiers, config)
    plan = normalize_bookmark_plan(infer_bpe_outline(headings, config))
    if not plan:
        raise RuntimeError("BPE bookmark 항목이 생성되지 않았다")
    total_pages = max(line.pdf_page for line in lines)
    roots = build_outline_tree(plan, total_pages)
    file_name = f"{safe_filename(pdf_path.stem)}_bookmark_tree.txt"
    output_path = OUTPUT_DIR / file_name
    output_path.write_text(_render_tree(roots), encoding="utf-8")
    return {
        "input": str(pdf_path.relative_to(ROOT_DIR)),
        "status": "processed",
        "bookmark_count": len(plan),
        "level_counts": dict(sorted(Counter(item.level for item in plan).items())),
        "output": str(output_path.relative_to(ROOT_DIR)),
    }


def _write_selected_split_tree(
    pdf_path: Path, results_by_input: dict[str, dict[str, object]]
) -> dict[str, object]:
    input_key = str(pdf_path.relative_to(ROOT_DIR))
    previous = results_by_input.get(input_key)
    if previous is None or previous.get("status") != "processed":
        raise RuntimeError("먼저 기본 bookmark tree를 생성해야 한다")
    tree_path = ROOT_DIR / str(previous["output"])
    plan = _load_plan_from_tree(tree_path)
    page_texts = {
        page.pdf_page: normalize_text(page.text)
        for page in extract_page_texts(pdf_path)
    }
    total_pages = max(page_texts, default=0)
    trials = {
        level: _render_split_documents(plan, page_texts, total_pages, level)
        for level in range(1, max(item.level for item in plan) + 1)
    }
    chosen_level = next(
        (
            level
            for level, documents in trials.items()
            if documents
            and sum(document.word_count <= MAX_WORDS for document in documents)
            / len(documents)
            >= MAX_WORDS_COVERAGE
        ),
        None,
    )
    constraint_satisfied = chosen_level is not None
    statistics_level = chosen_level if chosen_level is not None else max(trials)
    statistics = _statistics(trials[statistics_level], MAX_WORDS)
    roots = build_outline_tree(plan, total_pages)
    output_path = (
        OUTPUT_DIR / f"{safe_filename(pdf_path.stem)}_split_max10000_p90_tree.txt"
    )
    output_path.write_text(
        _render_tree(roots, split_level=chosen_level, statistics=statistics),
        encoding="utf-8",
    )
    result = dict(previous)
    result["split_selection"] = {
        "max_words": MAX_WORDS,
        "max_words_coverage": MAX_WORDS_COVERAGE,
        "chosen_level": chosen_level,
        "constraint_satisfied": constraint_satisfied,
        "statistics_level": statistics_level,
        "statistics": statistics,
        "output": str(output_path.relative_to(ROOT_DIR)),
    }
    return result


def _load_plan_from_tree(path: Path) -> list[BookmarkPlanItem]:
    plan: list[BookmarkPlanItem] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if match := _TREE_ITEM.match(raw_line):
            plan.append(
                BookmarkPlanItem(
                    title=normalize_text(match.group("title")),
                    level=int(match.group("level")),
                    pdf_page=int(match.group("page")),
                    source="bpe_typography",
                )
            )
    if not plan:
        raise RuntimeError(f"bookmark tree를 읽을 수 없다: {path}")
    return plan


def _render_tree(
    roots, split_level: int | None = None, statistics: dict[str, object] | None = None
) -> str:
    lines = ["# BPE hierarchical bookmark tree"]
    if statistics is not None:
        selected_label = f"L{split_level}" if split_level is not None else "none"
        lines.extend(
            [
                f"# split policy: max_words={MAX_WORDS}, coverage={MAX_WORDS_COVERAGE}",
                f"# chosen_level={selected_label}, files={statistics['file_count']}, coverage={statistics['coverage']}, p90_words={statistics['p90_word_count']}, max_words={statistics['max_word_count']}",
            ]
        )
    lines.append("")

    def visit(node) -> None:
        indent = "  " * (node.level - 1)
        marker = (
            " [SPLIT]" if split_level is not None and node.level <= split_level else ""
        )
        lines.append(
            f"{indent}- [L{node.level}, p.{node.start_pdf_page}] {normalize_text(node.title)}{marker}"
        )
        for child in node.children:
            visit(child)

    for root in roots:
        visit(root)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
