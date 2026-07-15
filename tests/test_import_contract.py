"""공개 import 계약을 검증한다."""

from __future__ import annotations

import pdfbooktree


def test_public_import_contract() -> None:
    assert pdfbooktree.Processor is not None
    assert pdfbooktree.BatchProcessor is not None
    assert pdfbooktree.ProcessingConfig is not None
    assert pdfbooktree.TypographyConfig is not None
    assert pdfbooktree.resolve_processing_config is not None
    assert pdfbooktree.create_run_context is not None
    assert pdfbooktree.RunManifest is not None
    assert pdfbooktree.analyze_pdf is not None
    assert pdfbooktree.infer_bookmarks is not None
    assert pdfbooktree.apply_plan is not None
    assert pdfbooktree.PdfAnalysis is not None
    assert pdfbooktree.BookmarkInferenceResult is not None
    assert pdfbooktree.ApplyResult is not None
