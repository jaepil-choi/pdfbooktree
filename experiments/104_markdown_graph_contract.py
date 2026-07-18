"""실험 104: Markdown progressive disclosure graph 계약을 실제 PDF로 검증한다.

목적
- 현재 inclusive Markdown tree와 direct-content graph 후보를 같은 실제 PDF에서
  생성해 본문 중복, link 탐색성, YAML 호환성과 page coverage를 비교한다.
- production 구현 전에 node ID, 고유 파일명, 관계 link, page 소유권과 manifest
  schema를 하나의 실행 가능한 계약으로 고정한다.

규칙
- bookmark가 있는 실제 PDF를 사용하고 synthetic/mock 입력으로 성공을 주장하지
  않는다.
- 모든 외부 PDF page는 1-based로 기록한다.
- 실험 코드는 AGENTS.md 규칙에 따라 이 파일 안에 monolithic하게 둔다.
- 표준 YAML 검증을 위해 ``uv run --with pyyaml python``으로 실행한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import yaml

from pdfbooktree.models import BookmarkPlanItem
from pdfbooktree.pdf.outline import outline_to_plan, read_outline

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "104_markdown_graph_contract"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
CURRENT_DIR = OUTPUT_DIR / "current"
CANDIDATE_DIR = OUTPUT_DIR / "candidate"
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DEFAULT_PDF = (
    ROOT_DIR
    / "data"
    / "scanned-pdf-indexed"
    / (
        "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I "
        "The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf"
    )
)

WIKI_LINK_RE = re.compile(r"\[\[([^|\]]+)")
PAGE_MARKER_RE = re.compile(r"<!-- pdf_page (\d+) -->")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass
class GraphNode:
    """실험용 Markdown graph의 단일 node다."""

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


def reset_output_dir(path: Path) -> None:
    """실험 전용 하위 디렉터리만 안전하게 초기화한다."""

    resolved = path.resolve()
    output_root = OUTPUT_DIR.resolve()
    if output_root not in resolved.parents:
        raise RuntimeError(f"실험 output 밖의 경로는 초기화할 수 없다: {resolved}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, value: Any) -> None:
    """UTF-8 JSON을 결정론적인 key 순서로 기록한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    """파일 SHA-256을 계산한다."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_slug(title: str, max_length: int = 64) -> str:
    """Unicode 제목을 Windows 안전하고 사람이 읽을 수 있는 slug로 바꾼다."""

    normalized = unicodedata.normalize("NFKC", title).strip()
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE)
    normalized = re.sub(r"-+", "-", normalized).strip(" .-_")
    if not normalized:
        normalized = "untitled"
    normalized = normalized[:max_length].rstrip(" .") or "untitled"
    if normalized.upper() in WINDOWS_RESERVED_NAMES:
        normalized = f"_{normalized}"
    return normalized


def filename_for(item: BookmarkPlanItem, order: int) -> str:
    """global order, level, 1-based page와 title을 담은 고유 파일명을 만든다."""

    slug = sanitize_slug(item.title)
    return f"{order:04d}_L{item.level}_p{item.pdf_page:04d}_{slug}.md"


def logical_end_page(plan: list[BookmarkPlanItem], index: int, total_pages: int) -> int:
    """현재 node의 descendant를 포함하는 논리적 page 범위 끝을 계산한다."""

    current = plan[index]
    for following in plan[index + 1 :]:
        if following.level <= current.level:
            return max(current.pdf_page, following.pdf_page - 1)
    return total_pages


def direct_content_range(
    plan: list[BookmarkPlanItem], index: int, total_pages: int
) -> tuple[int | None, int | None]:
    """다음 bookmark 전까지의 page를 현재 node의 직접 본문으로 배정한다.

    여러 bookmark가 같은 page에서 시작하면 plan상 마지막 bookmark가 그 page를
    소유한다. 앞선 node는 navigation-only 문서가 되며 manifest warning으로 남긴다.
    """

    start_page = plan[index].pdf_page
    next_page = plan[index + 1].pdf_page if index + 1 < len(plan) else total_pages + 1
    if next_page <= start_page:
        return None, None
    return start_page, next_page - 1


def build_graph(plan: list[BookmarkPlanItem], total_pages: int) -> list[GraphNode]:
    """flat plan을 결정론적 관계와 page 범위를 가진 graph node로 변환한다."""

    nodes: list[GraphNode] = []
    for index, item in enumerate(plan):
        order = index + 1
        filename = filename_for(item, order)
        content_start, content_end = direct_content_range(plan, index, total_pages)
        nodes.append(
            GraphNode(
                item=item,
                order=order,
                node_id=f"n{order:04d}",
                filename=filename,
                relative_path=str(Path("nodes") / filename),
                pdf_end_page=logical_end_page(plan, index, total_pages),
                content_start_page=content_start,
                content_end_page=content_end,
            )
        )

    stack: list[GraphNode] = []
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


def wiki_label(title: str) -> str:
    """Obsidian alias에서 link 구분 기호가 제목과 충돌하지 않게 escape한다."""

    return title.replace("\\", "\\\\").replace("|", "\\|").replace("]", "\\]")


def wiki_link(node: GraphNode) -> str:
    """고유 basename을 target으로 사용하는 Obsidian wiki link를 만든다."""

    return f"[[{Path(node.filename).stem}|{wiki_label(node.title)}]]"


def render_front_matter(metadata: dict[str, Any]) -> str:
    """표준 YAML parser가 type을 보존하는 front matter를 만든다."""

    yaml_body = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return f"---\n{yaml_body}---\n"


def render_navigation(node: GraphNode, by_id: dict[str, GraphNode]) -> str:
    """사람이 바로 읽을 수 있는 navigation block을 만든다."""

    lines = ["## Navigation", ""]
    relations = (
        ("Parent", node.parent_id),
        ("Previous", node.previous_id),
        ("Next", node.next_id),
    )
    for label, related_id in relations:
        value = wiki_link(by_id[related_id]) if related_id else "없음"
        lines.append(f"- {label}: {value}")
    lines.append("- Children:")
    if node.children_ids:
        lines.extend(f"  - {wiki_link(by_id[item])}" for item in node.children_ids)
    else:
        lines.append("  - 없음")
    return "\n".join(lines)


def render_node_markdown(
    node: GraphNode,
    by_id: dict[str, GraphNode],
    page_texts: dict[int, str],
) -> str:
    """front matter, navigation과 직접 소유 page text를 하나의 문서로 만든다."""

    metadata = {
        "schema_version": 1,
        "node_id": node.node_id,
        "order": node.order,
        "title": node.title,
        "level": node.level,
        "pdf_start_page": node.pdf_page,
        "pdf_end_page": node.pdf_end_page,
        "content_start_page": node.content_start_page,
        "content_end_page": node.content_end_page,
        "source": node.item.source,
        "confidence": node.item.confidence,
        "evidence_count": len(node.item.evidence),
        "parent_id": node.parent_id,
        "parent": wiki_link(by_id[node.parent_id]) if node.parent_id else None,
        "previous_id": node.previous_id,
        "previous": wiki_link(by_id[node.previous_id]) if node.previous_id else None,
        "next_id": node.next_id,
        "next": wiki_link(by_id[node.next_id]) if node.next_id else None,
        "children": [wiki_link(by_id[item]) for item in node.children_ids],
        "evidence_ref": f"../bookmark_plan.json#{node.node_id}",
    }
    lines = [
        render_front_matter(metadata).rstrip(),
        "",
        f"# {node.title}",
        "",
        render_navigation(node, by_id),
        "",
        "## Content",
        "",
    ]
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
        if text := page_texts[pdf_page].strip():
            lines.extend([text, ""])
    return "\n".join(lines).rstrip() + "\n"


def render_toc(nodes: list[GraphNode]) -> str:
    """root node와 전체 flat outline을 모두 link하는 root TOC를 만든다."""

    roots = [node for node in nodes if node.parent_id is None]
    metadata = {
        "schema_version": 1,
        "document_type": "toc",
        "title": "Table of Contents",
        "node_count": len(nodes),
        "root_count": len(roots),
        "content_mode": "direct",
    }
    lines = [
        render_front_matter(metadata).rstrip(),
        "",
        "# Table of Contents",
        "",
        "## Root nodes",
        "",
    ]
    lines.extend(f"- {wiki_link(node)}" for node in roots)
    lines.extend(["", "## Flat outline", ""])
    for node in nodes:
        indent = "  " * max(node.level - 1, 0)
        lines.append(f"{indent}- {wiki_link(node)} — PDF page {node.pdf_page}")
    return "\n".join(lines).rstrip() + "\n"


def plan_rows(nodes: list[GraphNode]) -> list[dict[str, Any]]:
    """plan의 source, confidence와 evidence를 손실 없이 JSON row로 만든다."""

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


def load_page_texts(pdf_path: Path) -> tuple[int, dict[int, str]]:
    """PDF의 모든 1-based page text를 한 번만 읽는다."""

    with fitz.open(pdf_path) as document:
        return document.page_count, {
            index + 1: page.get_text("text") for index, page in enumerate(document)
        }


def write_legacy_current_output(
    nodes: list[GraphNode], page_texts: dict[int, str]
) -> Path:
    """Phase 1 당시의 index.md/inclusive 형식을 실험 안에서 재현한다.

    production exporter가 graph 방식으로 바뀐 뒤에도 이 실험의 baseline이 움직이지
    않도록 public exporter에 의존하지 않는다.
    """

    root_dir = CURRENT_DIR / "legacy_markdown"
    root_dir.mkdir(parents=True, exist_ok=True)
    toc_lines = ["# Table of Contents", ""]
    directories: dict[str, Path] = {}
    for node in nodes:
        indent = "  " * max(node.level - 1, 0)
        toc_lines.append(f"{indent}- {node.title} (PDF page {node.pdf_page})")
        parent_dir = directories.get(node.parent_id, root_dir)
        node_dir = parent_dir / f"{node.order:04d}_{sanitize_slug(node.title)}"
        node_dir.mkdir(parents=True, exist_ok=True)
        directories[node.node_id] = node_dir
        lines = [
            f"# {node.title}",
            "",
            "---",
            f"title: {node.title}",
            f"level: {node.level}",
            f"pdf_start_page: {node.pdf_page}",
            f"pdf_end_page: {node.pdf_end_page}",
            "---",
            "",
        ]
        for pdf_page in range(node.pdf_page, node.pdf_end_page + 1):
            if text := page_texts[pdf_page].strip():
                lines.extend([f"<!-- pdf_page {pdf_page} -->", "", text, ""])
        (node_dir / "index.md").write_text(
            "\n".join(lines).rstrip() + "\n",
            encoding="utf-8",
        )
    (root_dir / "toc.md").write_text(
        "\n".join(toc_lines) + "\n",
        encoding="utf-8",
    )
    return root_dir


def parse_front_matter(path: Path) -> dict[str, Any]:
    """Markdown 첫 줄의 YAML front matter를 표준 parser로 읽는다."""

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


def graph_snapshot(nodes: list[GraphNode]) -> list[dict[str, Any]]:
    """결정성 비교에 사용하는 node mapping snapshot을 만든다."""

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


def mapping_sha256(nodes: list[GraphNode]) -> str:
    """node mapping의 결정론적 SHA-256을 반환한다."""

    encoded = json.dumps(
        graph_snapshot(nodes),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_graph(
    nodes: list[GraphNode],
    page_texts: dict[int, str],
    total_pages: int,
) -> dict[str, Any]:
    """YAML, relation, link, reachability와 page coverage를 기계적으로 검증한다."""

    by_id = {node.node_id: node for node in nodes}
    known_targets = {Path(node.filename).stem for node in nodes}
    node_id_counts = Counter(node.node_id for node in nodes)
    path_counts = Counter(node.relative_path.casefold() for node in nodes)
    yaml_errors: list[dict[str, str]] = []
    dangling_links: list[dict[str, str]] = []

    markdown_paths = [CANDIDATE_DIR / "toc.md"] + [
        CANDIDATE_DIR / node.relative_path for node in nodes
    ]
    for path in markdown_paths:
        try:
            parse_front_matter(path)
        except (ValueError, yaml.YAMLError) as error:
            yaml_errors.append(
                {"path": str(path.relative_to(CANDIDATE_DIR)), "reason": str(error)}
            )
        markdown = path.read_text(encoding="utf-8")
        for target in WIKI_LINK_RE.findall(markdown):
            if target not in known_targets:
                dangling_links.append(
                    {
                        "path": str(path.relative_to(CANDIDATE_DIR)),
                        "target": target,
                    }
                )

    parent_child_errors: list[str] = []
    previous_next_errors: list[str] = []
    for node in nodes:
        if node.parent_id:
            parent = by_id[node.parent_id]
            if node.node_id not in parent.children_ids:
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
    empty_text_pages = [page for page in assigned_pages if not page_texts[page].strip()]
    toc_targets = set(
        WIKI_LINK_RE.findall((CANDIDATE_DIR / "toc.md").read_text(encoding="utf-8"))
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
    rerendered = build_graph([node.item for node in nodes], total_pages)

    return {
        "valid": all(
            count == 0
            for count in (
                len(yaml_errors),
                sum(count - 1 for count in node_id_counts.values() if count > 1),
                sum(count - 1 for count in path_counts.values() if count > 1),
                len(dangling_links),
                len(parent_child_errors),
                len(previous_next_errors),
                len(nodes) - len(reachable),
                len(duplicated_pages),
                len(known_targets - toc_targets),
            )
        )
        and graph_snapshot(nodes) == graph_snapshot(rerendered),
        "yaml_file_count": len(markdown_paths),
        "yaml_parse_error_count": len(yaml_errors),
        "yaml_errors": yaml_errors,
        "duplicate_node_id_count": sum(
            count - 1 for count in node_id_counts.values() if count > 1
        ),
        "duplicate_output_path_count": sum(
            count - 1 for count in path_counts.values() if count > 1
        ),
        "dangling_link_count": len(dangling_links),
        "dangling_links": dangling_links,
        "parent_child_asymmetry_count": len(parent_child_errors),
        "previous_next_asymmetry_count": len(previous_next_errors),
        "unreachable_node_count": len(nodes) - len(reachable),
        "toc_unlinked_node_count": len(known_targets - toc_targets),
        "assigned_page_count": len(assigned_pages),
        "unassigned_page_count": len(unassigned_pages),
        "unassigned_pages": unassigned_pages,
        "empty_text_page_count": len(empty_text_pages),
        "empty_text_pages": empty_text_pages,
        "duplicated_page_count": len(duplicated_pages),
        "duplicated_pages": duplicated_pages,
        "same_page_boundary_count": len(same_page_boundaries),
        "same_page_parent_child_count": sum(
            item["parent_child"] for item in same_page_boundaries
        ),
        "same_page_boundaries": same_page_boundaries,
        "navigation_only_node_count": sum(not node.owned_pages for node in nodes),
        "deterministic_mapping": graph_snapshot(nodes) == graph_snapshot(rerendered),
    }


def write_candidate(
    pdf_path: Path,
    nodes: list[GraphNode],
    page_texts: dict[int, str],
    total_pages: int,
) -> tuple[dict[str, Any], Path]:
    """candidate graph와 validation 결과를 실험 output으로 기록한다."""

    reset_output_dir(CANDIDATE_DIR)
    node_dir = CANDIDATE_DIR / "nodes"
    node_dir.mkdir(parents=True, exist_ok=True)
    by_id = {node.node_id: node for node in nodes}
    plan_path = CANDIDATE_DIR / "bookmark_plan.json"
    write_json(plan_path, plan_rows(nodes))
    (CANDIDATE_DIR / "toc.md").write_text(render_toc(nodes), encoding="utf-8")
    for node in nodes:
        (CANDIDATE_DIR / node.relative_path).write_text(
            render_node_markdown(node, by_id, page_texts),
            encoding="utf-8",
        )

    validation = validate_graph(nodes, page_texts, total_pages)
    snapshot = graph_snapshot(nodes)
    manifest = {
        "schema_version": 1,
        "input": {
            "pdf_path": str(pdf_path.relative_to(ROOT_DIR)),
            "sha256": sha256_file(pdf_path),
            "page_count": total_pages,
        },
        "plan": {
            "path": "bookmark_plan.json",
            "sha256": sha256_file(plan_path),
        },
        "export_mode": "tree_graph",
        "content_mode": "direct",
        "same_page_content_owner": "last_plan_item_on_page",
        "confidence_semantics": (
            "pipeline evidence 값이며 bookmark 내용 품질의 합격 확률이 아니다"
        ),
        "node_count": len(nodes),
        "root_count": sum(node.parent_id is None for node in nodes),
        "mapping_sha256": mapping_sha256(nodes),
        "nodes": snapshot,
        "coverage": {
            key: value
            for key, value in validation.items()
            if key
            in {
                "assigned_page_count",
                "unassigned_page_count",
                "unassigned_pages",
                "empty_text_page_count",
                "empty_text_pages",
                "duplicated_page_count",
                "duplicated_pages",
                "navigation_only_node_count",
            }
        },
        "warnings": {
            "same_page_boundary_count": validation["same_page_boundary_count"],
            "same_page_parent_child_count": validation["same_page_parent_child_count"],
            "same_page_boundaries": validation["same_page_boundaries"],
        },
        "validation": {
            key: value
            for key, value in validation.items()
            if key
            not in {
                "assigned_page_count",
                "unassigned_page_count",
                "unassigned_pages",
                "empty_text_page_count",
                "empty_text_pages",
                "duplicated_page_count",
                "duplicated_pages",
                "navigation_only_node_count",
                "same_page_boundary_count",
                "same_page_parent_child_count",
                "same_page_boundaries",
            }
        },
    }
    manifest_path = CANDIDATE_DIR / "markdown_manifest.json"
    write_json(manifest_path, manifest)
    return manifest, manifest_path


def baseline_metrics(
    baseline_root: Path,
    nodes: list[GraphNode],
    page_texts: dict[int, str],
) -> dict[str, Any]:
    """현재 inclusive exporter의 중복량과 TOC link 상태를 계산한다."""

    markdown_paths = list(baseline_root.rglob("index.md"))
    marker_counts: Counter[int] = Counter()
    for path in markdown_paths:
        marker_counts.update(
            int(value)
            for value in PAGE_MARKER_RE.findall(path.read_text(encoding="utf-8"))
        )
    inclusive_chars = sum(
        len(page_texts[page])
        for node in nodes
        for page in range(node.pdf_page, node.pdf_end_page + 1)
    )
    toc_markdown = (baseline_root / "toc.md").read_text(encoding="utf-8")
    return {
        "output_dir": str(baseline_root.relative_to(OUTPUT_DIR)),
        "node_markdown_count": len(markdown_paths),
        "unique_basename_count": len({path.name for path in markdown_paths}),
        "toc_linked_node_count": len(set(WIKI_LINK_RE.findall(toc_markdown))),
        "payload_char_count": inclusive_chars,
        "page_marker_count": sum(marker_counts.values()),
        "duplicated_text_page_count": sum(
            count > 1 for count in marker_counts.values()
        ),
        "extra_page_assignment_count": sum(
            count - 1 for count in marker_counts.values() if count > 1
        ),
    }


def candidate_metrics(
    nodes: list[GraphNode], page_texts: dict[int, str], validation: dict[str, Any]
) -> dict[str, Any]:
    """candidate graph의 대응 지표를 계산한다."""

    return {
        "output_dir": str(CANDIDATE_DIR.relative_to(OUTPUT_DIR)),
        "node_markdown_count": len(nodes),
        "unique_basename_count": len({node.filename for node in nodes}),
        "toc_linked_node_count": len(nodes) - validation["toc_unlinked_node_count"],
        "payload_char_count": sum(
            len(page_texts[page]) for node in nodes for page in node.owned_pages
        ),
        "page_marker_count": sum(len(node.owned_pages) for node in nodes),
        "duplicated_text_page_count": validation["duplicated_page_count"],
        "extra_page_assignment_count": 0,
    }


def record_experiment(summary: dict[str, Any]) -> None:
    """experiments.json에 실험 실행 결과를 append하거나 갱신한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    experiments = data.get("experiments", data) if isinstance(data, dict) else data
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "현재 inclusive Markdown tree와 direct-content graph 후보를 실제 PDF에서 "
            "비교하고 YAML, wiki link, page coverage와 node mapping 계약을 검증한다."
        ),
        "inputs": [summary["input_pdf"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "같은 existing outline plan으로 현재 public exporter와 flat nodes graph를 "
            "생성하고 표준 YAML parser, link 대칭성, page assignment와 mapping hash를 "
            "기계적으로 검증했다."
        ),
        "summary": {
            "page_count": summary["page_count"],
            "node_count": summary["node_count"],
            "root_count": summary["root_count"],
            "current_payload_char_count": summary["current"]["payload_char_count"],
            "candidate_payload_char_count": summary["candidate"]["payload_char_count"],
            "payload_duplication_ratio": summary["payload_duplication_ratio"],
            "same_page_boundary_count": summary["validation"][
                "same_page_boundary_count"
            ],
            "unassigned_page_count": summary["validation"]["unassigned_page_count"],
            "mapping_sha256": summary["mapping_sha256"],
            "validation_passed": summary["validation"]["valid"],
        },
        "finding": summary["finding"],
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    filtered = [item for item in experiments if item.get("id") != EXPERIMENT_ID]
    filtered.append(entry)
    if isinstance(data, dict):
        data["experiments"] = filtered
    else:
        data = filtered
    write_json(EXPERIMENTS_JSON, data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="experiments.json 기록을 건너뛴다",
    )
    args = parser.parse_args()

    pdf_path = args.pdf.resolve()
    if not pdf_path.is_file():
        raise SystemExit(f"PDF가 없다: {pdf_path}")
    plan = outline_to_plan(read_outline(pdf_path))
    if not plan:
        raise SystemExit(f"existing outline이 없다: {pdf_path}")

    total_pages, page_texts = load_page_texts(pdf_path)
    nodes = build_graph(plan, total_pages)

    reset_output_dir(CURRENT_DIR)
    baseline_root = write_legacy_current_output(nodes, page_texts)
    manifest, manifest_path = write_candidate(
        pdf_path,
        nodes,
        page_texts,
        total_pages,
    )
    validation = {
        **manifest["validation"],
        **manifest["coverage"],
        **manifest["warnings"],
    }
    current = baseline_metrics(baseline_root, nodes, page_texts)
    candidate = candidate_metrics(nodes, page_texts, validation)
    duplication_ratio = round(
        current["payload_char_count"] / candidate["payload_char_count"],
        4,
    )
    comparison = {
        "current": current,
        "candidate": candidate,
        "payload_duplication_ratio": duplication_ratio,
        "payload_char_reduction": (
            current["payload_char_count"] - candidate["payload_char_count"]
        ),
        "toc_linked_node_increase": (
            candidate["toc_linked_node_count"] - current["toc_linked_node_count"]
        ),
    }
    write_json(OUTPUT_DIR / "comparison.json", comparison)

    finding = (
        f"{pdf_path.name}: node {len(nodes)}개를 current/candidate로 생성했다. "
        f"current inclusive payload는 {current['payload_char_count']:,}자, "
        f"candidate direct payload는 {candidate['payload_char_count']:,}자로 "
        f"중복 비율은 {duplication_ratio}배였다. candidate YAML/link/관계/page "
        f"validation={validation['valid']}, same-page boundary="
        f"{validation['same_page_boundary_count']}건, unassigned page="
        f"{validation['unassigned_page_count']}개다."
    )
    summary = {
        "input_pdf": str(pdf_path.relative_to(ROOT_DIR)),
        "page_count": total_pages,
        "node_count": len(nodes),
        "root_count": manifest["root_count"],
        "current": current,
        "candidate": candidate,
        "payload_duplication_ratio": duplication_ratio,
        "mapping_sha256": manifest["mapping_sha256"],
        "manifest_path": str(manifest_path.relative_to(ROOT_DIR)),
        "validation": validation,
        "finding": finding,
    }
    write_json(OUTPUT_DIR / "summary.json", summary)

    print(finding)
    print(f"manifest: {manifest_path.relative_to(ROOT_DIR)}")
    print(f"mapping_sha256: {manifest['mapping_sha256']}")
    if not validation["valid"]:
        raise SystemExit("candidate graph validation이 실패했다")
    if not args.no_record:
        record_experiment(summary)
        print("experiments.json에 기록 완료")


if __name__ == "__main__":
    main()
