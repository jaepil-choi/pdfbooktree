"""0.1.0 공개 문서, metadata와 release workflow 계약을 검증한다."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
import tomllib
from types import ModuleType
from pathlib import Path

import pdfbooktree
import pdfbooktree.classify
import pdfbooktree.ocr
import pdfbooktree.typography
import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
PUBLIC_DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "README.en.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CONTRIBUTING.en.md",
    ROOT / "SECURITY.md",
    ROOT / "SECURITY.en.md",
    ROOT / "CHANGELOG.md",
    ROOT / "CHANGELOG.en.md",
    ROOT / "RELEASING.md",
    ROOT / "docs" / "reference.md",
)
ENGLISH_API_REFERENCE = (
    ROOT / ".agents" / "skills" / "use-pdfbooktree" / "references" / "python-api.en.md"
)


def _load_script(name: str) -> ModuleType:
    """scripts의 직접 실행 파일을 test module로 읽는다."""

    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"release_script_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"script module을 읽을 수 없다: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EXTRACT_RELEASE_NOTES = _load_script("extract_release_notes")
VALIDATE_RELEASE = _load_script("validate_release")
WRITE_CHECKSUMS = _load_script("write_checksums")


def test_package_metadata는_rc와지원_python_documentation_url을_명시한다() -> None:
    with (ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]

    assert project["version"] == "0.1.0rc1"
    assert project["requires-python"] == ">=3.12"
    assert {
        "License :: OSI Approved :: MIT License",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    } <= set(project["classifiers"])
    assert project["urls"]["Documentation"].endswith("/docs/reference.md")


def test_공개문서는한영대응과release위험을_명시한다() -> None:
    for path in PUBLIC_DOCUMENTS:
        assert path.is_file(), path

    korean = (ROOT / "README.md").read_text(encoding="utf-8")
    english = (ROOT / "README.en.md").read_text(encoding="utf-8")
    for text in (korean, english):
        assert "Alpha" in text
        assert "400" in text
        assert "0.4089" in text
        assert "PNG" in text
        assert ".env" in text
        assert "encrypted PDF" in text
        assert "infer" in text and "apply" in text
    assert korean.index("## 기존 outline 정책") < korean.index("## 라이선스")


def test_공개문서의상대Markdown_link는_존재한다() -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for document in PUBLIC_DOCUMENTS:
        for target in link_pattern.findall(document.read_text(encoding="utf-8")):
            if (
                "://" in target
                or target.startswith("#")
                or target.startswith("mailto:")
            ):
                continue
            clean_target = target.split("#", 1)[0]
            assert (document.parent / clean_target).resolve().exists(), (
                document,
                target,
            )


def test_영문Python_API_reference는모든공개_symbol을_포함한다() -> None:
    reference = ENGLISH_API_REFERENCE.read_text(encoding="utf-8")
    modules = (
        pdfbooktree,
        pdfbooktree.ocr,
        pdfbooktree.classify,
        pdfbooktree.typography,
    )
    missing = sorted(
        symbol
        for module in modules
        for symbol in module.__all__
        if f"`{symbol}`" not in reference
    )
    assert missing == []


def test_GitHub_Action은모두_commit_SHA로_고정한다() -> None:
    uses_pattern = re.compile(r"^\s*uses:\s*[^@\s]+@([^\s#]+)", re.MULTILINE)
    for workflow in sorted(WORKFLOW_DIR.glob("*.yml")):
        references = uses_pattern.findall(workflow.read_text(encoding="utf-8"))
        assert references, workflow
        assert all(re.fullmatch(r"[0-9a-f]{40}", value) for value in references)


def test_CI는6개matrix와단일_package_artifact를_집계한다() -> None:
    workflow = (WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8")
    assert workflow.count('- "3.12"') == 2
    assert workflow.count('- "3.13"') == 2
    assert workflow.count('- "3.14"') == 2
    assert "Build sdist and wheel once" in workflow
    assert "needs: package" in workflow
    assert "name: ci-green" in workflow
    assert "--cli-launch-mode" not in workflow


@pytest.mark.parametrize(
    ("tag", "channel", "version"),
    [
        ("v0.1.0rc1", "testpypi", "0.1.0rc1"),
        ("v0.1.0rc12", "testpypi", "0.1.0rc12"),
        ("v0.1.0", "pypi", "0.1.0"),
    ],
)
def test_release_tag형식(tag: str, channel: str, version: str) -> None:
    assert VALIDATE_RELEASE.validate_tag(tag, channel) == version


@pytest.mark.parametrize(
    ("tag", "channel"),
    [
        ("v0.1.0", "testpypi"),
        ("v0.1.0rc1", "pypi"),
        ("0.1.0", "pypi"),
        ("v0.1.0rc0", "testpypi"),
    ],
)
def test_release_tag잘못된형식은거부한다(tag: str, channel: str) -> None:
    with pytest.raises(ValueError):
        VALIDATE_RELEASE.validate_tag(tag, channel)


def test_release_note와checksum_helper(tmp_path: Path) -> None:
    notes = EXTRACT_RELEASE_NOTES.release_section(
        "# Changelog\n\n## 0.1.0 - 2026-07-19\n\n- release\n\n## 0.0.1\n",
        "0.1.0",
    )
    assert notes == "## 0.1.0\n\n- release\n"

    artifact = tmp_path / "artifact.whl"
    artifact.write_bytes(b"pdfbooktree")
    assert (
        WRITE_CHECKSUMS.sha256(artifact) == hashlib.sha256(b"pdfbooktree").hexdigest()
    )
