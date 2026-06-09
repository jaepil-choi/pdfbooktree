"""bookmark가 삽입된 PDF 파일 저장 인터페이스다."""

from __future__ import annotations

from pathlib import Path

from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.utils.paths import build_bookmarked_pdf_path


def plan_output_pdf_path(input_pdf: Path, output_dir: Path) -> Path:
    """입력 PDF에 대응하는 `_bookmarked.pdf` 경로를 만든다."""

    return build_bookmarked_pdf_path(input_pdf, output_dir)


def write_bookmarked_pdf(
    input_pdf: Path,
    output_dir: Path,
    bookmark_plan: list[BookmarkPlanItem],
) -> Path:
    """실제 bookmark 삽입은 v0.1 다음 구현에서 채운다."""

    _ = bookmark_plan
    return plan_output_pdf_path(input_pdf, output_dir)
