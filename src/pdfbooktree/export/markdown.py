"""bookmark tree를 Markdown directory로 export한다."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from pdfbooktree.config import MarkdownSplitConfig
from pdfbooktree.export.fallback import choose_deepest_available_level
from pdfbooktree.export.markdown_graph import (
    MARKDOWN_MANIFEST_SCHEMA_VERSION,
    MarkdownContentMode,
    MarkdownSplitGraphDocument,
    export_markdown_graph,
    export_markdown_split_graph,
)
from pdfbooktree.models import (
    BookmarkPlanItem,
    MarkdownExportResult,
)
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.utils.jsonio import write_json
from pdfbooktree.utils.paths import build_markdown_dir_path
from pdfbooktree.utils.text_normalize import normalize_text


def plan_markdown_dir_path(input_pdf: Path, output_dir: Path) -> Path:
    """Markdown tree 출력 디렉터리 경로를 만든다."""

    return build_markdown_dir_path(input_pdf, output_dir)


def export_markdown_tree(
    input_pdf: Path,
    output_dir: Path,
    plan: list[BookmarkPlanItem],
    total_pages: int,
    content_mode: MarkdownContentMode = "direct",
) -> MarkdownExportResult:
    """bookmark plan을 progressive disclosure Markdown graph로 export한다."""

    return export_markdown_graph(
        input_pdf,
        output_dir,
        plan,
        total_pages,
        content_mode,
    )


def export_markdown_split(
    input_pdf: Path,
    output_dir: Path,
    plan: list[BookmarkPlanItem],
    total_pages: int,
    config: MarkdownSplitConfig,
) -> MarkdownExportResult:
    """coverage 조건을 만족하는 가장 얕은 level로 단일 Markdown 파일을 export한다."""

    if config.max_words <= 0:
        raise ValueError("max_words는 1 이상이어야 한다")
    if not 0 < config.max_words_coverage <= 1:
        raise ValueError("max_words_coverage는 0보다 크고 1 이하여야 한다")
    root_dir = output_dir / f"{input_pdf.stem}_markdown_split"
    root_dir.mkdir(parents=True, exist_ok=True)
    page_texts = {
        page.pdf_page: normalize_text(page.text)
        for page in extract_page_texts(input_pdf, max_pages=total_pages)
    }
    max_level = max((item.level for item in plan), default=0)
    trials: dict[int, list[_RenderedMarkdown]] = {
        level: _render_split_documents(plan, page_texts, total_pages, level)
        for level in range(1, max_level + 1)
    }
    chosen_level = next(
        (
            level
            for level, documents in trials.items()
            if documents
            and _coverage(documents, config.max_words) >= config.max_words_coverage
        ),
        None,
    )
    constraint_satisfied = chosen_level is not None
    fallback = choose_deepest_available_level(trials) if chosen_level is None else None
    if fallback is not None:
        chosen_level = fallback.chosen_level
    if chosen_level is None:
        manifest_path = root_dir / "markdown_manifest.json"
        write_json(
            manifest_path,
            {
                "schema_version": MARKDOWN_MANIFEST_SCHEMA_VERSION,
                "export_mode": "split",
                "content_mode": "bounded",
                "node_count": 0,
                "root_count": 0,
                "constraint_satisfied": False,
                "fallback_used": False,
                "fallback_reason": (fallback.reason if fallback is not None else None),
                "max_words": config.max_words,
                "max_words_coverage": config.max_words_coverage,
                "levels": {
                    str(level): _statistics(documents, config.max_words)
                    for level, documents in trials.items()
                },
            },
        )
        return MarkdownExportResult(
            output_dir=root_dir,
            chosen_level=None,
            constraint_satisfied=False,
            file_count=0,
            total_word_count=0,
            fallback_used=False,
            fallback_reason=(fallback.reason if fallback is not None else None),
            manifest_path=manifest_path,
        )
    documents = trials[chosen_level]
    split_documents = [
        MarkdownSplitGraphDocument(
            item=document.boundary,
            order=document.plan_index + 1,
            content_start_page=document.content_start_page,
            content_end_page=document.content_end_page,
            content_markdown=document.markdown,
            word_count=document.word_count,
            contained_plan_node_ids=[
                f"n{index + 1:04d}"
                for index in range(document.plan_index, document.end_index)
            ],
        )
        for document in documents
    ]
    return export_markdown_split_graph(
        input_pdf,
        output_dir,
        plan,
        total_pages,
        page_texts,
        split_documents,
        chosen_level=chosen_level,
        constraint_satisfied=constraint_satisfied,
        fallback_used=fallback.used if fallback is not None else False,
        fallback_reason=fallback.reason if fallback is not None else None,
        max_words=config.max_words,
        max_words_coverage=config.max_words_coverage,
        word_count_stats=_statistics(documents, config.max_words),
        level_statistics={
            str(level): _statistics(level_documents, config.max_words)
            for level, level_documents in trials.items()
        },
    )


class _RenderedMarkdown:
    def __init__(
        self,
        boundary: BookmarkPlanItem,
        plan_index: int,
        end_index: int,
        content_start_page: int | None,
        content_end_page: int | None,
        markdown: str,
        word_count: int,
    ) -> None:
        self.boundary = boundary
        self.plan_index = plan_index
        self.end_index = end_index
        self.content_start_page = content_start_page
        self.content_end_page = content_end_page
        self.markdown = markdown
        self._word_count = word_count

    @property
    def start_page(self) -> int:
        return self.boundary.pdf_page

    @property
    def end_page(self) -> int:
        return self.content_end_page or self.boundary.pdf_page

    @property
    def word_count(self) -> int:
        return self._word_count


def _render_split_documents(
    plan: list[BookmarkPlanItem],
    page_texts: dict[int, str],
    total_pages: int,
    level: int,
) -> list[_RenderedMarkdown]:
    boundaries = [index for index, item in enumerate(plan) if item.level <= level]
    rendered: list[_RenderedMarkdown] = []
    for position, start_index in enumerate(boundaries):
        end_index = (
            boundaries[position + 1] if position + 1 < len(boundaries) else len(plan)
        )
        boundary = plan[start_index]
        next_page = (
            plan[end_index].pdf_page if end_index < len(plan) else total_pages + 1
        )
        content_start_page = (
            boundary.pdf_page if next_page > boundary.pdf_page else None
        )
        content_end_page = next_page - 1 if content_start_page is not None else None
        lines: list[str] = []
        emitted: set[int] = set()
        word_count = 0
        for ancestor_index in _ancestor_indices(plan, start_index):
            ancestor = plan[ancestor_index]
            heading = _heading(ancestor)
            lines.extend([heading, ""])
            word_count += len(heading.split())
            emitted.add(ancestor_index)
        if content_start_page is not None and content_end_page is not None:
            for page in range(content_start_page, content_end_page + 1):
                for index, item in enumerate(
                    plan[start_index:end_index], start=start_index
                ):
                    if item.pdf_page == page and index not in emitted:
                        heading = _heading(item)
                        lines.extend([heading, ""])
                        word_count += len(heading.split())
                        emitted.add(index)
                if text := page_texts.get(page, ""):
                    lines.extend([f"<!-- pdf_page {page} -->", "", text, ""])
                    word_count += len(text.split())
        # 다음 boundary와 같은 page에 있는 하위 heading은 현재 segment에 속하지만
        # page 본문은 다음 segment가 소유한다. 본문을 복제하지 않고 heading만 보존한다.
        for index, item in enumerate(plan[start_index:end_index], start=start_index):
            if index not in emitted:
                heading = _heading(item)
                lines.extend([heading, ""])
                word_count += len(heading.split())
                emitted.add(index)
        rendered.append(
            _RenderedMarkdown(
                boundary=boundary,
                plan_index=start_index,
                end_index=end_index,
                content_start_page=content_start_page,
                content_end_page=content_end_page,
                markdown=("\n".join(lines).rstrip() + "\n" if lines else ""),
                word_count=word_count,
            )
        )
    return rendered


def _ancestor_indices(plan: list[BookmarkPlanItem], index: int) -> list[int]:
    item = plan[index]
    result = [index]
    expected_level = item.level - 1
    for previous in range(index - 1, -1, -1):
        if plan[previous].level == expected_level:
            result.append(previous)
            expected_level -= 1
            if expected_level == 0:
                break
    return list(reversed(result))


def _heading(item: BookmarkPlanItem) -> str:
    return f"{'#' * min(max(item.level, 1), 6)} {normalize_text(item.title)}"


def _coverage(documents: list[_RenderedMarkdown], max_words: int) -> float:
    return sum(document.word_count <= max_words for document in documents) / len(
        documents
    )


def _statistics(
    documents: list[_RenderedMarkdown], max_words: int
) -> dict[str, int | float | None]:
    counts = [document.word_count for document in documents]
    if not counts:
        return {"file_count": 0, "coverage": 0.0}
    return {
        "file_count": len(counts),
        "total_word_count": sum(counts),
        "min_word_count": min(counts),
        "p50_word_count": int(np.percentile(counts, 50)),
        "p90_word_count": int(np.percentile(counts, 90)),
        "p95_word_count": int(np.percentile(counts, 95)),
        "max_word_count": max(counts),
        "mean_word_count": round(float(np.mean(counts)), 1),
        "coverage": round(_coverage(documents, max_words), 4),
        "overflow_file_count": sum(count > max_words for count in counts),
    }
