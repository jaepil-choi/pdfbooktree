"""showcase 032: 실제 OCR plan을 근거에 따라 수정하고 검증·적용한다.

showcase 029에서 생성한 실제 637-page 수리통계학 review artifact의 n0008을
원문 preview와 candidate geometry로 확인한다. index/연습문제 표가 반복 위치
fallback에 잡힌 false positive이므로 해당 항목 하나만 제거하고 public CLI의
``apply --dry-run``과 실제 ``apply``를 연속 실행한다.

실행:
    uv run --no-sync python showcase/032_agent_edit_validate_apply.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree import (
    inspect_compare_plans,
    inspect_plan_artifact,
    load_bookmark_plan_json,
)
from pdfbooktree.utils.hashing import file_sha256

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
INPUT_PDF = (
    ROOT_DIR
    / "showcase"
    / "outputs"
    / "014_ocr_overlay_math_statistics"
    / "pdfs"
    / "수리통계학(개정판)-김우철_upocr_merged_ocr.pdf"
)
REVIEW_DIR = (
    ROOT_DIR
    / "showcase"
    / "outputs"
    / "029_bookmark_review_progressive_inspection"
    / "ocr_math_statistics"
)
ORIGINAL_PLAN = REVIEW_DIR / "bookmark_plan.json"
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "032_agent_edit_validate_apply"
MODIFIED_PLAN = OUTPUT_DIR / "bookmark_plan.edited.json"
RUN_ROOT = OUTPUT_DIR / "runs"
RESULT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "032_agent_edit_validate_apply"
REMOVED_NODE_ID = "n0008"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run_cli(arguments: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        ["uv", "run", "--no-sync", "pdfbooktree", *arguments],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"CLI 실패: args={arguments!r}, exit={completed.returncode}, "
            f"stdout={completed.stdout[-2000:]!r}, stderr={completed.stderr[-2000:]!r}"
        )
    payload = json.loads(completed.stdout)
    if not payload.get("ok"):
        raise RuntimeError(f"CLI JSON 결과가 실패다: {payload!r}")
    return payload


def main() -> None:
    if not INPUT_PDF.is_file():
        raise FileNotFoundError(f"실제 OCR PDF가 없다: {INPUT_PDF}")
    if not ORIGINAL_PLAN.is_file():
        raise FileNotFoundError(f"showcase 029 plan이 없다: {ORIGINAL_PLAN}")

    detail = inspect_plan_artifact(REVIEW_DIR, item_id=REMOVED_NODE_ID)[
        "bookmark_review_items"
    ][0]
    expected_false_positive = (
        detail["node_id"] == REMOVED_NODE_ID
        and detail["pdf_page"] == 98
        and detail["source"] == "geometry_position_fallback"
        and "position_fallback_source" in detail["attention_signals"]
        and "결합확률밀도함수" in detail["page_text_preview"]
        and "연습문제" in detail["page_text_preview"]
    )
    if not expected_false_positive:
        raise RuntimeError(f"n0008의 실제 review 근거가 예상과 다르다: {detail!r}")

    original = load_bookmark_plan_json(ORIGINAL_PLAN)
    removed_index = int(REMOVED_NODE_ID[1:]) - 1
    removed = original[removed_index]
    modified = original[:removed_index] + original[removed_index + 1 :]
    _write_json(MODIFIED_PLAN, [asdict(item) for item in modified])
    reloaded = load_bookmark_plan_json(MODIFIED_PLAN)
    preserved = all(
        asdict(before) == asdict(after)
        for before, after in zip(
            original[:removed_index] + original[removed_index + 1 :],
            reloaded,
            strict=True,
        )
    )

    comparison = inspect_compare_plans(ORIGINAL_PLAN, MODIFIED_PLAN)
    if not (
        comparison["removed_count"] == 1
        and comparison["added_count"] == 0
        and comparison["plan_b_item_count"] == len(original) - 1
    ):
        raise RuntimeError(f"수정 plan 비교 결과가 예상과 다르다: {comparison!r}")

    before_dry_run = {
        path.relative_to(OUTPUT_DIR).as_posix() for path in OUTPUT_DIR.rglob("*")
    }
    dry_run = _run_cli(
        [
            "apply",
            str(INPUT_PDF),
            "--plan",
            str(MODIFIED_PLAN),
            "--output-dir",
            str(RUN_ROOT),
            "--dry-run",
            "--format",
            "json",
        ]
    )
    after_dry_run = {
        path.relative_to(OUTPUT_DIR).as_posix() for path in OUTPUT_DIR.rglob("*")
    }
    if before_dry_run != after_dry_run:
        raise RuntimeError("apply --dry-run이 filesystem을 변경했다.")

    applied = _run_cli(
        [
            "apply",
            str(INPUT_PDF),
            "--plan",
            str(MODIFIED_PLAN),
            "--output-dir",
            str(RUN_ROOT),
            "--format",
            "json",
        ]
    )
    applied_result = applied["result"]["result"]
    manifest_path = Path(applied["result"]["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    markdown_manifest_path = Path(applied_result["artifact_paths"]["markdown_manifest"])
    markdown_manifest = json.loads(markdown_manifest_path.read_text(encoding="utf-8"))
    validation = {
        "false_positive_evidence_confirmed": expected_false_positive,
        "removed_exactly_one": comparison["removed_count"] == 1,
        "remaining_metadata_preserved": preserved,
        "dry_run_valid": dry_run["result"]["validation"]["valid"],
        "dry_run_filesystem_unchanged": before_dry_run == after_dry_run,
        "apply_processed": applied_result["status"] == "processed",
        "output_pdf_exists": Path(applied_result["output_pdf"]).is_file(),
        "output_markdown_exists": Path(applied_result["output_markdown_dir"]).is_dir(),
        "markdown_graph_valid": markdown_manifest["validation"]["valid"],
        "plan_source_hash_matches": (
            manifest["plan_source"]["sha256"] == file_sha256(MODIFIED_PLAN)
        ),
    }
    if not all(validation.values()):
        raise RuntimeError(f"showcase 032 validation 실패: {validation!r}")

    finding = (
        f"실제 OCR plan {len(original)}개에서 page 98의 {REMOVED_NODE_ID} "
        f"false positive 1개를 제거했다. dry-run valid=True, 실제 apply "
        f"bookmark={applied_result['bookmark_count']}, Markdown graph valid=True."
    )
    result = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "original_plan": str(ORIGINAL_PLAN.relative_to(ROOT_DIR)),
        "modified_plan": str(MODIFIED_PLAN.relative_to(ROOT_DIR)),
        "removed_item": {
            "node_id": REMOVED_NODE_ID,
            "title": removed.title,
            "pdf_page": removed.pdf_page,
            "source": removed.source,
            "attention_signals": detail["attention_signals"],
        },
        "original_count": len(original),
        "modified_count": len(modified),
        "comparison": {
            "added_count": comparison["added_count"],
            "removed_count": comparison["removed_count"],
            "unchanged_count": comparison["unchanged_count"],
        },
        "dry_run": dry_run["result"],
        "apply_run_dir": applied["result"]["run_dir"],
        "apply_manifest": str(manifest_path),
        "markdown_manifest": str(markdown_manifest_path),
        "validation": validation,
        "validation_passed": True,
        "finding": finding,
    }
    _write_json(RESULT_PATH, result)
    _record_showcase(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _record_showcase(result: dict[str, Any]) -> None:
    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "실제 637-page OCR 책의 review evidence로 false positive를 제거한 뒤 "
            "plan 비교, apply dry-run과 실제 PDF/Markdown 적용 전체 흐름을 검증한다."
        ),
        "inputs": [
            result["input_pdf"],
            result["original_plan"],
        ],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "finding": result["finding"],
        "command": "uv run --no-sync python showcase/032_agent_edit_validate_apply.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    showcases = data["showcases"]
    for index, existing in enumerate(showcases):
        if existing.get("id") == SHOWCASE_ID:
            showcases[index] = entry
            break
    else:
        showcases.append(entry)
    _write_json(SHOWCASE_JSON, data)


if __name__ == "__main__":
    main()
