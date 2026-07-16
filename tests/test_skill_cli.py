"""project scope skill 설치 CLI 계약을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pdfbooktree import PROJECT_SKILL_RELATIVE_PATH
from pdfbooktree.cli import app


RUNNER = CliRunner()


def _success_result(result) -> dict[str, object]:
    """skill.install 성공 envelope의 result를 반환한다."""

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    envelope = json.loads(result.stdout)
    assert envelope["schema_version"] == 1
    assert envelope["command"] == "skill.install"
    assert envelope["ok"] is True
    return envelope["result"]


def test_skill_install은_현재_directory에_설치한다(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)

    result = RUNNER.invoke(app, ["skill", "install", "--format", "json"])

    payload = _success_result(result)
    assert payload["status"] == "installed"
    assert Path(payload["project_dir"]) == project.resolve()
    assert Path(payload["skill_dir"]) == project / PROJECT_SKILL_RELATIVE_PATH
    assert (project / PROJECT_SKILL_RELATIVE_PATH / "SKILL.md").is_file()


def test_skill_install은_기존_target을_json_exit_2로_보호한다(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    args = [
        "skill",
        "install",
        "--project-dir",
        str(project),
        "--format",
        "json",
    ]
    first = RUNNER.invoke(app, args)
    second = RUNNER.invoke(app, args)

    assert first.exit_code == 0
    assert second.exit_code == 2
    assert second.stdout == ""
    envelope = json.loads(second.stderr)
    assert envelope["command"] == "skill.install"
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "skill_install_error"
    assert envelope["error"]["type"] == "SkillInstallError"


def test_skill_install_force는_기존_target을_교체한다(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    base_args = ["skill", "install", "--project-dir", str(project)]
    first = RUNNER.invoke(app, base_args)
    assert first.exit_code == 0
    extra = project / PROJECT_SKILL_RELATIVE_PATH / "extra.txt"
    extra.write_text("remove\n", encoding="utf-8")

    replaced = RUNNER.invoke(
        app,
        [*base_args, "--force", "--format", "json"],
    )

    assert _success_result(replaced)["status"] == "replaced"
    assert not extra.exists()


def test_skill_help에서_install_command를_발견할_수_있다() -> None:
    root_help = RUNNER.invoke(app, ["--help"])
    skill_help = RUNNER.invoke(app, ["skill", "--help"])

    assert root_help.exit_code == 0
    assert "skill" in root_help.stdout
    assert skill_help.exit_code == 0
    assert "install" in skill_help.stdout
