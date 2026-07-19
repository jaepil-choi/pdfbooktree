"""Windows와 Linux에서 clean wheel 설치 계약을 검증한다."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
_CLI_CONSOLE_PATH: str | None = None
_CLI_COMMAND_PREFIX: tuple[str, ...] | None = None


def utf8_environment() -> dict[str, str]:
    """clean subprocess가 OS locale과 무관하게 UTF-8 stream을 사용하게 한다."""

    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    return environment


def run(command: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    """명령을 실행하고 실패하면 stdout/stderr를 포함해 중단한다."""

    command = resolved_cli_command(command)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=utf8_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"명령 실패: command={command!r}, exit_code={completed.returncode}, "
            f"stdout={completed.stdout[-2000:]!r}, stderr={completed.stderr[-2000:]!r}"
        )
    return completed


def resolved_cli_command(command: list[str]) -> list[str]:
    """선택한 방식으로 설치 package의 CLI entrypoint command를 만든다."""

    if (
        _CLI_CONSOLE_PATH is not None
        and _CLI_COMMAND_PREFIX is not None
        and command
        and command[0] == _CLI_CONSOLE_PATH
    ):
        return [*_CLI_COMMAND_PREFIX, *command[1:]]
    return command


def run_json(command: list[str]) -> dict[str, Any]:
    """stdout 단일 JSON command를 실행해 object로 반환한다."""

    completed = run(command)
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON object가 아니다: command={command!r}")
    return value


def clean_environment_paths(venv_dir: Path) -> tuple[Path, Path]:
    """현재 OS에 맞는 clean Python과 CLI 경로를 반환한다."""

    if sys.platform == "win32":
        return (
            venv_dir / "Scripts" / "python.exe",
            venv_dir / "Scripts" / "pdfbooktree.exe",
        )
    return venv_dir / "bin" / "python", venv_dir / "bin" / "pdfbooktree"


def parse_args() -> argparse.Namespace:
    """CLI 인자를 해석한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--python-version",
        choices=("3.12", "3.13", "3.14"),
        default="3.12",
        help="clean install과 OCR extra를 검증할 Python minor version이다.",
    )
    parser.add_argument(
        "--cli-launch-mode",
        choices=("console-script", "python-entrypoint"),
        default="console-script",
        help=(
            "기본값은 설치 console script를 직접 실행한다. "
            "enterprise Application Control이 unsigned venv launcher를 차단하는 "
            "로컬 환경에서만 python-entrypoint를 사용한다."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("experiments/outputs/cross-platform-wheel-smoke"),
    )
    parser.add_argument(
        "--wheel",
        type=Path,
        help="지정하면 새로 build하지 않고 이 wheel을 clean install한다.",
    )
    parser.add_argument(
        "--sdist",
        type=Path,
        help="--wheel과 함께 지정해 이미 build한 source distribution을 검증한다.",
    )
    parser.add_argument(
        "--sample-pdf",
        type=Path,
        help="지정하면 생성 fixture 대신 이 PDF로 installed CLI process를 검증한다.",
    )
    return parser.parse_args()


def main() -> None:
    """wheel build부터 clean CLI와 실제 PDF graph 처리까지 검증한다."""

    args = parse_args()
    if (args.wheel is None) != (args.sdist is None):
        raise ValueError("--wheel과 --sdist는 함께 지정해야 한다.")
    output_root = args.output_root
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    run_dir = output_root / datetime.now().strftime("%Y%m%dT%H%M%S%f")
    dist_dir = run_dir / "dist"
    venv_dir = run_dir / "venv"
    ocr_venv_dir = run_dir / "ocr-venv"
    project_dir = run_dir / "project"
    process_output_dir = run_dir / "process-output"
    inference_output_dir = run_dir / "inference-output"
    project_dir.mkdir(parents=True, exist_ok=False)

    if args.wheel is None:
        dist_dir.mkdir(parents=True, exist_ok=False)
        build = run(["uv", "build", "--out-dir", str(dist_dir)])
        wheels = sorted(dist_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"wheel이 정확히 하나가 아니다: {wheels!r}")
        wheel = wheels[0]
        sdists = sorted(dist_dir.glob("*.tar.gz"))
        if len(sdists) != 1:
            raise RuntimeError(f"sdist가 정확히 하나가 아니다: {sdists!r}")
        sdist = sdists[0]
        build_log_tail = build.stderr.splitlines()[-10:]
        distribution_source = "built"
    else:
        wheel = args.wheel
        sdist = args.sdist
        if not wheel.is_absolute():
            wheel = ROOT / wheel
        if not sdist.is_absolute():
            sdist = ROOT / sdist
        wheel = wheel.resolve(strict=True)
        sdist = sdist.resolve(strict=True)
        build_log_tail = []
        distribution_source = "provided"

    run(["uv", "venv", "--python", args.python_version, str(venv_dir)])
    python_exe, cli_exe = clean_environment_paths(venv_dir)
    run(["uv", "pip", "install", "--python", str(python_exe), str(wheel)])
    if args.cli_launch_mode == "python-entrypoint":
        global _CLI_CONSOLE_PATH, _CLI_COMMAND_PREFIX
        _CLI_CONSOLE_PATH = str(cli_exe)
        _CLI_COMMAND_PREFIX = (
            str(python_exe),
            "-c",
            "from pdfbooktree.cli import main; main()",
        )

    metadata_code = """
import json
from importlib import resources
from importlib.metadata import metadata, requires, version
from importlib.util import find_spec

value = metadata("pdfbooktree")
print(json.dumps({
    "version": version("pdfbooktree"),
    "license_expression": value["License-Expression"],
    "license_files": value.get_all("License-File") or [],
    "project_urls": value.get_all("Project-URL") or [],
    "keywords": value["Keywords"],
    "classifiers": value.get_all("Classifier") or [],
    "requirements": requires("pdfbooktree") or [],
    "py_typed": resources.files("pdfbooktree").joinpath("py.typed").is_file(),
    "ocr_modules_installed": {
        name: find_spec(name) is not None
        for name in ("httpx", "pikepdf", "dotenv")
    },
}))
"""
    metadata_payload = run_json([str(python_exe), "-c", metadata_code])
    if metadata_payload["license_expression"] != "MIT":
        raise RuntimeError("wheel License-Expression이 MIT가 아니다.")
    if "LICENSE" not in metadata_payload["license_files"]:
        raise RuntimeError("wheel metadata가 LICENSE 파일을 연결하지 않는다.")
    package_version = str(metadata_payload["version"])
    if "Typing :: Typed" not in metadata_payload["classifiers"]:
        raise RuntimeError("wheel metadata에 Typing :: Typed classifier가 없다.")
    if not metadata_payload["py_typed"]:
        raise RuntimeError("설치 wheel에 py.typed가 없다.")
    if any(metadata_payload["ocr_modules_installed"].values()):
        raise RuntimeError("core-only 설치에 OCR package가 포함됐다.")
    ocr_requirements = {
        requirement.split(">=", 1)[0]
        for requirement in metadata_payload["requirements"]
        if "extra == 'ocr'" in requirement
    }
    if ocr_requirements != {"httpx", "pikepdf", "python-dotenv"}:
        raise RuntimeError(f"OCR extra metadata가 예상과 다르다: {ocr_requirements!r}")

    serialization_code = """
from pathlib import Path

from pdfbooktree import BookmarkPlanItem, to_json

item = BookmarkPlanItem(title="제1장", level=1, pdf_page=1)
print(to_json({"item": item, "path": Path("book.pdf")}, ensure_ascii=False))
"""
    serialization_payload = run_json([str(python_exe), "-c", serialization_code])
    if serialization_payload != {
        "item": {
            "title": "제1장",
            "level": 1,
            "pdf_page": 1,
            "source": "typography",
            "confidence": 0.0,
            "evidence": [],
        },
        "path": "book.pdf",
    }:
        raise RuntimeError(
            f"설치 wheel의 공개 직렬화 계약이 예상과 다르다: {serialization_payload!r}"
        )

    version = run([str(cli_exe), "--version"]).stdout.strip()
    if version != f"pdfbooktree {package_version}":
        raise RuntimeError(f"예상하지 못한 version 출력이다: {version!r}")
    run([str(cli_exe), "--help"])
    run([str(cli_exe), "ocr-overlay", "--help"])
    run([str(cli_exe), "ocr-overlay-batch", "--help"])
    run([str(cli_exe), "process", "--help"])
    run([str(cli_exe), "infer", "--help"])
    run([str(cli_exe), "apply", "--help"])
    run([str(cli_exe), "batch", "--help"])
    run([str(cli_exe), "classify-scan", "--help"])
    run([str(cli_exe), "inspect", "--help"])

    empty_input_dir = run_dir / "empty-input"
    ocr_dry_run_dir = run_dir / "ocr-dry-run"
    empty_input_dir.mkdir()
    ocr_dry_run_payload = run_json(
        [
            str(cli_exe),
            "ocr-overlay-batch",
            str(empty_input_dir),
            "--output-dir",
            str(ocr_dry_run_dir),
            "--dry-run",
            "--format",
            "json",
        ]
    )
    if not ocr_dry_run_payload.get("ok"):
        raise RuntimeError("core-only OCR batch dry-run이 실패했다.")

    config_payload = run_json([str(cli_exe), "config", "schema", "--format", "json"])
    if not config_payload.get("ok"):
        raise RuntimeError("config schema 결과가 실패다.")

    skill_payload = run_json(
        [
            str(cli_exe),
            "skill",
            "install",
            "--project-dir",
            str(project_dir),
            "--format",
            "json",
        ]
    )
    if not skill_payload.get("ok"):
        raise RuntimeError("package skill 설치 결과가 실패다.")
    skill_root = project_dir / ".agents" / "skills" / "use-pdfbooktree"
    skill_file_count = sum(path.is_file() for path in skill_root.rglob("*"))
    if skill_file_count != 8:
        raise RuntimeError(f"package skill 파일 수가 8이 아니다: {skill_file_count}")
    api_reference_path = skill_root / "references" / "python-api.md"
    api_reference = api_reference_path.read_text(encoding="utf-8")
    required_api_reference_contracts = (
        "pdfbooktree.__all__",
        "to_jsonable(value) -> JsonValue",
        "v0.1.0은 Upstage Document Parse 전용",
    )
    missing_api_reference_contracts = [
        contract
        for contract in required_api_reference_contracts
        if contract not in api_reference
    ]
    if missing_api_reference_contracts:
        raise RuntimeError(
            "설치 skill의 Python API reference 계약이 누락됐다: "
            f"{missing_api_reference_contracts!r}"
        )
    for english_reference_name in (
        "cli.en.md",
        "contracts.en.md",
        "python-api.en.md",
    ):
        english_reference_path = skill_root / "references" / english_reference_name
        if not english_reference_path.is_file():
            raise RuntimeError(
                f"설치 skill 영문 reference가 없다: {english_reference_name}"
            )

    if args.sample_pdf is not None:
        sample_pdf = args.sample_pdf
        if not sample_pdf.is_absolute():
            sample_pdf = ROOT / sample_pdf
        sample_pdf = sample_pdf.resolve(strict=True)
        sample_source = "provided"
    else:
        sample_pdf = run_dir / "generated-contract-book.pdf"
        sample_source = "generated"
        generate_code = """
import fitz
import sys

path = sys.argv[1]
document = fitz.open()
for page_number in range(1, 3):
    page = document.new_page()
    page.insert_text((72, 72), f"Page {page_number} body text")
document.set_toc([
    [1, "Chapter: 1 / Intro", 1],
    [2, "CON", 1],
    [1, "한글 Chapter", 2],
    [2, "Repeated Title", 2],
])
document.save(path)
document.close()
"""
        run([str(python_exe), "-c", generate_code, str(sample_pdf)])

    inference_pdf = run_dir / "generated-typography-book.pdf"
    generate_inference_code = """
import fitz
import sys

path = sys.argv[1]
document = fitz.open()
for page_number in range(1, 10):
    page = document.new_page(width=595.0, height=842.0)
    if page_number in (1, 4, 7):
        chapter = {1: 1, 4: 2, 7: 3}[page_number]
        page.insert_text((72, 90), f"Chapter {chapter} Title", fontsize=28)
        page.insert_text((72, 155), f"{chapter}.1 Section", fontsize=16)
    page.insert_text((72, 200), f"Note {page_number}", fontsize=10)
    for row in range(15):
        page.insert_text(
            (72, 260 + row * 15),
            "This is ordinary body text for the chapter.",
            fontsize=10,
        )
document.save(path)
document.close()
"""
    run([str(python_exe), "-c", generate_inference_code, str(inference_pdf)])

    missing_ocr_output = run_dir / "must-not-exist-ocr.pdf"
    missing_ocr_artifacts = run_dir / "must-not-exist-ocr_artifacts"
    missing_ocr = subprocess.run(
        resolved_cli_command(
            [
                str(cli_exe),
                "ocr-overlay",
                str(sample_pdf),
                "--output",
                str(missing_ocr_output),
                "--output-dir",
                str(missing_ocr_artifacts),
                "--format",
                "json",
            ]
        ),
        cwd=ROOT,
        env=utf8_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if missing_ocr.returncode != 1:
        raise RuntimeError(
            f"core-only live OCR exit code가 1이 아니다: {missing_ocr.returncode}"
        )
    missing_ocr_payload = json.loads(missing_ocr.stderr)
    if missing_ocr_payload["error"]["code"] != "missing_optional_dependency":
        raise RuntimeError(
            f"OCR optional error가 예상과 다르다: {missing_ocr_payload!r}"
        )
    if missing_ocr_output.exists() or missing_ocr_artifacts.exists():
        raise RuntimeError("core-only live OCR 실패가 output을 만들었다.")

    run(["uv", "venv", "--python", args.python_version, str(ocr_venv_dir)])
    ocr_python_exe, _ = clean_environment_paths(ocr_venv_dir)
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(ocr_python_exe),
            f"pdfbooktree[ocr] @ {wheel.as_uri()}",
        ]
    )
    ocr_import_code = """
from importlib.util import find_spec

from pdfbooktree.ocr import OcrOverlayBuilder, OcrOverlayConfig

assert OcrOverlayBuilder is not None
assert OcrOverlayConfig is not None
assert all(find_spec(name) is not None for name in ("httpx", "pikepdf", "dotenv"))
"""
    run([str(ocr_python_exe), "-c", ocr_import_code])

    inspect_payload = run_json(
        [
            str(cli_exe),
            "inspect",
            "page-count",
            str(sample_pdf),
            "--format",
            "json",
        ]
    )
    process_payload = run_json(
        [
            str(cli_exe),
            "process",
            str(sample_pdf),
            "-o",
            str(process_output_dir),
            "--log-mode",
            "none",
            "--format",
            "json",
        ]
    )
    process_result = process_payload["result"]["result"]
    if process_result["status"] != "processed":
        raise RuntimeError("설치 wheel의 실제 PDF process 결과가 processed가 아니다.")
    manifest_path = Path(process_result["artifact_paths"]["markdown_manifest"])
    validation_code = """
import json
import sys
from pathlib import Path

import yaml

manifest_path = Path(sys.argv[1])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
validation = manifest["validation"]
required_zero = [
    "yaml_parse_error_count",
    "duplicate_node_id_count",
    "duplicate_output_path_count",
    "dangling_link_count",
    "parent_child_asymmetry_count",
    "previous_next_asymmetry_count",
    "unreachable_node_count",
    "toc_unlinked_node_count",
]
if not validation["valid"] or any(validation[key] != 0 for key in required_zero):
    raise RuntimeError(f"Markdown graph validation 실패: {validation!r}")
relative_paths = [node["relative_path"] for node in manifest["nodes"]]
if len({path.casefold() for path in relative_paths}) != len(relative_paths):
    raise RuntimeError("node 파일명이 대소문자 기준으로 충돌한다.")
yaml_paths = [manifest_path.parent / "toc.md"] + [
    manifest_path.parent / relative for relative in relative_paths
]
for path in yaml_paths:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\\n"):
        raise RuntimeError(f"YAML front matter로 시작하지 않는다: {path}")
    _, front_matter, _ = text.split("---", 2)
    if not isinstance(yaml.safe_load(front_matter), dict):
        raise RuntimeError(f"YAML object가 아니다: {path}")
print(json.dumps({
    "node_count": manifest["node_count"],
    "yaml_file_count": len(yaml_paths),
    "validation": validation,
}))
"""
    graph_validation = run_json(
        [str(python_exe), "-c", validation_code, str(manifest_path)]
    )
    inspect_plan_payload = run_json(
        [
            str(cli_exe),
            "inspect",
            "plan",
            process_payload["result"]["run_dir"],
            "--summary",
            "--format",
            "json",
        ]
    )
    if not inspect_plan_payload.get("ok"):
        raise RuntimeError("installed CLI inspect plan 결과가 실패다.")
    sample_result = {
        "source": sample_source,
        "path": str(sample_pdf),
        "page_count": inspect_payload["result"]["page_count"],
        "process_run_dir": process_payload["result"]["run_dir"],
        "process_status": process_result["status"],
        "bookmark_count": process_result["bookmark_count"],
        "markdown_manifest": str(manifest_path),
        "graph_node_count": graph_validation["node_count"],
        "yaml_file_count": graph_validation["yaml_file_count"],
        "graph_validation": graph_validation["validation"],
    }

    infer_payload = run_json(
        [
            str(cli_exe),
            "infer",
            str(inference_pdf),
            "--output-dir",
            str(inference_output_dir / "infer"),
            "--set",
            "typography.min_tier_count=1",
            "--set",
            "typography.max_heading_tier=2",
            "--set",
            "typography.position_min_repeated_pages=5",
            "--log-mode",
            "none",
            "--format",
            "json",
        ]
    )
    infer_run = infer_payload["result"]
    infer_result = infer_run["result"]
    plan_path = Path(infer_result["artifact_paths"]["bookmark_plan"])
    if infer_result["bookmark_count"] <= 0 or not plan_path.is_file():
        raise RuntimeError(
            "설치 wheel의 typography infer가 non-empty plan을 만들지 않았다."
        )
    infer_inspection = run_json(
        [
            str(cli_exe),
            "inspect",
            "plan",
            infer_run["run_dir"],
            "--summary",
            "--format",
            "json",
        ]
    )
    if not infer_inspection.get("ok"):
        raise RuntimeError("설치 wheel의 typography infer plan 조사가 실패했다.")

    dry_run_root = inference_output_dir / "dry-run-must-not-exist"
    dry_run_payload = run_json(
        [
            str(cli_exe),
            "apply",
            str(inference_pdf),
            "--plan",
            str(plan_path),
            "--output-dir",
            str(dry_run_root),
            "--dry-run",
            "--format",
            "json",
        ]
    )
    if not dry_run_payload["result"]["validation"]["valid"] or dry_run_root.exists():
        raise RuntimeError("설치 wheel의 apply dry-run 무쓰기 계약이 실패했다.")

    apply_payload = run_json(
        [
            str(cli_exe),
            "apply",
            str(inference_pdf),
            "--plan",
            str(plan_path),
            "--output-dir",
            str(inference_output_dir / "apply"),
            "--format",
            "json",
        ]
    )
    apply_run = apply_payload["result"]
    apply_result = apply_run["result"]
    inference_manifest_path = Path(apply_result["artifact_paths"]["markdown_manifest"])
    inference_graph_validation = run_json(
        [
            str(python_exe),
            "-c",
            validation_code,
            str(inference_manifest_path),
        ]
    )
    apply_manifest = json.loads(
        Path(apply_run["manifest_path"]).read_text(encoding="utf-8")
    )
    if apply_manifest["plan_source"]["path"] != str(plan_path):
        raise RuntimeError("설치 wheel의 apply manifest가 infer plan source를 잃었다.")
    inference_result = {
        "path": str(inference_pdf),
        "infer_run_dir": infer_run["run_dir"],
        "apply_run_dir": apply_run["run_dir"],
        "bookmark_count": infer_result["bookmark_count"],
        "plan": str(plan_path),
        "dry_run_valid": dry_run_payload["result"]["validation"]["valid"],
        "dry_run_created_no_files": not dry_run_root.exists(),
        "output_pdf": apply_result["output_pdf"],
        "markdown_manifest": str(inference_manifest_path),
        "graph_validation": inference_graph_validation["validation"],
    }
    if not Path(apply_result["output_pdf"]).is_file():
        raise RuntimeError("설치 wheel의 typography apply PDF가 생성되지 않았다.")

    result = {
        "status": "passed",
        "platform": sys.platform,
        "python_version": args.python_version,
        "cli_launch_mode": args.cli_launch_mode,
        "distribution_source": distribution_source,
        "wheel": str(wheel),
        "sdist": str(sdist),
        "version": version,
        "license_expression": metadata_payload["license_expression"],
        "license_files": metadata_payload["license_files"],
        "project_url_count": len(metadata_payload["project_urls"]),
        "classifier_count": len(metadata_payload["classifiers"]),
        "py_typed": metadata_payload["py_typed"],
        "ocr_extra_requirements": sorted(ocr_requirements),
        "core_ocr_batch_dry_run": ocr_dry_run_payload["ok"],
        "core_live_ocr_error_code": missing_ocr_payload["error"]["code"],
        "ocr_extra_imports": "passed",
        "serialization_contract": "passed",
        "installed_skill_file_count": skill_file_count,
        "installed_skill_api_reference": str(
            api_reference_path.relative_to(project_dir)
        ),
        "sample": sample_result,
        "inference_sample": inference_result,
        "build_log_tail": build_log_tail,
        "run_dir": str(run_dir),
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    result_path = run_dir / "result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
