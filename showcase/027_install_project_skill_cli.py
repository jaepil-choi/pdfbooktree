"""빌드한 wheel을 설치한 CLI로 project scope skill 설치를 검증한다.

실행:
    uv run python showcase/027_install_project_skill_cli.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "027_install_project_skill_cli"
DIST_DIR = OUTPUT_DIR / "dist"
VENV_DIR = OUTPUT_DIR / "venv"
PROJECT_DIR = OUTPUT_DIR / "installed-project"
INSTALLED_SKILL_DIR = PROJECT_DIR / ".agents" / "skills" / "use-pdfbooktree"
INSTALLED_CLAUDE_SKILL_DIR = PROJECT_DIR / ".claude" / "skills" / "use-pdfbooktree"
SOURCE_SKILL_DIR = ROOT_DIR / ".agents" / "skills" / "use-pdfbooktree"
SOURCE_CLAUDE_SKILL_DIR = ROOT_DIR / ".claude" / "skills" / "use-pdfbooktree"
RESULT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "027_install_project_skill_cli"
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FULL_BODY_ONLY_MARKERS = ("## OCR 안전 규칙", "## 설정 사용", "## 계획 검토와 적용")


def tree_bytes(root: Path) -> dict[str, bytes]:
    """skill tree를 상대 경로별 bytes로 읽는다."""

    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def run(
    command: list[str], *, cwd: Path = ROOT_DIR
) -> subprocess.CompletedProcess[str]:
    """실제 외부 command를 실행하고 실패하면 즉시 중단한다."""

    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=utf8_environment(),
    )


def utf8_environment() -> dict[str, str]:
    """Windows subprocess의 JSON stream을 UTF-8로 고정한다."""

    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def parse_json_envelope(stream_text: str) -> dict[str, object]:
    """CLI stdout/stderr에서 JSON envelope 한 줄을 찾아 파싱한다.

    설치된 wheel의 `fitz` 모듈이 stdout에 deprecation warning 줄을 먼저 찍을 수
    있으므로, envelope이 아닌 앞선 줄은 건너뛴다.
    """

    for line in stream_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"CLI 출력에서 JSON envelope을 찾지 못했다: {stream_text!r}")


def parse_frontmatter(text: str) -> dict[str, object]:
    """Markdown 앞부분의 YAML frontmatter를 파싱한다."""

    match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
    if match is None:
        raise RuntimeError("Claude adapter에 YAML frontmatter가 없다.")
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise RuntimeError("Claude adapter frontmatter가 mapping이 아니다.")
    return meta


def relative_markdown_links(text: str) -> list[str]:
    """본문의 Markdown link 중 외부 URL이 아닌 상대 경로만 뽑는다."""

    links: list[str] = []
    for target in MARKDOWN_LINK_PATTERN.findall(text):
        if urlsplit(target).scheme:
            continue
        links.append(target)
    return links


def record_showcase(summary: dict[str, object]) -> None:
    """wheel 설치와 CLI 실행 결과를 showcase registry에 기록한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "현재 source로 wheel을 빌드해 격리 venv에 설치한 뒤, 설치된 "
            "pdfbooktree CLI가 실행 위치의 .agents/skills/use-pdfbooktree를 "
            "완전한 package resource로 생성하고, .claude/skills/use-pdfbooktree에는 "
            "frontmatter가 있고 본문을 복제하지 않으며 모든 상대 link가 실존 "
            "파일을 가리키는 Claude adapter를 생성하는지 검증한다."
        ),
        "inputs": [
            str(SOURCE_SKILL_DIR.relative_to(ROOT_DIR)),
            str(SOURCE_CLAUDE_SKILL_DIR.relative_to(ROOT_DIR)),
            "현재 source에서 빌드한 pdfbooktree wheel",
        ],
        "outputs": str(RESULT_PATH.relative_to(ROOT_DIR)),
        "finding": summary["finding"],
        "command": "uv run python showcase/027_install_project_skill_cli.py",
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    showcases = data["showcases"]
    for index, existing in enumerate(showcases):
        if existing.get("id") == SHOWCASE_ID:
            showcases[index] = entry
            break
    else:
        showcases.append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """wheel build, pip install, CLI 신규/보호/force 흐름을 실제 실행한다."""

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    DIST_DIR.mkdir(parents=True)
    PROJECT_DIR.mkdir(parents=True)

    run(["uv", "build", "--wheel", "--out-dir", str(DIST_DIR)])
    wheel = next(DIST_DIR.glob("pdfbooktree-*.whl"))
    run(["uv", "venv", str(VENV_DIR)])
    venv_python = VENV_DIR / "Scripts" / "python.exe"
    cli = VENV_DIR / "Scripts" / "pdfbooktree.exe"
    run(["uv", "pip", "install", "--python", str(venv_python), str(wheel)])

    installed_command = run(
        [str(cli), "skill", "install", "--format", "json"],
        cwd=PROJECT_DIR,
    )
    installed_envelope = parse_json_envelope(installed_command.stdout)
    installed_result = installed_envelope["result"]
    installed_identical = tree_bytes(INSTALLED_SKILL_DIR) == tree_bytes(
        SOURCE_SKILL_DIR
    )
    agents_full_instructions_present = (
        (INSTALLED_SKILL_DIR / "SKILL.md").is_file()
        and (INSTALLED_SKILL_DIR / "agents" / "openai.yaml").is_file()
        and (INSTALLED_SKILL_DIR / "references").is_dir()
        and any((INSTALLED_SKILL_DIR / "references").iterdir())
    )

    claude_adapter_path = INSTALLED_CLAUDE_SKILL_DIR / "SKILL.md"
    claude_adapter_text = claude_adapter_path.read_text(encoding="utf-8")
    claude_frontmatter = parse_frontmatter(claude_adapter_text)
    claude_description = str(claude_frontmatter.get("description", "")).strip()
    claude_adapter_has_frontmatter = (
        isinstance(claude_frontmatter.get("name"), str)
        and claude_frontmatter["name"].strip() != ""
        and claude_description != ""
    )
    agents_skill_md_text = (INSTALLED_SKILL_DIR / "SKILL.md").read_text(
        encoding="utf-8"
    )
    claude_adapter_does_not_duplicate_body = len(claude_adapter_text) < len(
        agents_skill_md_text
    ) and all(marker not in claude_adapter_text for marker in FULL_BODY_ONLY_MARKERS)
    claude_adapter_links = relative_markdown_links(claude_adapter_text)
    claude_adapter_link_targets = [
        (claude_adapter_path.parent / link).resolve() for link in claude_adapter_links
    ]
    claude_adapter_links_resolve = bool(claude_adapter_links) and all(
        target.is_file() for target in claude_adapter_link_targets
    )
    claude_adapter_points_into_agents_tree = all(
        target.is_relative_to(INSTALLED_SKILL_DIR.resolve())
        for target in claude_adapter_link_targets
    )

    protected = subprocess.run(
        [str(cli), "skill", "install", "--format", "json"],
        cwd=PROJECT_DIR,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=utf8_environment(),
    )
    protected_error = parse_json_envelope(protected.stderr)

    extra = INSTALLED_SKILL_DIR / "local-only.txt"
    extra.write_text("force에서 제거할 local file\n", encoding="utf-8")
    replaced_command = run(
        [str(cli), "skill", "install", "--force", "--format", "json"],
        cwd=PROJECT_DIR,
    )
    replaced_result = parse_json_envelope(replaced_command.stdout)["result"]
    force_identical = not extra.exists() and tree_bytes(
        INSTALLED_SKILL_DIR
    ) == tree_bytes(SOURCE_SKILL_DIR)

    summary: dict[str, object] = {
        "wheel": str(wheel.relative_to(ROOT_DIR)),
        "installed_cli": str(cli.relative_to(ROOT_DIR)),
        "project_dir": str(PROJECT_DIR.relative_to(ROOT_DIR)),
        "skill_dir": str(INSTALLED_SKILL_DIR.relative_to(ROOT_DIR)),
        "claude_skill_dir": str(INSTALLED_CLAUDE_SKILL_DIR.relative_to(ROOT_DIR)),
        "installed_status": installed_result["status"],
        "installed_file_count": installed_result["file_count"],
        "installed_identical": installed_identical,
        "claude_files": installed_result["claude_files"],
        "claude_frontmatter_name": claude_frontmatter.get("name"),
        "claude_frontmatter_description": claude_description,
        "claude_adapter_link_count": len(claude_adapter_links),
        "existing_target_exit_code": protected.returncode,
        "existing_target_error_code": protected_error["error"]["code"],
        "replaced_status": replaced_result["status"],
        "force_identical": force_identical,
        "proof": {
            "agents_target_has_full_instructions": agents_full_instructions_present,
            "claude_adapter_has_name_and_description": claude_adapter_has_frontmatter,
            "claude_adapter_does_not_duplicate_body": claude_adapter_does_not_duplicate_body,
            "claude_adapter_links_all_resolve": claude_adapter_links_resolve,
            "claude_adapter_links_point_into_agents_tree": (
                claude_adapter_points_into_agents_tree
            ),
        },
    }
    if not (
        installed_envelope["ok"] is True
        and installed_result["status"] == "installed"
        and installed_identical
        and agents_full_instructions_present
        and claude_adapter_has_frontmatter
        and claude_adapter_does_not_duplicate_body
        and claude_adapter_links_resolve
        and claude_adapter_points_into_agents_tree
        and protected.returncode == 2
        and protected_error["error"]["code"] == "skill_install_error"
        and replaced_result["status"] == "replaced"
        and force_identical
    ):
        raise RuntimeError(f"설치된 CLI showcase가 기대 계약과 다르다: {summary}")

    summary["finding"] = (
        f"wheel 설치 CLI가 agents target skill file {installed_result['file_count']}개를 "
        "실행 project에 byte-identical하게 생성했고, Claude adapter "
        f"{len(claude_adapter_links)}개 상대 link가 모두 agents target 내 실존 "
        f"파일을 가리키며 frontmatter description='{claude_description}'을 담고 "
        "전체 본문을 복제하지 않았다. 기존 target은 exit 2로 보호하며 --force에서 "
        "두 target 모두 전체 교체했다."
    )
    RESULT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record_showcase(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
