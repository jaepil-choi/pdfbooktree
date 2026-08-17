"""실험 115: Markdown inspection 진단의 경계값과 적대적 입력을 red team으로 흔든다.

목적:
    `inspect_markdown_tree()` / `inspect_compare_markdown()` / `pdfbooktree
    inspect markdown` CLI가 (1) 문턱값 경계에서 문서화된 대로 정확히 갈리는지,
    (2) 손상되거나 악의적으로 조작된 manifest에서 조용히 틀린 진단을 내지 않고
    명확한 오류나 경고를 내는지 확인한다.

판정 기준:
    - `expected`가 있는 probe는 관측값이 기대와 다르면 FAIL.
    - `expected`가 None인 probe는 관측 사실만 기록하는 OBSERVE(적대적 입력의
      현재 동작을 고정한다).

실행:
    uv run python experiments/115_markdown_inspection_boundary_redteam.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree.inspection import (
    FRAGMENTED_RATIO_THRESHOLD,
    OVER_SPLIT_MEAN_PAGES_PER_NODE_THRESHOLD,
    OVER_SPLIT_WORDS_PER_NODE_MEDIAN_THRESHOLD,
    THIN_MAX_NODE_COUNT,
    THIN_MEAN_PAGES_PER_NODE_THRESHOLD,
    THIN_MIN_PAGE_COUNT,
    UNASSIGNED_RATIO_BLOCKING_THRESHOLD,
    inspect_compare_markdown,
    inspect_markdown_tree,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "115_markdown_inspection_boundary_redteam"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
WORK_DIR = OUTPUT_DIR / "work"
RESULT_PATH = OUTPUT_DIR / "results.json"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"


# ---------------------------------------------------------------------------
# manifest fixture helpers
# ---------------------------------------------------------------------------


def node(
    index: int,
    level: int,
    start: int,
    end: int,
    title: str,
    *,
    source: str = "geometry_typography",
    words: Any = None,
) -> dict[str, Any]:
    return {
        "node_id": f"n{index:04d}",
        "order": index,
        "title": title,
        "level": level,
        "pdf_start_page": start,
        "pdf_end_page": end,
        "content_start_page": start,
        "content_end_page": end,
        "relative_path": f"nodes/n{index:04d}.md",
        "parent_id": None,
        "children_ids": [],
        "previous_id": None,
        "next_id": None,
        "source": source,
        "confidence": 1.0,
        "contained_plan_node_ids": [f"n{index:04d}"],
        "word_count": words,
        "evidence_ref": "x",
    }


def even_nodes(count: int, page_count: int, **kwargs: Any) -> list[dict[str, Any]]:
    """page를 count개 node로 균등 분할해 coverage 결함이 없게 만든다."""

    span = page_count // count
    nodes = []
    for i in range(1, count + 1):
        start = (i - 1) * span + 1
        end = page_count if i == count else i * span
        nodes.append(node(i, 1, start, end, f"Chapter {i} full title text", **kwargs))
    return nodes


def manifest(
    nodes: list[Any],
    *,
    page_count: int,
    export_mode: str = "split",
    content_mode: str = "direct",
    coverage: dict[str, Any] | None = None,
    node_count: Any = None,
    valid: bool = True,
    max_words: int | None = 10000,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "input": {"pdf_path": "book.pdf", "sha256": "x", "page_count": page_count},
        "export_mode": export_mode,
        "content_mode": content_mode,
        "node_count": len(nodes) if node_count is None else node_count,
        "root_count": len(nodes),
        "chosen_level": 1,
        "max_words": max_words,
        "nodes": nodes,
        "coverage": coverage
        or {
            "assigned_page_count": page_count,
            "unassigned_page_count": 0,
            "duplicated_page_count": 0,
            "empty_text_page_count": 0,
        },
        "validation": {"valid": valid},
    }


def write_manifest(name: str, payload: Any) -> Path:
    path = WORK_DIR / name / "markdown_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# probe runner
# ---------------------------------------------------------------------------

PROBES: list[dict[str, Any]] = []


def probe(
    probe_id: str,
    group: str,
    question: str,
    observe: Any,
    expected: Any = None,
) -> None:
    """probe 하나를 실행하고 기대와 비교한다. 예외도 관측값으로 기록한다."""

    try:
        observed = observe()
    except Exception as error:  # noqa: BLE001 - red team은 예외 자체가 관측 대상이다
        observed = {
            "raised": type(error).__name__,
            "message": str(error)[:400],
        }
    if expected is None:
        verdict = "observe"
    else:
        verdict = "pass" if observed == expected else "fail"
    entry = {
        "id": probe_id,
        "group": group,
        "question": question,
        "observed": observed,
        "expected": expected,
        "verdict": verdict,
    }
    PROBES.append(entry)
    marker = {"pass": "PASS", "fail": "FAIL", "observe": "OBS "}[verdict]
    print(f"[{marker}] {probe_id}: {question}")
    if verdict != "pass":
        print(f"        observed={json.dumps(observed, ensure_ascii=False)[:300]}")


def codes(result: dict[str, Any]) -> list[str]:
    return [finding["code"] for finding in result["findings"]]


def inspect_payload(name: str, payload: Any) -> dict[str, Any]:
    return inspect_markdown_tree(write_manifest(name, payload))


# ---------------------------------------------------------------------------
# group 1: 문턱값 경계
# ---------------------------------------------------------------------------


def run_threshold_probes() -> None:
    group = "threshold_boundary"

    # thin: node_count <= 2 AND page_count >= 20
    probe(
        "thin_node_count_exact",
        group,
        f"node_count={THIN_MAX_NODE_COUNT}, page_count={THIN_MIN_PAGE_COUNT}는 thin이다",
        lambda: "thin"
        in codes(inspect_payload("thin_exact", manifest(even_nodes(2, 20), page_count=20))),
        expected=True,
    )
    probe(
        "thin_node_count_just_above",
        group,
        "node_count=3, page_count=20(mean 6.7)은 thin이 아니다",
        lambda: "thin"
        in codes(inspect_payload("thin_above", manifest(even_nodes(3, 20), page_count=20))),
        expected=False,
    )
    probe(
        "thin_page_count_just_below",
        group,
        f"node_count=2, page_count={THIN_MIN_PAGE_COUNT - 1}은 thin이 아니다",
        lambda: "thin"
        in codes(inspect_payload("thin_pages_below", manifest(even_nodes(2, 19), page_count=19))),
        expected=False,
    )

    # thin: mean pages per node > 50.0 (strict)
    probe(
        "thin_mean_exact_threshold",
        group,
        f"pages_per_node.mean == {THIN_MEAN_PAGES_PER_NODE_THRESHOLD}은 thin이 아니다(strict >)",
        lambda: "thin"
        in codes(inspect_payload("thin_mean_eq", manifest(even_nodes(4, 200), page_count=200))),
        expected=False,
    )
    probe(
        "thin_mean_just_above",
        group,
        "pages_per_node.mean=50.25는 thin이다",
        lambda: "thin"
        in codes(inspect_payload("thin_mean_gt", manifest(even_nodes(4, 201), page_count=201))),
        expected=True,
    )

    # over_split: mean < 1.0 (strict)
    probe(
        "over_split_mean_exact_threshold",
        group,
        f"pages_per_node.mean == {OVER_SPLIT_MEAN_PAGES_PER_NODE_THRESHOLD}은 over_split이 아니다",
        lambda: "over_split"
        in codes(
            inspect_payload(
                "over_split_eq",
                manifest(even_nodes(30, 30, words=1000), page_count=30),
            )
        ),
        expected=False,
    )
    probe(
        "over_split_mean_just_below",
        group,
        "pages_per_node.mean=0.968(node 31 > page 30)은 over_split이다",
        lambda: "over_split"
        in codes(
            inspect_payload(
                "over_split_lt",
                manifest(
                    even_nodes(30, 30, words=1000) + [node(31, 1, 30, 30, "Extra tail node")],
                    page_count=30,
                ),
            )
        ),
        expected=True,
    )

    # over_split: words median < 50 (strict) - page 조건은 만족하지 않게 둔다
    probe(
        "over_split_words_exact_threshold",
        group,
        f"words median == {OVER_SPLIT_WORDS_PER_NODE_MEDIAN_THRESHOLD}은 over_split이 아니다",
        lambda: "over_split"
        in codes(
            inspect_payload(
                "over_split_words_eq",
                manifest(even_nodes(10, 100, words=50), page_count=100),
            )
        ),
        expected=False,
    )
    probe(
        "over_split_words_just_below",
        group,
        "words median=49는 over_split이다",
        lambda: "over_split"
        in codes(
            inspect_payload(
                "over_split_words_lt",
                manifest(even_nodes(10, 100, words=49), page_count=100),
            )
        ),
        expected=True,
    )

    # fragmented: ratio >= 0.30
    def fragmented_nodes(fragment_count: int, total: int) -> list[dict[str, Any]]:
        nodes = even_nodes(total, total * 10)
        for i in range(fragment_count):
            nodes[i]["title"] = "a"
        return nodes

    probe(
        "fragmented_exact_threshold",
        group,
        f"fragment_ratio == {FRAGMENTED_RATIO_THRESHOLD}은 fragmented다(>=)",
        lambda: "fragmented"
        in codes(
            inspect_payload(
                "fragment_eq",
                manifest(fragmented_nodes(3, 10), page_count=100),
            )
        ),
        expected=True,
    )
    probe(
        "fragmented_just_below",
        group,
        "fragment_ratio=0.29는 fragmented가 아니다",
        lambda: "fragmented"
        in codes(
            inspect_payload(
                "fragment_below",
                manifest(fragmented_nodes(29, 100), page_count=1000),
            )
        ),
        expected=False,
    )
    probe(
        "fragmented_rounding_flip",
        group,
        "fragment_ratio=0.29996(29999/100000 아님, 2999/10000)은 반올림 후 0.3으로 fragmented가 되는가",
        lambda: {
            "ratio": inspect_payload(
                "fragment_round",
                manifest(fragmented_nodes(2999, 10000), page_count=100000),
            )["titles"]["fragment_ratio"],
            "fragmented": "fragmented"
            in codes(
                inspect_payload(
                    "fragment_round",
                    manifest(fragmented_nodes(2999, 10000), page_count=100000),
                )
            ),
        },
    )

    # uncovered: unassigned_ratio >= 0.10
    def coverage_manifest(unassigned: int, page_count: int) -> dict[str, Any]:
        return manifest(
            even_nodes(10, page_count),
            page_count=page_count,
            coverage={
                "assigned_page_count": page_count - unassigned,
                "unassigned_page_count": unassigned,
                "duplicated_page_count": 0,
                "empty_text_page_count": 0,
            },
        )

    probe(
        "uncovered_exact_threshold",
        group,
        f"unassigned_ratio == {UNASSIGNED_RATIO_BLOCKING_THRESHOLD}은 uncovered다(>=)",
        lambda: "uncovered" in codes(inspect_payload("uncov_eq", coverage_manifest(10, 100))),
        expected=True,
    )
    probe(
        "uncovered_just_below",
        group,
        "unassigned_ratio=0.09는 uncovered가 아니다",
        lambda: "uncovered" in codes(inspect_payload("uncov_below", coverage_manifest(9, 100))),
        expected=False,
    )

    # thin과 over_split 상호 배타
    probe(
        "thin_and_over_split_exclusive",
        group,
        "thin과 over_split은 동시에 발화하지 않는다(node 2개 + 짧은 word)",
        lambda: codes(
            inspect_payload(
                "thin_vs_over_split",
                manifest(even_nodes(2, 200, words=10), page_count=200),
            )
        ),
        expected=["thin"],
    )


# ---------------------------------------------------------------------------
# group 2: 손상/적대적 manifest
# ---------------------------------------------------------------------------


def run_adversarial_probes() -> None:
    group = "adversarial_manifest"

    probe(
        "declared_node_count_mismatch",
        group,
        "manifest node_count가 실제 nodes 길이와 다르면 어떻게 되는가(선언값 999, 실제 10)",
        lambda: {
            "graph_node_count": (
                result := inspect_payload(
                    "count_mismatch",
                    manifest(even_nodes(10, 1000), page_count=1000, node_count=999),
                )
            )["graph"]["node_count"],
            "pages_per_node_mean": result["pages_per_node"]["mean"],
            "findings": codes(result),
            "warnings": result["warnings"],
        },
    )

    probe(
        "bool_word_count_leak",
        group,
        "word_count=True(bool)는 word signal로 취급되는가",
        lambda: {
            "words": (
                result := inspect_payload(
                    "bool_words",
                    manifest(even_nodes(10, 100, words=True), page_count=100),
                )
            )["words_per_node"],
            "findings": codes(result),
        },
    )

    probe(
        "non_numeric_coverage",
        group,
        "coverage 값이 문자열이면 명확한 입력 오류를 내는가",
        lambda: inspect_payload(
            "bad_coverage",
            manifest(
                even_nodes(10, 100),
                page_count=100,
                coverage={
                    "assigned_page_count": "90",
                    "unassigned_page_count": "10",
                    "duplicated_page_count": 0,
                    "empty_text_page_count": 0,
                },
            ),
        ),
    )

    probe(
        "reversed_page_span",
        group,
        "pdf_end_page < pdf_start_page인 node는 어떤 통계를 만드는가",
        lambda: {
            "pages_per_node": inspect_payload(
                "reversed_span",
                manifest(
                    [
                        node(1, 1, 100, 1, "Reversed span node"),
                        node(2, 1, 101, 200, "Normal node full title"),
                    ],
                    page_count=200,
                ),
            )["pages_per_node"],
        },
    )

    probe(
        "nodes_contains_non_dict",
        group,
        "nodes에 dict가 아닌 항목이 섞이면 crash 없이 무시하는가",
        lambda: {
            "findings": (
                result := inspect_payload(
                    "junk_nodes",
                    manifest(
                        [*even_nodes(3, 30), "junk", 42, None],
                        page_count=30,
                    ),
                )
            )["graph"]["node_count"],
            "titles_total": result["titles"]["total"],
        },
    )

    probe(
        "missing_page_count",
        group,
        "input.page_count가 없으면 입력 오류로 거절한다",
        lambda: inspect_markdown_tree(
            write_manifest(
                "no_page_count",
                {
                    "schema_version": 1,
                    "input": {"pdf_path": "book.pdf", "sha256": "x"},
                    "nodes": [],
                    "node_count": 0,
                },
            )
        ),
        expected={
            "raised": "ValueError",
            "message": (
                "Markdown manifest의 page_count가 유효하지 않다: path="
                + str(WORK_DIR / "no_page_count" / "markdown_manifest.json")
            ),
        },
    )

    probe(
        "negative_page_count",
        group,
        "input.page_count가 음수면 입력 오류로 거절한다",
        lambda: isinstance(
            inspect_payload("negative_pages", manifest(even_nodes(2, 10), page_count=-5)),
            dict,
        ),
        expected={
            "raised": "ValueError",
            "message": (
                "Markdown manifest의 page_count가 유효하지 않다: path="
                + str(WORK_DIR / "negative_pages" / "markdown_manifest.json")
            ),
        },
    )

    probe(
        "empty_nodes_full_book",
        group,
        "node가 0개인 manifest는 어떤 verdict를 내는가",
        lambda: {
            "verdict": (
                result := inspect_payload(
                    "empty_nodes",
                    manifest(
                        [],
                        page_count=300,
                        coverage={
                            "assigned_page_count": 0,
                            "unassigned_page_count": 300,
                            "duplicated_page_count": 0,
                            "empty_text_page_count": 0,
                        },
                    ),
                )
            )["verdict"],
            "findings": codes(result),
            "retry_causes": [c["cause"] for c in result["retry"]],
        },
    )

    probe(
        "limit_zero_rejected",
        group,
        "limit=0은 입력 오류로 거절한다",
        lambda: inspect_markdown_tree(
            write_manifest("limit_zero", manifest(even_nodes(2, 40), page_count=40)),
            limit=0,
        ),
        expected={"raised": "ValueError", "message": "limit은 1 이상이어야 한다."},
    )

    probe(
        "duplicated_suppressed_only_for_inclusive",
        group,
        "content_mode=inclusive가 아닌 오타(inclusive_ 등)에서는 duplicated를 발화한다",
        lambda: [
            "duplicated"
            in codes(
                inspect_payload(
                    f"dup_{mode}",
                    manifest(
                        even_nodes(10, 100),
                        page_count=100,
                        content_mode=mode,
                        coverage={
                            "assigned_page_count": 100,
                            "unassigned_page_count": 0,
                            "duplicated_page_count": 7,
                            "empty_text_page_count": 0,
                        },
                    ),
                )
            )
            for mode in ("direct", "inclusive", "Inclusive", "inclusive_")
        ],
        expected=[True, False, True, True],
    )


# ---------------------------------------------------------------------------
# group 3: compare 경계
# ---------------------------------------------------------------------------


def run_compare_probes() -> None:
    group = "compare_boundary"

    same = write_manifest("cmp_same", manifest(even_nodes(10, 100, words=500), page_count=100))
    probe(
        "compare_identical_is_zero_delta",
        group,
        "같은 manifest를 비교하면 모든 delta가 0이고 verdict_changed=False다",
        lambda: inspect_compare_markdown(same, same)["delta"],
        expected={
            "node_count": 0,
            "chosen_level": 0,
            "words_per_node_median": 0,
            "pages_per_node_mean": 0.0,
            "unassigned_ratio": 0.0,
            "fragment_ratio": 0.0,
            "verdict_changed": False,
            "added_node_count": 0,
            "removed_node_count": 0,
        },
    )

    no_words = write_manifest("cmp_no_words", manifest(even_nodes(10, 100), page_count=100))
    probe(
        "compare_word_signal_asymmetry",
        group,
        "한쪽만 word signal이 있으면 words_per_node_median delta는 None이다",
        lambda: inspect_compare_markdown(same, no_words)["delta"]["words_per_node_median"],
        expected=None,
    )

    probe(
        "compare_rejects_plan_json",
        group,
        "nodes가 없는 JSON(plan)은 compare에서 명확히 거절한다",
        lambda: inspect_compare_markdown(
            same,
            write_manifest("cmp_plan", [{"title": "t", "level": 1, "pdf_page": 1}]),
        ),
        expected={
            "raised": "ValueError",
            "message": (
                "Markdown manifest 형식이 JSON object가 아니다: path="
                + str(WORK_DIR / "cmp_plan" / "markdown_manifest.json")
                + ", actual_type=list"
            ),
        },
    )

    probe(
        "compare_zero_page_count_manifest",
        group,
        "page_count가 0인 manifest를 compare에 넣으면 어떻게 되는가(inspect는 거절하는 입력)",
        lambda: inspect_compare_markdown(
            same,
            write_manifest("cmp_zero_pages", manifest(even_nodes(2, 10), page_count=0)),
        )["after"],
    )


# ---------------------------------------------------------------------------
# group 4: CLI 경계
# ---------------------------------------------------------------------------


def run_cli_probes() -> None:
    group = "cli_boundary"
    executable = shutil.which("pdfbooktree")
    if executable is None:
        raise RuntimeError("pdfbooktree CLI를 찾지 못했다. uv run으로 실행하라.")

    def cli(*args: str) -> dict[str, Any]:
        completed = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        payload: Any = None
        for stream in (completed.stdout, completed.stderr):
            stream = stream.strip()
            if not stream:
                continue
            try:
                payload = json.loads(stream.splitlines()[-1])
            except json.JSONDecodeError:
                continue
            break
        return {
            "exit_code": completed.returncode,
            "error_code": (payload or {}).get("error", {}).get("code")
            if isinstance(payload, dict)
            else None,
        }

    good = WORK_DIR / "cli_good"
    write_manifest("cli_good", manifest(even_nodes(10, 100, words=500), page_count=100))

    probe(
        "cli_missing_path_is_invalid_input",
        group,
        "없는 경로는 invalid_input 오류로 끝난다",
        lambda: cli("inspect", "markdown", str(WORK_DIR / "does_not_exist"), "--format", "json"),
        expected={"exit_code": 2, "error_code": "invalid_input"},
    )

    corrupt = WORK_DIR / "cli_corrupt"
    corrupt.mkdir(parents=True, exist_ok=True)
    (corrupt / "markdown_manifest.json").write_text("{not json", encoding="utf-8")
    probe(
        "cli_corrupt_json_is_invalid_input",
        group,
        "손상된 JSON은 invalid_input 오류로 끝난다",
        lambda: cli("inspect", "markdown", str(corrupt), "--format", "json"),
        expected={"exit_code": 2, "error_code": "invalid_input"},
    )

    probe(
        "cli_limit_zero_rejected",
        group,
        "--limit 0은 CLI 인자 검증에서 거절한다",
        lambda: cli("inspect", "markdown", str(good), "--limit", "0", "--format", "json")[
            "exit_code"
        ],
        expected=2,
    )

    probe(
        "cli_limit_upper_bound",
        group,
        "--limit 1001은 CLI 인자 검증에서 거절한다",
        lambda: cli("inspect", "markdown", str(good), "--limit", "1001", "--format", "json")[
            "exit_code"
        ],
        expected=2,
    )

    probe(
        "cli_compare_mixed_inputs_rejected",
        group,
        "manifest와 plan을 섞어 compare하면 invalid_input으로 거절한다",
        lambda: cli(
            "inspect",
            "compare",
            str(WORK_DIR / "cli_good" / "markdown_manifest.json"),
            str(WORK_DIR / "cmp_plan" / "markdown_manifest.json"),
            "--format",
            "json",
        ),
        expected={"exit_code": 2, "error_code": "invalid_input"},
    )


def main() -> None:
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    run_threshold_probes()
    run_adversarial_probes()
    run_compare_probes()
    run_cli_probes()

    failed = [p for p in PROBES if p["verdict"] == "fail"]
    observed = [p for p in PROBES if p["verdict"] == "observe"]
    summary = {
        "probe_count": len(PROBES),
        "pass_count": sum(1 for p in PROBES if p["verdict"] == "pass"),
        "fail_count": len(failed),
        "observe_count": len(observed),
        "failed_ids": [p["id"] for p in failed],
        "observed_ids": [p["id"] for p in observed],
    }
    result = {
        "experiment_id": EXPERIMENT_ID,
        "summary": summary,
        "probes": PROBES,
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
