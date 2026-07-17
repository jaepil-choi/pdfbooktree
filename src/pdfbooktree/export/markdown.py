"""bookmark tree를 Markdown directory로 export한다."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from pdfbooktree.config import MarkdownSplitConfig
from pdfbooktree.export.fallback import choose_deepest_available_level
from pdfbooktree.export.markdown_graph import MarkdownContentMode, export_markdown_graph
from pdfbooktree.models import (
    BookmarkPlanItem,
    MarkdownExportResult,
    MarkdownFileStat,
)
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.utils.jsonio import write_json
from pdfbooktree.utils.paths import build_markdown_dir_path, sanitize_title_for_path
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
        manifest_path = root_dir / "manifest.json"
        write_json(
            manifest_path,
            {
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
    file_stats: list[MarkdownFileStat] = []
    for index, document in enumerate(documents, start=1):
        title = sanitize_title_for_path(document.boundary.title, max_length=60)
        path = (
            root_dir
            / f"{index:03d}_L{document.boundary.level}_p{document.start_page}_{title}.md"
        )
        path.write_text(document.markdown, encoding="utf-8")
        file_stats.append(
            MarkdownFileStat(
                path=path,
                title=document.boundary.title,
                level=document.boundary.level,
                start_pdf_page=document.start_page,
                end_pdf_page=document.end_page,
                word_count=document.word_count,
            )
        )
    statistics = _statistics(documents, config.max_words)
    overflow = [stat for stat in file_stats if stat.word_count > config.max_words]
    manifest_path = root_dir / "manifest.json"
    write_json(
        manifest_path,
        {
            "constraint_satisfied": constraint_satisfied,
            "fallback_used": fallback.used if fallback is not None else False,
            "fallback_reason": fallback.reason if fallback is not None else None,
            "chosen_level": chosen_level,
            "max_words": config.max_words,
            "max_words_coverage": config.max_words_coverage,
            "statistics": statistics,
            "levels": {
                str(level): _statistics(documents, config.max_words)
                for level, documents in trials.items()
            },
            "files": file_stats,
        },
    )
    return MarkdownExportResult(
        output_dir=root_dir,
        chosen_level=chosen_level,
        constraint_satisfied=constraint_satisfied,
        file_count=len(file_stats),
        total_word_count=sum(stat.word_count for stat in file_stats),
        fallback_used=fallback.used if fallback is not None else False,
        fallback_reason=fallback.reason if fallback is not None else None,
        word_count_stats=statistics,
        overflow_files=overflow,
        manifest_path=manifest_path,
    )


class _RenderedMarkdown:
    def __init__(
        self,
        boundary: BookmarkPlanItem,
        start_page: int,
        end_page: int,
        markdown: str,
    ) -> None:
        self.boundary = boundary
        self.start_page = start_page
        self.end_page = end_page
        self.markdown = markdown

    @property
    def word_count(self) -> int:
        return len(self.markdown.split())


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
        end_page = max(boundary.pdf_page, next_page - 1)
        lines: list[str] = []
        emitted: set[int] = set()
        for ancestor_index in _ancestor_indices(plan, start_index):
            ancestor = plan[ancestor_index]
            lines.extend([_heading(ancestor), ""])
            emitted.add(ancestor_index)
        for page in range(boundary.pdf_page, next_page):
            for index, item in enumerate(
                plan[start_index:end_index], start=start_index
            ):
                if item.pdf_page == page and index not in emitted:
                    lines.extend([_heading(item), ""])
                    emitted.add(index)
            if text := page_texts.get(page, ""):
                lines.extend([text, ""])
        rendered.append(
            _RenderedMarkdown(
                boundary=boundary,
                start_page=boundary.pdf_page,
                end_page=end_page,
                markdown="\n".join(lines).rstrip() + "\n",
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
