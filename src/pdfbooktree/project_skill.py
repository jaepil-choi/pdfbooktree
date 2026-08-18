"""package에 번들된 skill을 project scope에 설치한다.

`.agents/skills/use-pdfbooktree`는 전체 지침을 담은 agents target이고,
`.claude/skills/use-pdfbooktree`는 이 저장소의 `CLAUDE.md`가 `AGENTS.md`에
위임하는 것과 같은 adapter target이다. 두 target 모두 package에 번들된 단일
``SKILL.md``(agents target 본문)와 ``claude_adapter.md.template``(adapter
뼈대)에서 파생되므로, workflow 목록 같은 내용을 두 곳에 손으로 중복 유지하지
않는다.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from typing import Iterator, Literal, Sequence

import yaml


PROJECT_SKILL_NAME = "use-pdfbooktree"
PROJECT_SKILL_RELATIVE_PATH = Path(".agents") / "skills" / PROJECT_SKILL_NAME
CLAUDE_SKILL_RELATIVE_PATH = Path(".claude") / "skills" / PROJECT_SKILL_NAME
_RESOURCE_PARTS = ("_skill_templates", PROJECT_SKILL_NAME)
_CLAUDE_TEMPLATE_RESOURCE_PARTS = ("_skill_templates", "claude_adapter.md.template")
_REQUIRED_FILES = {"SKILL.md", "agents/openai.yaml"}
_WORKFLOW_SECTION_HEADING = "Workflow 선택"

_FRONTMATTER_PATTERN = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_ORDERED_LIST_ITEM_PATTERN = re.compile(r"^\d+\.\s")


class SkillInstallError(ValueError):
    """project skill을 안전하게 설치할 수 없을 때 발생한다."""


@dataclass(frozen=True)
class SkillInstallResult:
    """project scope skill 설치 결과다.

    ``skill_dir``/``files``/``file_count``는 전체 지침과 ``references/``를 담은
    agents target(``.agents/skills/use-pdfbooktree``)을 가리키고,
    ``claude_skill_dir``/``claude_files``는 그 agents target을 요약해 가리키는
    Claude adapter target(``.claude/skills/use-pdfbooktree``)을 가리킨다.
    """

    status: Literal["installed", "replaced"]
    skill_name: str
    project_dir: Path
    skill_dir: Path
    file_count: int
    files: tuple[str, ...]
    claude_skill_dir: Path
    claude_files: tuple[str, ...]


def install_project_skill(
    project_dir: Path | str = ".",
    *,
    force: bool = False,
) -> SkillInstallResult:
    """번들된 ``use-pdfbooktree`` skill을 agents/Claude 두 target에 설치한다.

    agents target(``.agents/skills/use-pdfbooktree``)에는 전체 ``SKILL.md``
    본문, ``references/``, ``agents/openai.yaml``을 그대로 설치한다. Claude
    target(``.claude/skills/use-pdfbooktree/SKILL.md``)에는 같은
    ``SKILL.md``에서 frontmatter와 workflow 목록을 추출해 렌더링한 adapter
    한 파일만 설치하며, 전체 본문은 복제하지 않고 agents target과 그
    ``references/``를 가리킨다.
    """

    project = Path(project_dir).resolve()
    if not project.is_dir():
        raise SkillInstallError(f"project directory가 없다: {project}")
    if not isinstance(force, bool):
        raise SkillInstallError("force는 bool이어야 한다.")

    agents_target = project / PROJECT_SKILL_RELATIVE_PATH
    claude_target = project / CLAUDE_SKILL_RELATIVE_PATH

    agents_target_parent = _validate_target_chain(
        project, agents_target, project / ".agents"
    )
    claude_target_parent = _validate_target_chain(
        project, claude_target, project / ".claude"
    )

    agents_replacing = agents_target.exists()
    claude_replacing = claude_target.exists()
    if (agents_replacing or claude_replacing) and not force:
        existing = agents_target if agents_replacing else claude_target
        raise SkillInstallError(
            f"skill directory가 이미 있다: {existing}. 교체하려면 force를 사용하라."
        )

    resource_root = _skill_resource_root()
    resources = tuple(_iter_resource_files(resource_root))
    relative_files = tuple(path.as_posix() for path, _ in resources)
    missing = sorted(_REQUIRED_FILES - set(relative_files))
    if missing:
        raise SkillInstallError(f"번들 skill 필수 파일이 없다: {missing}")

    agents_files = {
        relative_path.as_posix(): resource.read_bytes()
        for relative_path, resource in resources
    }
    skill_md_text = agents_files["SKILL.md"].decode("utf-8")
    reference_paths = sorted(
        path for path in agents_files if path.startswith("references/")
    )
    claude_files = {
        "SKILL.md": _render_claude_skill_md(skill_md_text, reference_paths),
    }

    _atomic_install_tree(
        agents_target_parent, agents_target, agents_files, replacing=agents_replacing
    )
    _atomic_install_tree(
        claude_target_parent, claude_target, claude_files, replacing=claude_replacing
    )

    return SkillInstallResult(
        status="replaced" if (agents_replacing or claude_replacing) else "installed",
        skill_name=PROJECT_SKILL_NAME,
        project_dir=project,
        skill_dir=agents_target,
        file_count=len(relative_files),
        files=relative_files,
        claude_skill_dir=claude_target,
        claude_files=tuple(sorted(claude_files)),
    )


def _validate_target_chain(project: Path, target: Path, scope_dir: Path) -> Path:
    """target 상위 경로가 project 밖을 가리키거나 link가 아닌지 검사한다."""

    for directory in (scope_dir, target.parent):
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

    target_parent = target.parent
    target_parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = target_parent.resolve()
    if not resolved_parent.is_relative_to(project):
        raise SkillInstallError(
            f"project skill directory 경로가 project 밖을 가리킨다: {resolved_parent}"
        )
    if target.is_symlink() or target.is_junction():
        raise SkillInstallError(f"skill target link는 교체하지 않는다: {target}")
    if target.exists() and not target.is_dir():
        raise SkillInstallError(f"skill target이 directory가 아니다: {target}")
    return target_parent


def _atomic_install_tree(
    target_parent: Path,
    target: Path,
    file_contents: dict[str, bytes],
    *,
    replacing: bool,
) -> None:
    """staging directory에 파일을 쓴 뒤 target을 원자적으로 교체한다."""

    staging = Path(
        tempfile.mkdtemp(prefix=f".{PROJECT_SKILL_NAME}-", dir=target_parent)
    )
    backup: Path | None = None
    try:
        for relative_path, content in file_contents.items():
            destination = staging.joinpath(*PurePosixPath(relative_path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)

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


def _render_claude_skill_md(
    agents_skill_md_text: str,
    reference_relative_paths: Sequence[str],
) -> bytes:
    """agents target의 ``SKILL.md``에서 Claude adapter를 파생시킨다.

    frontmatter의 ``name``/``description``과 workflow 번호 목록을 agents
    ``SKILL.md``에서 그대로 추출해서 쓰고, 전체 본문은 복제하지 않는다.
    ``description``은 Claude가 이 skill을 불러올지 판단하는 근거이므로 3인칭으로
    무엇을 하는지와 언제 쓰는지를 함께 담아야 하는데, agents ``SKILL.md``의
    description은 이미 그 두 조건(수행 내용 + 사용 시점)을 3인칭으로 담고 있으므로
    "Codex가" 부분만 "Claude가"로 바꿔 재사용한다.
    """

    meta, body = _parse_frontmatter(agents_skill_md_text)
    name = str(meta.get("name", PROJECT_SKILL_NAME))
    agents_description = str(meta.get("description", "")).strip()
    if not agents_description:
        raise SkillInstallError("SKILL.md frontmatter에 description이 없다.")
    description = agents_description.replace("Codex가", "Claude가")

    workflow_section = _extract_section(body, _WORKFLOW_SECTION_HEADING)
    workflow_items = [
        line
        for line in workflow_section.splitlines()
        if _ORDERED_LIST_ITEM_PATTERN.match(line)
    ]
    if not workflow_items:
        raise SkillInstallError(
            f"SKILL.md의 '{_WORKFLOW_SECTION_HEADING}' 섹션에서 번호 목록을 찾지 못했다."
        )

    agents_root = PROJECT_SKILL_RELATIVE_PATH.as_posix()
    up_to_project_root = "../../../"
    agents_skill_md_link = f"{up_to_project_root}{agents_root}/SKILL.md"
    reference_links = "\n".join(
        f"- [{path}]({up_to_project_root}{agents_root}/{path})"
        for path in reference_relative_paths
    )

    frontmatter = yaml.safe_dump(
        {"name": name, "description": description},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()

    template = _claude_adapter_template()
    rendered = template.format(
        frontmatter=frontmatter,
        agents_skill_md_link=agents_skill_md_link,
        workflow_list="\n".join(workflow_items),
        reference_links=reference_links,
    )
    return rendered.encode("utf-8")


def _claude_adapter_template() -> str:
    """번들된 Claude adapter template 문자열을 읽는다."""

    root = files("pdfbooktree")
    for part in _CLAUDE_TEMPLATE_RESOURCE_PARTS:
        root = root.joinpath(part)
    if not root.is_file():
        raise SkillInstallError(
            f"package에 Claude adapter template이 없다: "
            f"{'/'.join(_CLAUDE_TEMPLATE_RESOURCE_PARTS)}"
        )
    return root.read_text(encoding="utf-8")


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Markdown 앞부분의 YAML frontmatter와 나머지 본문을 분리한다."""

    match = _FRONTMATTER_PATTERN.match(text)
    if not match:
        raise SkillInstallError("SKILL.md에 YAML frontmatter가 없다.")
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise SkillInstallError("SKILL.md frontmatter가 mapping이 아니다.")
    return meta, text[match.end() :]


def _extract_section(body: str, heading: str) -> str:
    """``## {heading}``부터 다음 ``## `` heading 전까지의 본문을 반환한다."""

    pattern = re.compile(
        rf"^## {re.escape(heading)}\r?\n(.*?)(?=^## |\Z)", re.DOTALL | re.MULTILINE
    )
    match = pattern.search(body)
    if not match:
        raise SkillInstallError(f"SKILL.md에 '{heading}' 섹션이 없다.")
    return match.group(1).strip()


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
