"""Markdown tree export 인터페이스다."""

from __future__ import annotations

from pathlib import Path

from pdfbooktree.models import ContentRange
from pdfbooktree.utils.paths import build_markdown_dir_path


def plan_markdown_dir_path(input_pdf: Path, output_dir: Path) -> Path:
    """입력 PDF에 대응하는 Markdown output 디렉터리를 만든다."""

    return build_markdown_dir_path(input_pdf, output_dir)


def export_markdown_tree(
    input_pdf: Path,
    output_dir: Path,
    ranges: list[ContentRange],
) -> Path:
    """본문 Markdown export는 v0.1 다음 구현에서 채운다."""

    _ = ranges
    return plan_markdown_dir_path(input_pdf, output_dir)
