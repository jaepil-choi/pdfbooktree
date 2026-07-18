"""실제 PDF에서 고수준 Python workflow 전체를 검증한다.

실행:
    uv run python showcase/033_python_workflow_api.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree import apply_plan_file, infer_pdf, preview_apply_plan


ROOT = Path(__file__).resolve().parents[1]
INPUT_PDF = (
    ROOT
    / "data"
    / "300STUDY"
    / "b_nonbooks"
    / "b_lecture"
    / "MIT OCW 18.06 Linear Algebra"
    / "18-06sc-fall-2011"
    / "18-06sc-fall-2011"
    / "contents"
    / "resource-index"
    / "problem-solving-eigenvalues-and-eigenvectors"
    / "mVeuZzJdd1w.pdf"
)
OUTPUT_DIR = ROOT / "showcase" / "outputs" / "033_python_workflow_api"
RUN_ROOT = OUTPUT_DIR / "runs"
RESULT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT / "showcase" / "showcase.json"
SHOWCASE_ID = "033_python_workflow_api"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    if not INPUT_PDF.is_file():
        raise FileNotFoundError(f"실제 PDF가 없다: {INPUT_PDF}")

    inferred = infer_pdf(INPUT_PDF, RUN_ROOT / "infer")
    plan_path = inferred.result.bookmark_plan_path
    if plan_path is None:
        raise RuntimeError("infer 결과에 canonical bookmark plan이 없다.")

    preview_root = OUTPUT_DIR / "preview-must-not-exist"
    preview = preview_apply_plan(INPUT_PDF, plan_path, preview_root)
    applied = apply_plan_file(INPUT_PDF, plan_path, RUN_ROOT / "apply")
    applied_plan_path = applied.result.bookmark_plan_path
    if applied_plan_path is None:
        raise RuntimeError("apply 결과에 canonical bookmark plan이 없다.")

    validation = {
        "infer_succeeded": inferred.manifest.status == "succeeded",
        "infer_plan_is_run_owned": plan_path == inferred.run_dir / "bookmark_plan.json",
        "preview_valid": preview.validation.valid,
        "preview_created_no_files": not preview_root.exists(),
        "apply_succeeded": applied.manifest.status == "succeeded",
        "apply_plan_is_run_owned": applied_plan_path
        == applied.run_dir / "bookmark_plan.json",
        "plan_snapshot_matches": plan_path.read_bytes()
        == applied_plan_path.read_bytes(),
        "plan_source_hash_matches": applied.manifest.plan_source
        == {"path": str(plan_path), "sha256": preview.plan_sha256},
        "output_pdf_exists": applied.result.output_pdf is not None
        and applied.result.output_pdf.is_file(),
        "markdown_manifest_exists": applied.result.markdown_manifest_path is not None
        and applied.result.markdown_manifest_path.is_file(),
    }
    if not all(validation.values()):
        raise RuntimeError(f"showcase 033 validation 실패: {validation!r}")

    finding = (
        f"실제 {preview.total_pages}-page MIT OCW PDF에서 "
        f"infer→preview→apply Python workflow가 bookmark "
        f"{preview.bookmark_count}개를 같은 canonical plan snapshot으로 처리했다."
    )
    result = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT)),
        "infer_run_id": inferred.run_id,
        "infer_run_dir": str(inferred.run_dir),
        "apply_run_id": applied.run_id,
        "apply_run_dir": str(applied.run_dir),
        "bookmark_count": preview.bookmark_count,
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
            "실제 PDF에서 infer_pdf → preview_apply_plan → apply_plan_file 고수준 "
            "Python workflow와 canonical plan snapshot을 검증한다."
        ),
        "inputs": [result["input_pdf"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT)),
        "finding": result["finding"],
        "command": "uv run python showcase/033_python_workflow_api.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    showcases = data["showcases"]
    for index, existing in enumerate(showcases):
        if existing["id"] == SHOWCASE_ID:
            showcases[index] = entry
            break
    else:
        showcases.append(entry)
    _write_json(SHOWCASE_JSON, data)


if __name__ == "__main__":
    main()
