"""실험 105: 길이 제한 Markdown split의 graph 계약을 실제 PDF로 검증한다.

목적
- 현재 flat split 파일과 YAML/wiki-link/manifest를 가진 split graph 후보를 같은
  실제 PDF에서 비교한다.
- 선택된 split boundary가 원래 bookmark plan의 global order 기반 node ID를
  유지하면서 source, confidence, evidence reference를 보존하는지 검증한다.
- production 구현 전에 split 전용 page 소유권과 word-count 의미를 고정한다.

실행
    uv run python experiments/105_markdown_split_graph_contract.py
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
from pdfbooktree.utils.text_normalize import normalize_text

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "105_markdown_split_graph_contract"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
CURRENT_DIR = OUTPUT_DIR / "current"
CANDIDATE_DIR = OUTPUT_DIR / "candidate"
RESULT_PATH = OUTPUT_DIR / "result.json"
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
MAX_WORDS = 10_000
MAX_WORDS_COVERAGE = 0.95
WIKI_LINK_RE = re.compile(r"\[\[([^|\]]+)")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass
class Segment:
    """선택된 split boundary와 graph 관계를 담는다."""

    item: BookmarkPlanItem
    plan_index: int
    order: int
    node_id: str
    filename: str
    relative_path: str
    content_start_page: int | None
    content_end_page: int | None
    contained_node_ids: list[str]
    content_markdown: str
    word_count: int
    parent_id: str | None = None
    children_ids: list[str] = field(default_factory=list)
    previous_id: str | None = None
    next_id: str | None = None

    @property
    def owned_pages(self) -> list[int]:
        if self.content_start_page is None or self.content_end_page is None:
            return []
        return list(range(self.content_start_page, self.content_end_page + 1))


def reset_dir(path: Path) -> None:
    """실험 output 내부의 지정 경로만 초기화한다."""

    resolved = path.resolve()
    if OUTPUT_DIR.resolve() not in resolved.parents:
        raise RuntimeError(f"실험 output 밖의 경로는 초기화할 수 없다: {resolved}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, value: Any) -> None:
    """UTF-8 JSON을 기록한다."""

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


def load_pdf(pdf_path: Path) -> tuple[int, dict[int, str]]:
    """실제 PDF page text를 1-based mapping으로 읽는다."""

    with fitz.open(pdf_path) as document:
        return document.page_count, {
            index + 1: normalize_text(page.get_text("text"))
            for index, page in enumerate(document)
        }


def ancestor_indices(plan: list[BookmarkPlanItem], index: int) -> list[int]:
    """현재 plan item의 조상과 자기 index를 root부터 반환한다."""

    result = [index]
    expected_level = plan[index].level - 1
    for previous in range(index - 1, -1, -1):
        if plan[previous].level == expected_level:
            result.append(previous)
            expected_level -= 1
            if expected_level == 0:
                break
    return list(reversed(result))


def heading(item: BookmarkPlanItem) -> str:
    """split 본문에 넣을 Markdown heading을 만든다."""

    return f"{'#' * min(max(item.level, 1), 6)} {normalize_text(item.title)}"


def render_content(
    plan: list[BookmarkPlanItem],
    page_texts: dict[int, str],
    start_index: int,
    end_index: int,
    start_page: int,
    end_page: int,
) -> str:
    """기존 split과 동일한 heading/page 본문 payload를 만든다."""

    lines: list[str] = []
    emitted: set[int] = set()
    for index in ancestor_indices(plan, start_index):
        lines.extend([heading(plan[index]), ""])
        emitted.add(index)
    for pdf_page in range(start_page, end_page + 1):
        for index in range(start_index, end_index):
            item = plan[index]
            if item.pdf_page == pdf_page and index not in emitted:
                lines.extend([heading(item), ""])
                emitted.add(index)
        if text := page_texts.get(pdf_page, ""):
            lines.extend([f"<!-- pdf_page {pdf_page} -->", "", text, ""])
    return "\n".join(lines).rstrip() + "\n"


def level_segments(
    plan: list[BookmarkPlanItem],
    page_texts: dict[int, str],
    total_pages: int,
    level: int,
) -> list[dict[str, Any]]:
    """현재 flat split 선택과 동일한 level별 문서 후보를 만든다."""

    boundaries = [index for index, item in enumerate(plan) if item.level <= level]
    result: list[dict[str, Any]] = []
    for position, start_index in enumerate(boundaries):
        end_index = (
            boundaries[position + 1] if position + 1 < len(boundaries) else len(plan)
        )
        next_page = (
            plan[end_index].pdf_page if end_index < len(plan) else total_pages + 1
        )
        start_page = plan[start_index].pdf_page
        end_page = max(start_page, next_page - 1)
        markdown = render_content(
            plan,
            page_texts,
            start_index,
            end_index,
            start_page,
            end_page,
        )
        result.append(
            {
                "start_index": start_index,
                "end_index": end_index,
                "start_page": start_page,
                "end_page": end_page,
                "markdown": markdown,
                "word_count": sum(
                    len(line.split())
                    for line in markdown.splitlines()
                    if not line.startswith("<!-- pdf_page ")
                ),
            }
        )
    return result


def coverage(documents: list[dict[str, Any]], max_words: int) -> float:
    """max_words 이하 문서 비율을 반환한다."""

    if not documents:
        return 0.0
    return sum(item["word_count"] <= max_words for item in documents) / len(documents)


def select_level(
    trials: dict[int, list[dict[str, Any]]],
    max_words: int,
    target: float,
) -> tuple[int, bool]:
    """조건을 만족하는 가장 얕은 level 또는 가장 깊은 fallback을 고른다."""

    for level, documents in trials.items():
        if documents and coverage(documents, max_words) >= target:
            return level, True
    available = [level for level, documents in trials.items() if documents]
    if not available:
        raise RuntimeError("split 문서 후보가 없다")
    return max(available), False


def sanitize_slug(title: str, max_length: int = 64) -> str:
    """Unicode 제목을 Windows 안전 slug로 바꾼다."""

    normalized = unicodedata.normalize("NFKC", title).strip()
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE)
    normalized = re.sub(r"-+", "-", normalized).strip(" .-_")
    normalized = normalized[:max_length].rstrip(" .") or "untitled"
    if normalized.upper() in WINDOWS_RESERVED_NAMES:
        normalized = f"_{normalized}"
    return normalized


def build_segments(
    plan: list[BookmarkPlanItem],
    selected_documents: list[dict[str, Any]],
) -> list[Segment]:
    """선택된 boundary를 원래 plan order 기반 graph node로 만든다."""

    segments: list[Segment] = []
    for position, document in enumerate(selected_documents):
        start_index = document["start_index"]
        end_index = document["end_index"]
        item = plan[start_index]
        order = start_index + 1
        next_page = (
            selected_documents[position + 1]["start_page"]
            if position + 1 < len(selected_documents)
            else document["end_page"] + 1
        )
        if next_page <= document["start_page"]:
            content_start_page = None
            content_end_page = None
            content_markdown = ""
            word_count = 0
        else:
            content_start_page = document["start_page"]
            content_end_page = document["end_page"]
            content_markdown = document["markdown"]
            word_count = document["word_count"]
        filename = (
            f"{order:04d}_L{item.level}_p{item.pdf_page:04d}_"
            f"{sanitize_slug(item.title)}.md"
        )
        segments.append(
            Segment(
                item=item,
                plan_index=start_index,
                order=order,
                node_id=f"n{order:04d}",
                filename=filename,
                relative_path=(Path("nodes") / filename).as_posix(),
                content_start_page=content_start_page,
                content_end_page=content_end_page,
                contained_node_ids=[
                    f"n{index + 1:04d}" for index in range(start_index, end_index)
                ],
                content_markdown=content_markdown,
                word_count=word_count,
            )
        )

    stack: list[Segment] = []
    for segment in segments:
        while stack and stack[-1].item.level >= segment.item.level:
            stack.pop()
        if stack:
            segment.parent_id = stack[-1].node_id
            stack[-1].children_ids.append(segment.node_id)
        stack.append(segment)
    for index, segment in enumerate(segments):
        if index > 0:
            segment.previous_id = segments[index - 1].node_id
        if index + 1 < len(segments):
            segment.next_id = segments[index + 1].node_id
    return segments


def wiki_label(title: str) -> str:
    """Obsidian alias 예약 문자를 escape한다."""

    return title.replace("\\", "\\\\").replace("|", "\\|").replace("]", "\\]")


def wiki_link(segment: Segment) -> str:
    """고유 basename을 사용하는 wiki link를 만든다."""

    return f"[[{Path(segment.filename).stem}|{wiki_label(segment.item.title)}]]"


def render_front_matter(metadata: dict[str, Any]) -> str:
    """표준 YAML front matter를 만든다."""

    body = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return f"---\n{body}---\n"


def render_segment(segment: Segment, by_id: dict[str, Segment]) -> str:
    """split node의 metadata, navigation과 bounded content를 만든다."""

    metadata = {
        "schema_version": 1,
        "node_id": segment.node_id,
        "order": segment.order,
        "title": segment.item.title,
        "level": segment.item.level,
        "pdf_start_page": segment.item.pdf_page,
        "pdf_end_page": segment.content_end_page,
        "content_start_page": segment.content_start_page,
        "content_end_page": segment.content_end_page,
        "content_mode": "bounded",
        "source": segment.item.source,
        "confidence": segment.item.confidence,
        "evidence_count": len(segment.item.evidence),
        "parent_id": segment.parent_id,
        "parent": wiki_link(by_id[segment.parent_id]) if segment.parent_id else None,
        "previous_id": segment.previous_id,
        "previous": (
            wiki_link(by_id[segment.previous_id]) if segment.previous_id else None
        ),
        "next_id": segment.next_id,
        "next": wiki_link(by_id[segment.next_id]) if segment.next_id else None,
        "children": [wiki_link(by_id[item]) for item in segment.children_ids],
        "contained_plan_node_ids": segment.contained_node_ids,
        "evidence_ref": f"../bookmark_plan.json#{segment.node_id}",
    }
    lines = [
        render_front_matter(metadata).rstrip(),
        "",
        f"# {segment.item.title}",
        "",
        "## Navigation",
        "",
    ]
    for label, related_id in (
        ("Parent", segment.parent_id),
        ("Previous", segment.previous_id),
        ("Next", segment.next_id),
    ):
        value = wiki_link(by_id[related_id]) if related_id else "없음"
        lines.append(f"- {label}: {value}")
    lines.append("- Children:")
    if segment.children_ids:
        lines.extend(f"  - {wiki_link(by_id[item])}" for item in segment.children_ids)
    else:
        lines.append("  - 없음")
    lines.extend(["", "## Content", ""])
    if segment.content_markdown:
        lines.append(segment.content_markdown.rstrip())
    else:
        lines.append("이 segment가 직접 소유하는 page text는 없습니다.")
    return "\n".join(lines).rstrip() + "\n"


def write_current(
    plan: list[BookmarkPlanItem], documents: list[dict[str, Any]]
) -> list[Path]:
    """현재 flat split output을 실험 내부에서 재현한다."""

    paths: list[Path] = []
    for index, document in enumerate(documents, start=1):
        item = plan[document["start_index"]]
        path = CURRENT_DIR / (
            f"{index:03d}_L{item.level}_p{item.pdf_page}_{sanitize_slug(item.title)}.md"
        )
        path.write_text(document["markdown"], encoding="utf-8")
        paths.append(path)
    return paths


def write_candidate(
    pdf_path: Path,
    plan: list[BookmarkPlanItem],
    total_pages: int,
    segments: list[Segment],
    chosen_level: int,
    constraint_satisfied: bool,
    trials: dict[int, list[dict[str, Any]]],
    rerendered_segments: list[Segment],
) -> tuple[list[Path], dict[str, Any]]:
    """candidate split graph와 manifest를 기록한다."""

    nodes_dir = CANDIDATE_DIR / "nodes"
    nodes_dir.mkdir(parents=True, exist_ok=True)
    by_id = {segment.node_id: segment for segment in segments}
    plan_rows = [
        {
            "node_id": f"n{index:04d}",
            "order": index,
            "title": item.title,
            "level": item.level,
            "pdf_page": item.pdf_page,
            "source": item.source,
            "confidence": item.confidence,
            "evidence": item.evidence,
        }
        for index, item in enumerate(plan, start=1)
    ]
    plan_path = CANDIDATE_DIR / "bookmark_plan.json"
    write_json(plan_path, plan_rows)
    roots = [segment for segment in segments if segment.parent_id is None]
    toc_metadata = {
        "schema_version": 1,
        "document_type": "toc",
        "title": "Table of Contents",
        "node_count": len(segments),
        "root_count": len(roots),
        "content_mode": "bounded",
        "export_mode": "split",
    }
    toc_lines = [
        render_front_matter(toc_metadata).rstrip(),
        "",
        "# Table of Contents",
        "",
        "## Root nodes",
        "",
        *(f"- {wiki_link(segment)}" for segment in roots),
        "",
        "## Flat outline",
        "",
    ]
    for segment in segments:
        toc_lines.append(
            f"{'  ' * max(segment.item.level - 1, 0)}- "
            f"{wiki_link(segment)} — PDF page {segment.item.pdf_page}"
        )
    toc_path = CANDIDATE_DIR / "toc.md"
    toc_path.write_text("\n".join(toc_lines).rstrip() + "\n", encoding="utf-8")

    node_paths: list[Path] = []
    for segment in segments:
        path = CANDIDATE_DIR / segment.relative_path
        path.write_text(render_segment(segment, by_id), encoding="utf-8")
        node_paths.append(path)

    validation = validate_candidate(
        segments,
        rerendered_segments,
        node_paths,
        toc_path,
        total_pages,
    )
    manifest = {
        "schema_version": 1,
        "input": {
            "pdf_path": str(pdf_path),
            "sha256": sha256_file(pdf_path),
            "page_count": total_pages,
        },
        "plan": {"path": "bookmark_plan.json", "sha256": sha256_file(plan_path)},
        "export_mode": "split",
        "content_mode": "bounded",
        "chosen_level": chosen_level,
        "constraint_satisfied": constraint_satisfied,
        "fallback_used": not constraint_satisfied,
        "max_words": MAX_WORDS,
        "max_words_coverage": MAX_WORDS_COVERAGE,
        "word_count_semantics": (
            "본문과 plan heading을 포함하고 front matter/navigation은 제외한다"
        ),
        "node_count": len(segments),
        "root_count": len(roots),
        "nodes": snapshot(segments),
        "coverage": validation["coverage"],
        "warnings": validation["warnings"],
        "validation": validation["validation"],
        "statistics": level_statistics(trials[chosen_level], MAX_WORDS),
        "levels": {
            str(level): level_statistics(documents, MAX_WORDS)
            for level, documents in trials.items()
        },
    }
    write_json(CANDIDATE_DIR / "markdown_manifest.json", manifest)
    return node_paths, manifest


def parse_front_matter(path: Path) -> dict[str, Any]:
    """Markdown 첫 줄의 YAML front matter를 읽는다."""

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("front matter가 첫 줄에서 시작하지 않는다")
    end = lines.index("---", 1)
    loaded = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(loaded, dict):
        raise ValueError("front matter가 YAML object가 아니다")
    return loaded


def snapshot(segments: list[Segment]) -> list[dict[str, Any]]:
    """결정성과 manifest에 쓰는 node mapping을 반환한다."""

    return [
        {
            "node_id": segment.node_id,
            "order": segment.order,
            "title": segment.item.title,
            "level": segment.item.level,
            "pdf_start_page": segment.item.pdf_page,
            "pdf_end_page": segment.content_end_page,
            "content_start_page": segment.content_start_page,
            "content_end_page": segment.content_end_page,
            "relative_path": segment.relative_path,
            "parent_id": segment.parent_id,
            "children_ids": segment.children_ids,
            "previous_id": segment.previous_id,
            "next_id": segment.next_id,
            "source": segment.item.source,
            "confidence": segment.item.confidence,
            "contained_plan_node_ids": segment.contained_node_ids,
            "evidence_ref": f"../bookmark_plan.json#{segment.node_id}",
        }
        for segment in segments
    ]


def validate_candidate(
    segments: list[Segment],
    rerendered_segments: list[Segment],
    node_paths: list[Path],
    toc_path: Path,
    total_pages: int,
) -> dict[str, Any]:
    """YAML, link, 관계, identity와 page coverage를 검증한다."""

    by_id = {segment.node_id: segment for segment in segments}
    known_targets = {Path(segment.filename).stem for segment in segments}
    yaml_errors: list[str] = []
    dangling: list[str] = []
    for path in [toc_path, *node_paths]:
        try:
            parse_front_matter(path)
        except (ValueError, yaml.YAMLError) as error:
            yaml_errors.append(f"{path.name}: {error}")
        for target in WIKI_LINK_RE.findall(path.read_text(encoding="utf-8")):
            if target not in known_targets:
                dangling.append(f"{path.name}: {target}")

    relation_errors: list[str] = []
    for segment in segments:
        if (
            segment.parent_id
            and segment.node_id not in by_id[segment.parent_id].children_ids
        ):
            relation_errors.append(f"parent:{segment.parent_id}->{segment.node_id}")
        for child_id in segment.children_ids:
            if by_id[child_id].parent_id != segment.node_id:
                relation_errors.append(f"child:{segment.node_id}->{child_id}")
        if (
            segment.previous_id
            and by_id[segment.previous_id].next_id != segment.node_id
        ):
            relation_errors.append(f"previous:{segment.previous_id}->{segment.node_id}")
        if segment.next_id and by_id[segment.next_id].previous_id != segment.node_id:
            relation_errors.append(f"next:{segment.node_id}->{segment.next_id}")

    reachable: set[str] = set()
    stack = [segment.node_id for segment in segments if segment.parent_id is None]
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        stack.extend(by_id[node_id].children_ids)
    occurrences = Counter(page for segment in segments for page in segment.owned_pages)
    assigned = sorted(occurrences)
    unassigned = sorted(set(range(1, total_pages + 1)) - set(assigned))
    duplicated = sorted(page for page, count in occurrences.items() if count > 1)
    toc_targets = set(WIKI_LINK_RE.findall(toc_path.read_text(encoding="utf-8")))
    deterministic = snapshot(segments) == snapshot(rerendered_segments)
    return {
        "coverage": {
            "assigned_page_count": len(assigned),
            "unassigned_page_count": len(unassigned),
            "unassigned_pages": unassigned,
            "duplicated_page_count": len(duplicated),
            "duplicated_pages": duplicated,
            "navigation_only_node_count": sum(
                not segment.owned_pages for segment in segments
            ),
        },
        "warnings": {
            "same_page_boundary_count": sum(
                left.item.pdf_page == right.item.pdf_page
                for left, right in zip(segments, segments[1:])
            )
        },
        "validation": {
            "valid": not any(
                (
                    yaml_errors,
                    dangling,
                    relation_errors,
                    duplicated,
                    len(segments) - len(reachable),
                    known_targets - toc_targets,
                )
            )
            and deterministic,
            "yaml_file_count": len(node_paths) + 1,
            "yaml_parse_error_count": len(yaml_errors),
            "dangling_link_count": len(dangling),
            "relation_asymmetry_count": len(relation_errors),
            "duplicate_node_id_count": len(segments) - len(by_id),
            "duplicate_output_path_count": len(segments)
            - len({segment.relative_path.casefold() for segment in segments}),
            "unreachable_node_count": len(segments) - len(reachable),
            "toc_unlinked_node_count": len(known_targets - toc_targets),
            "deterministic_mapping": deterministic,
        },
    }


def level_statistics(
    documents: list[dict[str, Any]], max_words: int
) -> dict[str, int | float]:
    """level별 split word-count 통계를 만든다."""

    counts = [int(document["word_count"]) for document in documents]
    if not counts:
        return {"file_count": 0, "coverage": 0.0}
    return {
        "file_count": len(counts),
        "total_word_count": sum(counts),
        "min_word_count": min(counts),
        "max_word_count": max(counts),
        "coverage": round(coverage(documents, max_words), 4),
        "overflow_file_count": sum(count > max_words for count in counts),
    }


def record_experiment(pdf_path: Path, result: dict[str, Any]) -> None:
    """실험 registry에 결과와 판단을 기록한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    summary = result["summary"]
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "현재 flat length-limited split과 원래 plan identity를 보존하는 split "
            "graph 후보를 실제 PDF에서 비교하고 YAML, wiki link, relation, page "
            "coverage와 evidence reference 계약을 검증한다."
        ),
        "inputs": [str(pdf_path.relative_to(ROOT_DIR))],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "같은 outline plan과 max_words=10000, coverage=0.95 조건으로 현재 flat "
            "파일과 candidate nodes/toc/bookmark_plan/markdown_manifest를 생성했다."
        ),
        "summary": summary,
        "finding": (
            f"chosen_level={summary['chosen_level']}, node={summary['node_count']}, "
            f"current YAML={summary['current_yaml_file_count']}, candidate YAML="
            f"{summary['candidate_yaml_file_count']}, dangling="
            f"{summary['dangling_link_count']}, duplicated_page="
            f"{summary['duplicated_page_count']}, validation="
            f"{summary['validation_passed']}"
        ),
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    experiments = data["experiments"]
    for index, existing in enumerate(experiments):
        if existing.get("id") == EXPERIMENT_ID:
            experiments[index] = entry
            break
    else:
        experiments.append(entry)
    write_json(EXPERIMENTS_JSON, data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", nargs="?", type=Path, default=DEFAULT_PDF)
    args = parser.parse_args()
    pdf_path = args.pdf.resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"입력 PDF가 없다: {pdf_path}")

    plan = outline_to_plan(read_outline(pdf_path))
    if not plan:
        raise RuntimeError("실제 기존 outline plan이 비어 있다")
    total_pages, page_texts = load_pdf(pdf_path)
    max_level = max(item.level for item in plan)
    trials = {
        level: level_segments(plan, page_texts, total_pages, level)
        for level in range(1, max_level + 1)
    }
    chosen_level, constraint_satisfied = select_level(
        trials, MAX_WORDS, MAX_WORDS_COVERAGE
    )
    selected = trials[chosen_level]
    reset_dir(CURRENT_DIR)
    reset_dir(CANDIDATE_DIR)
    current_paths = write_current(plan, selected)
    segments = build_segments(plan, selected)
    rerendered_segments = build_segments(plan, selected)
    candidate_paths, manifest = write_candidate(
        pdf_path,
        plan,
        total_pages,
        segments,
        chosen_level,
        constraint_satisfied,
        trials,
        rerendered_segments,
    )
    current_yaml_count = 0
    for path in current_paths:
        try:
            parse_front_matter(path)
        except ValueError:
            continue
        current_yaml_count += 1
    summary = {
        "page_count": total_pages,
        "plan_item_count": len(plan),
        "chosen_level": chosen_level,
        "constraint_satisfied": constraint_satisfied,
        "node_count": len(segments),
        "current_file_count": len(current_paths),
        "candidate_file_count": len(candidate_paths),
        "current_yaml_file_count": current_yaml_count,
        "candidate_yaml_file_count": manifest["validation"]["yaml_file_count"],
        "dangling_link_count": manifest["validation"]["dangling_link_count"],
        "duplicated_page_count": manifest["coverage"]["duplicated_page_count"],
        "unassigned_page_count": manifest["coverage"]["unassigned_page_count"],
        "navigation_only_node_count": manifest["coverage"][
            "navigation_only_node_count"
        ],
        "validation_passed": manifest["validation"]["valid"],
    }
    result = {
        "experiment_id": EXPERIMENT_ID,
        "input_pdf": str(pdf_path),
        "max_words": MAX_WORDS,
        "max_words_coverage": MAX_WORDS_COVERAGE,
        "summary": summary,
    }
    write_json(RESULT_PATH, result)
    record_experiment(pdf_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
