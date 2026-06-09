"""출력 파일과 디렉터리 경로를 만든다."""

from __future__ import annotations

import re
from pathlib import Path


def safe_filename(value: str, max_length: int = 80) -> str:
    """파일명으로 안전한 ASCII 중심 문자열을 만든다."""

    normalized = re.sub(r"[^\w가-힣.-]+", "_", value.strip(), flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized).strip("_.")
    if not normalized:
        normalized = "untitled"
    return normalized[:max_length]


def build_bookmarked_pdf_path(input_pdf: Path, output_dir: Path) -> Path:
    """`_bookmarked.pdf` 출력 경로를 만든다."""

    return output_dir / f"{input_pdf.stem}_bookmarked.pdf"


def build_markdown_dir_path(input_pdf: Path, output_dir: Path) -> Path:
    """Markdown tree 출력 디렉터리 경로를 만든다."""

    return output_dir / f"{input_pdf.stem}_markdown"


def build_report_path(input_pdf: Path, output_dir: Path) -> Path:
    """처리 report JSON 경로를 만든다."""

    return output_dir / f"{input_pdf.stem}_report.json"
