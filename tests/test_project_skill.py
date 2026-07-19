"""project scope Codex skill 설치 API를 검증한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdfbooktree import (
    PROJECT_SKILL_NAME,
    PROJECT_SKILL_RELATIVE_PATH,
    SkillInstallError,
    install_project_skill,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
REPO_SKILL_DIR = ROOT_DIR / ".agents" / "skills" / PROJECT_SKILL_NAME
PACKAGE_SKILL_DIR = (
    ROOT_DIR / "src" / "pdfbooktree" / "_skill_templates" / PROJECT_SKILL_NAME
)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """directory tree를 상대 경로별 bytes로 읽는다."""

    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_package_skill은_repo_local_skill과_byte_identical하다() -> None:
    assert _tree_bytes(PACKAGE_SKILL_DIR) == _tree_bytes(REPO_SKILL_DIR)


def test_install_project_skill은_project_scope에_전체_tree를_설치한다(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    result = install_project_skill(project)

    assert result.status == "installed"
    assert result.skill_name == PROJECT_SKILL_NAME
    assert result.project_dir == project.resolve()
    assert result.skill_dir == project.resolve() / PROJECT_SKILL_RELATIVE_PATH
    assert result.file_count == len(result.files) == 8
    assert set(result.files) == set(_tree_bytes(REPO_SKILL_DIR))
    assert _tree_bytes(result.skill_dir) == _tree_bytes(REPO_SKILL_DIR)


def test_install_project_skill은_기존_target을_기본적으로_보호한다(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    installed = install_project_skill(project)
    skill_md = installed.skill_dir / "SKILL.md"
    skill_md.write_text("local change\n", encoding="utf-8")

    with pytest.raises(SkillInstallError, match="이미 있다"):
        install_project_skill(project)

    assert skill_md.read_text(encoding="utf-8") == "local change\n"


def test_install_project_skill_force는_target_전체를_번들로_교체한다(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    installed = install_project_skill(project)
    (installed.skill_dir / "SKILL.md").write_text("broken\n", encoding="utf-8")
    (installed.skill_dir / "local-only.txt").write_text("remove me\n", encoding="utf-8")

    replaced = install_project_skill(project, force=True)

    assert replaced.status == "replaced"
    assert not (replaced.skill_dir / "local-only.txt").exists()
    assert _tree_bytes(replaced.skill_dir) == _tree_bytes(REPO_SKILL_DIR)


def test_install_project_skill은_없는_project를_거절한다(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(SkillInstallError, match="project directory가 없다"):
        install_project_skill(missing)


def test_install_project_skill은_agents_file을_거절한다(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".agents").write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(SkillInstallError, match="directory가 아니다"):
        install_project_skill(project)
