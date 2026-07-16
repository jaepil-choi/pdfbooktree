"""versioned TOML config를 public dataclass로 해석하고 설명한다."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from types import UnionType
from typing import Any, Literal, get_args, get_origin, get_type_hints

from pdfbooktree.config import (
    CONFIG_SCHEMA_VERSION,
    ConfigError,
    MarkdownSplitConfig,
    OutlineQualityConfig,
    ProcessingConfig,
    TypographyConfig,
)
from pdfbooktree.utils.hashing import stable_json_hash
from pdfbooktree.utils.jsonio import to_jsonable


_TOP_LEVEL_KEYS = {
    "schema_version",
    "processing",
    "typography",
    "outline_quality",
    "markdown",
}
_PROCESSING_FIELDS = ("skip_existing_bookmarks", "write_artifacts", "ocr_policy")
_ALWAYS_PRESENT_SECTIONS = ("processing", "typography", "outline_quality")
_SECTION_CLASSES = {
    "processing": ProcessingConfig,
    "typography": TypographyConfig,
    "outline_quality": OutlineQualityConfig,
    "markdown": MarkdownSplitConfig,
}


@dataclass(frozen=True)
class ResolvedConfig:
    """실행에 사용할 최종 config와 재현 정보를 함께 보관한다."""

    config: ProcessingConfig
    data: dict[str, Any]
    config_hash: str
    sources: tuple[dict[str, Any], ...]
    source_path: Path | None = None


def resolve_processing_config(
    config_path: Path | str | None = None,
    *,
    cli_overrides: dict[str, object] | None = None,
    set_overrides: list[str] | tuple[str, ...] = (),
) -> ResolvedConfig:
    """defaults, TOML, 명시적 CLI option, --set 순서로 config를 합친다."""

    data = processing_config_to_data(ProcessingConfig())
    sources: list[dict[str, Any]] = [{"kind": "defaults"}]
    source_path = Path(config_path) if config_path is not None else None
    if source_path is not None:
        file_data = _read_toml(source_path)
        _merge_file_data(data, file_data)
        sources.append(
            {
                "kind": "file",
                "path": str(source_path),
                "sha256": stable_json_hash(file_data),
            }
        )
    if cli_overrides:
        for key, value in cli_overrides.items():
            _set_dotted_value(data, key, value)
        sources.append({"kind": "cli_options", "values": to_jsonable(cli_overrides)})
    if set_overrides:
        parsed: dict[str, object] = {}
        for expression in set_overrides:
            key, value = parse_set_override(expression)
            _set_dotted_value(data, key, value)
            parsed[key] = value
        sources.append({"kind": "set_overrides", "values": to_jsonable(parsed)})

    config = processing_config_from_data(data)
    resolved_data = processing_config_to_data(config)
    return ResolvedConfig(
        config=config,
        data=resolved_data,
        config_hash=stable_json_hash(resolved_data),
        sources=tuple(sources),
        source_path=source_path,
    )


def processing_config_to_data(config: ProcessingConfig) -> dict[str, Any]:
    """ProcessingConfig를 외부 TOML/JSON section 구조로 바꾼다."""

    processing = {name: getattr(config, name) for name in _PROCESSING_FIELDS}
    data: dict[str, Any] = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "processing": processing,
        "typography": to_jsonable(config.typography),
        "outline_quality": to_jsonable(config.outline_quality),
    }
    if config.markdown_split is not None:
        data["markdown"] = to_jsonable(config.markdown_split)
    return data


def processing_config_from_data(data: dict[str, Any]) -> ProcessingConfig:
    """검증된 section dict를 public config dataclass로 만든다."""

    _validate_top_level(data)
    processing = _require_section(data, "processing")
    typography = _require_section(data, "typography")
    outline_quality = _require_section(data, "outline_quality")
    markdown = data.get("markdown")
    if markdown is not None and not isinstance(markdown, dict):
        raise ConfigError("markdown section은 TOML table이어야 한다.")

    _reject_unknown_keys("processing", processing, set(_PROCESSING_FIELDS))
    _reject_unknown_keys(
        "typography",
        typography,
        {item.name for item in fields(TypographyConfig)},
    )
    _reject_unknown_keys(
        "outline_quality",
        outline_quality,
        {item.name for item in fields(OutlineQualityConfig)},
    )
    if isinstance(markdown, dict):
        _reject_unknown_keys(
            "markdown",
            markdown,
            {item.name for item in fields(MarkdownSplitConfig)},
        )
    try:
        typography_config = TypographyConfig(**typography)
        outline_quality_config = OutlineQualityConfig(**outline_quality)
        markdown_config = (
            MarkdownSplitConfig(**markdown) if isinstance(markdown, dict) else None
        )
        return ProcessingConfig(
            **processing,
            typography=typography_config,
            markdown_split=markdown_config,
            outline_quality=outline_quality_config,
        )
    except TypeError as error:
        raise ConfigError(f"config field type 또는 이름이 잘못됐다: {error}") from error


def parse_set_override(expression: str) -> tuple[str, object]:
    """CLI의 dotted.key=value 문자열을 typed 값으로 바꾼다."""

    if "=" not in expression:
        raise ConfigError("--set은 dotted.key=value 형식이어야 한다.")
    key, raw = expression.split("=", 1)
    key = key.strip()
    raw = raw.strip()
    if not key:
        raise ConfigError("--set key가 비어 있다.")
    if key not in config_field_specs():
        raise ConfigError(_unknown_key_message(key, set(config_field_specs())))
    if not raw:
        raise ConfigError(f"--set 값이 비어 있다: key={key}")
    try:
        value = tomllib.loads(f"value = {raw}")["value"]
    except tomllib.TOMLDecodeError:
        value = raw
    return key, value


def config_schema() -> dict[str, Any]:
    """현재 public config의 JSON Schema를 반환한다."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://pdfbooktree.local/config/v{CONFIG_SCHEMA_VERSION}.schema.json",
        "title": "pdfbooktree processing config",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version"],
        "properties": {
            "schema_version": {
                "type": "integer",
                "const": CONFIG_SCHEMA_VERSION,
            },
            "processing": _section_schema(
                ProcessingConfig, include=set(_PROCESSING_FIELDS)
            ),
            "typography": _section_schema(TypographyConfig),
            "outline_quality": _section_schema(OutlineQualityConfig),
            "markdown": _section_schema(MarkdownSplitConfig),
        },
    }


def config_field_specs() -> dict[str, dict[str, Any]]:
    """explain과 --set validation에 쓸 dotted field spec을 반환한다."""

    result: dict[str, dict[str, Any]] = {}
    for section, cls in _SECTION_CLASSES.items():
        include = set(_PROCESSING_FIELDS) if section == "processing" else None
        hints = get_type_hints(cls)
        instance = cls()
        for item in fields(cls):
            if include is not None and item.name not in include:
                continue
            result[f"{section}.{item.name}"] = _field_schema(
                item,
                hints[item.name],
                getattr(instance, item.name),
            )
    return result


def render_config_toml(
    config: ProcessingConfig,
    *,
    include_comments: bool = False,
    include_disabled_markdown: bool = False,
) -> str:
    """ProcessingConfig를 deterministic TOML text로 렌더링한다."""

    data = processing_config_to_data(config)
    specs = config_field_specs()
    lines = [f"schema_version = {CONFIG_SCHEMA_VERSION}", ""]
    for section in _ALWAYS_PRESENT_SECTIONS:
        lines.append(f"[{section}]")
        for key, value in data[section].items():
            dotted = f"{section}.{key}"
            if include_comments:
                lines.append(f"# {specs[dotted]['description']}")
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")

    if "markdown" in data:
        lines.append("[markdown]")
        for key, value in data["markdown"].items():
            dotted = f"markdown.{key}"
            if include_comments:
                lines.append(f"# {specs[dotted]['description']}")
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    elif include_disabled_markdown:
        lines.append("# Markdown split은 기본적으로 비활성화되어 있다.")
        lines.append("# 사용하려면 아래 table과 field의 주석을 제거한다.")
        lines.append("# [markdown]")
        defaults = MarkdownSplitConfig()
        for item in fields(MarkdownSplitConfig):
            dotted = f"markdown.{item.name}"
            lines.append(f"# {specs[dotted]['description']}")
            lines.append(f"# {item.name} = {_toml_value(getattr(defaults, item.name))}")
        lines.append("")
    return "\n".join(lines)


def write_config_template(path: Path | str, *, force: bool = False) -> Path:
    """주석이 포함된 기본 TOML을 새 파일로 저장한다."""

    target = Path(path)
    if target.exists() and not force:
        raise ConfigError(f"config 파일이 이미 있다: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_config_toml(
            ProcessingConfig(),
            include_comments=True,
            include_disabled_markdown=True,
        ),
        encoding="utf-8",
    )
    return target


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"config 파일이 없다: {path}")
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"TOML을 읽지 못했다: path={path}, reason={error}") from error
    if not isinstance(data, dict):
        raise ConfigError("config root는 TOML table이어야 한다.")
    _validate_top_level(data)
    return data


def _validate_top_level(data: dict[str, Any]) -> None:
    unknown = set(data) - _TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(_unknown_key_message(sorted(unknown)[0], _TOP_LEVEL_KEYS))
    version = data.get("schema_version")
    if version != CONFIG_SCHEMA_VERSION:
        raise ConfigError(
            "지원하지 않는 config schema_version이다: "
            f"expected={CONFIG_SCHEMA_VERSION}, actual={version!r}"
        )
    for section in _ALWAYS_PRESENT_SECTIONS:
        if section in data and not isinstance(data[section], dict):
            raise ConfigError(f"{section} section은 TOML table이어야 한다.")
    if "markdown" in data and not isinstance(data["markdown"], dict):
        raise ConfigError("markdown section은 TOML table이어야 한다.")


def _merge_file_data(target: dict[str, Any], source: dict[str, Any]) -> None:
    for section in _ALWAYS_PRESENT_SECTIONS:
        values = source.get(section, {})
        if isinstance(values, dict):
            allowed = (
                set(_PROCESSING_FIELDS)
                if section == "processing"
                else {item.name for item in fields(_SECTION_CLASSES[section])}
            )
            _reject_unknown_keys(section, values, allowed)
            target[section].update(values)
    if "markdown" in source:
        values = source["markdown"]
        if not isinstance(values, dict):
            raise ConfigError("markdown section은 TOML table이어야 한다.")
        _reject_unknown_keys(
            "markdown",
            values,
            {item.name for item in fields(MarkdownSplitConfig)},
        )
        target["markdown"] = to_jsonable(MarkdownSplitConfig())
        target["markdown"].update(values)


def _set_dotted_value(data: dict[str, Any], key: str, value: object) -> None:
    if key not in config_field_specs():
        raise ConfigError(_unknown_key_message(key, set(config_field_specs())))
    section, field_name = key.split(".", 1)
    if section == "markdown" and "markdown" not in data:
        data["markdown"] = to_jsonable(MarkdownSplitConfig())
    section_data = data.get(section)
    if not isinstance(section_data, dict):
        raise ConfigError(f"{section} section을 갱신할 수 없다.")
    section_data[field_name] = value


def _require_section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{name} section은 object여야 한다.")
    return value


def _reject_unknown_keys(
    section: str, values: dict[str, Any], allowed: set[str]
) -> None:
    unknown = set(values) - allowed
    if unknown:
        key = sorted(unknown)[0]
        dotted_allowed = {f"{section}.{name}" for name in allowed}
        raise ConfigError(_unknown_key_message(f"{section}.{key}", dotted_allowed))


def _unknown_key_message(key: str, allowed: set[str]) -> str:
    import difflib

    suggestions = difflib.get_close_matches(key, sorted(allowed), n=3)
    suffix = f", candidates={suggestions}" if suggestions else ""
    return f"알 수 없는 config key다: {key}{suffix}"


def _section_schema(
    cls: type[Any], *, include: set[str] | None = None
) -> dict[str, Any]:
    hints = get_type_hints(cls)
    instance = cls()
    properties = {
        item.name: _field_schema(item, hints[item.name], getattr(instance, item.name))
        for item in fields(cls)
        if include is None or item.name in include
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }


def _field_schema(item: Any, annotation: Any, default: object) -> dict[str, Any]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        values = list(args)
        schema_type = _json_type(values[0])
        result: dict[str, Any] = {"type": schema_type, "enum": values}
    elif origin in {UnionType} and type(None) in args:
        non_null = next(value for value in args if value is not type(None))
        result = {"type": [_json_type_from_annotation(non_null), "null"]}
    else:
        result = {"type": _json_type_from_annotation(annotation)}
    result["description"] = item.metadata.get("description", "")
    result["default"] = to_jsonable(default)
    minimum = item.metadata.get("minimum")
    maximum = item.metadata.get("maximum")
    if minimum is not None:
        key = (
            "exclusiveMinimum" if item.metadata.get("exclusive_minimum") else "minimum"
        )
        result[key] = minimum
    if maximum is not None:
        result["maximum"] = maximum
    return result


def _json_type_from_annotation(annotation: Any) -> str:
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is str:
        return "string"
    return "object"


def _json_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return str(value)
