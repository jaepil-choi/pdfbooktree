"""입력 파일과 JSON 호환 값의 안정 hash를 계산한다."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pdfbooktree.utils.jsonio import to_jsonable


def file_sha256(path: Path) -> str:
    """파일 전체의 SHA-256 hash를 계산한다."""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json_hash(data: Any) -> str:
    """JSON 호환 값을 canonical serialization한 SHA-256 hash를 반환한다."""

    payload = json.dumps(
        to_jsonable(data),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
