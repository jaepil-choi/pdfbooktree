"""flat bookmark 목록을 own_span이 채워진 중첩 트리로 복원한다.

PyMuPDF에 의존하지 않고 ``extract_existing_bookmarks``가 돌려준 dict 목록과
``page_count``만으로 동작하므로, 실제 PDF 없이 순수하게 단위 테스트할 수 있다.
실험 019(`experiments/019_bookmark_tree_to_markdown_dir.py`)에서 검증한 트리 복원과
own_span 계산 로직을 그대로 옮긴 것이다.
"""

from __future__ import annotations

from typing import Any

from pdfbooktree.models import BookmarkTreeNode


def _next_start_page(bookmarks: list[dict[str, Any]], index: int) -> int | None:
    """reading order상 ``index`` 다음에 오는 첫 non-None pdf_page를 찾는다.

    같은 page에서 시작하는 형제/자식 bookmark가 본문 구간의 exclusive end가 되며,
    pdf_page가 None인(깨진 OCR) bookmark는 경계로 쓰지 않고 건너뛴다.
    """

    for nxt in bookmarks[index + 1 :]:
        if nxt["pdf_page"] is not None:
            return int(nxt["pdf_page"])
    return None


def _own_span(
    start_page: int | None, next_start_page: int | None, page_count: int
) -> tuple[int, int] | None:
    """노드의 자기 본문 page 구간 [start, end](1-based, inclusive)를 계산한다.

    end는 다음 bookmark 시작 page 직전이고, 다음 bookmark가 없으면 문서 끝이다.
    다음 bookmark가 같은 page에서 시작해 구간이 비면 None을 돌려준다.
    """

    if start_page is None:
        return None
    end_exclusive = next_start_page if next_start_page else page_count + 1
    end = end_exclusive - 1
    if end < start_page:
        return None
    return (start_page, end)


def build_bookmark_tree(
    bookmarks: list[dict[str, Any]], page_count: int
) -> list[BookmarkTreeNode]:
    """flat bookmark 목록을 own_span이 채워진 중첩 트리로 복원한다.

    bookmark dict는 ``extract_existing_bookmarks`` 형식(order/level/title/pdf_page)을
    따른다. level stack으로 중첩하므로 부모가 먼저 만들어지고 자식이 나중에 붙는다.
    frozen 노드는 자식을 나중에 추가할 수 없어, mutable builder로 트리를 만든 뒤
    post-order로 ``BookmarkTreeNode``로 동결한다.
    """

    builders: list[dict[str, Any]] = []
    for index, bookmark in enumerate(bookmarks):
        start_page = bookmark["pdf_page"]
        next_page = _next_start_page(bookmarks, index)
        builders.append(
            {
                "title": bookmark["title"],
                "level": int(bookmark["level"]),
                "start_pdf_page": start_page,
                "own_span": _own_span(start_page, next_page, page_count),
                "order": int(bookmark["order"]),
                "children": [],
            }
        )

    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for node in builders:
        while stack and stack[-1]["level"] >= node["level"]:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            roots.append(node)
        stack.append(node)

    return [_freeze(root) for root in roots]


def _freeze(builder: dict[str, Any]) -> BookmarkTreeNode:
    """mutable builder dict를 post-order로 frozen BookmarkTreeNode로 변환한다."""

    children = tuple(_freeze(child) for child in builder["children"])
    return BookmarkTreeNode(
        title=builder["title"],
        level=builder["level"],
        start_pdf_page=builder["start_pdf_page"],
        own_span=builder["own_span"],
        order=builder["order"],
        children=children,
    )


def iter_tree_pages(roots: list[BookmarkTreeNode]) -> set[int]:
    """트리 전체 own_span이 덮는 1-based PDF page 집합을 반환한다.

    이 집합만 text로 추출하면 markdown 본문을 모두 채울 수 있다.
    """

    pages: set[int] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node.own_span is not None:
            start, end = node.own_span
            pages.update(range(start, end + 1))
        stack.extend(node.children)
    return pages


def count_tree_nodes(roots: list[BookmarkTreeNode]) -> int:
    """트리의 전체 노드 수를 센다."""

    total = 0
    stack = list(roots)
    while stack:
        node = stack.pop()
        total += 1
        stack.extend(node.children)
    return total
