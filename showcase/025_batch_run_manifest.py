"""showcase 025: 실제 책 batch 전체의 durable manifest를 검증한다.

Phase 7 3차 증분에서 ``BatchProcessor``가 batch 실행 자체의 immutable
directory와 manifest를 만들고, 그 안에서 item run과 실제 output을 연결하는지
기존 outline이 있는 실제 책 한 권으로 확인한다.

실행:
    uv run python showcase/025_batch_run_manifest.py
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from pdfbooktree import BatchProcessor, resolve_processing_config

try:  # 콘솔에서 한글이 깨지지 않게 한다.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
SOURCE_PDF = ROOT_DIR / "data" / "native-pdf-indexed" / "퀀트의 세계 - 홍창수.pdf"
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "025_batch_run_manifest"
INPUT_DIR = OUTPUT_DIR / "input"
RUN_ROOT = OUTPUT_DIR / "runs"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "025_batch_run_manifest"


def main() -> None:
    if not SOURCE_PDF.is_file():
        raise FileNotFoundError(f"입력 PDF가 없다: {SOURCE_PDF}")

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    input_pdf = INPUT_DIR / SOURCE_PDF.name
    shutil.copy2(SOURCE_PDF, input_pdf)

    resolved = resolve_processing_config(
        set_overrides=["processing.write_artifacts=false"]
    )
    result = BatchProcessor(INPUT_DIR, RUN_ROOT, resolved).run()
    if result.total_pdf_count != 1 or len(result.results) != 1:
        raise RuntimeError(f"단일 PDF batch 결과가 아니다: {result}")
    if result.batch_manifest_path is None or not result.batch_manifest_path.is_file():
        raise RuntimeError(f"batch manifest가 없다: {result}")

    item = result.results[0]
    manifest = json.loads(result.batch_manifest_path.read_text(encoding="utf-8"))
    if manifest["status"] != "succeeded":
        raise RuntimeError(f"batch run이 성공하지 않았다: {manifest}")
    if result.batch_run_id != manifest["batch_run_id"]:
        raise RuntimeError("BatchResult와 manifest의 batch_run_id가 다르다.")
    if result.config_hash != manifest["config_hash"]:
        raise RuntimeError("BatchResult와 manifest의 config_hash가 다르다.")
    if manifest["summary"]["completed_count"] != 1:
        raise RuntimeError(f"완료 item 집계가 잘못됐다: {manifest['summary']}")
    if len(manifest["item_runs"]) != 1:
        raise RuntimeError(f"item run 연결이 잘못됐다: {manifest['item_runs']}")

    item_reference = manifest["item_runs"][0]
    if item_reference["run_id"] != item.run_id:
        raise RuntimeError("batch manifest와 item result의 run_id가 다르다.")
    if item_reference["manifest_path"] != str(item.manifest_path):
        raise RuntimeError("batch manifest가 실제 item manifest를 가리키지 않는다.")
    output_paths = item_reference["output_paths"]
    for path in output_paths.values():
        if not Path(path).exists():
            raise RuntimeError(f"batch manifest의 output이 존재하지 않는다: {path}")

    summary: dict[str, Any] = {
        "source_pdf": str(SOURCE_PDF.relative_to(ROOT_DIR)),
        "batch_input_pdf": str(input_pdf.relative_to(ROOT_DIR)),
        "total_pdf_count": result.total_pdf_count,
        "processed_count": result.processed_count,
        "failed_count": result.failed_count,
        "batch_run_id": result.batch_run_id,
        "batch_run_dir": str(result.batch_run_dir.relative_to(ROOT_DIR)),
        "batch_manifest_path": str(result.batch_manifest_path.relative_to(ROOT_DIR)),
        "batch_manifest_status": manifest["status"],
        "selection_hash": manifest["selection_hash"],
        "config_hash": manifest["config_hash"],
        "summary": manifest["summary"],
        "item_run_id": item_reference["run_id"],
        "item_manifest_path": item_reference["manifest_path"],
        "item_output_paths": output_paths,
    }
    summary["finding"] = (
        "실제 PDF 1권의 batch 실행 자체에 immutable manifest를 생성하고, "
        f"batch_run_id={result.batch_run_id}, status={manifest['status']}, "
        f"completed={manifest['summary']['completed_count']}, "
        f"item run/output 연결={bool(item_reference['manifest_path'] and output_paths)}를 "
        "확인했다."
    )

    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record_showcase(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def record_showcase(summary: dict[str, Any]) -> None:
    """batch run manifest 검증 결과를 showcase registry에 기록한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "BatchProcessor와 BatchResult가 실제 batch 전체의 immutable manifest, "
            "item run, 실제 output 경로를 연결하는지 검증한다."
        ),
        "inputs": [str(SOURCE_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_PATH.relative_to(ROOT_DIR)),
        "finding": summary["finding"],
        "command": "uv run python showcase/025_batch_run_manifest.py",
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


if __name__ == "__main__":
    main()
