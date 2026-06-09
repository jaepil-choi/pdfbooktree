"""dataclass 기반 중간 산출물을 JSON으로 저장한다."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Path와 dataclass를 JSON 직렬화 가능한 값으로 바꾼다."""

    if is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    return value


def write_json(path: Path, data: Any) -> None:
    """부모 디렉터리를 만든 뒤 JSON 파일을 저장한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
