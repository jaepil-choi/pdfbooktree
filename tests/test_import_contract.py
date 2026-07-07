"""공개 import 계약을 검증한다."""

from __future__ import annotations

import pdfbooktree


def test_public_import_contract() -> None:
    assert pdfbooktree.Processor is not None
    assert pdfbooktree.BatchProcessor is not None
    assert pdfbooktree.ProcessingConfig is not None
    assert pdfbooktree.TypographyConfig is not None
