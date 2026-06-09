"""처리 결과 report JSON을 저장한다."""

from __future__ import annotations

from pathlib import Path

from pdfbooktree.models import ProcessingResult
from pdfbooktree.utils.jsonio import write_json
from pdfbooktree.utils.paths import build_report_path


def write_processing_report(result: ProcessingResult, output_dir: Path) -> Path:
    """단일 PDF 처리 결과를 JSON report로 저장한다."""

    path = build_report_path(result.input_pdf, output_dir)
    write_json(path, result)
    return path
