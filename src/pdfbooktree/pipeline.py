"""production bookmark 파이프라인을 analyze -> infer -> apply 세 단계로 조립한다.

이 모듈은 typography extraction부터 최종 PDF/Markdown 생성까지 이어지는
production 조립 순서가 존재하는 유일한 곳이다. ``Processor``와
``experiments/102_engine_bookmark_fuzzy_eval.py``의 ``_predict_plan()``은
모두 이 함수들을 호출해야 하며, 조립 순서를 각자 복제하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from pdfbooktree.config import MarkdownSplitConfig, ProcessingConfig, TypographyConfig
from pdfbooktree.export.markdown import export_markdown_split, export_markdown_tree
from pdfbooktree.export.pdf import export_bookmarked_pdf
from pdfbooktree.models import (
    ApplyResult,
    BookmarkInferenceResult,
    BookmarkPlanItem,
    ExistingOutlineItem,
    OutlineQualityAssessment,
    PdfAnalysis,
)
from pdfbooktree.outline.plan import insert_position_fallback, normalize_bookmark_plan
from pdfbooktree.outline.validate import validate_bookmark_plan
from pdfbooktree.pdf.outline import read_outline
from pdfbooktree.pdf.outline_quality import assess_outline_quality
from pdfbooktree.typography.bpe import infer_bpe_outline
from pdfbooktree.typography.geometry import (
    build_geometry_context,
    compute_geometry_font_tier_set,
    select_geometry_headings,
)
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts
from pdfbooktree.typography.position_fallback import select_body_tier_position_fallback
from pdfbooktree.typography.tiers import compute_tier_set
from pdfbooktree.utils.hashing import stable_json_hash


@dataclass(frozen=True)
class ExistingOutlineDecision:
    """기존 outline 유무·품질·config로 typography 추론을 건너뛸지 정한 결과다."""

    existing_outline: list[ExistingOutlineItem]
    quality: OutlineQualityAssessment | None
    reuse_existing: bool


def resolve_existing_outline_action(
    input_pdf: Path, total_pages: int, config: ProcessingConfig
) -> ExistingOutlineDecision:
    """existing-outline policy: 품질 판정을 항상 남기고, 재사용 여부만 config로 정한다.

    outline이 있으면 품질은 ``skip_existing_bookmarks`` 값과 무관하게 항상
    계산해 결과에 남긴다 - 호출자가 "왜 이 outline을 재사용/교체했는지"를
    항상 확인할 수 있어야 한다. 실제로 재사용할지는 세 조건을 모두 만족해야
    한다: outline이 있고, ``skip_existing_bookmarks``가 True이고, low
    quality라도 ``outline_quality.replace_when_low_quality``가 False다.
    """

    existing_outline = read_outline(input_pdf)
    if not existing_outline:
        return ExistingOutlineDecision(
            existing_outline=[], quality=None, reuse_existing=False
        )
    quality = assess_outline_quality(
        existing_outline, total_pages, config.outline_quality
    )
    reuse_existing = config.skip_existing_bookmarks and not (
        quality.is_low_quality and config.outline_quality.replace_when_low_quality
    )
    return ExistingOutlineDecision(
        existing_outline=existing_outline,
        quality=quality,
        reuse_existing=reuse_existing,
    )


def analyze_pdf(input_pdf: Path, config: TypographyConfig | None = None) -> PdfAnalysis:
    """PDF에서 raw ``TypographyLine``만 추출한다.

    margin exclusion, tiering, heading 선택, BPE, fallback은 여기서 하지 않는다
    - 이 함수는 여러 typography 설정이 재사용할 수 있는 비용이 큰 추출만 담당한다.
    """

    resolved = config or TypographyConfig()
    with fitz.open(input_pdf) as document:
        total_pages = document.page_count
    lines = extract_typography_lines(input_pdf, resolved)
    return PdfAnalysis(
        input_pdf=input_pdf,
        total_pages=total_pages,
        lines=lines,
        extraction_config_hash=stable_json_hash(resolved),
    )


def infer_bookmarks(
    analysis: PdfAnalysis, config: TypographyConfig | None = None
) -> BookmarkInferenceResult:
    """margin exclusion -> tier -> geometry -> heading -> BPE -> fallback -> normalize -> validate.

    PDF나 Markdown을 만들지 않는 순수 함수다.
    """

    resolved = config or TypographyConfig()
    lines = exclude_margin_artifacts(analysis.lines, resolved)
    font_tiers = compute_geometry_font_tier_set(lines)
    height_tiers = compute_tier_set(lines, "height", resolved)
    context = build_geometry_context(lines, font_tiers, resolved)
    candidates = select_geometry_headings(context, resolved)
    font_plan = normalize_bookmark_plan(infer_bpe_outline(candidates, resolved))
    fallback_candidates = (
        select_body_tier_position_fallback(context, font_plan, resolved)
        if resolved.position_fallback_enabled
        else []
    )
    plan = normalize_bookmark_plan(
        insert_position_fallback(font_plan, fallback_candidates, analysis.total_pages)
    )
    validation = validate_bookmark_plan(plan, analysis.total_pages)
    return BookmarkInferenceResult(
        lines=lines,
        font_tiers=font_tiers,
        height_tiers=height_tiers,
        heading_candidates=candidates,
        fallback_candidates=fallback_candidates,
        plan=plan,
        validation=validation,
    )


def apply_plan(
    input_pdf: Path,
    output_dir: Path,
    plan: list[BookmarkPlanItem],
    total_pages: int,
    markdown_split: MarkdownSplitConfig | None = None,
) -> ApplyResult:
    """plan을 재검증한 뒤에만 bookmarked PDF와 Markdown을 만든다.

    typography extraction과 inference는 다시 실행하지 않는다.
    """

    validation = validate_bookmark_plan(plan, total_pages)
    if not validation.valid:
        return ApplyResult(validation=validation)

    output_pdf = export_bookmarked_pdf(input_pdf, output_dir, plan)
    if markdown_split is not None:
        markdown_export = export_markdown_split(
            input_pdf, output_dir, plan, total_pages, markdown_split
        )
        output_markdown_dir = markdown_export.output_dir
    else:
        markdown_export = None
        output_markdown_dir = export_markdown_tree(
            input_pdf, output_dir, plan, total_pages
        )
    return ApplyResult(
        validation=validation,
        output_pdf=output_pdf,
        output_markdown_dir=output_markdown_dir,
        markdown_export=markdown_export,
    )
