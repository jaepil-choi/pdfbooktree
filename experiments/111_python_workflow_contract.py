"""고수준 Python workflow와 canonical plan snapshot 계약을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from pdfbooktree import apply_plan_file, infer_pdf, preview_apply_plan


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "experiments" / "outputs" / "111_python_workflow_contract"
BOOK_PATH = OUTPUT_DIR / "book.pdf"
RUNS_DIR = OUTPUT_DIR / "runs"
RESULT_PATH = OUTPUT_DIR / "result.json"


OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
document = fitz.open()
try:
    for page_number in range(1, 4):
        page = document.new_page()
        page.insert_text((72, 72), f"Page {page_number} body")
    document.set_toc(
        [
            [1, "Chapter 1", 1],
            [2, "Section 1.1", 2],
            [1, "Chapter 2", 3],
            [2, "Section 2.1", 3],
        ]
    )
    document.save(BOOK_PATH)
finally:
    document.close()

inferred = infer_pdf(BOOK_PATH, RUNS_DIR / "infer")
plan_path = inferred.result.bookmark_plan_path
if plan_path is None:
    raise AssertionError("infer 결과에 canonical bookmark plan이 없다.")

preview_root = OUTPUT_DIR / "preview-must-not-exist"
preview = preview_apply_plan(BOOK_PATH, plan_path, preview_root)
applied = apply_plan_file(BOOK_PATH, plan_path, RUNS_DIR / "apply")

applied_plan_path = applied.result.bookmark_plan_path
if applied_plan_path is None:
    raise AssertionError("apply 결과에 canonical bookmark plan이 없다.")

validation = {
    "infer_manifest_succeeded": inferred.manifest.status == "succeeded",
    "infer_plan_is_run_owned": plan_path == inferred.run_dir / "bookmark_plan.json",
    "preview_valid": preview.validation.valid,
    "preview_created_no_files": not preview_root.exists(),
    "apply_manifest_succeeded": applied.manifest.status == "succeeded",
    "apply_plan_is_run_owned": applied_plan_path
    == applied.run_dir / "bookmark_plan.json",
    "plan_snapshot_matches": plan_path.read_bytes() == applied_plan_path.read_bytes(),
    "plan_source_hash_matches": applied.manifest.plan_source
    == {"path": str(plan_path), "sha256": preview.plan_sha256},
}
result = {
    "infer_run_id": inferred.run_id,
    "infer_run_dir": str(inferred.run_dir),
    "apply_run_id": applied.run_id,
    "apply_run_dir": str(applied.run_dir),
    "bookmark_count": preview.bookmark_count,
    "validation": validation,
    "validation_passed": all(validation.values()),
}
RESULT_PATH.write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(result, ensure_ascii=False))

if not result["validation_passed"]:
    raise SystemExit(1)
