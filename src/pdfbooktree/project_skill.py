"""package에 번들된 Codex skill을 project scope에 설치한다."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from typing import Iterator, Literal


PROJECT_SKILL_NAME = "use-pdfbooktree"
PROJECT_SKILL_RELATIVE_PATH = Path(".agents") / "skills" / PROJECT_SKILL_NAME
_RESOURCE_PARTS = ("_skill_templates", PROJECT_SKILL_NAME)
_REQUIRED_FILES = {"SKILL.md", "agents/openai.yaml"}


class SkillInstallError(ValueError):
    """project skill을 안전하게 설치할 수 없을 때 발생한다."""


@dataclass(frozen=True)
class SkillInstallResult:
    """project scope skill 설치 결과다."""

    status: Literal["installed", "replaced"]
    skill_name: str
    project_dir: Path
    skill_dir: Path
    file_count: int
    files: tuple[str, ...]


def install_project_skill(
    project_dir: Path | str = ".",
    *,
    force: bool = False,
) -> SkillInstallResult:
    """번들된 ``use-pdfbooktree`` skill을 project의 ``.agents/skills``에 설치한다."""

    project = Path(project_dir).resolve()
    if not project.is_dir():
        raise SkillInstallError(f"project directory가 없다: {project}")
    if not isinstance(force, bool):
        raise SkillInstallError("force는 bool이어야 한다.")

    target = project / PROJECT_SKILL_RELATIVE_PATH
    agents_dir = project / ".agents"
    target_parent = target.parent
    for directory in (agents_dir, target_parent):
        if directory.is_symlink() or directory.is_junction():
            raise SkillInstallError(
                f"project skill 상위 경로 link는 사용하지 않는다: {directory}"
            )
        if directory.exists() and not directory.is_dir():
            raise SkillInstallError(
                f"project skill 상위 경로가 directory가 아니다: {directory}"
            )
        if directory.exists() and not directory.resolve().is_relative_to(project):
            raise SkillInstallError(
                f"project skill 상위 경로가 project 밖을 가리킨다: {directory}"
            )
    target_parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = target_parent.resolve()
    if not resolved_parent.is_relative_to(project):
        raise SkillInstallError(
            f"project의 .agents/skills 경로가 project 밖을 가리킨다: {resolved_parent}"
        )
    if target.is_symlink() or target.is_junction():
        raise SkillInstallError(f"skill target link는 교체하지 않는다: {target}")
    if target.exists() and not target.is_dir():
        raise SkillInstallError(f"skill target이 directory가 아니다: {target}")

    replacing = target.exists()
    if replacing and not force:
        raise SkillInstallError(
            f"skill directory가 이미 있다: {target}. 교체하려면 force를 사용하라."
        )

    resource_root = _skill_resource_root()
    resources = tuple(_iter_resource_files(resource_root))
    relative_files = tuple(path.as_posix() for path, _ in resources)
    missing = sorted(_REQUIRED_FILES - set(relative_files))
    if missing:
        raise SkillInstallError(f"번들 skill 필수 파일이 없다: {missing}")

    staging = Path(
        tempfile.mkdtemp(prefix=f".{PROJECT_SKILL_NAME}-", dir=target_parent)
    )
    backup: Path | None = None
    try:
        for relative_path, resource in resources:
            destination = staging.joinpath(*relative_path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(resource.read_bytes())

        if replacing:
            backup = target_parent / (
                f".{PROJECT_SKILL_NAME}.backup-{uuid.uuid4().hex}"
            )
            target.replace(backup)
        try:
            staging.replace(target)
        except Exception:
            if backup is not None and backup.exists() and not target.exists():
                backup.replace(target)
            raise
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists() and target.exists():
            shutil.rmtree(backup)

    return SkillInstallResult(
        status="replaced" if replacing else "installed",
        skill_name=PROJECT_SKILL_NAME,
        project_dir=project,
        skill_dir=target,
        file_count=len(relative_files),
        files=relative_files,
    )


def _skill_resource_root() -> Traversable:
    """설치할 package resource directory를 반환한다."""

    root = files("pdfbooktree")
    for part in _RESOURCE_PARTS:
        root = root.joinpath(part)
    if not root.is_dir():
        raise SkillInstallError(
            f"package에 번들 skill이 없다: {'/'.join(_RESOURCE_PARTS)}"
        )
    return root


def _iter_resource_files(
    root: Traversable,
    prefix: PurePosixPath = PurePosixPath(),
) -> Iterator[tuple[PurePosixPath, Traversable]]:
    """resource tree의 파일을 안정된 상대 경로 순서로 순회한다."""

    for item in sorted(root.iterdir(), key=lambda value: value.name):
        relative = prefix / item.name
        if item.is_dir():
            yield from _iter_resource_files(item, relative)
        elif item.is_file():
            yield relative, item
