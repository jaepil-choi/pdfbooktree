"""showcase 030: 실제 PDF 처리 전에 unsupported OCR policy를 거부한다.

실제 native PDF를 process CLI에 전달하되 processing.ocr_policy=always를 함께
지정한다. config schema, config validate, direct Python config와 process CLI가
모두 never-only 계약을 노출하고 PDF 분석·output 생성 전에 실패하는지 검증한다.

실행
    uv run python showcase/030_ocr_policy_fail_fast.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.config import ConfigError, ProcessingConfig


try:  # 콘솔에서 한글이 깨지지 않게 한다.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
INPUT_PDF = (
    ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / (
        "John Hull - Options, Futures, and Other Derivatives, "
        "Global Edition-Pearson (2021).pdf"
    )
)
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "030_ocr_policy_fail_fast"
PROCESS_OUTPUT_DIR = OUTPUT_DIR / "process-output"
CONFIG_PATH = OUTPUT_DIR / "unsupported-auto.toml"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "030_ocr_policy_fail_fast"


def write_json(path: Path, value: Any) -> None:
    """UTF-8 JSON을 기록한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def error_envelope(result: Any, command: str) -> dict[str, Any]:
    """exit 2 JSON 오류 envelope를 검증하고 반환한다."""

    if result.exit_code != 2 or result.stdout != "":
        raise RuntimeError(
            f"{command}가 exit 2/stderr-only 계약을 지키지 않았다: "
            f"exit={result.exit_code}, stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
    envelope = json.loads(result.stderr)
    if (
        envelope.get("command") != command
        or envelope.get("ok") is not False
        or envelope.get("error", {}).get("type") != "ConfigError"
        or envelope.get("error", {}).get("code") != "invalid_config"
    ):
        raise RuntimeError(f"{command} 오류 envelope가 잘못됐다: {envelope}")
    return envelope


def update_showcase_json(result: dict[str, Any]) -> None:
    """showcase 실행 결과를 registry에 upsert한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "실제 PDF를 process CLI에 전달했을 때 unsupported ocr_policy가 "
            "분석·output·외부 OCR 호출 전에 ConfigError/exit 2로 종료되는지 검증한다."
        ),
        "inputs": [
            str(INPUT_PDF.relative_to(ROOT_DIR)),
            str(CONFIG_PATH.relative_to(ROOT_DIR)),
        ],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "finding": result["finding"],
        "command": "uv run python showcase/030_ocr_policy_fail_fast.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    showcases = data["showcases"]
    for index, existing in enumerate(showcases):
        if existing.get("id") == SHOWCASE_ID:
            showcases[index] = entry
            break
    else:
        showcases.append(entry)
    write_json(SHOWCASE_JSON, data)


def main() -> None:
    if not INPUT_PDF.is_file():
        raise FileNotFoundError(f"실제 showcase PDF가 없다: {INPUT_PDF}")
    if PROCESS_OUTPUT_DIR.exists():
        raise RuntimeError(
            "fail-fast 검증 전에 process output 경로가 이미 존재한다: "
            f"{PROCESS_OUTPUT_DIR}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        'schema_version = 1\n[processing]\nocr_policy = "auto"\n',
        encoding="utf-8",
    )
    with fitz.open(INPUT_PDF) as document:
        page_count = document.page_count

    runner = CliRunner()
    schema_result = runner.invoke(
        app,
        ["config", "schema", "--format", "json"],
    )
    if schema_result.exit_code != 0:
        raise RuntimeError(f"config schema가 실패했다: {schema_result.stderr}")
    schema_envelope = json.loads(schema_result.stdout)
    schema_enum = schema_envelope["result"]["properties"]["processing"]["properties"][
        "ocr_policy"
    ]["enum"]

    validate_result = runner.invoke(
        app,
        ["config", "validate", str(CONFIG_PATH), "--format", "json"],
    )
    validate_error = error_envelope(validate_result, "config.validate")

    process_result = runner.invoke(
        app,
        [
            "process",
            str(INPUT_PDF),
            "-o",
            str(PROCESS_OUTPUT_DIR),
            "--set",
            "processing.ocr_policy=always",
            "--format",
            "json",
        ],
    )
    process_error = error_envelope(process_result, "process")

    direct_error = None
    try:
        ProcessingConfig(ocr_policy="auto")  # type: ignore[arg-type]
    except ConfigError as error:
        direct_error = str(error)
    if direct_error is None:
        raise RuntimeError("ProcessingConfig가 ocr_policy=auto를 허용했다.")

    validation = {
        "schema_exposes_only_never": schema_enum == ["never"],
        "config_validate_rejects_auto": "현재 never만 지원"
        in validate_error["error"]["message"],
        "process_rejects_always": "ocr-overlay" in process_error["error"]["message"],
        "python_config_rejects_auto": "현재 never만 지원" in direct_error,
        "process_output_not_created": not PROCESS_OUTPUT_DIR.exists(),
    }
    if not all(validation.values()):
        raise RuntimeError(f"OCR policy showcase validation이 실패했다: {validation}")

    finding = (
        f"actual_pdf_pages={page_count}, schema={schema_enum}, "
        "config_auto_exit=2, process_always_exit=2, output_created=False"
    )
    result = {
        "input_pdf": str(INPUT_PDF.relative_to(ROOT_DIR)),
        "page_count": page_count,
        "schema_enum": schema_enum,
        "config_validate_error": validate_error,
        "process_error": process_error,
        "python_config_error": direct_error,
        "validation": validation,
        "validation_passed": True,
        "finding": finding,
    }
    write_json(OUTPUT_PATH, result)
    update_showcase_json(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
