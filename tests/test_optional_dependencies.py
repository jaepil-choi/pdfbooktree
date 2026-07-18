"""선택 OCR dependency가 core 설치 계약을 침범하지 않는지 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.ocr import (
    OcrOverlayBatchConfig,
    OcrOverlayBatchRunner,
    OcrOverlayBuilder,
    OcrOverlayConfig,
)
from pdfbooktree.optional_dependencies import (
    OptionalDependencyError,
    require_optional_dependencies,
)


def _hide_all_optional_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pdfbooktree.optional_dependencies.find_spec",
        lambda _module: None,
    )


def test_optional_dependency_error는_extra와_설치_명령을_보존한다() -> None:
    with pytest.raises(OptionalDependencyError) as captured:
        require_optional_dependencies("ocr", {"httpx": "missing_httpx"})

    error = captured.value
    assert error.extra == "ocr"
    assert error.missing_packages == ("httpx",)
    assert error.install_command == 'python -m pip install "pdfbooktree[ocr]"'


def test_single_ocr는_dependency_확인_전에_output을_만들지_않는다(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _hide_all_optional_modules(monkeypatch)
    output_pdf = tmp_path / "output.pdf"
    output_dir = tmp_path / "artifacts"
    builder = OcrOverlayBuilder(
        OcrOverlayConfig(
            input_pdf=tmp_path / "missing.pdf",
            output_pdf=output_pdf,
            output_dir=output_dir,
        )
    )

    with pytest.raises(OptionalDependencyError):
        builder.run()

    assert not output_pdf.exists()
    assert not output_dir.exists()


def test_ocr_batch_dry_run은_extra_없이_report를_만든다(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _hide_all_optional_modules(monkeypatch)
    input_dir = tmp_path / "books"
    output_dir = tmp_path / "runs"
    input_dir.mkdir()

    result = OcrOverlayBatchRunner(
        OcrOverlayBatchConfig(
            input_dir=input_dir,
            output_dir=output_dir,
            dry_run=True,
        )
    ).run()

    assert result.total_pdf_count == 0
    assert result.summary_path.is_file()


def test_live_ocr_batch는_extra_없으면_output_전에_실패한다(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _hide_all_optional_modules(monkeypatch)
    input_dir = tmp_path / "books"
    output_dir = tmp_path / "runs"
    input_dir.mkdir()

    with pytest.raises(OptionalDependencyError):
        OcrOverlayBatchRunner(
            OcrOverlayBatchConfig(
                input_dir=input_dir,
                output_dir=output_dir,
                dry_run=False,
            )
        ).run()

    assert not output_dir.exists()


def test_ocr_cli_json_error는_install_hint와_stable_code를_반환한다(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _hide_all_optional_modules(monkeypatch)
    output_pdf = tmp_path / "output.pdf"

    result = CliRunner().invoke(
        app,
        [
            "ocr-overlay",
            str(tmp_path / "missing.pdf"),
            "--output",
            str(output_pdf),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["error"]["code"] == "missing_optional_dependency"
    assert "pdfbooktree[ocr]" in result.stderr
    assert not output_pdf.exists()
