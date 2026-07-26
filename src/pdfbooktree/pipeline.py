"""production bookmark 파이프라인을 analyze -> infer -> apply 세 단계로 조립한다.

이 모듈은 typography extraction부터 최종 PDF/Markdown 생성까지 이어지는
production 조립 순서가 존재하는 유일한 곳이다. ``Processor``와
``experiments/102_engine_bookmark_fuzzy_eval.py``의 ``_predict_plan()``은
모두 이 함수들을 호출해야 하며, 조립 순서를 각자 복제하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import time

import fitz

from pdfbooktree.config import MarkdownSplitConfig, ProcessingConfig, TypographyConfig
from pdfbooktree.export.markdown import export_markdown_split, export_markdown_tree
from pdfbooktree.export.markdown_graph import MarkdownContentMode
from pdfbooktree.export.pdf import export_bookmarked_pdf
from pdfbooktree.models import (
    ApplyResult,
    BookmarkInferenceResult,
    BookmarkPlanItem,
    BookmarkPlanValidation,
    ConfidenceSummary,
    ExistingOutlineItem,
    OutlineQualityAssessment,
    PdfAnalysis,
    TierSet,
)
from pdfbooktree.outline.plan import insert_position_fallback, normalize_bookmark_plan
from pdfbooktree.outline.validate import validate_bookmark_plan
from pdfbooktree.pdf.outline import read_outline
from pdfbooktree.pdf.outline_quality import assess_outline_quality
from pdfbooktree.processing_logger import (
    NullProcessingLogger,
    ProcessingLogEvent,
    ProcessingLogger,
)
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
from pdfbooktree.utils.hashing import file_sha256
from pdfbooktree.utils.jsonio import write_json


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


def analyze_pdf(
    input_pdf: Path,
    config: TypographyConfig | None = None,
    *,
    log: ProcessingLogger | None = None,
) -> PdfAnalysis:
    """PDF에서 raw ``TypographyLine``만 추출한다.

    margin exclusion, tiering, heading 선택, BPE, fallback은 여기서 하지 않는다
    - 이 함수는 여러 typography 설정이 재사용할 수 있는 비용이 큰 추출만 담당한다.
    """

    resolved = config or TypographyConfig()
    logger = log or NullProcessingLogger()
    started_at = time.perf_counter()
    with fitz.open(input_pdf) as document:
        total_pages = document.page_count
    logger.emit(
        ProcessingLogEvent(
            event="analysis_started",
            level="info",
            input_pdf=input_pdf,
            completed_pages=0,
            total_pages=total_pages,
            bookmark_count=0,
            elapsed_sec=0.0,
            message="typography 분석 시작",
        )
    )

    def on_page(completed_pages: int, page_count: int) -> None:
        logger.emit(
            ProcessingLogEvent(
                event="page_extracted",
                level="info",
                input_pdf=input_pdf,
                completed_pages=completed_pages,
                total_pages=page_count,
                bookmark_count=0,
                elapsed_sec=time.perf_counter() - started_at,
                message=f"PDF page {completed_pages} 추출 완료",
            )
        )

    lines = extract_typography_lines(input_pdf, resolved, on_page)
    logger.emit(
        ProcessingLogEvent(
            event="analysis_completed",
            level="info",
            input_pdf=input_pdf,
            completed_pages=total_pages,
            total_pages=total_pages,
            bookmark_count=0,
            elapsed_sec=time.perf_counter() - started_at,
            message=f"typography 분석 완료: lines={len(lines)}",
        )
    )
    return PdfAnalysis(
        input_pdf=input_pdf,
        total_pages=total_pages,
        lines=lines,
        extraction_config_hash=stable_json_hash(resolved),
    )


def validate_plan(
    input_pdf: Path | str, plan: list[BookmarkPlanItem]
) -> BookmarkPlanValidation:
    """PDF page 수를 직접 읽어 외부 bookmark plan을 쓰기 없이 검증한다."""

    input_path = Path(input_pdf)
    if not input_path.is_file():
        raise FileNotFoundError(f"입력 PDF가 없다: {input_path.resolve()}")
    with fitz.open(input_path) as document:
        total_pages = document.page_count
    return validate_bookmark_plan(plan, total_pages)


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
    markdown_content_mode: MarkdownContentMode = "direct",
    *,
    in_place: bool = False,
) -> ApplyResult:
    """plan을 재검증한 뒤에만 bookmarked PDF와 Markdown을 만든다.

    typography extraction과 inference는 다시 실행하지 않는다.
    """

    validation = validate_bookmark_plan(plan, total_pages)
    if not validation.valid:
        return ApplyResult(
            validation=validation,
            applied_plan=list(plan),
            source_bookmark_count=len(plan),
            in_place=in_place,
        )

    original_pdf_sha256 = file_sha256(input_pdf)
    if markdown_split is not None and markdown_split.enabled:
        markdown_export = export_markdown_split(
            input_pdf, output_dir, plan, total_pages, markdown_split
        )
        output_markdown_dir = markdown_export.output_dir
        chosen_level = markdown_export.chosen_level
        applied_plan = (
            [item for item in plan if item.level <= chosen_level]
            if chosen_level is not None
            else []
        )
    else:
        markdown_export = export_markdown_tree(
            input_pdf,
            output_dir,
            plan,
            total_pages,
            markdown_content_mode,
        )
        output_markdown_dir = markdown_export.output_dir
        applied_plan = list(plan)
    applied_validation = validate_bookmark_plan(applied_plan, total_pages)
    if not applied_validation.valid:
        return ApplyResult(
            validation=applied_validation,
            output_markdown_dir=output_markdown_dir,
            markdown_export=markdown_export,
            applied_plan=applied_plan,
            source_bookmark_count=len(plan),
            in_place=in_place,
            original_pdf_sha256=original_pdf_sha256,
        )
    output_pdf = export_bookmarked_pdf(
        input_pdf,
        output_dir,
        applied_plan,
        in_place=in_place,
    )
    final_pdf_sha256 = file_sha256(output_pdf)
    if in_place and markdown_export.manifest_path is not None:
        _refresh_markdown_manifest_pdf_hash(
            markdown_export.manifest_path,
            final_pdf_sha256,
        )
    return ApplyResult(
        validation=applied_validation,
        output_pdf=output_pdf,
        output_markdown_dir=output_markdown_dir,
        markdown_export=markdown_export,
        applied_plan=applied_plan,
        source_bookmark_count=len(plan),
        in_place=in_place,
        original_pdf_sha256=original_pdf_sha256,
        final_pdf_sha256=final_pdf_sha256,
    )


def _refresh_markdown_manifest_pdf_hash(
    manifest_path: Path,
    final_pdf_sha256: str,
) -> None:
    """in-place 교체 후 Markdown manifest의 input identity를 최종 PDF와 맞춘다."""

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    input_payload = payload.get("input")
    if isinstance(input_payload, dict):
        input_payload["sha256"] = final_pdf_sha256
    write_json(manifest_path, payload)


def confidence_summary_for_inference(
    inference: BookmarkInferenceResult,
) -> ConfidenceSummary:
    """``infer_bookmarks()`` 결과를 요약 신뢰도로 바꾼다.

    ``Processor``와 ``infer`` CLI가 같은 공식을 쓰도록 공유한다.
    """

    return ConfidenceSummary(
        line_extraction=1.0 if inference.lines else 0.0,
        tiering=_tiering_confidence(inference.font_tiers, inference.height_tiers),
        heading_candidates=_mean(
            [candidate.confidence for candidate in inference.heading_candidates]
            + [candidate.confidence for candidate in inference.fallback_candidates]
        ),
        outline=_mean([item.confidence for item in inference.plan]),
    )


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _tiering_confidence(font_tiers: TierSet, height_tiers: TierSet) -> float:
    counts = [
        tier_set.final_tier_count
        for tier_set in [font_tiers, height_tiers]
        if tier_set.final_tier_count
    ]
    if not counts:
        return 0.0
    return min(1.0, round(max(counts) / 4.0, 4))
