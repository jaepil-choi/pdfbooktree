"""중간 산출물 저장 helper다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pdfbooktree.utils.jsonio import to_jsonable, write_json


def write_artifact(output_dir: Path, name: str, data: Any) -> Path:
    """JSON artifact를 저장하고 경로를 반환한다."""

    path = output_dir / f"{name}.json"
    write_json(path, data)
    return path


def write_jsonl_artifact(output_dir: Path, name: str, rows: list[Any]) -> Path:
    """JSONL artifact를 저장하고 경로를 반환한다."""

    path = output_dir / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(to_jsonable(row), ensure_ascii=False) + "\n")
    return path
