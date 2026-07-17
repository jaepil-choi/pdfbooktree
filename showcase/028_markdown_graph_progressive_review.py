"""showcase 028: 실제 PDF의 tree/split Markdown graph를 점진적으로 검토한다.

같은 Shreve 실제 PDF를 두 경로로 처리한다.

1. ``Processor`` 기본 정책으로 기존 outline을 재사용해 tree graph를 만든다.
2. ``analyze_pdf -> infer_bookmarks -> apply_plan``으로 typography plan을 만들고
   length-limited split graph를 생성한다.

두 결과 모두 ``inspect_plan_artifact``에서 manifest validation과 coverage를 읽고,
모든 Markdown YAML과 source/confidence/evidence reference 보존을 확인한다.

실행
    uv run python showcase/028_markdown_graph_progressive_review.py
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import yaml

from pdfbooktree import (
    MarkdownSplitConfig,
    ProcessingConfig,
    Processor,
    analyze_pdf,
    apply_plan,
    infer_bookmarks,
    inspect_plan_artifact,
    write_inference_artifacts,
)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
INPUT_PDF = (
    ROOT_DIR
    / "data"
    / "scanned-pdf-indexed"
    / (
        "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I "
        "The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf"
    )
)
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "028_markdown_graph_review"
TREE_DIR = OUTPUT_DIR / "existing_outline_tree"
INFERRED_DIR = OUTPUT_DIR / "typography_split"
RESULT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "028_markdown_graph_progressive_review"


def reset_output() -> None:
    """이 showcase의 생성 output만 안전하게 초기화한다."""

    resolved = OUTPUT_DIR.resolve()
    expected_parent = (ROOT_DIR / "showcase" / "outputs").resolve()
    if resolved.parent != expected_parent:
        raise RuntimeError(f"예상하지 않은 showcase output 경로다: {resolved}")
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def parse_front_matter(path: Path) -> dict[str, Any]:
    """Markdown 첫 줄에서 표준 YAML front matter를 읽는다."""

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise RuntimeError(f"front matter가 첫 줄에서 시작하지 않는다: {path}")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise RuntimeError(f"front matter 종료 구분자가 없다: {path}") from error
    loaded = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(loaded, dict):
        raise RuntimeError(f"front matter가 YAML object가 아니다: {path}")
    return loaded


def validate_graph_output(
    manifest_path: Path,
    expected_export_mode: str,
) -> dict[str, Any]:
    """manifest만으로 node를 찾고 생성 Markdown의 YAML을 검증한다."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("export_mode") != expected_export_mode:
        raise RuntimeError(f"예상 export mode와 다르다: {manifest.get('export_mode')}")
    validation = manifest.get("validation")
    if not isinstance(validation, dict) or validation.get("valid") is not True:
        raise RuntimeError(f"Markdown graph validation이 실패했다: {validation}")

    root_dir = manifest_path.parent
    markdown_paths = [root_dir / "toc.md"] + [
        root_dir / node["relative_path"] for node in manifest["nodes"]
    ]
    front_matters = [parse_front_matter(path) for path in markdown_paths]
    node_metadata = front_matters[1:]
    return {
        "manifest_path": str(manifest_path.relative_to(ROOT_DIR)),
        "export_mode": manifest["export_mode"],
        "content_mode": manifest["content_mode"],
        "node_count": manifest["node_count"],
        "root_count": manifest["root_count"],
        "yaml_file_count": len(markdown_paths),
        "validation": validation,
        "coverage": manifest["coverage"],
        "warnings": manifest["warnings"],
        "source_counts": dict(
            Counter(metadata.get("source") for metadata in node_metadata)
        ),
        "evidence_node_count": sum(
            int(metadata.get("evidence_count", 0)) > 0 for metadata in node_metadata
        ),
    }


def process_existing_outline() -> dict[str, Any]:
    """기존 outline을 재사용해 실제 tree graph를 만든다."""

    result = Processor(INPUT_PDF, TREE_DIR, ProcessingConfig()).run()
    if result.status != "processed" or result.markdown_export is None:
        raise RuntimeError(f"기존 outline tree export가 실패했다: {result.status}")
    if result.markdown_export.manifest_path is None:
        raise RuntimeError("tree graph manifest가 없다")
    inspection = inspect_plan_artifact(TREE_DIR)
    if inspection["markdown_manifest"] is None:
        raise RuntimeError("inspect plan이 tree graph manifest를 찾지 못했다")
    graph = validate_graph_output(
        result.markdown_export.manifest_path,
        "tree_graph",
    )
    if graph["source_counts"] != {"existing_outline": result.bookmark_count}:
        raise RuntimeError(f"기존 outline source가 보존되지 않았다: {graph}")
    return {
        "bookmark_count": result.bookmark_count,
        "report_path": str(result.report_path.relative_to(ROOT_DIR)),
        "inspection": inspection["markdown_manifest"],
        "graph": graph,
    }


def process_typography_split() -> dict[str, Any]:
    """실제 typography plan을 infer하고 bounded split graph에 적용한다."""

    config = ProcessingConfig()
    analysis = analyze_pdf(INPUT_PDF, config.typography)
    inference = infer_bookmarks(analysis, config.typography)
    if not inference.validation.valid:
        raise RuntimeError(
            f"실제 typography plan이 구조적으로 유효하지 않다: "
            f"{inference.validation.warnings}"
        )
    write_inference_artifacts(INFERRED_DIR, inference)
    result = apply_plan(
        INPUT_PDF,
        INFERRED_DIR,
        inference.plan,
        analysis.total_pages,
        MarkdownSplitConfig(max_words=10_000, max_words_coverage=0.95),
    )
    if result.markdown_export is None or result.markdown_export.manifest_path is None:
        raise RuntimeError("typography split graph manifest가 없다")
    inspection = inspect_plan_artifact(INFERRED_DIR)
    if inspection["markdown_manifest"] is None:
        raise RuntimeError("inspect plan이 split graph manifest를 찾지 못했다")
    graph = validate_graph_output(result.markdown_export.manifest_path, "split")
    if graph["evidence_node_count"] == 0:
        raise RuntimeError("실제 typography evidence가 split node에 보존되지 않았다")
    if not any(source != "existing_outline" for source in graph["source_counts"]):
        raise RuntimeError(f"typography source가 보존되지 않았다: {graph}")
    return {
        "bookmark_count": len(inference.plan),
        "chosen_level": result.markdown_export.chosen_level,
        "constraint_satisfied": result.markdown_export.constraint_satisfied,
        "output_pdf": str(result.output_pdf.relative_to(ROOT_DIR)),
        "inspection": inspection["markdown_manifest"],
        "graph": graph,
    }


def record_showcase(summary: dict[str, Any]) -> None:
    """실제 실행 결과와 판단을 showcase registry에 기록한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    tree = summary["existing_outline_tree"]["graph"]
    split = summary["typography_split"]["graph"]
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "실제 Shreve PDF에서 기존 outline tree graph와 typography inference "
            "length-limited split graph를 만들고 inspect plan, YAML, wiki relation, "
            "coverage와 source/confidence/evidence 보존을 검증한다."
        ),
        "inputs": [str(INPUT_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "finding": (
            f"tree nodes={tree['node_count']}, tree valid="
            f"{tree['validation']['valid']}, split nodes={split['node_count']}, "
            f"split valid={split['validation']['valid']}, split evidence nodes="
            f"{split['evidence_node_count']}, dangling="
            f"{split['validation']['dangling_link_count']}"
        ),
        "command": ("uv run python showcase/028_markdown_graph_progressive_review.py"),
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    showcases = data["showcases"]
    for index, existing in enumerate(showcases):
        if existing.get("id") == SHOWCASE_ID:
            showcases[index] = entry
            break
    else:
        showcases.append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    if not INPUT_PDF.is_file():
        raise FileNotFoundError(f"실제 입력 PDF가 없다: {INPUT_PDF}")
    with fitz.open(INPUT_PDF) as document:
        page_count = document.page_count
    reset_output()
    summary = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "page_count": page_count,
        "existing_outline_tree": process_existing_outline(),
        "typography_split": process_typography_split(),
    }
    RESULT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record_showcase(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
