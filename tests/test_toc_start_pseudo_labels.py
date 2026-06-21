from __future__ import annotations

from pathlib import Path
from types import ModuleType
import importlib.util

import fitz


def write_pdf(
    path: Path,
    page_texts: list[str],
    toc: list[list[object]] | None = None,
) -> None:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    if toc is not None:
        document.set_toc(toc)
    document.save(path)
    document.close()


def load_script_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "make-toc-start-pseudo-labels.py"
    )
    spec = importlib.util.spec_from_file_location(
        "make_toc_start_pseudo_labels",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_make_toc_start_pseudo_labels_labels_only_bookmarked_pdfs(
    tmp_path: Path,
) -> None:
    module = load_script_module()
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    bookmarked_pdf = tmp_path / "bookmarked.pdf"
    no_bookmark_pdf = nested_dir / "plain.pdf"

    write_pdf(
        bookmarked_pdf,
        [
            "Preface",
            "Contents\nChapter 1 Introduction ........ 3\n1.1 Motivation ........ 7",
            "1.2 Background ........ 12\nChapter 2 Probability ........ 25",
            "Chapter 1 Introduction\nBody",
            "1.1 Motivation\nBody",
            "1.2 Background\nBody",
            "Chapter 2 Probability\nBody",
        ],
        toc=[
            [1, "Chapter 1 Introduction", 4],
            [2, "1.1 Motivation", 5],
            [2, "1.2 Background", 6],
            [1, "Chapter 2 Probability", 7],
        ],
    )
    write_pdf(no_bookmark_pdf, ["Contents\nNo bookmark entry ........ 1", "Body"])

    diagnostics: list[str] = []
    result = module.run_batch(
        input_dir=tmp_path,
        output_json=tmp_path / "labels.json",
        output_csv=tmp_path / "labels.csv",
        max_text_pages=5,
        workers=1,
        recursive=True,
        diagnostics=diagnostics.append,
    )
    summary = result["summary"]
    labels = result["labels"]

    assert summary["total_pdf_count"] == 2
    assert summary["skipped_no_bookmark_count"] == 1
    assert summary["bookmarked_pdf_count"] == 1
    assert summary["labeled_count"] == 1
    assert summary["failed_count"] == 0
    assert len(labels) == 1
    label = labels[0]
    assert label["status"] == "labeled"
    assert label["input_pdf"] == bookmarked_pdf
    assert label["root_relative_pdf"] == Path("bookmarked.pdf")
    assert label["bookmark_count"] == 4
    assert label["toc_start_page"] == 2
    assert label["toc_end_page"] == 3
    assert label["toc_page_count"] == 2
    assert label["confidence"] > 0
    assert label["label_source"] == "bookmark_guided_toc_start_pseudo_label"
    assert label["review_status"] == "unreviewed"
    assert label["evidence"]["toc_pages"] == [2, 3]
    assert (tmp_path / "labels.json").exists()
    assert (tmp_path / "labels.csv").exists()
    assert any("PDF 검색 완료: 2개 발견" in message for message in diagnostics)
    assert any("bookmark 보유 PDF 요약: 1개" in message for message in diagnostics)
    assert any(
        "start page label 생성 완료" in message and "start=2" in message
        for message in diagnostics
    )


def test_make_toc_start_pseudo_labels_csv_writes_review_fields(
    tmp_path: Path,
) -> None:
    module = load_script_module()
    pdf_path = tmp_path / "bookmarked.pdf"
    write_pdf(
        pdf_path,
        [
            "Preface",
            "Contents\nChapter 1 Introduction ........ 3\n1.1 Motivation ........ 7",
            "1.2 Background ........ 12\nChapter 2 Probability ........ 25",
            "Chapter 1 Introduction\nBody",
            "1.1 Motivation\nBody",
            "1.2 Background\nBody",
            "Chapter 2 Probability\nBody",
        ],
        toc=[
            [1, "Chapter 1 Introduction", 4],
            [2, "1.1 Motivation", 5],
            [2, "1.2 Background", 6],
            [1, "Chapter 2 Probability", 7],
        ],
    )
    csv_path = tmp_path / "toc_start_labels.csv"
    module.run_batch(
        input_dir=tmp_path,
        output_json=tmp_path / "toc_start_labels.json",
        output_csv=csv_path,
        max_text_pages=80,
        workers=1,
        recursive=True,
        diagnostics=None,
    )

    csv_text = csv_path.read_text(encoding="utf-8")
    assert "toc_start_page" in csv_text
    assert "label_source" in csv_text
    assert "review_status" in csv_text
    assert "bookmark_guided_toc_start_pseudo_label" in csv_text
    assert "unreviewed" in csv_text
