from __future__ import annotations


def test_package_import_exposes_llm_public_api() -> None:
    """기본 설치 의존성만으로 패키지 공개 API를 import할 수 있어야 한다."""

    import pdfbooktree

    assert pdfbooktree.Processor is not None
    assert pdfbooktree.ProcessingConfig is not None
    assert pdfbooktree.LlmTocExtractor is not None
    assert pdfbooktree.LlmTocRangeReviewer is not None
    assert pdfbooktree.SizeAwareStagedTocExtractor is not None
