"""Markdown tree inspection, compare, heading sweep과 CLI command를 검증한다."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import fitz
from typer.testing import CliRunner

from pdfbooktree.cli import app
import pdfbooktree.inspection as inspection_module
from pdfbooktree.inspection import (
    inspect_compare_markdown,
    inspect_heading_sweep,
    inspect_markdown_tree,
)


def json_result(result: Any, command: str) -> dict[str, object]:
    """schema v1 success envelope에서 inspection result를 꺼낸다."""

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    envelope = json.loads(result.stdout)
    assert envelope["schema_version"] == 1
    assert envelope["command"] == command
    assert envelope["ok"] is True
    return envelope["result"]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def make_node(
    node_id: str,
    level: int,
    start: int,
    end: int,
    title: str,
    *,
    source: str = "geometry_typography",
    words: int | None = None,
) -> dict[str, Any]:
    """tree_graph 계약대로 word_count가 없으면 기본값은 None이다.

    실제 tree_graph export(export_mode="tree_graph", 기본값)는
    node.word_count를 절대 채우지 않는다. words를 명시적으로 넘기는 호출부는
    split export(export_mode="split")를 시뮬레이션하는 것이다.
    """

    return {
        "node_id": node_id,
        "order": int(node_id[1:]),
        "title": title,
        "level": level,
        "pdf_start_page": start,
        "pdf_end_page": end,
        "content_start_page": start,
        "content_end_page": end,
        "relative_path": f"nodes/{node_id}.md",
        "parent_id": None,
        "children_ids": [],
        "previous_id": None,
        "next_id": None,
        "source": source,
        "confidence": 1.0,
        "contained_plan_node_ids": [node_id],
        "word_count": words,
        "evidence_ref": "x",
    }


def make_manifest(
    nodes: list[dict[str, Any]],
    *,
    page_count: int,
    pdf_path: str = "book.pdf",
    export_mode: str = "tree_graph",
    content_mode: str = "direct",
    coverage: dict[str, Any] | None = None,
    valid: bool = True,
    max_words: int | None = None,
    chosen_level: int | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "input": {"pdf_path": pdf_path, "sha256": "x", "page_count": page_count},
        "export_mode": export_mode,
        "content_mode": content_mode,
        "node_count": len(nodes),
        "root_count": len(nodes),
        "nodes": nodes,
        "coverage": coverage
        or {
            "assigned_page_count": page_count,
            "unassigned_page_count": 0,
            "duplicated_page_count": 0,
            "empty_text_page_count": 0,
        },
        "warnings": {},
        "validation": {"valid": valid},
    }
    if max_words is not None:
        manifest["max_words"] = max_words
    if chosen_level is not None:
        manifest["chosen_level"] = chosen_level
    return manifest


def write_manifest(directory: Path, manifest: dict[str, Any]) -> Path:
    path = directory / "markdown_manifest.json"
    write_json(path, manifest)
    return path


def full_pages_nodes(
    count: int, page_count: int, **kwargs: Any
) -> list[dict[str, Any]]:
    """page_count를 count개 node로 균등 분할해 uncovered/duplicate가 없게 한다."""

    span = page_count // count
    nodes = []
    for i in range(1, count + 1):
        start = (i - 1) * span + 1
        end = page_count if i == count else i * span
        nodes.append(
            make_node(
                f"n{i:04d}",
                1,
                start,
                end,
                f"Chapter {i} full length title text",
                **kwargs,
            )
        )
    return nodes


def test_inspect_markdown_tree_reused_thin_reports_cause_and_retry(
    tmp_path: Path,
) -> None:
    nodes = [
        make_node("n0001", 1, 1, 150, "Chapter 1", source="existing_outline"),
        make_node("n0002", 1, 151, 300, "Chapter 2", source="existing_outline"),
    ]
    output_dir = tmp_path / "reused_thin"
    output_dir.mkdir()
    write_manifest(output_dir, make_manifest(nodes, page_count=300))

    result = inspect_markdown_tree(output_dir)

    assert result["verdict"] == "thin"
    thin_finding = next(f for f in result["findings"] if f["code"] == "thin")
    assert thin_finding["cause"] == "reused_existing_outline"
    assert thin_finding["severity"] == "advisory"
    retry_causes = {candidate["cause"] for candidate in result["retry"]}
    assert "reused_existing_outline" in retry_causes
    reused_retry = next(
        c for c in result["retry"] if c["cause"] == "reused_existing_outline"
    )
    assert reused_retry["overrides"] == ["processing.skip_existing_bookmarks=false"]
    assert reused_retry["command"] == (
        "pdfbooktree process book.pdf --set processing.skip_existing_bookmarks=false"
    )
    assert "37" in reused_retry["reason"]


def test_inspect_markdown_tree_inferred_thin_reports_sparse_heading_cause(
    tmp_path: Path,
) -> None:
    nodes = [
        make_node("n0001", 1, 1, 150, "Chapter One Overview"),
        make_node("n0002", 1, 151, 300, "Chapter Two Overview"),
    ]
    output_dir = tmp_path / "inferred_thin"
    output_dir.mkdir()
    write_manifest(output_dir, make_manifest(nodes, page_count=300))

    result = inspect_markdown_tree(output_dir)

    assert result["verdict"] == "thin"
    thin_finding = next(f for f in result["findings"] if f["code"] == "thin")
    assert thin_finding["cause"] == "sparse_heading_candidates"
    retry_causes = {candidate["cause"] for candidate in result["retry"]}
    assert retry_causes == {"sparse_heading_candidates"}
    retry = result["retry"][0]
    assert retry["overrides"] == ["typography.heading_candidate_mode=position"]
    assert "over_split" in retry["reason"]


def test_sparse_heading_follow_up은_split_export에서만_max_words를_제안한다(
    tmp_path: Path,
) -> None:
    """thin 재시도의 후속 안내가 export mode에 따라 달라지는지 확인한다.

    `markdown.max_words`는 `markdown.enabled=false`인 tree_graph 경로에서
    아무 영향을 주지 못하므로, 그 모드에서는 후속 후보로 지목하면 안 된다.
    split export에서만 제안돼야 한다.
    """

    nodes = [
        make_node("n0001", 1, 1, 150, "Chapter One Overview"),
        make_node("n0002", 1, 151, 300, "Chapter Two Overview"),
    ]

    tree_dir = tmp_path / "sparse_tree_graph"
    tree_dir.mkdir()
    write_manifest(
        tree_dir,
        make_manifest(nodes, page_count=300, export_mode="tree_graph"),
    )
    tree_retry = inspect_markdown_tree(tree_dir)["retry"][0]
    assert tree_retry["cause"] == "sparse_heading_candidates"
    assert "markdown.max_words" not in tree_retry["reason"]

    split_dir = tmp_path / "sparse_split"
    split_dir.mkdir()
    write_manifest(
        split_dir,
        make_manifest(nodes, page_count=300, export_mode="split"),
    )
    split_retry = inspect_markdown_tree(split_dir)["retry"][0]
    assert split_retry["cause"] == "sparse_heading_candidates"
    assert "markdown.max_words" in split_retry["reason"]


def test_inspect_markdown_tree_tree_graph_word_count_absent_skips_word_signal(
    tmp_path: Path,
) -> None:
    """tree_graph export의 word_count 부재가 over_split 오탐을 만들지 않는다.

    node 100개가 page 100개(mean=1.0)를 나눈, page 기반으로도 경계값인
    manifest다. words_per_node에 signal이 없으면 word 조건은 평가하지 않고
    page 조건만으로 판정해야 한다. mean=1.0은 threshold(<1.0) 미만이 아니므로
    over_split이 발화하지 않아야 한다.
    """

    nodes = full_pages_nodes(100, 100)
    output_dir = tmp_path / "tree_graph_no_words"
    output_dir.mkdir()
    write_manifest(
        output_dir, make_manifest(nodes, page_count=100, export_mode="tree_graph")
    )

    result = inspect_markdown_tree(output_dir)

    assert result["words_per_node"]["has_data"] is False
    assert result["pages_per_node"]["mean"] == 1.0
    assert "over_split" not in {f["code"] for f in result["findings"]}
    assert result["verdict"] == "ok"


def test_inspect_markdown_tree_tree_graph_true_over_split_via_pages_only(
    tmp_path: Path,
) -> None:
    """word signal이 없어도 page 기반 조건만으로 진짜 over_split을 잡는다."""

    page_count = 50
    nodes = [
        make_node(f"n{i:04d}", 1, i, i, f"Node {i} full length title text")
        for i in range(1, page_count + 1)
    ]
    # 50 node가 50 page를 1:1로 나눠 mean=1.0을 만들고, 마지막 node를 하나 더
    # 추가해 node_count(51) > page_count(50)가 되어 mean이 1.0 미만이 되게 한다.
    nodes.append(
        make_node("n0051", 1, page_count, page_count, "Extra split fragment title")
    )
    output_dir = tmp_path / "tree_graph_over_split"
    output_dir.mkdir()
    write_manifest(
        output_dir,
        make_manifest(
            nodes,
            page_count=page_count,
            export_mode="tree_graph",
            coverage={
                "assigned_page_count": page_count,
                "unassigned_page_count": 0,
                "duplicated_page_count": 0,
                "empty_text_page_count": 0,
            },
        ),
    )

    result = inspect_markdown_tree(output_dir)

    assert result["words_per_node"]["has_data"] is False
    assert result["pages_per_node"]["mean"] < 1.0
    assert result["verdict"] == "over_split"
    finding = next(f for f in result["findings"] if f["code"] == "over_split")
    assert finding["cause"] == "heading_candidates_too_permissive"
    assert "signal이 없다" in finding["detail"]


def test_inspect_markdown_tree_over_split_tree_graph_retry_names_export_mode(
    tmp_path: Path,
) -> None:
    """tree_graph 경로에서는 markdown.max_words override가 효과가 없음을 밝힌다."""

    page_count = 50
    nodes = [
        make_node(f"n{i:04d}", 1, i, i, f"Node {i} full length title text")
        for i in range(1, page_count + 1)
    ]
    nodes.append(
        make_node("n0051", 1, page_count, page_count, "Extra split fragment title")
    )
    output_dir = tmp_path / "tree_graph_over_split_retry"
    output_dir.mkdir()
    write_manifest(
        output_dir,
        make_manifest(nodes, page_count=page_count, export_mode="tree_graph"),
    )

    result = inspect_markdown_tree(output_dir)

    retry = next(
        c for c in result["retry"] if c["cause"] == "heading_candidates_too_permissive"
    )
    assert retry["command"] is None
    assert retry["overrides"] == []
    assert "tree_graph" in retry["reason"]
    assert "markdown.enabled=false" in retry["reason"]


def test_inspect_markdown_tree_over_split_split_export_scales_recorded_max_words(
    tmp_path: Path,
) -> None:
    """split export의 word 기반 over_split retry는 manifest에 기록된 실제
    max_words의 2배를 제시하고, max_words가 없으면 현재 값이라고 말하지
    않는다."""

    nodes = full_pages_nodes(10, 300, words=10)  # median words=10 < threshold(50)
    output_dir = tmp_path / "split_over_split_with_max_words"
    output_dir.mkdir()
    write_manifest(
        output_dir,
        make_manifest(nodes, page_count=300, export_mode="split", max_words=8000),
    )

    result = inspect_markdown_tree(output_dir)

    assert result["verdict"] == "over_split"
    retry = next(
        c for c in result["retry"] if c["cause"] == "heading_candidates_too_permissive"
    )
    assert retry["overrides"] == ["markdown.max_words=16000"]
    assert "8000" in retry["reason"]

    no_max_words_dir = tmp_path / "split_over_split_without_max_words"
    no_max_words_dir.mkdir()
    write_manifest(
        no_max_words_dir,
        make_manifest(nodes, page_count=300, export_mode="split"),
    )
    no_max_words_result = inspect_markdown_tree(no_max_words_dir)
    no_max_words_retry = next(
        c
        for c in no_max_words_result["retry"]
        if c["cause"] == "heading_candidates_too_permissive"
    )
    assert "현재 값의 2배라고 말할 수 없" in no_max_words_retry["reason"]


def test_inspect_markdown_tree_no_max_heading_tier_retry_candidate(
    tmp_path: Path,
) -> None:
    """over_split retry는 typography.max_heading_tier 감소 후보를 내지 않는다."""

    nodes = full_pages_nodes(10, 300, words=10)
    output_dir = tmp_path / "no_max_heading_tier"
    output_dir.mkdir()
    write_manifest(
        output_dir,
        make_manifest(nodes, page_count=300, export_mode="split", max_words=8000),
    )

    result = inspect_markdown_tree(output_dir)

    overrides = {
        override for candidate in result["retry"] for override in candidate["overrides"]
    }
    assert not any("max_heading_tier" in override for override in overrides)


def test_inspect_markdown_tree_thin_and_over_split_conflict_keeps_thin_only(
    tmp_path: Path,
) -> None:
    """thin과 over_split이 동시에 성립하는 조건이면 thin만 finding/retry에 남는다."""

    # node_count=2 <= THIN_MAX_NODE_COUNT(2), page_count=300 >= THIN_MIN(20)로
    # thin이 발화한다. 동시에 node 하나의 word median을 낮게 줘도 mean_pages는
    # 150이라 page 조건으로는 over_split이 안 걸리지만, word 조건으로 걸리게
    # split export로 만든다.
    nodes = [
        make_node("n0001", 1, 1, 150, "Chapter 1", words=10),
        make_node("n0002", 1, 151, 300, "Chapter 2", words=10),
    ]
    output_dir = tmp_path / "thin_over_split_conflict"
    output_dir.mkdir()
    write_manifest(
        output_dir, make_manifest(nodes, page_count=300, export_mode="split")
    )

    result = inspect_markdown_tree(output_dir)

    codes = {f["code"] for f in result["findings"]}
    assert "thin" in codes
    assert "over_split" not in codes
    assert result["verdict"] == "thin"
    retry_causes = {c["cause"] for c in result["retry"]}
    assert "heading_candidates_too_permissive" not in retry_causes


def test_inspect_markdown_tree_duplicated_pages_separate_from_uncovered(
    tmp_path: Path,
) -> None:
    """duplicated page는 uncovered와 분리된 code/cause를 받는다."""

    nodes = full_pages_nodes(10, 300)
    coverage = {
        "assigned_page_count": 300,
        "unassigned_page_count": 0,
        "duplicated_page_count": 5,
        "empty_text_page_count": 0,
    }
    output_dir = tmp_path / "duplicated_direct"
    output_dir.mkdir()
    write_manifest(
        output_dir,
        make_manifest(
            nodes,
            page_count=300,
            content_mode="direct",
            coverage=coverage,
        ),
    )

    result = inspect_markdown_tree(output_dir)

    codes = {f["code"] for f in result["findings"]}
    assert "duplicated" in codes
    assert "uncovered" not in codes
    duplicated_finding = next(
        f for f in result["findings"] if f["code"] == "duplicated"
    )
    assert duplicated_finding["cause"] == "pages_owned_by_multiple_nodes"
    assert duplicated_finding["severity"] == "advisory"


def test_inspect_markdown_tree_duplicated_pages_silent_when_inclusive(
    tmp_path: Path,
) -> None:
    """content_mode=inclusive는 duplicated page를 설계상 허용해 발화하지 않는다."""

    nodes = full_pages_nodes(10, 300)
    coverage = {
        "assigned_page_count": 300,
        "unassigned_page_count": 0,
        "duplicated_page_count": 5,
        "empty_text_page_count": 0,
    }
    output_dir = tmp_path / "duplicated_inclusive"
    output_dir.mkdir()
    write_manifest(
        output_dir,
        make_manifest(
            nodes,
            page_count=300,
            content_mode="inclusive",
            coverage=coverage,
        ),
    )

    result = inspect_markdown_tree(output_dir)

    codes = {f["code"] for f in result["findings"]}
    assert "duplicated" not in codes
    assert result["verdict"] == "ok"


def test_inspect_markdown_tree_retry_command_quotes_space_bracket_korean_paths(
    tmp_path: Path,
) -> None:
    """공백, 대괄호, 한글이 섞인 PDF 경로도 shell에서 그대로 실행 가능하게 인용한다."""

    import shlex

    tricky_path = "book (final) [v2] 한글 제목.pdf"
    nodes = [
        make_node("n0001", 1, 1, 150, "Chapter 1", source="existing_outline"),
        make_node("n0002", 1, 151, 300, "Chapter 2", source="existing_outline"),
    ]
    output_dir = tmp_path / "tricky_path"
    output_dir.mkdir()
    write_manifest(
        output_dir, make_manifest(nodes, page_count=300, pdf_path=tricky_path)
    )

    result = inspect_markdown_tree(output_dir)

    retry = next(c for c in result["retry"] if c["cause"] == "reused_existing_outline")
    command = retry["command"]
    assert command is not None
    parsed = shlex.split(command)
    assert parsed == [
        "pdfbooktree",
        "process",
        tricky_path,
        "--set",
        "processing.skip_existing_bookmarks=false",
    ]
    # command_argv는 shell quoting 없이 그대로 subprocess argv로 실행 가능해야
    # 한다(cmd.exe는 command의 POSIX single-quote를 해석하지 못하므로 이 목록이
    # shell-free 실행 경로다).
    assert retry["command_argv"] == [
        "pdfbooktree",
        "process",
        tricky_path,
        "--set",
        "processing.skip_existing_bookmarks=false",
    ]


def test_inspect_markdown_tree_retry_command_argv_none_when_no_override(
    tmp_path: Path,
) -> None:
    """override가 없는 candidate는 command와 command_argv 모두 None이다."""

    nodes = full_pages_nodes(10, 270)
    coverage = {
        "assigned_page_count": 270,
        "unassigned_page_count": 30,
        "duplicated_page_count": 0,
        "empty_text_page_count": 0,
    }
    output_dir = tmp_path / "uncovered_argv"
    output_dir.mkdir()
    write_manifest(output_dir, make_manifest(nodes, page_count=300, coverage=coverage))

    result = inspect_markdown_tree(output_dir)

    retry = next(c for c in result["retry"] if c["cause"] == "pages_outside_any_node")
    assert retry["command"] is None
    assert retry["command_argv"] is None


def test_inspect_markdown_tree_duplicated_cause_names_duplicated_pages_field(
    tmp_path: Path,
) -> None:
    """duplicated cause retry는 unassigned_pages가 아닌 duplicated_pages를 가리켜야 한다."""

    nodes = full_pages_nodes(10, 300)
    coverage = {
        "assigned_page_count": 300,
        "unassigned_page_count": 0,
        "duplicated_page_count": 5,
        "empty_text_page_count": 0,
    }
    output_dir = tmp_path / "duplicated_argv"
    output_dir.mkdir()
    write_manifest(
        output_dir,
        make_manifest(nodes, page_count=300, content_mode="direct", coverage=coverage),
    )

    result = inspect_markdown_tree(output_dir)

    retry = next(
        c for c in result["retry"] if c["cause"] == "pages_owned_by_multiple_nodes"
    )
    assert "coverage.duplicated_pages" in retry["reason"]
    assert "unassigned_pages" not in retry["reason"]


def test_inspect_markdown_tree_manifest_error_reasons_are_distinct(
    tmp_path: Path,
) -> None:
    """손상된 JSON과 non-object manifest는 서로 다른 오류 메시지를 낸다."""

    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    (corrupt_dir / "markdown_manifest.json").write_text(
        "{not valid json", encoding="utf-8"
    )
    try:
        inspect_markdown_tree(corrupt_dir)
    except ValueError as error:
        assert "유효한 JSON이 아니다" in str(error)
    else:
        raise AssertionError("손상된 JSON을 거절해야 한다.")

    non_object_dir = tmp_path / "non_object"
    non_object_dir.mkdir()
    (non_object_dir / "markdown_manifest.json").write_text(
        "[1, 2, 3]", encoding="utf-8"
    )
    try:
        inspect_markdown_tree(non_object_dir)
    except ValueError as error:
        assert "JSON object가 아니다" in str(error)
        assert "list" in str(error)
    else:
        raise AssertionError("non-object manifest를 거절해야 한다.")


def test_inspect_markdown_tree_multiple_manifests_warning_preserved(
    tmp_path: Path,
) -> None:
    """directory 아래 manifest가 여러 개면 그 경고를 결과 warnings에 남긴다.

    root에 직접 markdown_manifest.json이 없어야 rglob 다중 발견 경로를
    실제로 거치므로, 두 manifest 모두 하위 directory에 둔다.
    """

    output_dir = tmp_path / "multi_manifest"
    output_dir.mkdir()
    nodes = full_pages_nodes(10, 300)
    nested_a = output_dir / "a"
    nested_a.mkdir()
    write_manifest(nested_a, make_manifest(nodes, page_count=300))
    nested_b = output_dir / "b"
    nested_b.mkdir()
    write_manifest(nested_b, make_manifest(nodes, page_count=300))

    result = inspect_markdown_tree(output_dir)

    assert any("여러 개" in warning for warning in result["warnings"])


def test_inspect_markdown_tree_fragment_ratio_boundary(tmp_path: Path) -> None:
    nodes = full_pages_nodes(10, 300)
    # 3/10 = 0.30, threshold is >=0.30 → should trip fragmented
    for i in range(3):
        nodes[i]["title"] = "a"
    output_dir = tmp_path / "fragmented"
    output_dir.mkdir()
    write_manifest(output_dir, make_manifest(nodes, page_count=300))

    result = inspect_markdown_tree(output_dir)

    assert result["titles"]["fragment_ratio"] == 0.3
    assert result["verdict"] == "fragmented"
    finding = next(f for f in result["findings"] if f["code"] == "fragmented")
    assert finding["cause"] == "non_heading_text_selected"
    retry = next(
        c for c in result["retry"] if c["cause"] == "non_heading_text_selected"
    )
    assert retry["overrides"] == ["typography.heading_candidate_mode=position_and_font"]
    assert "2/5" in retry["reason"] or "2권" in retry["reason"]

    # 바로 아래 (2/10 = 0.20)는 fragmented가 아니어야 한다
    nodes_below = full_pages_nodes(10, 300)
    for i in range(2):
        nodes_below[i]["title"] = "a"
    below_dir = tmp_path / "not_fragmented"
    below_dir.mkdir()
    write_manifest(below_dir, make_manifest(nodes_below, page_count=300))
    below_result = inspect_markdown_tree(below_dir)
    assert below_result["titles"]["fragment_ratio"] == 0.2
    assert "fragmented" not in {f["code"] for f in below_result["findings"]}


def test_inspect_markdown_tree_fragmented_detail_reports_level_distribution(
    tmp_path: Path,
) -> None:
    """fragmented detail은 level별 fragment 비율을 관측 사실로 담는다.

    fragment가 하위 level에만 몰려 있는지 최상위 level에도 있는지를 보여줘야
    split level 조정으로 해결되는 문제인지 판단할 수 있다.
    """

    nodes = [
        make_node("n0001", 1, 1, 100, "Chapter 1 full length title text"),
        make_node("n0002", 1, 101, 200, "Chapter 2 full length title text"),
        make_node("n0003", 2, 201, 250, "a"),
        make_node("n0004", 2, 251, 300, "b"),
    ]
    output_dir = tmp_path / "fragmented_levels"
    output_dir.mkdir()
    write_manifest(output_dir, make_manifest(nodes, page_count=300))

    result = inspect_markdown_tree(output_dir)

    finding = next(f for f in result["findings"] if f["code"] == "fragmented")
    detail = finding["detail"]
    assert "level1=0.0" in detail
    assert "level2=1.0" in detail
    assert "fragment_count=2/4" in detail
    assert "threshold=" in detail


def test_inspect_markdown_tree_unassigned_ratio_boundary(tmp_path: Path) -> None:
    nodes = full_pages_nodes(10, 270)
    coverage = {
        "assigned_page_count": 270,
        "unassigned_page_count": 30,
        "duplicated_page_count": 0,
        "empty_text_page_count": 0,
    }
    output_dir = tmp_path / "uncovered"
    output_dir.mkdir()
    write_manifest(output_dir, make_manifest(nodes, page_count=300, coverage=coverage))

    result = inspect_markdown_tree(output_dir)

    assert result["coverage"]["unassigned_ratio"] == 0.1
    assert result["verdict"] == "uncovered"
    finding = next(f for f in result["findings"] if f["code"] == "uncovered")
    assert finding["severity"] == "blocking"
    assert finding["cause"] == "pages_outside_any_node"
    retry = next(c for c in result["retry"] if c["cause"] == "pages_outside_any_node")
    assert retry["command"] is None
    assert retry["overrides"] == []

    # 바로 아래(0.09)는 uncovered가 아니어야 한다
    coverage_below = {
        "assigned_page_count": 273,
        "unassigned_page_count": 27,
        "duplicated_page_count": 0,
        "empty_text_page_count": 0,
    }
    below_dir = tmp_path / "not_uncovered"
    below_dir.mkdir()
    write_manifest(
        below_dir, make_manifest(nodes, page_count=300, coverage=coverage_below)
    )
    below_result = inspect_markdown_tree(below_dir)
    assert below_result["coverage"]["unassigned_ratio"] == 0.09
    assert "uncovered" not in {f["code"] for f in below_result["findings"]}


def test_inspect_markdown_tree_healthy_document_is_ok(tmp_path: Path) -> None:
    nodes = full_pages_nodes(10, 300)
    output_dir = tmp_path / "healthy"
    output_dir.mkdir()
    write_manifest(output_dir, make_manifest(nodes, page_count=300))

    result = inspect_markdown_tree(output_dir)

    assert result["verdict"] == "ok"
    assert result["findings"] == []
    assert result["retry"] == []
    assert result["source"] == {"pdf_path": "book.pdf", "page_count": 300}
    assert result["graph"]["node_count"] == 10
    assert result["pages_per_node"]["mean"] == 30.0


def test_inspect_markdown_tree_invalid_graph_is_blocking(tmp_path: Path) -> None:
    nodes = full_pages_nodes(10, 300)
    output_dir = tmp_path / "invalid"
    output_dir.mkdir()
    write_manifest(output_dir, make_manifest(nodes, page_count=300, valid=False))

    result = inspect_markdown_tree(output_dir)

    assert result["verdict"] == "invalid_graph"
    finding = result["findings"][0]
    assert finding["code"] == "invalid_graph"
    assert finding["severity"] == "blocking"
    retry = next(c for c in result["retry"] if c["cause"] == "graph_contract_violation")
    assert retry["command"] is None
    assert retry["command_argv"] is None


def test_inspect_markdown_tree_invalid_graph_detail_is_structured(
    tmp_path: Path,
) -> None:
    """invalid_graph detail은 dict repr이 아니라 구조화된 count와 offender 목록이다."""

    nodes = full_pages_nodes(10, 300)
    output_dir = tmp_path / "invalid_structured"
    output_dir.mkdir()
    manifest = make_manifest(nodes, page_count=300, valid=True)
    manifest["validation"] = {
        "valid": False,
        "yaml_file_count": 11,
        "yaml_parse_error_count": 1,
        "yaml_errors": [{"path": "nodes/n0001.md", "reason": "bad front matter"}],
        "duplicate_node_id_count": 0,
        "duplicate_output_path_count": 0,
        "dangling_link_count": 2,
        "dangling_links": [
            {"path": "nodes/n0002.md", "target": "missing-a"},
            {"path": "nodes/n0003.md", "target": "missing-b"},
        ],
        "parent_child_asymmetry_count": 0,
        "previous_next_asymmetry_count": 0,
        "unreachable_node_count": 0,
        "toc_unlinked_node_count": 0,
        "deterministic_mapping": True,
    }
    write_manifest(output_dir, manifest)

    result = inspect_markdown_tree(output_dir)

    finding = next(f for f in result["findings"] if f["code"] == "invalid_graph")
    detail = finding["detail"]
    assert "yaml_parse_error_count=1" in detail
    assert "dangling_link_count=2" in detail
    assert "missing-a" in detail
    assert "missing-b" in detail
    # 전체 validation dict repr(예: 'deterministic_mapping': True)은 더 이상
    # 그대로 담기지 않는다.
    assert "deterministic_mapping" not in detail


def test_inspect_markdown_tree_accepts_manifest_path_directly(tmp_path: Path) -> None:
    nodes = full_pages_nodes(10, 300)
    output_dir = tmp_path / "direct"
    output_dir.mkdir()
    manifest_path = write_manifest(output_dir, make_manifest(nodes, page_count=300))

    result = inspect_markdown_tree(manifest_path)

    assert result["manifest_path"] == str(manifest_path)
    assert result["verdict"] == "ok"


def test_inspect_markdown_tree_missing_target_raises_with_context(
    tmp_path: Path,
) -> None:
    missing_dir = tmp_path / "missing"

    try:
        inspect_markdown_tree(missing_dir)
    except FileNotFoundError as error:
        assert str(missing_dir) in str(error)
    else:
        raise AssertionError("존재하지 않는 경로를 거절해야 한다.")

    empty_dir = tmp_path / "empty_output"
    empty_dir.mkdir()
    try:
        inspect_markdown_tree(empty_dir)
    except FileNotFoundError as error:
        assert "markdown_manifest.json" in str(error)
    else:
        raise AssertionError("manifest가 없는 directory를 거절해야 한다.")


def test_inspect_compare_markdown_reports_delta_and_added_removed(
    tmp_path: Path,
) -> None:
    before_nodes = full_pages_nodes(10, 300)
    after_nodes = full_pages_nodes(10, 300)
    for i in range(3):
        after_nodes[i]["title"] = "a"

    before_path = write_manifest(
        tmp_path / "before", make_manifest(before_nodes, page_count=300)
    )
    (tmp_path / "before").mkdir(exist_ok=True)
    after_dir = tmp_path / "after"
    after_dir.mkdir()
    after_path = write_manifest(after_dir, make_manifest(after_nodes, page_count=300))

    result = inspect_compare_markdown(before_path, after_path)

    assert result["before"]["verdict"] == "ok"
    assert result["after"]["verdict"] == "fragmented"
    assert result["delta"]["verdict_changed"] is True
    assert result["delta"]["fragment_ratio"] == 0.3
    assert result["delta"]["added_node_count"] == 3
    assert result["delta"]["removed_node_count"] == 3
    assert result["delta"]["node_count"] == 0


def test_inspect_compare_dispatches_between_markdown_and_plan(tmp_path: Path) -> None:
    plan_a = tmp_path / "before.json"
    plan_b = tmp_path / "after.json"
    write_json(plan_a, [{"title": "Chapter 1", "level": 1, "pdf_page": 10}])
    write_json(plan_b, [{"title": "Chapter 1", "level": 2, "pdf_page": 10}])

    plan_result = CliRunner().invoke(
        app,
        ["inspect", "compare", str(plan_a), str(plan_b), "--format", "json"],
    )
    plan_payload = json_result(plan_result, "inspect.compare")
    assert plan_payload["level_changed_count"] == 1

    before_nodes = full_pages_nodes(10, 300)
    after_nodes = full_pages_nodes(10, 300)
    for i in range(3):
        after_nodes[i]["title"] = "a"
    manifest_a = write_manifest(
        tmp_path / "manifest_before", make_manifest(before_nodes, page_count=300)
    )
    (tmp_path / "manifest_before").mkdir(exist_ok=True)
    manifest_after_dir = tmp_path / "manifest_after"
    manifest_after_dir.mkdir()
    manifest_b = write_manifest(
        manifest_after_dir, make_manifest(after_nodes, page_count=300)
    )

    markdown_result = CliRunner().invoke(
        app,
        [
            "inspect",
            "compare",
            str(manifest_a),
            str(manifest_b),
            "--format",
            "json",
        ],
    )
    markdown_payload = json_result(markdown_result, "inspect.compare")
    assert markdown_payload["delta"]["verdict_changed"] is True


def test_inspect_compare_rejects_mixed_manifest_and_plan(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    write_json(plan_path, [{"title": "Chapter 1", "level": 1, "pdf_page": 10}])

    manifest_dir = tmp_path / "manifest_only"
    manifest_dir.mkdir()
    nodes = full_pages_nodes(10, 300)
    manifest_path = write_manifest(manifest_dir, make_manifest(nodes, page_count=300))

    result = CliRunner().invoke(
        app,
        [
            "inspect",
            "compare",
            str(plan_path),
            str(manifest_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    envelope = json.loads(result.stderr)
    assert envelope["error"]["code"] == "invalid_input"


def test_inspect_compare_corrupt_first_file_reports_input_error(
    tmp_path: Path,
) -> None:
    """손상된 첫 번째 파일은 plan 경로로 조용히 넘어가지 않고 input 오류를 낸다."""

    corrupt_path = tmp_path / "corrupt.json"
    corrupt_path.write_text("{not valid json", encoding="utf-8")
    plan_b = tmp_path / "after.json"
    write_json(plan_b, [{"title": "Chapter 1", "level": 1, "pdf_page": 10}])

    result = CliRunner().invoke(
        app,
        [
            "inspect",
            "compare",
            str(corrupt_path),
            str(plan_b),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    envelope = json.loads(result.stderr)
    assert envelope["command"] == "inspect.compare"
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_input"


def test_inspect_compare_corrupt_second_file_reports_input_error(
    tmp_path: Path,
) -> None:
    """두 번째 파일이 손상돼도 첫 파일 판정만으로 plan 경로에 조용히 위임하지 않는다."""

    plan_a = tmp_path / "before.json"
    write_json(plan_a, [{"title": "Chapter 1", "level": 1, "pdf_page": 10}])
    corrupt_path = tmp_path / "corrupt.json"
    corrupt_path.write_text("[1, 2", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "inspect",
            "compare",
            str(plan_a),
            str(corrupt_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
    envelope = json.loads(result.stderr)
    assert envelope["error"]["code"] == "invalid_input"


def test_inspect_compare_markdown_words_per_node_absent_signal_propagates(
    tmp_path: Path,
) -> None:
    """tree_graph manifest 비교는 words median 0이 아니라 signal 부재를 낸다."""

    before_nodes = full_pages_nodes(10, 300)
    after_nodes = full_pages_nodes(10, 300)
    before_path = write_manifest(
        tmp_path / "before_no_words",
        make_manifest(before_nodes, page_count=300, export_mode="tree_graph"),
    )
    (tmp_path / "before_no_words").mkdir(exist_ok=True)
    after_dir = tmp_path / "after_no_words"
    after_dir.mkdir()
    after_path = write_manifest(
        after_dir,
        make_manifest(after_nodes, page_count=300, export_mode="tree_graph"),
    )

    result = inspect_compare_markdown(before_path, after_path)

    assert result["before"]["words_per_node_has_data"] is False
    assert result["before"]["words_per_node_median"] is None
    assert result["after"]["words_per_node_has_data"] is False
    assert result["after"]["words_per_node_median"] is None
    assert result["delta"]["words_per_node_median"] is None


def test_inspect_compare_markdown_words_per_node_present_signal_computes_delta(
    tmp_path: Path,
) -> None:
    """양쪽 다 word_count signal이 있으면 median delta를 계산한다."""

    before_nodes = full_pages_nodes(10, 300, words=10)
    after_nodes = full_pages_nodes(10, 300, words=20)
    before_path = write_manifest(
        tmp_path / "before_words",
        make_manifest(before_nodes, page_count=300, export_mode="split"),
    )
    (tmp_path / "before_words").mkdir(exist_ok=True)
    after_dir = tmp_path / "after_words"
    after_dir.mkdir()
    after_path = write_manifest(
        after_dir,
        make_manifest(after_nodes, page_count=300, export_mode="split"),
    )

    result = inspect_compare_markdown(before_path, after_path)

    assert result["before"]["words_per_node_has_data"] is True
    assert result["before"]["words_per_node_median"] == 10
    assert result["after"]["words_per_node_median"] == 20
    assert result["delta"]["words_per_node_median"] == 10.0


def test_inspect_cli_markdown_json_and_human_formats(tmp_path: Path) -> None:
    nodes = [
        make_node("n0001", 1, 1, 150, "Chapter 1", source="existing_outline"),
        make_node("n0002", 1, 151, 300, "Chapter 2", source="existing_outline"),
    ]
    output_dir = tmp_path / "cli_reused"
    output_dir.mkdir()
    write_manifest(output_dir, make_manifest(nodes, page_count=300))

    json_invocation = CliRunner().invoke(
        app,
        ["inspect", "markdown", str(output_dir), "--format", "json"],
    )
    payload = json_result(json_invocation, "inspect.markdown")
    assert payload["verdict"] == "thin"
    assert payload["findings"][0]["cause"] == "reused_existing_outline"

    human_invocation = CliRunner().invoke(app, ["inspect", "markdown", str(output_dir)])
    assert human_invocation.exit_code == 0
    assert "verdict: thin" in human_invocation.stdout
    assert "reused_existing_outline" in human_invocation.stdout
    assert "schema_version" not in human_invocation.stdout


def test_inspect_cli_markdown_missing_path_is_json_input_error(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing_output"

    result = CliRunner().invoke(
        app,
        ["inspect", "markdown", str(missing), "--format", "json"],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    envelope = json.loads(result.stderr)
    assert envelope["command"] == "inspect.markdown"
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_input"
    assert envelope["error"]["type"] == "FileNotFoundError"


# ---------------------------------------------------------------------------
# inspect_heading_sweep / `inspect sweep` CLI
# ---------------------------------------------------------------------------


def make_sweepable_book_pdf(path: Path, chapter_count: int = 4) -> None:
    """chapter heading과 본문이 섞인 검사용 PDF를 만든다."""

    document = fitz.open()
    try:
        for chapter in range(1, chapter_count + 1):
            for offset in range(5):
                page = document.new_page(width=595, height=842)
                if offset == 0:
                    page.insert_text(
                        (72, 90), f"Chapter {chapter} Overview", fontsize=24
                    )
                page.insert_text(
                    (72, 150), f"{chapter}.{offset} Section body header", fontsize=14
                )
                for row in range(12):
                    page.insert_text(
                        (72, 250 + row * 20),
                        "This is ordinary body text for testing purposes today.",
                        fontsize=10,
                    )
        document.save(path)
    finally:
        document.close()


def test_inspect_heading_sweep은_typography_분석을_1회만_수행한다(
    tmp_path: Path,
) -> None:
    """설정이 여러 개여도 ``analyze_pdf``는 정확히 한 번만 호출돼야 한다."""

    pdf_path = tmp_path / "sweep_book.pdf"
    make_sweepable_book_pdf(pdf_path)
    call_count = {"n": 0}
    original_analyze_pdf = inspection_module.analyze_pdf

    def counting_analyze_pdf(*args: Any, **kwargs: Any) -> Any:
        call_count["n"] += 1
        return original_analyze_pdf(*args, **kwargs)

    inspection_module.analyze_pdf = counting_analyze_pdf
    try:
        result = inspect_heading_sweep(
            pdf_path,
            size_class_depths=[1, 2],
            max_headings_per_page_values=[1, 3],
            min_word_counts=[1],
        )
    finally:
        inspection_module.analyze_pdf = original_analyze_pdf

    assert call_count["n"] == 1
    assert result["settings_tried"] == 4
    assert len(result["settings"]) == 4


def test_inspect_heading_sweep_각_setting은_candidate_수와_page_비율을_담는다(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "sweep_fields.pdf"
    make_sweepable_book_pdf(pdf_path)

    result = inspect_heading_sweep(
        pdf_path,
        size_class_depths=[1],
        max_headings_per_page_values=[1],
        min_word_counts=[1],
    )

    setting = result["settings"][0]
    assert setting["size_class_depth"] == 1
    assert setting["max_headings_per_page"] == 1
    assert setting["min_words"] == 1
    assert isinstance(setting["candidate_count"], int)
    assert isinstance(setting["pages_with_candidate_count"], int)
    assert setting["pages_per_candidate"] is None or isinstance(
        setting["pages_per_candidate"], float
    )


def test_inspect_heading_sweep_summary는_plausible_setting과_knob_방향을_낸다(
    tmp_path: Path,
) -> None:
    """agent가 책을 다시 읽지 않고 다음 knob 방향을 고를 수 있어야 한다."""

    pdf_path = tmp_path / "sweep_summary.pdf"
    make_sweepable_book_pdf(pdf_path)

    result = inspect_heading_sweep(pdf_path)

    summary = result["summary"]
    assert summary["sensible_pages_per_candidate_range"] == [5.0, 40.0]
    assert isinstance(summary["plausible_setting_count"], int)
    for setting in summary["plausible_settings"]:
        low, high = summary["sensible_pages_per_candidate_range"]
        assert low <= setting["pages_per_candidate"] <= high
    for knob in (
        "size_class_depth_direction",
        "max_headings_per_page_direction",
        "min_words_direction",
    ):
        assert summary[knob] in {
            "increases_candidates",
            "mostly_increases_candidates",
            "decreases_candidates",
            "mostly_decreases_candidates",
            "no_effect",
            "mixed",
            "unknown",
        }


def test_inspect_heading_sweep은_size_class_depth와_max_headings_per_page가_없으면_명확히_실패한다(
    tmp_path: Path,
) -> None:
    """leader가 두 lane을 함께 검증하므로 field 부재를 조용히 넘기지 않는다."""

    pdf_path = tmp_path / "sweep_missing_field.pdf"
    make_sweepable_book_pdf(pdf_path, chapter_count=1)

    original_fields = dataclasses.fields

    def fields_without_size_class_depth(target: Any) -> Any:
        result = original_fields(target)
        if target is inspection_module.TypographyConfig:
            return [field for field in result if field.name != "size_class_depth"]
        return result

    inspection_module.dataclass_fields = fields_without_size_class_depth
    try:
        try:
            inspect_heading_sweep(pdf_path)
        except ValueError as error:
            assert "size_class_depth" in str(error)
        else:
            raise AssertionError("필요한 field가 없으면 실패해야 한다.")
    finally:
        inspection_module.dataclass_fields = original_fields


def test_inspect_heading_sweep은_1_미만_값을_거절한다(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sweep_invalid_value.pdf"
    make_sweepable_book_pdf(pdf_path, chapter_count=1)

    try:
        inspect_heading_sweep(pdf_path, size_class_depths=[0])
    except ValueError as error:
        assert "size_class_depths" in str(error)
    else:
        raise AssertionError("1 미만 값을 거절해야 한다.")


def test_inspect_cli_sweep_json_and_human_formats(tmp_path: Path) -> None:
    pdf_path = tmp_path / "cli_sweep.pdf"
    make_sweepable_book_pdf(pdf_path)

    json_invocation = CliRunner().invoke(
        app,
        [
            "inspect",
            "sweep",
            str(pdf_path),
            "--size-class-depths",
            "1,2",
            "--max-headings-per-page",
            "1,3",
            "--min-words",
            "1",
            "--format",
            "json",
        ],
    )
    payload = json_result(json_invocation, "inspect.sweep")
    assert payload["settings_tried"] == 4

    human_invocation = CliRunner().invoke(
        app,
        [
            "inspect",
            "sweep",
            str(pdf_path),
            "--size-class-depths",
            "1,2",
            "--max-headings-per-page",
            "1,3",
            "--min-words",
            "1",
        ],
    )
    assert human_invocation.exit_code == 0
    assert "settings_tried: 4" in human_invocation.stdout
    assert "knob direction:" in human_invocation.stdout
    assert "schema_version" not in human_invocation.stdout


def test_inspect_cli_sweep_missing_pdf_is_json_input_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"

    result = CliRunner().invoke(
        app,
        ["inspect", "sweep", str(missing), "--format", "json"],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    envelope = json.loads(result.stderr)
    assert envelope["command"] == "inspect.sweep"
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "invalid_input"
    assert envelope["error"]["type"] == "FileNotFoundError"


def test_inspect_cli_sweep_invalid_option_value_is_bad_parameter(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "cli_sweep_invalid.pdf"
    make_sweepable_book_pdf(pdf_path, chapter_count=1)

    result = CliRunner().invoke(
        app,
        [
            "inspect",
            "sweep",
            str(pdf_path),
            "--size-class-depths",
            "0",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 2
