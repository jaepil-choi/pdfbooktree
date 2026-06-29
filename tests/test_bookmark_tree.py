"""flat bookmark → 중첩 트리 복원과 own_span 계산을 검증한다(순수 로직, PDF 불필요)."""

from __future__ import annotations

from typing import Any

from pdfbooktree.toc.bookmark_tree import (
    build_bookmark_tree,
    count_tree_nodes,
    iter_tree_pages,
)


def _bm(order: int, level: int, title: str, pdf_page: int | None) -> dict[str, Any]:
    return {"order": order, "level": level, "title": title, "pdf_page": pdf_page}


def test_build_tree_nests_by_level() -> None:
    bookmarks = [
        _bm(1, 1, "Chapter 1", 2),
        _bm(2, 2, "1.1", 3),
        _bm(3, 2, "1.2", 4),
        _bm(4, 1, "Chapter 2", 5),
    ]
    roots = build_bookmark_tree(bookmarks, page_count=10)

    assert len(roots) == 2
    assert roots[0].title == "Chapter 1"
    assert [child.title for child in roots[0].children] == ["1.1", "1.2"]
    assert roots[1].title == "Chapter 2"
    assert roots[1].children == ()
    assert roots[0].order == 1


def test_own_span_to_next_bookmark() -> None:
    bookmarks = [
        _bm(1, 1, "A", 2),
        _bm(2, 1, "B", 5),
        _bm(3, 1, "C", 9),
    ]
    roots = build_bookmark_tree(bookmarks, page_count=12)

    assert roots[0].own_span == (2, 4)
    assert roots[1].own_span == (5, 8)
    # 마지막 노드는 문서 끝까지 갖는다.
    assert roots[2].own_span == (9, 12)


def test_own_span_empty_when_next_starts_same_page() -> None:
    bookmarks = [
        _bm(1, 1, "A", 5),
        _bm(2, 1, "B", 5),
    ]
    roots = build_bookmark_tree(bookmarks, page_count=10)

    # 다음 bookmark가 같은 page에서 시작하면 본문 구간이 빈다.
    assert roots[0].own_span is None
    assert roots[1].own_span == (5, 10)


def test_own_span_last_node_to_eof() -> None:
    roots = build_bookmark_tree([_bm(1, 1, "only", 3)], page_count=10)
    assert roots[0].own_span == (3, 10)


def test_build_tree_handles_none_pdf_page() -> None:
    bookmarks = [
        _bm(1, 1, "A", 2),
        _bm(2, 1, "broken", None),
        _bm(3, 1, "C", 6),
    ]
    roots = build_bookmark_tree(bookmarks, page_count=10)

    # None page bookmark는 start/own_span이 None이고, 경계로도 쓰이지 않는다.
    assert roots[1].start_pdf_page is None
    assert roots[1].own_span is None
    # 앞 노드 A는 None을 건너뛰고 다음 실제 page(6) 직전까지 확장된다.
    assert roots[0].own_span == (2, 5)
    assert roots[2].own_span == (6, 10)


def test_iter_tree_pages_union() -> None:
    bookmarks = [
        _bm(1, 1, "A", 2),
        _bm(2, 2, "1.1", 4),
        _bm(3, 1, "B", 7),
    ]
    roots = build_bookmark_tree(bookmarks, page_count=8)
    # A:(2,3), 1.1:(4,6), B:(7,8) → 합집합 2..8
    assert iter_tree_pages(roots) == set(range(2, 9))


def test_count_tree_nodes() -> None:
    bookmarks = [
        _bm(1, 1, "A", 2),
        _bm(2, 2, "1.1", 3),
        _bm(3, 2, "1.2", 4),
        _bm(4, 1, "B", 5),
    ]
    roots = build_bookmark_tree(bookmarks, page_count=10)
    assert count_tree_nodes(roots) == 4
