"""flat bookmark plan을 tree와 page range로 변환한다."""

from __future__ import annotations

from dataclasses import replace

from pdfbooktree.models import BookmarkPlanItem, BookmarkTreeNode


def build_outline_tree(
    plan: list[BookmarkPlanItem], total_pages: int
) -> list[BookmarkTreeNode]:
    """flat bookmark plan을 level 기반 tree로 만든다."""

    nodes = [
        BookmarkTreeNode(
            title=item.title,
            level=item.level,
            start_pdf_page=item.pdf_page,
            end_pdf_page=_end_page(plan, index, total_pages),
            order=index + 1,
        )
        for index, item in enumerate(plan)
    ]
    roots: list[BookmarkTreeNode] = []
    stack: list[BookmarkTreeNode] = []
    child_map: dict[int, list[BookmarkTreeNode]] = {id(node): [] for node in nodes}
    for node in nodes:
        while stack and stack[-1].level >= node.level:
            stack.pop()
        if stack:
            child_map[id(stack[-1])].append(node)
        else:
            roots.append(node)
        stack.append(node)
    return [_attach_children(root, child_map) for root in roots]


def _attach_children(
    node: BookmarkTreeNode, child_map: dict[int, list[BookmarkTreeNode]]
) -> BookmarkTreeNode:
    children = tuple(
        _attach_children(child, child_map) for child in child_map[id(node)]
    )
    return replace(node, children=children)


def _end_page(plan: list[BookmarkPlanItem], index: int, total_pages: int) -> int:
    current = plan[index]
    for next_item in plan[index + 1 :]:
        if next_item.level <= current.level:
            return max(current.pdf_page, next_item.pdf_page - 1)
    return total_pages
