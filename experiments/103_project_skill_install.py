"""repo-local skill tree를 project scope에 동일하게 설치할 수 있는지 검증한다.

실행:
    uv run python experiments/103_project_skill_install.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SOURCE_SKILL_DIR = ROOT_DIR / ".agents" / "skills" / "use-pdfbooktree"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / "103_project_skill_install"
PROJECT_DIR = OUTPUT_DIR / "project"
TARGET_SKILL_DIR = PROJECT_DIR / ".agents" / "skills" / "use-pdfbooktree"
RESULT_PATH = OUTPUT_DIR / "result.json"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "103_project_skill_install"


def tree_hashes(root: Path) -> dict[str, str]:
    """directory 아래 모든 파일의 상대 경로와 SHA-256을 반환한다."""

    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def install_skill(project_dir: Path, *, force: bool = False) -> Path:
    """실험용으로 source skill을 project-local target에 복사한다."""

    target = project_dir / ".agents" / "skills" / SOURCE_SKILL_DIR.name
    if target.exists():
        if not force:
            raise FileExistsError(f"skill directory가 이미 있다: {target}")
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE_SKILL_DIR, target)
    return target


def record_experiment(summary: dict[str, object], finding: str) -> None:
    """실험 결과를 experiments registry에 기록한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "pip 설치 package가 제공할 use-pdfbooktree skill tree를 현재 project의 "
            ".agents/skills 아래에 동일하게 설치하는 경로와 overwrite 정책을 검증한다."
        ),
        "inputs": [str(SOURCE_SKILL_DIR.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "repo-local skill의 모든 파일을 project/.agents/skills/use-pdfbooktree로 "
            "복사하고 상대 경로별 SHA-256을 비교했다. 기존 target은 기본적으로 "
            "거절하고, force일 때 전체 directory를 교체한 뒤 다시 hash를 비교했다."
        ),
        "summary": summary,
        "finding": finding,
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    experiments = data["experiments"]
    for index, existing in enumerate(experiments):
        if existing.get("id") == EXPERIMENT_ID:
            experiments[index] = entry
            break
    else:
        experiments.append(entry)
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """신규 설치, 기존 target 보호, force 교체를 차례로 검증한다."""

    if not SOURCE_SKILL_DIR.is_dir():
        raise FileNotFoundError(f"source skill directory가 없다: {SOURCE_SKILL_DIR}")
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    source_hashes = tree_hashes(SOURCE_SKILL_DIR)
    installed = install_skill(PROJECT_DIR)
    initial_identical = tree_hashes(installed) == source_hashes

    existing_target_rejected = False
    try:
        install_skill(PROJECT_DIR)
    except FileExistsError:
        existing_target_rejected = True

    (installed / "SKILL.md").write_text("손상된 파일\n", encoding="utf-8")
    replaced = install_skill(PROJECT_DIR, force=True)
    force_identical = tree_hashes(replaced) == source_hashes

    summary: dict[str, object] = {
        "source_skill_dir": str(SOURCE_SKILL_DIR.relative_to(ROOT_DIR)),
        "target_skill_dir": str(TARGET_SKILL_DIR.relative_to(ROOT_DIR)),
        "file_count": len(source_hashes),
        "files": sorted(source_hashes),
        "initial_identical": initial_identical,
        "existing_target_rejected": existing_target_rejected,
        "force_identical": force_identical,
    }
    if not all((initial_identical, existing_target_rejected, force_identical)):
        raise RuntimeError(
            f"skill install PoC가 기대 계약을 만족하지 못했다: {summary}"
        )

    finding = (
        f"skill file {len(source_hashes)}개를 project scope에 byte-identical하게 설치했고, "
        "기존 target은 기본 거절, force에서는 전체 교체 후 동일성을 복원했다."
    )
    summary["finding"] = finding
    RESULT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record_experiment(summary, finding)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
