"""bookmark tree를 Markdown directory로 export한다."""

from __future__ import annotations

from pathlib import Path

from pdfbooktree.models import BookmarkPlanItem, BookmarkTreeNode
from pdfbooktree.outline.tree import build_outline_tree
from pdfbooktree.pdf.text import extract_selected_page_texts
from pdfbooktree.utils.jsonio import write_json
from pdfbooktree.utils.paths import build_markdown_dir_path, sanitize_title_for_path


def plan_markdown_dir_path(input_pdf: Path, output_dir: Path) -> Path:
    """Markdown tree 출력 디렉터리 경로를 만든다."""

    return build_markdown_dir_path(input_pdf, output_dir)


def export_markdown_tree(
    input_pdf: Path,
    output_dir: Path,
    plan: list[BookmarkPlanItem],
    total_pages: int,
) -> Path:
    """bookmark plan을 directory tree와 toc 파일로 export한다."""

    root_dir = plan_markdown_dir_path(input_pdf, output_dir)
    root_dir.mkdir(parents=True, exist_ok=True)
    roots = build_outline_tree(plan, total_pages)
    write_json(root_dir / "toc.json", plan)
    (root_dir / "toc.md").write_text(_render_toc_markdown(plan), encoding="utf-8")
    page_texts = _load_page_texts(input_pdf, plan, total_pages)
    for index, root in enumerate(roots, start=1):
        _write_node(root, root_dir, index, page_texts)
    return root_dir


def _render_toc_markdown(plan: list[BookmarkPlanItem]) -> str:
    lines = ["# Table of Contents", ""]
    for item in plan:
        indent = "  " * max(item.level - 1, 0)
        lines.append(f"{indent}- {item.title} (PDF page {item.pdf_page})")
    return "\n".join(lines) + "\n"


def _load_page_texts(
    input_pdf: Path, plan: list[BookmarkPlanItem], total_pages: int
) -> dict[int, str]:
    needed: set[int] = set()
    for index, item in enumerate(plan):
        end = plan[index + 1].pdf_page - 1 if index + 1 < len(plan) else total_pages
        for page in range(item.pdf_page, max(item.pdf_page, end) + 1):
            needed.add(page)
    return {
        page.pdf_page: page.text
        for page in extract_selected_page_texts(input_pdf, sorted(needed))
    }


def _write_node(
    node: BookmarkTreeNode, parent_dir: Path, index: int, page_texts: dict[int, str]
) -> None:
    dir_name = f"{index:02d}_{sanitize_title_for_path(node.title)}"
    node_dir = parent_dir / dir_name
    node_dir.mkdir(parents=True, exist_ok=True)
    body = _render_node_body(node, page_texts)
    (node_dir / "index.md").write_text(body, encoding="utf-8")
    for child_index, child in enumerate(node.children, start=1):
        _write_node(child, node_dir, child_index, page_texts)


def _render_node_body(node: BookmarkTreeNode, page_texts: dict[int, str]) -> str:
    lines = [
        f"# {node.title}",
        "",
        "---",
        f"title: {node.title}",
        f"level: {node.level}",
        f"pdf_start_page: {node.start_pdf_page}",
        f"pdf_end_page: {node.end_pdf_page}",
        "---",
        "",
    ]
    end = node.end_pdf_page or node.start_pdf_page
    for pdf_page in range(node.start_pdf_page, end + 1):
        text = page_texts.get(pdf_page, "").strip()
        if text:
            lines.extend([f"<!-- pdf_page {pdf_page} -->", "", text, ""])
    return "\n".join(lines)
