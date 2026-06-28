"""bookmark 트리를 디렉터리 트리 + markdown 본문으로 export한다.

PDF에 이미 bookmark가 있으면 TOC 탐지/LLM 없이 그 트리를 그대로 파일시스템에
펼칠 수 있다. 각 노드는 ``NN_<제목>`` 디렉터리가 되고, 그 안에 디렉터리명과 같은
markdown 파일과 자식 디렉터리가 들어간다. 실험 019에서 검증하고 사용자가 승인한
출력 형태를 그대로 옮긴 production 구현이다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from pdfbooktree.models import BookmarkTreeNode
from pdfbooktree.output.markdown import plan_markdown_dir_path
from pdfbooktree.pdf.text import extract_selected_page_texts
from pdfbooktree.toc.bookmark_tree import (
    build_bookmark_tree,
    count_tree_nodes,
    iter_tree_pages,
)
from pdfbooktree.utils.paths import sanitize_title_for_path


def render_node_markdown(node: BookmarkTreeNode, page_texts: dict[int, str]) -> str:
    """노드 하나의 markdown 본문 문자열을 만든다.

    헤더(`# 제목` + own page span 주석) 뒤에, 구간 내 각 page의 text를
    ``<!-- pdf_page N -->`` 주석과 함께 붙인다. 빈 page text는 건너뛰고, own_span이
    없으면 헤더만 남는다.
    """

    span = node.own_span
    span_label = f"{span[0]}-{span[1]}" if span else "none"
    header = f"# {node.title}\n\n<!-- own page span: {span_label} -->\n\n"

    if span is None:
        return header

    chunks: list[str] = []
    for pdf_page in range(span[0], span[1] + 1):
        text = page_texts.get(pdf_page, "").strip()
        if text:
            chunks.append(f"<!-- pdf_page {pdf_page} -->\n\n{text}")
    return header + "\n\n".join(chunks)


def _write_node(
    node: BookmarkTreeNode,
    parent_dir: Path,
    index: int,
    page_texts: dict[int, str],
) -> None:
    """노드를 ``NN_<제목>`` 디렉터리로 만들고 markdown과 자식을 재귀로 기록한다.

    디렉터리는 지우지 않고 ``exist_ok=True``로 제자리 덮어쓴다(열린 폴더에서의
    Windows 파일 잠금 WinError 32를 피한다). NN은 부모 안에서 1부터 다시 매긴다.
    """

    dir_name = f"{index:02d}_{sanitize_title_for_path(node.title)}"
    node_dir = parent_dir / dir_name
    node_dir.mkdir(parents=True, exist_ok=True)

    body = render_node_markdown(node, page_texts)
    (node_dir / f"{dir_name}.md").write_text(body, encoding="utf-8")

    for child_index, child in enumerate(node.children, start=1):
        _write_node(child, node_dir, child_index, page_texts)


def export_bookmark_markdown_tree(
    input_pdf: Path,
    output_dir: Path,
    bookmarks: list[dict[str, Any]],
) -> tuple[int, Path]:
    """bookmark 트리를 markdown 디렉터리 트리로 export한다.

    (생성한 노드 수, 루트 markdown 디렉터리)를 돌려준다. 본문 text는 트리가 덮는
    page만 한 번에 추출해 page→text map으로 쓴다.
    """

    root_dir = plan_markdown_dir_path(input_pdf, output_dir)
    root_dir.mkdir(parents=True, exist_ok=True)

    with fitz.open(input_pdf) as document:
        page_count = document.page_count

    roots = build_bookmark_tree(bookmarks, page_count)

    needed_pages = sorted(iter_tree_pages(roots))
    page_texts: dict[int, str] = {}
    if needed_pages:
        for page in extract_selected_page_texts(input_pdf, needed_pages):
            page_texts[page.pdf_page] = page.text

    for index, root in enumerate(roots, start=1):
        _write_node(root, root_dir, index, page_texts)

    return count_tree_nodes(roots), root_dir
