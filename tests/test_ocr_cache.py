from __future__ import annotations

from pathlib import Path

from pdfbooktree.ocr.cache import OcrCache


def test_raw_cache_key_changes_when_request_params_change(tmp_path: Path) -> None:
    cache = OcrCache(tmp_path)

    first = cache.raw_cache_key(
        input_pdf_hash="pdf",
        pdf_page=1,
        render_dpi=300,
        engine="upstage",
        request_params={"output_formats": ["text"]},
    )
    second = cache.raw_cache_key(
        input_pdf_hash="pdf",
        pdf_page=1,
        render_dpi=300,
        engine="upstage",
        request_params={"output_formats": ["text", "html"]},
    )

    assert first != second


def test_insertable_cache_key_changes_when_adapter_version_changes(tmp_path: Path) -> None:
    cache = OcrCache(tmp_path)
    raw = {"elements": [{"id": "1", "content": {"text": "Hello"}}]}

    first = cache.insertable_cache_key(raw_response=raw, adapter_version="v1")
    second = cache.insertable_cache_key(raw_response=raw, adapter_version="v2")

    assert first != second
