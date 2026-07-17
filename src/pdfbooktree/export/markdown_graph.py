"""bookmark plan을 progressive disclosure Markdown graph로 export한다."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from pdfbooktree.models import BookmarkPlanItem, MarkdownExportResult
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.utils.hashing import file_sha256
from pdfbooktree.utils.jsonio import write_json
from pdfbooktree.utils.paths import build_markdown_dir_path

MARKDOWN_MANIFEST_SCHEMA_VERSION = 1
MarkdownContentMode = Literal["direct", "inclusive"]

_WIKI_LINK_RE = re.compile(r"\[\[([^|\]]+)")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass
class MarkdownGraphNode:
    """Markdown graph를 만들기 위한 내부 node다."""

    item: BookmarkPlanItem
    order: int
    node_id: str
    filename: str
    relative_path: str
    pdf_end_page: int
    content_start_page: int | None
    content_end_page: int | None
    parent_id: str | None = None
    children_ids: list[str] = field(default_factory=list)
    previous_id: str | None = None
    next_id: str | None = None

    @property
    def title(self) -> str:
        return self.item.title

    @property
    def level(self) -> int:
        return self.item.level

    @property
    def pdf_page(self) -> int:
        return self.item.pdf_page

    @property
    def owned_pages(self) -> list[int]:
        if self.content_start_page is None or self.content_end_page is None:
            return []
        return list(range(self.content_start_page, self.content_end_page + 1))


def export_markdown_graph(
    input_pdf: Path,
    output_dir: Path,
    plan: list[BookmarkPlanItem],
    total_pages: int,
    content_mode: MarkdownContentMode = "direct",
) -> MarkdownExportResult:
    """bookmark plan을 self-contained Markdown graph로 export한다."""

    if content_mode not in {"direct", "inclusive"}:
        raise ValueError("content_mode는 direct 또는 inclusive여야 한다")
    if not plan:
        raise ValueError("Markdown graph를 만들 bookmark plan이 비어 있다")

    root_dir = build_markdown_dir_path(input_pdf, output_dir)
    root_dir.mkdir(parents=True, exist_ok=True)
    nodes_dir = root_dir / "nodes"
    if nodes_dir.exists():
        shutil.rmtree(nodes_dir)
    nodes_dir.mkdir(parents=True, exist_ok=True)

    page_texts = {
        page.pdf_page: page.text
        for page in extract_page_texts(input_pdf, max_pages=total_pages)
    }
    nodes = _build_graph(plan, total_pages, content_mode)
    by_id = {node.node_id: node for node in nodes}

    plan_path = root_dir / "bookmark_plan.json"
    write_json(plan_path, _plan_rows(nodes))
    toc_path = root_dir / "toc.md"
    toc_path.write_text(_render_toc(nodes, content_mode), encoding="utf-8")

    node_paths: list[Path] = []
    for node in nodes:
        path = root_dir / node.relative_path
        path.write_text(
            _render_node(node, by_id, page_texts, content_mode),
            encoding="utf-8",
        )
        node_paths.append(path)

    validation = _validate_graph(
        root_dir,
        nodes,
        page_texts,
        total_pages,
        content_mode,
    )
    manifest = {
        "schema_version": MARKDOWN_MANIFEST_SCHEMA_VERSION,
        "input": {
            "pdf_path": str(input_pdf),
            "sha256": file_sha256(input_pdf),
            "page_count": total_pages,
        },
        "plan": {
            "path": "bookmark_plan.json",
            "sha256": file_sha256(plan_path),
        },
        "export_mode": "tree_graph",
        "content_mode": content_mode,
        "same_page_content_owner": "last_plan_item_on_page",
        "confidence_semantics": (
            "pipeline evidence 값이며 bookmark 내용 품질의 합격 확률이 아니다"
        ),
        "node_count": len(nodes),
        "root_count": sum(node.parent_id is None for node in nodes),
        "mapping_sha256": _mapping_sha256(nodes),
        "nodes": _graph_snapshot(nodes),
        "coverage": validation["coverage"],
        "warnings": validation["warnings"],
        "validation": validation["validation"],
    }
    manifest_path = root_dir / "markdown_manifest.json"
    write_json(manifest_path, manifest)
    if not validation["validation"]["valid"]:
        raise RuntimeError(
            f"생성한 Markdown graph validation이 실패했다: manifest={manifest_path}"
        )

    total_word_count = sum(
        len(path.read_text(encoding="utf-8").split()) for path in node_paths
    )
    return MarkdownExportResult(
        output_dir=root_dir,
        chosen_level=None,
        constraint_satisfied=True,
        file_count=len(nodes),
        total_word_count=total_word_count,
        export_mode="tree_graph",
        manifest_path=manifest_path,
    )


def _build_graph(
    plan: list[BookmarkPlanItem],
    total_pages: int,
    content_mode: MarkdownContentMode,
) -> list[MarkdownGraphNode]:
    nodes: list[MarkdownGraphNode] = []
    for index, item in enumerate(plan):
        order = index + 1
        pdf_end_page = _logical_end_page(plan, index, total_pages)
        content_start_page, content_end_page = _content_range(
            plan,
            index,
            total_pages,
            pdf_end_page,
            content_mode,
        )
        filename = _filename_for(item, order)
        nodes.append(
            MarkdownGraphNode(
                item=item,
                order=order,
                node_id=f"n{order:04d}",
                filename=filename,
                relative_path=(Path("nodes") / filename).as_posix(),
                pdf_end_page=pdf_end_page,
                content_start_page=content_start_page,
                content_end_page=content_end_page,
            )
        )

    stack: list[MarkdownGraphNode] = []
    for node in nodes:
        while stack and stack[-1].level >= node.level:
            stack.pop()
        if stack:
            node.parent_id = stack[-1].node_id
            stack[-1].children_ids.append(node.node_id)
        stack.append(node)

    for index, node in enumerate(nodes):
        if index > 0:
            node.previous_id = nodes[index - 1].node_id
        if index + 1 < len(nodes):
            node.next_id = nodes[index + 1].node_id
    return nodes


def _logical_end_page(
    plan: list[BookmarkPlanItem], index: int, total_pages: int
) -> int:
    current = plan[index]
    for following in plan[index + 1 :]:
        if following.level <= current.level:
            return max(current.pdf_page, following.pdf_page - 1)
    return total_pages


def _content_range(
    plan: list[BookmarkPlanItem],
    index: int,
    total_pages: int,
    pdf_end_page: int,
    content_mode: MarkdownContentMode,
) -> tuple[int | None, int | None]:
    start_page = plan[index].pdf_page
    if content_mode == "inclusive":
        return start_page, pdf_end_page
    next_page = plan[index + 1].pdf_page if index + 1 < len(plan) else total_pages + 1
    if next_page <= start_page:
        return None, None
    return start_page, next_page - 1


def _filename_for(item: BookmarkPlanItem, order: int) -> str:
    slug = _sanitize_slug(item.title)
    return f"{order:04d}_L{item.level}_p{item.pdf_page:04d}_{slug}.md"


def _sanitize_slug(title: str, max_length: int = 64) -> str:
    normalized = unicodedata.normalize("NFKC", title).strip()
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE)
    normalized = re.sub(r"-+", "-", normalized).strip(" .-_")
    if not normalized:
        normalized = "untitled"
    normalized = normalized[:max_length].rstrip(" .") or "untitled"
    if normalized.upper() in _WINDOWS_RESERVED_NAMES:
        normalized = f"_{normalized}"
    return normalized


def _wiki_label(title: str) -> str:
    return title.replace("\\", "\\\\").replace("|", "\\|").replace("]", "\\]")


def _wiki_link(node: MarkdownGraphNode) -> str:
    return f"[[{Path(node.filename).stem}|{_wiki_label(node.title)}]]"


def _render_front_matter(metadata: dict[str, Any]) -> str:
    yaml_body = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return f"---\n{yaml_body}---\n"


def _render_node(
    node: MarkdownGraphNode,
    by_id: dict[str, MarkdownGraphNode],
    page_texts: dict[int, str],
    content_mode: MarkdownContentMode,
) -> str:
    metadata = {
        "schema_version": MARKDOWN_MANIFEST_SCHEMA_VERSION,
        "node_id": node.node_id,
        "order": node.order,
        "title": node.title,
        "level": node.level,
        "pdf_start_page": node.pdf_page,
        "pdf_end_page": node.pdf_end_page,
        "content_start_page": node.content_start_page,
        "content_end_page": node.content_end_page,
        "content_mode": content_mode,
        "source": node.item.source,
        "confidence": node.item.confidence,
        "evidence_count": len(node.item.evidence),
        "parent_id": node.parent_id,
        "parent": _wiki_link(by_id[node.parent_id]) if node.parent_id else None,
        "previous_id": node.previous_id,
        "previous": _wiki_link(by_id[node.previous_id]) if node.previous_id else None,
        "next_id": node.next_id,
        "next": _wiki_link(by_id[node.next_id]) if node.next_id else None,
        "children": [_wiki_link(by_id[item]) for item in node.children_ids],
        "evidence_ref": f"../bookmark_plan.json#{node.node_id}",
    }
    lines = [
        _render_front_matter(metadata).rstrip(),
        "",
        f"# {node.title}",
        "",
        "## Navigation",
        "",
    ]
    for label, related_id in (
        ("Parent", node.parent_id),
        ("Previous", node.previous_id),
        ("Next", node.next_id),
    ):
        value = _wiki_link(by_id[related_id]) if related_id else "없음"
        lines.append(f"- {label}: {value}")
    lines.append("- Children:")
    if node.children_ids:
        lines.extend(f"  - {_wiki_link(by_id[item])}" for item in node.children_ids)
    else:
        lines.append("  - 없음")
    lines.extend(["", "## Content", ""])
    if not node.owned_pages:
        lines.extend(
            [
                "이 node가 직접 소유하는 page text는 없습니다. ",
                "하위 내용은 Children link를 따라가서 확인합니다.",
                "",
            ]
        )
    for pdf_page in node.owned_pages:
        lines.extend([f"<!-- pdf_page {pdf_page} -->", ""])
        if text := page_texts.get(pdf_page, "").strip():
            lines.extend([text, ""])
    return "\n".join(lines).rstrip() + "\n"


def _render_toc(
    nodes: list[MarkdownGraphNode], content_mode: MarkdownContentMode
) -> str:
    roots = [node for node in nodes if node.parent_id is None]
    metadata = {
        "schema_version": MARKDOWN_MANIFEST_SCHEMA_VERSION,
        "document_type": "toc",
        "title": "Table of Contents",
        "node_count": len(nodes),
        "root_count": len(roots),
        "content_mode": content_mode,
    }
    lines = [
        _render_front_matter(metadata).rstrip(),
        "",
        "# Table of Contents",
        "",
        "## Root nodes",
        "",
        *(f"- {_wiki_link(node)}" for node in roots),
        "",
        "## Flat outline",
        "",
    ]
    for node in nodes:
        indent = "  " * max(node.level - 1, 0)
        lines.append(f"{indent}- {_wiki_link(node)} — PDF page {node.pdf_page}")
    return "\n".join(lines).rstrip() + "\n"


def _plan_rows(nodes: list[MarkdownGraphNode]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": node.node_id,
            "order": node.order,
            "title": node.title,
            "level": node.level,
            "pdf_page": node.pdf_page,
            "source": node.item.source,
            "confidence": node.item.confidence,
            "evidence": node.item.evidence,
        }
        for node in nodes
    ]


def _graph_snapshot(nodes: list[MarkdownGraphNode]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": node.node_id,
            "order": node.order,
            "title": node.title,
            "level": node.level,
            "pdf_start_page": node.pdf_page,
            "pdf_end_page": node.pdf_end_page,
            "content_start_page": node.content_start_page,
            "content_end_page": node.content_end_page,
            "relative_path": node.relative_path,
            "parent_id": node.parent_id,
            "children_ids": node.children_ids,
            "previous_id": node.previous_id,
            "next_id": node.next_id,
            "source": node.item.source,
            "confidence": node.item.confidence,
            "evidence_ref": f"../bookmark_plan.json#{node.node_id}",
        }
        for node in nodes
    ]


def _mapping_sha256(nodes: list[MarkdownGraphNode]) -> str:
    encoded = json.dumps(
        _graph_snapshot(nodes),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_front_matter(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("front matter가 첫 줄에서 시작하지 않는다")
    try:
        end_index = lines.index("---", 1)
    except ValueError as error:
        raise ValueError("front matter 종료 구분자가 없다") from error
    loaded = yaml.safe_load("\n".join(lines[1:end_index]))
    if not isinstance(loaded, dict):
        raise ValueError("front matter가 YAML object가 아니다")
    return loaded


def _validate_graph(
    root_dir: Path,
    nodes: list[MarkdownGraphNode],
    page_texts: dict[int, str],
    total_pages: int,
    content_mode: MarkdownContentMode,
) -> dict[str, Any]:
    by_id = {node.node_id: node for node in nodes}
    known_targets = {Path(node.filename).stem for node in nodes}
    node_id_counts = Counter(node.node_id for node in nodes)
    path_counts = Counter(node.relative_path.casefold() for node in nodes)
    yaml_errors: list[dict[str, str]] = []
    dangling_links: list[dict[str, str]] = []
    markdown_paths = [root_dir / "toc.md"] + [
        root_dir / node.relative_path for node in nodes
    ]
    for path in markdown_paths:
        try:
            _parse_front_matter(path)
        except (ValueError, yaml.YAMLError) as error:
            yaml_errors.append(
                {"path": str(path.relative_to(root_dir)), "reason": str(error)}
            )
        for target in _WIKI_LINK_RE.findall(path.read_text(encoding="utf-8")):
            if target not in known_targets:
                dangling_links.append(
                    {"path": str(path.relative_to(root_dir)), "target": target}
                )

    parent_child_errors: list[str] = []
    previous_next_errors: list[str] = []
    for node in nodes:
        if node.parent_id and node.node_id not in by_id[node.parent_id].children_ids:
            parent_child_errors.append(f"{node.parent_id}->{node.node_id}")
        for child_id in node.children_ids:
            if by_id[child_id].parent_id != node.node_id:
                parent_child_errors.append(f"{node.node_id}->{child_id}")
        if node.previous_id and by_id[node.previous_id].next_id != node.node_id:
            previous_next_errors.append(f"{node.previous_id}->{node.node_id}")
        if node.next_id and by_id[node.next_id].previous_id != node.node_id:
            previous_next_errors.append(f"{node.node_id}->{node.next_id}")

    reachable: set[str] = set()
    stack = [node.node_id for node in nodes if node.parent_id is None]
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        stack.extend(by_id[node_id].children_ids)

    page_occurrences = Counter(page for node in nodes for page in node.owned_pages)
    assigned_pages = sorted(page_occurrences)
    unassigned_pages = sorted(set(range(1, total_pages + 1)) - set(assigned_pages))
    duplicated_pages = sorted(
        page for page, count in page_occurrences.items() if count > 1
    )
    empty_text_pages = [
        page for page in assigned_pages if not page_texts.get(page, "").strip()
    ]
    toc_targets = set(
        _WIKI_LINK_RE.findall((root_dir / "toc.md").read_text(encoding="utf-8"))
    )
    same_page_boundaries = [
        {
            "left_id": left.node_id,
            "right_id": right.node_id,
            "pdf_page": left.pdf_page,
            "parent_child": right.level > left.level,
        }
        for left, right in zip(nodes, nodes[1:])
        if left.pdf_page == right.pdf_page
    ]
    rerendered = _build_graph([node.item for node in nodes], total_pages, content_mode)
    duplicate_node_ids = sum(
        count - 1 for count in node_id_counts.values() if count > 1
    )
    duplicate_paths = sum(count - 1 for count in path_counts.values() if count > 1)
    direct_duplicate_error_count = (
        len(duplicated_pages) if content_mode == "direct" else 0
    )
    validation_counts = (
        len(yaml_errors),
        duplicate_node_ids,
        duplicate_paths,
        len(dangling_links),
        len(parent_child_errors),
        len(previous_next_errors),
        len(nodes) - len(reachable),
        len(known_targets - toc_targets),
        direct_duplicate_error_count,
    )
    return {
        "coverage": {
            "assigned_page_count": len(assigned_pages),
            "unassigned_page_count": len(unassigned_pages),
            "unassigned_pages": unassigned_pages,
            "empty_text_page_count": len(empty_text_pages),
            "empty_text_pages": empty_text_pages,
            "duplicated_page_count": len(duplicated_pages),
            "duplicated_pages": duplicated_pages,
            "navigation_only_node_count": sum(not node.owned_pages for node in nodes),
        },
        "warnings": {
            "same_page_boundary_count": len(same_page_boundaries),
            "same_page_parent_child_count": sum(
                item["parent_child"] for item in same_page_boundaries
            ),
            "same_page_boundaries": same_page_boundaries,
        },
        "validation": {
            "valid": all(count == 0 for count in validation_counts)
            and _graph_snapshot(nodes) == _graph_snapshot(rerendered),
            "yaml_file_count": len(markdown_paths),
            "yaml_parse_error_count": len(yaml_errors),
            "yaml_errors": yaml_errors,
            "duplicate_node_id_count": duplicate_node_ids,
            "duplicate_output_path_count": duplicate_paths,
            "dangling_link_count": len(dangling_links),
            "dangling_links": dangling_links,
            "parent_child_asymmetry_count": len(parent_child_errors),
            "previous_next_asymmetry_count": len(previous_next_errors),
            "unreachable_node_count": len(nodes) - len(reachable),
            "toc_unlinked_node_count": len(known_targets - toc_targets),
            "deterministic_mapping": _graph_snapshot(nodes)
            == _graph_snapshot(rerendered),
        },
    }
