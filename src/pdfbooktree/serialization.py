"""공개 결과 객체를 JSON 계약으로 변환한다."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import PurePath
from typing import Any, TypeAlias


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def to_jsonable(value: Any) -> JsonValue:
    """공개 결과와 중첩 값을 JSON 호환 값으로 변환한다.

    dataclass는 field 이름을 key로 갖는 object, ``Path``는 문자열, tuple은
    array로 변환한다. 지원하지 않는 객체는 조용히 문자열화하지 않고
    ``TypeError``를 발생시킨다.
    """

    if is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(asdict(value))
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NaN과 Infinity는 JSON 결과 계약에서 지원하지 않는다.")
        return value
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    raise TypeError(f"JSON으로 변환할 수 없는 타입이다: {type(value).__name__}")


def to_json(
    value: Any,
    *,
    ensure_ascii: bool = False,
    indent: int | None = None,
) -> str:
    """공개 결과를 표준 JSON 문자열로 직렬화한다."""

    return json.dumps(
        to_jsonable(value),
        ensure_ascii=ensure_ascii,
        indent=indent,
        allow_nan=False,
    )
