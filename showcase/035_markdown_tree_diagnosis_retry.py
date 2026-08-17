"""showcase 035: 실제 책으로 inspect_markdown_tree 진단부터 재시도 후보 적용까지 돈다.

`data/300STUDY_ocr_overlay`의 실제 scansnap OCR 책 한 권을 기본 설정으로
process한 뒤, `inspect_markdown_tree()`가 내는 verdict/finding/retry 후보를
그대로 받아 두 번째 run에 적용하고, `inspect_compare_markdown()`으로 전후
Markdown tree를 비교한다. CLI `pdfbooktree inspect markdown --format json`도
같은 manifest에 live로 호출해 Python API와 결과가 일치하는지 확인한다.

실행:
    uv run python showcase/035_markdown_tree_diagnosis_retry.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree import (
    inspect_compare_markdown,
    inspect_markdown_tree,
    process_pdf,
    resolve_processing_config,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
SHOWCASE_ID = "035_markdown_tree_diagnosis_retry"
INPUT_PDF = (
    ROOT_DIR
    / "data"
    / "300STUDY_ocr_overlay"
    / "pdfs"
    / "scansnap_compressed"
    / "books"
    / "당뇨병_완치_설명서_-_차봉수.compressed[health book].pdf"
)
OUTPUT_ROOT = ROOT_DIR / "showcase" / "outputs" / SHOWCASE_ID
BASELINE_DIR = OUTPUT_ROOT / "baseline"
RETRY_DIR = OUTPUT_ROOT / "retry"
RESULT_PATH = OUTPUT_ROOT / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"


def main() -> None:
    if not INPUT_PDF.exists():
        raise FileNotFoundError(f"실제 입력 PDF가 없다: {INPUT_PDF}")

    baseline_manifest = run_process(BASELINE_DIR, overrides=[])
    baseline = inspect_markdown_tree(baseline_manifest)

    retry_candidate = pick_retry_candidate(baseline)
    retry_manifest = run_process(RETRY_DIR, overrides=retry_candidate["overrides"])
    retry = inspect_markdown_tree(retry_manifest)

    comparison = inspect_compare_markdown(baseline_manifest, retry_manifest)
    cli_baseline = run_cli_inspect(BASELINE_DIR)

    proof = {
        "baseline_verdict_is_thin": baseline["verdict"] == "thin",
        "baseline_cause_is_reused_existing_outline": retry_candidate["cause"]
        == "reused_existing_outline",
        "baseline_sources_only_existing_outline": set(baseline["sources"])
        == {"existing_outline"},
        "retry_overrides_are_actionable": retry_candidate["overrides"]
        == ["processing.skip_existing_bookmarks=false"],
        "retry_command_argv_is_shell_free": retry_candidate["command_argv"] is not None
        and retry_candidate["command_argv"][:2] == ["pdfbooktree", "process"],
        "retry_increased_node_count": retry["graph"]["node_count"]
        > baseline["graph"]["node_count"],
        "retry_dropped_thin_verdict": retry["verdict"] != "thin",
        "retry_stopped_reusing_existing_outline": "existing_outline"
        not in retry["sources"],
        "compare_reports_verdict_change": comparison["delta"]["verdict_changed"]
        is True,
        "compare_added_nodes": comparison["delta"]["added_node_count"] > 0,
        "compare_node_count_delta_matches": comparison["delta"]["node_count"]
        == retry["graph"]["node_count"] - baseline["graph"]["node_count"],
        "cli_matches_python_api": cli_baseline["verdict"] == baseline["verdict"]
        and cli_baseline["graph"]["node_count"] == baseline["graph"]["node_count"]
        and [f["code"] for f in cli_baseline["findings"]]
        == [f["code"] for f in baseline["findings"]],
    }

    result = {
        "status": "proved" if all(proof.values()) else "failed",
        "input_pdf": rel(INPUT_PDF),
        "page_count": baseline["source"]["page_count"],
        "baseline": summarize(baseline, baseline_manifest),
        "retry": summarize(retry, retry_manifest),
        "retry_candidate": retry_candidate,
        "comparison": comparison,
        "cli_command": cli_baseline["_command"],
        "proof": proof,
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_showcase(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "proved":
        raise RuntimeError(f"showcase proof 실패: {proof}")


def run_process(output_root: Path, *, overrides: list[str]) -> Path:
    """실제 PDF를 공개 process_pdf()로 처리하고 markdown manifest 경로를 낸다."""

    if output_root.exists():
        shutil.rmtree(output_root)
    resolved = resolve_processing_config(set_overrides=overrides)
    run = process_pdf(INPUT_PDF, output_root, resolved)
    if run.result.status != "processed":
        raise RuntimeError(
            f"process 실패: status={run.result.status}, errors={run.result.errors}"
        )
    manifest_path = run.result.markdown_manifest_path
    if manifest_path is None:
        raise RuntimeError(f"Markdown manifest가 생성되지 않았다: {output_root}")
    return manifest_path


def pick_retry_candidate(inspection: dict[str, Any]) -> dict[str, Any]:
    """진단이 낸 재시도 후보 중 override가 실제로 있는 첫 후보를 고른다."""

    for candidate in inspection["retry"]:
        if candidate["overrides"]:
            return candidate
    raise RuntimeError(
        "실행 가능한 재시도 후보가 없다: "
        f"verdict={inspection['verdict']}, retry={inspection['retry']}"
    )


def run_cli_inspect(output_dir: Path) -> dict[str, Any]:
    """설치된 CLI로 같은 진단을 live 호출해 Python API 결과와 대조한다."""

    executable = shutil.which("pdfbooktree")
    if executable is None:
        raise RuntimeError(
            "pdfbooktree CLI를 찾지 못했다. `uv run python showcase/...`로 실행하라."
        )
    argv = [executable, "inspect", "markdown", str(output_dir), "--format", "json"]
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"CLI 실패: returncode={completed.returncode}, stderr={completed.stderr}"
        )
    payload = json.loads(completed.stdout)
    if not payload.get("ok"):
        raise RuntimeError(f"CLI envelope가 성공이 아니다: {payload}")
    data = payload["result"]
    data["_command"] = " ".join(["pdfbooktree", *argv[1:]])
    return data


def summarize(inspection: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    return {
        "manifest_path": rel(manifest_path),
        "verdict": inspection["verdict"],
        "node_count": inspection["graph"]["node_count"],
        "chosen_level": inspection["graph"]["chosen_level"],
        "export_mode": inspection["graph"]["export_mode"],
        "sources": {str(key): value for key, value in inspection["sources"].items()},
        "pages_per_node_mean": inspection["pages_per_node"]["mean"],
        "unassigned_ratio": inspection["coverage"]["unassigned_ratio"],
        "fragment_ratio": inspection["titles"]["fragment_ratio"],
        "findings": [
            {
                "code": finding["code"],
                "severity": finding["severity"],
                "cause": finding["cause"],
            }
            for finding in inspection["findings"]
        ],
    }


def record_showcase(result: dict[str, Any]) -> None:
    catalog = read_json(SHOWCASE_JSON)
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "실제 scansnap OCR 책 한 권으로 inspect_markdown_tree()의 verdict와 "
            "retry 후보를 받고, 그 override를 그대로 두 번째 process run에 적용해 "
            "inspect_compare_markdown()으로 전후 Markdown tree 개선을 확인하며, "
            "CLI `inspect markdown --format json`이 Python API와 같은 진단을 "
            "내는지 대조한다."
        ),
        "inputs": [result["input_pdf"]],
        "outputs": rel(RESULT_PATH),
        "finding": (
            f"baseline verdict={result['baseline']['verdict']}, "
            f"node_count={result['baseline']['node_count']}, "
            f"cause={result['retry_candidate']['cause']} -> "
            f"retry verdict={result['retry']['verdict']}, "
            f"node_count={result['retry']['node_count']}, "
            f"delta={result['comparison']['delta']['node_count']}, "
            f"proof={result['proof']}"
        ),
        "command": "uv run python showcase/035_markdown_tree_diagnosis_retry.py",
        "ran_at": result["ran_at"],
    }
    catalog["showcases"] = [
        item for item in catalog.get("showcases", []) if item.get("id") != SHOWCASE_ID
    ]
    catalog["showcases"].append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(ROOT_DIR))


if __name__ == "__main__":
    main()
