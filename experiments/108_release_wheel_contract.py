"""0.1.0 wheel 배포 계약의 현재 baseline과 누락 항목을 기록한다."""

from __future__ import annotations

import json
import subprocess
import tomllib
import zipfile
from datetime import datetime
from email.parser import Parser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "experiments" / "outputs" / "108_release_wheel_contract"
DIST_DIR = OUTPUT_DIR / "dist"
RESULT_PATH = OUTPUT_DIR / "result.json"
SAMPLE_PDF = (
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


def run(command: list[str]) -> dict[str, object]:
    """명령 하나를 실행하고 재현 가능한 결과만 반환한다."""

    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def read_wheel_metadata(wheel_path: Path) -> tuple[dict[str, str], list[str]]:
    """wheel의 METADATA와 package skill member를 읽는다."""

    with zipfile.ZipFile(wheel_path) as archive:
        members = sorted(archive.namelist())
        metadata_member = next(
            member for member in members if member.endswith(".dist-info/METADATA")
        )
        metadata_text = archive.read(metadata_member).decode("utf-8")
    parsed = Parser().parsestr(metadata_text)
    metadata = {
        "name": parsed.get("Name", ""),
        "version": parsed.get("Version", ""),
        "license_expression": parsed.get("License-Expression", ""),
        "requires_python": parsed.get("Requires-Python", ""),
        "project_urls": parsed.get_all("Project-URL", []),
        "keywords": parsed.get("Keywords", ""),
    }
    skill_members = [
        member
        for member in members
        if "pdfbooktree/_skill_templates/use-pdfbooktree/" in member
        and not member.endswith("/")
    ]
    return metadata, skill_members


def main() -> None:
    """현재 배포 계약의 성공과 누락을 result JSON으로 기록한다."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    version_result = run(["uv", "run", "--no-sync", "pdfbooktree", "--version"])
    build_result = run(
        [
            "uv",
            "build",
            "--no-index",
            "--clear",
            "--out-dir",
            str(DIST_DIR),
        ]
    )
    inspect_result = run(
        [
            "uv",
            "run",
            "--no-sync",
            "pdfbooktree",
            "inspect",
            "page-count",
            str(SAMPLE_PDF),
            "--format",
            "json",
        ]
    )

    wheels = sorted(DIST_DIR.glob("*.whl"))
    wheel_metadata: dict[str, object] = {}
    skill_members: list[str] = []
    if wheels:
        wheel_metadata, skill_members = read_wheel_metadata(wheels[-1])

    expected_gaps = {
        "license_missing": "license" not in project,
        "project_urls_missing": "urls" not in project,
        "keywords_missing": "keywords" not in project,
        "classifiers_missing": "classifiers" not in project,
        "version_option_missing": version_result["exit_code"] != 0,
    }
    result = {
        "experiment_id": "108_release_wheel_contract",
        "sample_pdf": str(SAMPLE_PDF.relative_to(ROOT)),
        "sample_pdf_size": SAMPLE_PDF.stat().st_size,
        "source_project": {
            "name": project["name"],
            "version": project["version"],
            "requires_python": project["requires-python"],
        },
        "version_command": version_result,
        "build": build_result,
        "wheel_paths": [str(path.relative_to(ROOT)) for path in wheels],
        "wheel_metadata": wheel_metadata,
        "package_skill_member_count": len(skill_members),
        "package_skill_members": skill_members,
        "installed_surface_probe": inspect_result,
        "expected_gaps": expected_gaps,
        "baseline_reproduced": (
            build_result["exit_code"] == 0
            and inspect_result["exit_code"] == 0
            and len(skill_members) == 5
            and all(expected_gaps.values())
        ),
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
