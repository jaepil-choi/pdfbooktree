"""Windows와 Linux에서 clean wheel 설치 계약을 검증한다."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    """명령을 실행하고 실패하면 stdout/stderr를 포함해 중단한다."""

    completed = subprocess.run(
        command,
        cwd=cwd,
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
        "--output-root",
        type=Path,
        default=Path("experiments/outputs/cross-platform-wheel-smoke"),
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
    output_root = args.output_root
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    run_dir = output_root / datetime.now().strftime("%Y%m%dT%H%M%S%f")
    dist_dir = run_dir / "dist"
    venv_dir = run_dir / "venv"
    ocr_venv_dir = run_dir / "ocr-venv"
    project_dir = run_dir / "project"
    process_output_dir = run_dir / "process-output"
    dist_dir.mkdir(parents=True, exist_ok=False)
    project_dir.mkdir(parents=True, exist_ok=False)

    build = run(["uv", "build", "--out-dir", str(dist_dir)])
    wheels = sorted(dist_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"wheel이 정확히 하나가 아니다: {wheels!r}")
    wheel = wheels[0]
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(sdists) != 1:
        raise RuntimeError(f"sdist가 정확히 하나가 아니다: {sdists!r}")
    sdist = sdists[0]

    run(["uv", "venv", "--python", "3.12", str(venv_dir)])
    python_exe, cli_exe = clean_environment_paths(venv_dir)
    run(["uv", "pip", "install", "--python", str(python_exe), str(wheel)])

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
    if metadata_payload["version"] != "0.1.0":
        raise RuntimeError("설치 wheel metadata version이 0.1.0이 아니다.")
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

    version = run([str(cli_exe), "--version"]).stdout.strip()
    if version != "pdfbooktree 0.1.0":
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
    if skill_file_count != 5:
        raise RuntimeError(f"package skill 파일 수가 5가 아니다: {skill_file_count}")

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

    missing_ocr_output = run_dir / "must-not-exist-ocr.pdf"
    missing_ocr_artifacts = run_dir / "must-not-exist-ocr_artifacts"
    missing_ocr = subprocess.run(
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
        ],
        cwd=ROOT,
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

    run(["uv", "venv", "--python", "3.12", str(ocr_venv_dir)])
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

    result = {
        "status": "passed",
        "platform": sys.platform,
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
        "installed_skill_file_count": skill_file_count,
        "sample": sample_result,
        "build_log_tail": build.stderr.splitlines()[-10:],
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
