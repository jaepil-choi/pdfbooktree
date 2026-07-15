"""agent가 config CLI를 발견하고 machine-readable하게 쓸 수 있는지 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.config import CONFIG_SCHEMA_VERSION


def test_config_defaults와_schema는_json으로_parse된다() -> None:
    runner = CliRunner()

    defaults = runner.invoke(app, ["config", "defaults", "--format", "json"])
    schema = runner.invoke(app, ["config", "schema", "--format", "json"])

    assert defaults.exit_code == 0
    assert schema.exit_code == 0
    default_payload = json.loads(defaults.stdout)
    schema_payload = json.loads(schema.stdout)
    assert default_payload["schema_version"] == CONFIG_SCHEMA_VERSION
    assert default_payload["typography"]["heading_candidate_mode"] == "font"
    assert schema_payload["properties"]["schema_version"]["const"] == 1


def test_config_init_validate_explain_workflow(tmp_path: Path) -> None:
    runner = CliRunner()
    path = tmp_path / "book.toml"

    created = runner.invoke(app, ["config", "init", str(path)])
    validated = runner.invoke(
        app,
        [
            "config",
            "validate",
            str(path),
            "--set",
            "typography.position_fallback_tolerance=1.5",
            "--format",
            "json",
        ],
    )
    explained = runner.invoke(
        app,
        [
            "config",
            "explain",
            "typography.position_fallback_tolerance",
            "--format",
            "json",
        ],
    )

    assert created.exit_code == 0
    assert path.is_file()
    assert validated.exit_code == 0
    payload = json.loads(validated.stdout)
    assert payload["status"] == "valid"
    assert (
        payload["resolved_config"]["typography"]["position_fallback_tolerance"] == 1.5
    )
    assert len(payload["config_hash"]) == 64
    assert explained.exit_code == 0
    assert json.loads(explained.stdout)["type"] == "number"


def test_config_init은_기존_파일을_기본적으로_보호한다(tmp_path: Path) -> None:
    runner = CliRunner()
    path = tmp_path / "book.toml"

    first = runner.invoke(app, ["config", "init", str(path)])
    second = runner.invoke(app, ["config", "init", str(path)])

    assert first.exit_code == 0
    assert second.exit_code == 2
    assert "이미 있다" in second.stderr


def test_config_validate는_잘못된_key를_nonzero로_거절한다(
    tmp_path: Path,
) -> None:
    path = tmp_path / "book.toml"
    path.write_text(
        f"schema_version = {CONFIG_SCHEMA_VERSION}\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "config",
            "validate",
            str(path),
            "--set",
            "typography.unknown=1",
        ],
    )

    assert result.exit_code == 2
    assert "알 수 없는 config key" in result.stderr


def test_config_help에서_하위_command를_발견할_수_있다() -> None:
    result = CliRunner().invoke(app, ["config", "--help"])

    assert result.exit_code == 0
    for command in ("defaults", "schema", "init", "explain", "validate"):
        assert command in result.stdout
