"""versioned TOML config와 override의 재현 계약을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdfbooktree.config import CONFIG_SCHEMA_VERSION, ConfigError
from pdfbooktree.config_io import (
    config_field_specs,
    config_schema,
    parse_set_override,
    render_config_toml,
    resolve_processing_config,
    write_config_template,
)


def test_partial_toml은_defaults와_병합된다(tmp_path: Path) -> None:
    path = tmp_path / "book.toml"
    path.write_text(
        "\n".join(
            [
                f"schema_version = {CONFIG_SCHEMA_VERSION}",
                "",
                "[typography]",
                'heading_candidate_mode = "position"',
                "body_font_text_coverage = 0.9",
            ]
        ),
        encoding="utf-8",
    )

    resolved = resolve_processing_config(path)

    assert resolved.config.typography.heading_candidate_mode == "position"
    assert resolved.config.typography.body_font_text_coverage == 0.9
    assert resolved.config.typography.position_min_repeated_pages == 5
    assert resolved.sources[1]["path"] == str(path)


def test_config_precedence는_set_override가_가장_높다(tmp_path: Path) -> None:
    path = tmp_path / "book.toml"
    path.write_text(
        "\n".join(
            [
                f"schema_version = {CONFIG_SCHEMA_VERSION}",
                "",
                "[typography]",
                "position_min_repeated_pages = 3",
            ]
        ),
        encoding="utf-8",
    )

    resolved = resolve_processing_config(
        path,
        cli_overrides={"typography.position_min_repeated_pages": 5},
        set_overrides=["typography.position_min_repeated_pages=8"],
    )

    assert resolved.config.typography.position_min_repeated_pages == 8
    assert [source["kind"] for source in resolved.sources] == [
        "defaults",
        "file",
        "cli_options",
        "set_overrides",
    ]


def test_markdown_override는_optional_section을_활성화한다() -> None:
    resolved = resolve_processing_config(
        set_overrides=[
            "markdown.max_words=1200",
            "markdown.max_words_coverage=0.9",
        ]
    )

    assert resolved.config.markdown_split is not None
    assert resolved.config.markdown_split.max_words == 1200
    assert resolved.data["markdown"]["max_words_coverage"] == 0.9


def test_markdown_content_mode는_processing_override로_설정한다() -> None:
    resolved = resolve_processing_config(
        set_overrides=["processing.markdown_content_mode=inclusive"]
    )

    assert resolved.config.markdown_content_mode == "inclusive"
    assert resolved.data["processing"]["markdown_content_mode"] == "inclusive"


def test_unknown_key와_schema_version을_거절한다(tmp_path: Path) -> None:
    unknown = tmp_path / "unknown.toml"
    unknown.write_text(
        f"schema_version = {CONFIG_SCHEMA_VERSION}\n[typography]\npositon_min = 3\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="알 수 없는 config key"):
        resolve_processing_config(unknown)

    wrong_version = tmp_path / "wrong.toml"
    wrong_version.write_text("schema_version = 99\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="schema_version"):
        resolve_processing_config(wrong_version)


def test_set_override는_typed_value와_bare_string을_해석한다() -> None:
    assert parse_set_override("processing.write_artifacts=false") == (
        "processing.write_artifacts",
        False,
    )
    assert parse_set_override("typography.body_font_text_coverage=0.98") == (
        "typography.body_font_text_coverage",
        0.98,
    )
    assert parse_set_override("typography.heading_candidate_mode=font") == (
        "typography.heading_candidate_mode",
        "font",
    )


def test_resolved_hash는_같은_config에서_결정적이다() -> None:
    first = resolve_processing_config(
        set_overrides=["typography.position_fallback_tolerance=1.5"]
    )
    second = resolve_processing_config(
        set_overrides=["typography.position_fallback_tolerance=1.5"]
    )

    assert first.config_hash == second.config_hash
    assert len(first.config_hash) == 64


def test_schema와_specs는_전체_public_field를_설명한다() -> None:
    schema = config_schema()
    specs = config_field_specs()

    assert schema["properties"]["schema_version"]["const"] == CONFIG_SCHEMA_VERSION
    assert "typography.position_fallback_tolerance" in specs
    assert specs["typography.position_fallback_tolerance"]["type"] == "number"
    assert specs["processing.ocr_policy"]["enum"] == ["never"]
    assert "ocr-overlay" in specs["processing.ocr_policy"]["description"]
    assert specs["processing.markdown_content_mode"]["enum"] == [
        "direct",
        "inclusive",
    ]


def test_config_template은_기존_파일을_보호하고_다시_읽을_수_있다(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"

    write_config_template(path)
    resolved = resolve_processing_config(path)

    assert resolved.config.typography.heading_candidate_mode == "font"
    assert "# [markdown]" in path.read_text(encoding="utf-8")
    with pytest.raises(ConfigError, match="이미 있다"):
        write_config_template(path)


def test_rendered_toml과_json_data는_agent가_parse할_수_있다() -> None:
    resolved = resolve_processing_config()
    rendered = render_config_toml(resolved.config)

    assert f"schema_version = {CONFIG_SCHEMA_VERSION}" in rendered
    assert "[typography]" in rendered
    assert json.loads(json.dumps(resolved.data))["processing"]["ocr_policy"] == "never"


@pytest.mark.parametrize("ocr_policy", ["auto", "always"])
def test_resolve_processing_config는_지원하지_않는_ocr_policy를_거절한다(
    ocr_policy: str,
) -> None:
    with pytest.raises(ConfigError, match="ocr-overlay"):
        resolve_processing_config(set_overrides=[f"processing.ocr_policy={ocr_policy}"])
