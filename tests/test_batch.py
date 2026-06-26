"""디렉터리 단위 batch 처리가 단일 PDF 실패에 회복력이 있는지 검증한다.

offset이 clean하지 않은 PDF가 섞여 있어도 batch 전체가 중단되지 않고, 그 PDF만
failed로 기록하고 다음 PDF로 넘어가야 한다. data/ 실제 PDF 대신 fitz 합성 PDF를
사용한다.
"""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.batch import BatchProcessor

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
FOOTER_Y = 810.0  # 하위 10% band 안


def _make_pdf(path: Path, page_specs: list[list[tuple[float, float, str]]]) -> None:
    """page_specs대로 텍스트를 배치한 bookmark 없는 합성 PDF를 만든다."""

    document = fitz.open()
    try:
        for spec in page_specs:
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            for x, y, text in spec:
                page.insert_text((x, y), text, fontsize=12)
        document.save(str(path))
    finally:
        document.close()


def test_batch_continues_when_one_pdf_offset_fails(tmp_path: Path) -> None:
    """offset fast-fail PDF가 있어도 batch는 멈추지 않고 failed로 기록 후 진행한다."""

    input_dir = tmp_path / "in"
    input_dir.mkdir()

    # a: band에 숫자가 전혀 없어 offset fast-fail.
    _make_pdf(
        input_dir / "a_no_numbers.pdf",
        [[(72.0, 400.0, "본문 텍스트 줄입니다")] for _ in range(6)],
    )
    # b: footer page number가 있어 offset(=0)이 clean하게 잡힌다.
    _make_pdf(
        input_dir / "b_with_numbers.pdf",
        [[(300.0, FOOTER_Y, str(pdf_page))] for pdf_page in range(1, 9)],
    )

    output_dir = tmp_path / "out"
    batch_result = BatchProcessor(input_dir, output_dir).run()

    assert batch_result.total_pdf_count == 2
    assert batch_result.failed_count == 2
    assert len(batch_result.results) == 2

    by_name = {result.input_pdf.name: result for result in batch_result.results}

    failed = by_name["a_no_numbers.pdf"]
    assert failed.status == "failed"
    assert failed.warnings[0].startswith("offset 추정 실패")
    assert failed.report_path is not None
    assert failed.report_path.exists()

    processed_offset = by_name["b_with_numbers.pdf"]
    assert processed_offset.status == "failed"
    # offset이 성립했으므로 confidence가 채워진다.
    assert processed_offset.confidence_summary.offset is not None
    assert processed_offset.confidence_summary.offset > 0.0
