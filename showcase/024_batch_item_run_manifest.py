"""showcase 024: 실제 책 batch item의 immutable run manifest를 검증한다.

Phase 7 2차 증분에서 ``BatchProcessor``가 각 PDF를 독립 run directory에서
처리하고, ``BatchItemResult``가 run identity와 실제 manifest를 연결하는지
기존 outline이 있는 실제 책 한 권으로 확인한다.

실행:
    uv run python showcase/024_batch_item_run_manifest.py
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
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "024_batch_item_run_manifest"
INPUT_DIR = OUTPUT_DIR / "input"
RUN_ROOT = OUTPUT_DIR / "runs"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "024_batch_item_run_manifest"


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

    item = result.results[0]
    if item.manifest_path is None or not item.manifest_path.is_file():
        raise RuntimeError(f"item manifest가 없다: {item}")
    manifest = json.loads(item.manifest_path.read_text(encoding="utf-8"))
    if manifest["status"] != "succeeded":
        raise RuntimeError(f"batch item run이 성공하지 않았다: {manifest}")
    if item.run_id != manifest["run_id"]:
        raise RuntimeError("BatchItemResult와 manifest의 run_id가 다르다.")
    if item.config_hash != manifest["config_hash"]:
        raise RuntimeError("BatchItemResult와 manifest의 config_hash가 다르다.")
    if item.run_dir != item.manifest_path.parent:
        raise RuntimeError("manifest가 item run directory 밖에 있다.")

    summary: dict[str, Any] = {
        "source_pdf": str(SOURCE_PDF.relative_to(ROOT_DIR)),
        "batch_input_pdf": str(input_pdf.relative_to(ROOT_DIR)),
        "total_pdf_count": result.total_pdf_count,
        "processed_count": result.processed_count,
        "failed_count": result.failed_count,
        "item_status": item.status,
        "run_id": item.run_id,
        "run_dir": str(item.run_dir.relative_to(ROOT_DIR)) if item.run_dir else None,
        "manifest_path": str(item.manifest_path.relative_to(ROOT_DIR)),
        "config_hash": item.config_hash,
        "manifest_status": manifest["status"],
        "manifest_processing_status": manifest["processing_status"],
        "manifest_output_paths": manifest["output_paths"],
    }
    summary["finding"] = (
        "실제 PDF 1권을 batch 처리해 item별 immutable run directory와 manifest를 "
        f"생성했다. status={item.status}, run_id={item.run_id}, "
        f"config_hash 일치={item.config_hash == manifest['config_hash']}, "
        f"manifest_status={manifest['status']}."
    )

    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record_showcase(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def record_showcase(summary: dict[str, Any]) -> None:
    """batch item run 검증 결과를 showcase registry에 기록한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "BatchProcessor와 BatchItemResult가 실제 책의 item별 immutable run "
            "identity, manifest, output 경로를 연결하는지 검증한다."
        ),
        "inputs": [str(SOURCE_PDF.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_PATH.relative_to(ROOT_DIR)),
        "finding": summary["finding"],
        "command": "uv run python showcase/024_batch_item_run_manifest.py",
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
