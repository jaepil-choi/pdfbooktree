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
        help="지정하면 설치 wheel로 실제 PDF inspect/process까지 실행한다.",
    )
    return parser.parse_args()


def main() -> None:
    """wheel build부터 clean CLI와 선택적 실제 PDF 처리까지 검증한다."""

    args = parse_args()
    output_root = args.output_root
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    run_dir = output_root / datetime.now().strftime("%Y%m%dT%H%M%S%f")
    dist_dir = run_dir / "dist"
    venv_dir = run_dir / "venv"
    project_dir = run_dir / "project"
    process_output_dir = run_dir / "process-output"
    dist_dir.mkdir(parents=True, exist_ok=False)
    project_dir.mkdir(parents=True, exist_ok=False)

    build = run(["uv", "build", "--out-dir", str(dist_dir)])
    wheels = sorted(dist_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"wheel이 정확히 하나가 아니다: {wheels!r}")
    wheel = wheels[0]

    run(["uv", "venv", "--python", "3.12", str(venv_dir)])
    python_exe, cli_exe = clean_environment_paths(venv_dir)
    run(["uv", "pip", "install", "--python", str(python_exe), str(wheel)])

    metadata_code = """
import json
from importlib.metadata import metadata

value = metadata("pdfbooktree")
print(json.dumps({
    "license_expression": value["License-Expression"],
    "license_files": value.get_all("License-File") or [],
    "project_urls": value.get_all("Project-URL") or [],
    "keywords": value["Keywords"],
    "classifiers": value.get_all("Classifier") or [],
}))
"""
    metadata_payload = run_json([str(python_exe), "-c", metadata_code])
    if metadata_payload["license_expression"] != "MIT":
        raise RuntimeError("wheel License-Expression이 MIT가 아니다.")
    if "LICENSE" not in metadata_payload["license_files"]:
        raise RuntimeError("wheel metadata가 LICENSE 파일을 연결하지 않는다.")

    version = run([str(cli_exe), "--version"]).stdout.strip()
    if version != "pdfbooktree 0.1.0":
        raise RuntimeError(f"예상하지 못한 version 출력이다: {version!r}")
    run([str(cli_exe), "--help"])

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

    sample_result: dict[str, Any] | None = None
    if args.sample_pdf is not None:
        sample_pdf = args.sample_pdf
        if not sample_pdf.is_absolute():
            sample_pdf = ROOT / sample_pdf
        sample_pdf = sample_pdf.resolve(strict=True)
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
                "--format",
                "json",
            ]
        )
        process_result = process_payload["result"]["result"]
        if process_result["status"] != "processed":
            raise RuntimeError(
                "설치 wheel의 실제 PDF process 결과가 processed가 아니다."
            )
        sample_result = {
            "path": str(sample_pdf),
            "page_count": inspect_payload["result"]["page_count"],
            "process_run_dir": process_payload["result"]["run_dir"],
            "process_status": process_result["status"],
            "bookmark_count": process_result["bookmark_count"],
            "markdown_manifest": process_result["artifact_paths"]["markdown_manifest"],
        }

    result = {
        "status": "passed",
        "platform": sys.platform,
        "wheel": str(wheel),
        "version": version,
        "license_expression": metadata_payload["license_expression"],
        "license_files": metadata_payload["license_files"],
        "project_url_count": len(metadata_payload["project_urls"]),
        "classifier_count": len(metadata_payload["classifiers"]),
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
