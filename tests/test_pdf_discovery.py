"""공통 PDF 탐색 계약을 검증한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdfbooktree.utils.pdf_discovery import discover_pdfs


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n")


def test_discovery_is_case_insensitive_filtered_and_deterministic(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "books"
    output_dir = input_dir / "runs"
    _touch(input_dir / "ROOT.PDF")
    _touch(input_dir / "nested" / "keep.pdf")
    _touch(input_dir / "nested" / "skip.PdF")
    _touch(output_dir / "generated.pdf")

    result = discover_pdfs(
        input_dir,
        output_dir,
        recursive=True,
        include_globs=("*.pdf", "nested/*.pdf"),
        exclude_globs=("nested/skip.pdf",),
    )

    assert [path.relative_to(input_dir).as_posix() for path in result.paths] == [
        "nested/keep.pdf",
        "ROOT.PDF",
    ]
    assert result.excluded_output_subtree == output_dir.resolve()


def test_discovery_shallow_does_not_include_nested_pdf(tmp_path: Path) -> None:
    input_dir = tmp_path / "books"
    _touch(input_dir / "root.pdf")
    _touch(input_dir / "nested" / "book.pdf")

    result = discover_pdfs(input_dir, tmp_path / "out")

    assert [path.name for path in result.paths] == ["root.pdf"]


def test_discovery_rejects_equal_input_and_output(tmp_path: Path) -> None:
    input_dir = tmp_path / "books"
    input_dir.mkdir()

    with pytest.raises(ValueError, match="입력과 출력 디렉터리는 달라야"):
        discover_pdfs(input_dir, input_dir)
