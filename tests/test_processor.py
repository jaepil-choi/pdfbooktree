"""단일 PDF 처리 파이프라인을 검증한다."""

from __future__ import annotations

from pathlib import Path

from pdfbooktree.processor import Processor


def test_processor_skips_any_pdf_with_existing_bookmark(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """runtime Processor는 bookmark가 있으면 PDF 본문을 열기 전에 제외한다."""

    def fake_extract_existing_bookmarks(_: Path) -> list[dict[str, object]]:
        return [
            {
                "order": 1,
                "level": 1,
                "title": "1",
                "pdf_page": 1,
            }
        ]

    monkeypatch.setattr(
        "pdfbooktree.processor.extract_existing_bookmarks",
        fake_extract_existing_bookmarks,
    )

    result = Processor(tmp_path / "bookmarked.pdf", tmp_path / "out").run()

    assert result.status == "skipped"
    assert result.output_pdf is None
    assert result.output_markdown_dir is None
    assert result.toc_pages == []
    assert result.warnings == [
        "기존 bookmark 1개가 있어서 runtime 자동 처리를 건너뛰었다."
    ]
    assert result.report_path is not None
    assert result.report_path.exists()
