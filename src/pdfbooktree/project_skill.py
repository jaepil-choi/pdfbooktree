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

# AGENTS.md/CLAUDE.md에 심는 pointer block의 marker다. 이름에 package를 명시해서
# 다른 도구가 심은 block과 절대 섞이지 않게 한다. block 자체는 짧게 유지하고,
# 전체 지침은 항상 agents target의 SKILL.md 하나만 가리킨다.
_INSTRUCTION_MARKER_BEGIN = "<!-- pdfbooktree:skill:begin -->"
_INSTRUCTION_MARKER_END = "<!-- pdfbooktree:skill:end -->"
_INSTRUCTION_BLOCK_PATTERN = re.compile(
    re.escape(_INSTRUCTION_MARKER_BEGIN) + r".*?" + re.escape(_INSTRUCTION_MARKER_END),
    re.DOTALL,
)
_INSTRUCTION_FILE_NAMES = ("AGENTS.md", "CLAUDE.md")
# install은 기존 내용 뒤에 항상 정확히 줄바꿈 하나만 구분자로 붙이고 block
# 뒤에도 줄바꿈 하나만 붙인다(``_upsert_instruction_block`` 참고). 그 결과
# begin marker 앞에는 "기존 내용이 원래 갖고 있던 줄바꿈 수 + 1"만큼의
# 줄바꿈이 남고, 정확히 하나만 우리가 추가한 구분자다. 이 pattern은 좌우 모두
# "있으면 하나만" 지우는 optional group을 쓰는데, ``re.sub``는 가장 왼쪽에서
# 매치 가능한 위치부터 시도하므로 항상 begin marker에 바로 붙어 있는 줄바꿈
# 하나만 소비하고 그 앞의 기존 내용 자체의 줄바꿈은 그대로 남긴다. 그래서
# 기존 내용이 이미 줄바꿈으로 끝나 있었는지 여부와 무관하게 원래 상태로
# 정확히 되돌아간다.
_INSTRUCTION_REMOVE_PATTERN = re.compile(
    r"(?:\r?\n)?"
    + re.escape(_INSTRUCTION_MARKER_BEGIN)
    + r".*?"
    + re.escape(_INSTRUCTION_MARKER_END)
    + r"(?:\r?\n)?",
    re.DOTALL,
)


class SkillInstallError(ValueError):
    """project skill을 안전하게 설치하거나 제거할 수 없을 때 발생한다."""


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
    instruction_files: tuple[str, ...]


@dataclass(frozen=True)
class SkillUninstallResult:
    """project scope skill 제거 결과다.

    ``removed_skill_dirs``는 이 package가 소유를 확인하고 실제로 지운
    skill directory의 project-relative 경로이고, ``removed_instruction_files``는
    marker block만 담고 있어서 제거로 통째로 삭제한 지침 파일 이름이며,
    ``updated_instruction_files``는 block만 제거하고 나머지 사용자 내용은
    남긴 지침 파일 이름이다.
    """

    status: Literal["uninstalled", "not_installed"]
    skill_name: str
    project_dir: Path
    removed_skill_dirs: tuple[str, ...]
    removed_instruction_files: tuple[str, ...]
    updated_instruction_files: tuple[str, ...]


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

    for file_name in _INSTRUCTION_FILE_NAMES:
        _upsert_instruction_block(project / file_name)

    return SkillInstallResult(
        status="replaced" if (agents_replacing or claude_replacing) else "installed",
        skill_name=PROJECT_SKILL_NAME,
        project_dir=project,
        skill_dir=agents_target,
        file_count=len(relative_files),
        files=relative_files,
        claude_skill_dir=claude_target,
        claude_files=tuple(sorted(claude_files)),
        instruction_files=_INSTRUCTION_FILE_NAMES,
    )


def uninstall_project_skill(project_dir: Path | str = ".") -> SkillUninstallResult:
    """``install_project_skill``이 만든 것만 정확히 제거한다.

    두 skill directory는 ``SKILL.md`` frontmatter의 ``name``이
    ``use-pdfbooktree``일 때만 이 package의 것으로 인정하고 지운다. 다른 도구나
    사용자가 같은 경로에 만든 directory는 건드리지 않는다. ``AGENTS.md``와
    ``CLAUDE.md``에서는 marker block만 제거하며, block 제거로 파일이 비면 파일
    자체를 지우고 아니면 나머지 사용자 내용을 그대로 남긴다. 아무것도 설치돼
    있지 않으면 오류 없이 ``status="not_installed"``를 반환한다.
    """

    project = Path(project_dir).resolve()
    if not project.is_dir():
        raise SkillInstallError(f"project directory가 없다: {project}")

    agents_target = project / PROJECT_SKILL_RELATIVE_PATH
    claude_target = project / CLAUDE_SKILL_RELATIVE_PATH

    _validate_removal_target(project, agents_target, project / ".agents")
    _validate_removal_target(project, claude_target, project / ".claude")

    removed_dirs: list[str] = []
    for target, relative in (
        (agents_target, PROJECT_SKILL_RELATIVE_PATH),
        (claude_target, CLAUDE_SKILL_RELATIVE_PATH),
    ):
        if target.exists() and _skill_dir_is_ours(target):
            shutil.rmtree(target)
            removed_dirs.append(relative.as_posix())
            _remove_if_empty(target.parent)
            _remove_if_empty(target.parent.parent)

    removed_instruction_files: list[str] = []
    updated_instruction_files: list[str] = []
    for file_name in _INSTRUCTION_FILE_NAMES:
        outcome = _remove_instruction_block(project / file_name)
        if outcome == "removed_file":
            removed_instruction_files.append(file_name)
        elif outcome == "updated_file":
            updated_instruction_files.append(file_name)

    removed_dirs_t = tuple(removed_dirs)
    removed_files_t = tuple(removed_instruction_files)
    updated_files_t = tuple(updated_instruction_files)
    status: Literal["uninstalled", "not_installed"] = (
        "uninstalled"
        if (removed_dirs_t or removed_files_t or updated_files_t)
        else "not_installed"
    )

    return SkillUninstallResult(
        status=status,
        skill_name=PROJECT_SKILL_NAME,
        project_dir=project,
        removed_skill_dirs=removed_dirs_t,
        removed_instruction_files=removed_files_t,
        updated_instruction_files=updated_files_t,
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


def _validate_removal_target(project: Path, target: Path, scope_dir: Path) -> None:
    """제거 대상 상위 경로가 project 밖을 가리키거나 link가 아닌지 검사한다.

    ``install_project_skill``의 ``_validate_target_chain``과 달리 target
    자체가 아직 없어도 되고 target의 상위 directory를 새로 만들지도 않는다.
    """

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
    if target.is_symlink() or target.is_junction():
        raise SkillInstallError(f"skill target link는 지우지 않는다: {target}")
    if target.exists() and not target.is_dir():
        raise SkillInstallError(f"skill target이 directory가 아니다: {target}")


def _remove_if_empty(directory: Path) -> None:
    """directory가 존재하고 비어 있으면 지운다.

    install이 ``.agents/skills``나 ``.claude/skills`` 같은 상위 directory를
    새로 만들었을 수 있으므로, 우리 skill directory를 지운 뒤 그 부모가 이제
    비었으면 함께 정리해서 install 이전 project 상태로 완전히 되돌린다.
    사용자가 다른 파일/directory를 넣어 비어 있지 않으면 그대로 둔다.
    """

    try:
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    except OSError:
        pass


def _skill_dir_is_ours(target: Path) -> bool:
    """target directory의 ``SKILL.md``가 이 package 소유인지 확인한다.

    frontmatter의 ``name``이 ``use-pdfbooktree``와 정확히 같을 때만 우리
    것으로 인정한다. 다른 도구가 만든 동명의 directory나 사용자가 손으로
    바꿔친 ``SKILL.md``는 이름이 다르거나 frontmatter를 읽지 못하므로 안전하게
    걸러진다.
    """

    skill_md = target / "SKILL.md"
    if not skill_md.is_file():
        return False
    try:
        meta, _ = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    except SkillInstallError:
        return False
    return meta.get("name") == PROJECT_SKILL_NAME


def _read_text_raw(path: Path) -> str:
    """줄바꿈을 변환하지 않고 파일을 UTF-8 문자열로 읽는다.

    ``Path.read_text``의 ``newline`` keyword는 Python 3.13부터 지원하므로,
    이 저장소가 지원하는 3.12에서도 동작하도록 ``open()``을 직접 쓴다.
    """

    with path.open("r", encoding="utf-8", newline="") as file:
        return file.read()


def _write_text_raw(path: Path, text: str) -> None:
    """줄바꿈을 변환하지 않고 UTF-8 문자열을 파일로 쓴다."""

    with path.open("w", encoding="utf-8", newline="") as file:
        file.write(text)


def _instruction_block_text(project: Path) -> str:
    """AGENTS.md/CLAUDE.md에 심을 marker block 본문을 만든다.

    agents target의 project-relative 경로를 가리키는 짧은 안내만 담고, 전체
    지침은 절대 복제하지 않는다.
    """

    skill_md_relative = PROJECT_SKILL_RELATIVE_PATH.as_posix() + "/SKILL.md"
    return (
        f"{_INSTRUCTION_MARKER_BEGIN}\n"
        f"이 project에는 `{PROJECT_SKILL_NAME}` skill(패키지 `pdfbooktree`)이 "
        f"설치돼 있다. 전체 지침은 `{skill_md_relative}`에 있다.\n"
        f"{_INSTRUCTION_MARKER_END}"
    )


def _upsert_instruction_block(path: Path) -> None:
    """``path``에 marker block을 넣거나, 있으면 그 자리에서 교체한다.

    marker 밖의 내용과 줄바꿈 방식은 절대 건드리지 않는다. 파일이 없으면 block
    하나만 담은 새 파일을 만든다.
    """

    block = _instruction_block_text(path.parent)
    if not path.is_file():
        _write_text_raw(path, block + "\n")
        return

    original = _read_text_raw(path)
    newline = "\r\n" if "\r\n" in original else "\n"
    block_native = block.replace("\n", newline)

    if _INSTRUCTION_BLOCK_PATTERN.search(original):
        updated = _INSTRUCTION_BLOCK_PATTERN.sub(
            lambda _match: block_native, original, count=1
        )
        if updated != original:
            _write_text_raw(path, updated)
        return

    if original == "":
        _write_text_raw(path, block_native + newline)
        return

    # 기존 내용 원본은 절대 정규화하지 않고, block 앞에 구분자 줄바꿈을
    # 정확히 하나만 추가한다. 이 구분자가 항상 하나뿐이므로 제거할 때도
    # BEGIN marker 바로 앞의 줄바꿈 하나만 지우면 기존 내용을 그 자신의
    # 줄바꿈까지 포함해서 byte 그대로 복원할 수 있다.
    updated = f"{original}{newline}{block_native}{newline}"
    _write_text_raw(path, updated)


def _remove_instruction_block(
    path: Path,
) -> Literal["removed_file", "updated_file", "absent"]:
    """``path``에서 marker block만 제거하고 결과를 보고한다.

    block을 걷어낸 결과가 공백만 남으면 파일 자체를 지우고, 아니면 나머지
    사용자 내용을 그대로 보존한 채 다시 쓴다. block이 아예 없으면 아무것도
    건드리지 않는다.
    """

    if not path.is_file():
        return "absent"

    original = _read_text_raw(path)
    if not _INSTRUCTION_BLOCK_PATTERN.search(original):
        return "absent"

    updated = _INSTRUCTION_REMOVE_PATTERN.sub("", original)
    if updated.strip() == "":
        path.unlink()
        return "removed_file"

    _write_text_raw(path, updated)
    return "updated_file"


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
