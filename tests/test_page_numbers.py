from __future__ import annotations

import pytest

from pdfbooktree.utils.page_numbers import (
    ensure_pdf_page,
    from_pymupdf_index,
    to_pymupdf_index,
)


def test_page_number_conversion_uses_one_based_pdf_pages() -> None:
    assert ensure_pdf_page(1) == 1
    assert to_pymupdf_index(1) == 0
    assert from_pymupdf_index(0) == 1


def test_page_number_conversion_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        to_pymupdf_index(0)
    with pytest.raises(ValueError):
        from_pymupdf_index(-1)
