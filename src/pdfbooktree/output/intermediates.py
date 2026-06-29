"""디버깅용 중간 산출물을 저장한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pdfbooktree.utils.jsonio import write_json


INTERMEDIATE_FILENAMES = {
    "toc_page_candidates": "toc_page_candidates.json",
    "toc_range_review": "toc_range_review.json",
    "toc_raw": "toc_raw.json",
    "page_offset": "page_offset.json",
    "toc_aligned": "toc_aligned.json",
    "ranges": "ranges.json",
    "bookmark_plan": "bookmark_plan.json",
}


def write_intermediate(output_dir: Path, name: str, data: Any) -> Path:
    """정해진 이름의 중간 산출물을 JSON으로 저장한다."""

    if name not in INTERMEDIATE_FILENAMES:
        raise ValueError(f"알 수 없는 intermediate 이름이다: {name}")
    path = output_dir / INTERMEDIATE_FILENAMES[name]
    write_json(path, data)
    return path
