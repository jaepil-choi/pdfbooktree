"""JSON 중간 산출물을 파일로 저장한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pdfbooktree.serialization import to_json, to_jsonable as to_jsonable


def write_json(path: Path, data: Any) -> None:
    """부모 디렉터리를 만든 뒤 JSON 파일을 저장한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        to_json(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
