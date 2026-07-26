"""bookmark plan을 PDF 파일로 export한다."""

from __future__ import annotations

from pathlib import Path

from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.pdf.outline import replace_outline_pdf_atomic, write_outline_pdf
from pdfbooktree.utils.paths import build_bookmarked_pdf_path


def plan_bookmarked_pdf_path(input_pdf: Path, output_dir: Path) -> Path:
    """입력 PDF에 대응하는 `_bookmarked.pdf` 경로를 만든다."""

    return build_bookmarked_pdf_path(input_pdf, output_dir)


def export_bookmarked_pdf(
    input_pdf: Path,
    output_dir: Path,
    plan: list[BookmarkPlanItem],
    *,
    in_place: bool = False,
) -> Path:
    """bookmark plan을 삽입한 PDF 사본을 만든다."""

    if in_place:
        return replace_outline_pdf_atomic(input_pdf, plan)
    output_pdf = plan_bookmarked_pdf_path(input_pdf, output_dir)
    return write_outline_pdf(input_pdf, output_pdf, plan)
