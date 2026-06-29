"""bookmark 트리 → markdown 디렉터리 export를 검증한다.

page_count와 본문 text는 합성 fitz PDF로 실제 추출하고, bookmark 목록만 인자로
주입해 디렉터리/파일 구조와 markdown 포맷을 격리 검증한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from pdfbooktree.output.bookmark_markdown import (
    export_bookmark_markdown_tree,
    render_node_markdown,
)
from pdfbooktree.toc.bookmark_tree import build_bookmark_tree


def _make_text_pdf(path: Path, page_count: int) -> None:
    """각 page에 'PAGE N BODY' 텍스트를 넣은 bookmark 없는 PDF를 만든다."""

    document = fitz.open()
    try:
        for page_number in range(1, page_count + 1):
            page = document.new_page(width=595.0, height=842.0)
            page.insert_text((72.0, 72.0), f"PAGE {page_number} BODY", fontsize=12)
        document.save(str(path))
    finally:
        document.close()


def _bm(order: int, level: int, title: str, pdf_page: int | None) -> dict[str, Any]:
    return {"order": order, "level": level, "title": title, "pdf_page": pdf_page}


def test_export_creates_nested_dirs_and_md(tmp_path: Path) -> None:
    pdf_path = tmp_path / "book.pdf"
    _make_text_pdf(pdf_path, page_count=10)
    bookmarks = [
        _bm(1, 1, "Chapter 1", 2),
        _bm(2, 2, "1.1 First", 3),
        _bm(3, 2, "1.2 Second", 5),
        _bm(4, 1, "Chapter 2", 7),
    ]

    node_count, root_dir = export_bookmark_markdown_tree(
        pdf_path, tmp_path / "out", bookmarks
    )

    assert node_count == 4
    assert root_dir == tmp_path / "out" / "book_markdown"

    ch1 = root_dir / "01_Chapter 1"
    assert (ch1 / "01_Chapter 1.md").exists()
    # 자식 디렉터리의 NN은 부모 안에서 1부터 다시 매겨진다.
    assert (ch1 / "01_1.1 First" / "01_1.1 First.md").exists()
    assert (ch1 / "02_1.2 Second" / "02_1.2 Second.md").exists()
    # 두 번째 root는 부모 기준으로 다시 02로 시작한다.
    ch2 = root_dir / "02_Chapter 2"
    assert (ch2 / "02_Chapter 2.md").exists()


def test_markdown_content_format(tmp_path: Path) -> None:
    pdf_path = tmp_path / "book.pdf"
    _make_text_pdf(pdf_path, page_count=6)
    bookmarks = [_bm(1, 1, "Intro", 2), _bm(2, 1, "Body", 4)]

    _, root_dir = export_bookmark_markdown_tree(pdf_path, tmp_path / "out", bookmarks)

    text = (root_dir / "01_Intro" / "01_Intro.md").read_text(encoding="utf-8")
    assert text.startswith("# Intro\n\n")
    # Intro own_span은 (2,3)이다.
    assert "<!-- own page span: 2-3 -->" in text
    assert "<!-- pdf_page 2 -->" in text
    assert "<!-- pdf_page 3 -->" in text
    assert "PAGE 2 BODY" in text
    # page 마커는 page 순서대로 나온다.
    assert text.index("<!-- pdf_page 2 -->") < text.index("<!-- pdf_page 3 -->")


def test_empty_span_node_has_none_label_and_no_page_markers() -> None:
    # 같은 page에서 다음 bookmark가 시작 → own_span None.
    roots = build_bookmark_tree([_bm(1, 1, "A", 5), _bm(2, 1, "B", 5)], page_count=10)
    rendered = render_node_markdown(roots[0], page_texts={5: "PAGE 5 BODY"})

    assert rendered == "# A\n\n<!-- own page span: none -->\n\n"
    assert "<!-- pdf_page" not in rendered


def test_same_title_siblings_get_distinct_dirs_via_index(tmp_path: Path) -> None:
    pdf_path = tmp_path / "book.pdf"
    _make_text_pdf(pdf_path, page_count=8)
    bookmarks = [_bm(1, 1, "Summary", 2), _bm(2, 1, "Summary", 5)]

    _, root_dir = export_bookmark_markdown_tree(pdf_path, tmp_path / "out", bookmarks)

    # NN이 부모 안에서 유일하므로 동일 제목도 서로 다른 디렉터리가 된다.
    assert (root_dir / "01_Summary" / "01_Summary.md").exists()
    assert (root_dir / "02_Summary" / "02_Summary.md").exists()


def test_export_overwrites_in_place_without_error(tmp_path: Path) -> None:
    pdf_path = tmp_path / "book.pdf"
    _make_text_pdf(pdf_path, page_count=6)
    bookmarks = [_bm(1, 1, "Intro", 2)]

    # 두 번 연속 실행해도 rmtree 없이 제자리 덮어써 에러가 없어야 한다.
    export_bookmark_markdown_tree(pdf_path, tmp_path / "out", bookmarks)
    node_count, root_dir = export_bookmark_markdown_tree(
        pdf_path, tmp_path / "out", bookmarks
    )

    assert node_count == 1
    assert (root_dir / "01_Intro" / "01_Intro.md").exists()
