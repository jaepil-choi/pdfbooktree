from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.toc.bookmark_batch import (
    BookmarkTocBatchDetector,
    write_toc_page_dataset_csv,
)


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


def test_bookmark_toc_batch_detects_only_bookmarked_pdfs_recursively(
    tmp_path: Path,
) -> None:
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
    result = BookmarkTocBatchDetector(
        tmp_path,
        max_text_pages=5,
        diagnostics=diagnostics.append,
    ).run()

    assert result.total_pdf_count == 2
    assert result.skipped_no_bookmark_count == 1
    assert result.bookmarked_pdf_count == 1
    assert result.detected_count == 1
    assert result.failed_count == 0
    assert result.dataset_row_count == 4
    assert len(result.results) == 1
    detection = result.results[0]
    assert detection.input_pdf == bookmarked_pdf
    assert detection.root_relative_pdf == Path("bookmarked.pdf")
    assert detection.bookmark_count == 4
    assert detection.toc_pages == [2, 3]
    assert detection.detection is not None
    assert detection.detection.method == "bookmark_guided_feature_vote"
    assert len(detection.dataset_rows) == 4
    assert [row.pdf_page for row in detection.dataset_rows if row.label == 1] == [2, 3]
    first_positive = next(row for row in detection.dataset_rows if row.pdf_page == 2)
    assert first_positive.prev_page_available is True
    assert first_positive.prev_line_count == 1
    assert first_positive.prev_word_count == 1
    assert first_positive.prev_toc_keyword_presence is False
    assert len([row for row in detection.dataset_rows if row.label == 0]) == 2
    assert all(
        row.root_relative_pdf == Path("bookmarked.pdf") for row in result.dataset_rows
    )
    assert all(
        row.label_source == "bookmark_guided_toc_detection"
        for row in result.dataset_rows
    )
    assert any("PDF 검색 완료: 2개 발견" in message for message in diagnostics)
    assert any("bookmark 보유 PDF 요약: 1개" in message for message in diagnostics)
    assert any(
        "bookmark 있음: bookmarked.pdf (4개)" in message for message in diagnostics
    )
    assert any(
        "TOC/dataset 생성 완료" in message
        and "bookmarked.pdf positives=2 negatives=2" in message
        for message in diagnostics
    )
    assert not any("bookmark 없음" in message for message in diagnostics)


def test_bookmark_toc_batch_can_scan_non_recursive(tmp_path: Path) -> None:
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    top_pdf = tmp_path / "top.pdf"
    nested_pdf = nested_dir / "nested.pdf"

    write_pdf(top_pdf, ["Contents\nChapter 1 Introduction ........ 3", "Body"], toc=[])
    write_pdf(
        nested_pdf,
        ["Contents\nChapter 1 Introduction ........ 3", "Body"],
        toc=[[1, "Chapter 1 Introduction", 2]],
    )

    result = BookmarkTocBatchDetector(tmp_path, recursive=False).run()

    assert result.total_pdf_count == 1
    assert result.skipped_no_bookmark_count == 1
    assert result.bookmarked_pdf_count == 0


def test_write_toc_page_dataset_csv_writes_flat_rows(tmp_path: Path) -> None:
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
    result = BookmarkTocBatchDetector(tmp_path, random_seed=1).run()
    csv_path = tmp_path / "dataset.csv"

    write_toc_page_dataset_csv(csv_path, result.dataset_rows)

    csv_text = csv_path.read_text(encoding="utf-8")
    assert "root_relative_pdf,pdf_page,label,sample_role" in csv_text
    assert "prev_page_available" in csv_text
    assert "prev_line_final_number_count" in csv_text
    assert "bookmark_guided_toc_detection" in csv_text


def test_bookmark_toc_batch_supports_process_workers(tmp_path: Path) -> None:
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

    result = BookmarkTocBatchDetector(tmp_path, workers=2).run()

    assert result.workers == 2
    assert result.detected_count == 1
    assert result.dataset_row_count == 4
