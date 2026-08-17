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
    HeadingCandidate,
    OutlineQualityAssessment,
    PdfAnalysis,
    TierSet,
)
from pdfbooktree.outline.infer import infer_outline
from pdfbooktree.outline.plan import insert_position_fallback, normalize_bookmark_plan
from pdfbooktree.outline.validate import validate_bookmark_plan
from pdfbooktree.pdf.outline import outline_to_plan, read_outline
from pdfbooktree.pdf.outline_quality import assess_outline_quality
from pdfbooktree.processing_logger import (
    NullProcessingLogger,
    ProcessingLogEvent,
    ProcessingLogger,
)
from pdfbooktree.typography.bpe import BpeHeading, infer_bpe_outline
from pdfbooktree.typography.geometry import (
    build_geometry_context,
    compute_geometry_font_tier_set,
    select_geometry_headings,
)
from pdfbooktree.typography.headings import extract_heading_candidates
from pdfbooktree.typography.lines import extract_typography_lines
from pdfbooktree.typography.margins import exclude_margin_artifacts
from pdfbooktree.typography.position_fallback import select_body_tier_position_fallback
from pdfbooktree.typography.tiers import compute_tier_set
from pdfbooktree.utils.hashing import stable_json_hash
from pdfbooktree.utils.hashing import file_sha256
from pdfbooktree.utils.jsonio import write_json
from pdfbooktree.utils.text_normalize import normalize_text


@dataclass(frozen=True)
class ExistingOutlineDecision:
    """기존 outline 유무·품질·config로 typography 추론을 건너뛸지 정한 결과다."""

    existing_outline: list[ExistingOutlineItem]
    quality: OutlineQualityAssessment | None
    reuse_existing: bool
    structure_validation: BookmarkPlanValidation | None = None
    reuse_rejected_reason: str | None = None


def resolve_existing_outline_action(
    input_pdf: Path, total_pages: int, config: ProcessingConfig
) -> ExistingOutlineDecision:
    """existing-outline policy: 품질 판정을 항상 남기고, 재사용 여부만 config로 정한다.

    outline이 있으면 품질은 ``skip_existing_bookmarks`` 값과 무관하게 항상
    계산해 결과에 남긴다 - 호출자가 "왜 이 outline을 재사용/교체했는지"를
    항상 확인할 수 있어야 한다. 재사용하려면 outline 구조가 유효해야 하며,
    다음 세 정책 조건도 모두 만족해야 한다: outline이 있고,
    ``skip_existing_bookmarks``가 True이고, low quality라도
    ``outline_quality.replace_when_low_quality``가 False다. 구조 검증
    (``structure_validation``)과 거부하면 그 사유(``reuse_rejected_reason``)도
    항상 결과에 남겨, reuse하지 않은 원인이 quality가 아니라 구조 오류였는지도
    호출자가 구분할 수 있게 한다.
    """

    existing_outline = read_outline(input_pdf)
    if not existing_outline:
        return ExistingOutlineDecision(
            existing_outline=[], quality=None, reuse_existing=False
        )
    quality = assess_outline_quality(
        existing_outline, total_pages, config.outline_quality
    )
    validation = validate_bookmark_plan(outline_to_plan(existing_outline), total_pages)
    reuse_existing = (
        validation.valid
        and config.skip_existing_bookmarks
        and not (
            quality.is_low_quality and config.outline_quality.replace_when_low_quality
        )
    )
    reuse_rejected_reason: str | None = None
    if not reuse_existing:
        if not validation.valid:
            reuse_rejected_reason = "invalid_structure"
        elif not config.skip_existing_bookmarks:
            reuse_rejected_reason = "skip_existing_bookmarks_disabled"
        else:
            reuse_rejected_reason = "low_quality_replace"
    return ExistingOutlineDecision(
        existing_outline=existing_outline,
        quality=quality,
        reuse_existing=reuse_existing,
        structure_validation=validation,
        reuse_rejected_reason=reuse_rejected_reason,
    )


def existing_outline_check_message(decision: ExistingOutlineDecision) -> str:
    """기존 outline 확인 결과를 진행 event 메시지 한 줄로 만든다.

    ``Processor``와 ``infer_to_directory()``가 같은 문구를 내보내야 하므로
    두 곳에서 문자열을 각자 조립하지 않고 이 함수를 공유한다.
    """

    message = f"기존 outline 확인 완료: items={len(decision.existing_outline)}"
    if decision.reuse_rejected_reason is None:
        return message
    return f"{message}, reuse_rejected_reason={decision.reuse_rejected_reason}"


def existing_outline_replacement_warnings(
    decision: ExistingOutlineDecision,
) -> list[str]:
    """기존 outline을 typography 추론 결과로 대체한 사유 경고를 만든다.

    quality 저하와 구조 오류는 서로 다른 원인이므로 둘 다 성립하면 두 경고를
    모두 남긴다. ``Processor``와 ``infer_to_directory()``가 같은 경고를 내야
    하므로 문구를 여기서 한 번만 정의한다.
    """

    warnings: list[str] = []
    if decision.quality is not None and decision.quality.is_low_quality:
        warnings.append(
            "기존 outline이 low quality로 판정돼 typography 추론 결과로 "
            f"교체했다: reasons={decision.quality.reasons}"
        )
    if decision.reuse_rejected_reason == "invalid_structure":
        structure_warnings = (
            decision.structure_validation.warnings
            if decision.structure_validation is not None
            else []
        )
        warnings.append(
            "기존 outline 구조가 유효하지 않아 재사용하지 못하고 typography "
            f"추론 결과로 대체했다: structure_warnings={structure_warnings}"
        )
    return warnings


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
    if candidates:
        font_plan = normalize_bookmark_plan(infer_bpe_outline(candidates, resolved))
    else:
        legacy_candidates = _select_page_strongest_heading_candidates(
            extract_heading_candidates(lines, font_tiers, height_tiers, resolved)
        )
        font_plan = normalize_bookmark_plan(infer_outline(legacy_candidates))
        candidates = _legacy_heading_candidates_to_bpe_headings(legacy_candidates)
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


def _select_page_strongest_heading_candidates(
    candidates: list[HeadingCandidate],
) -> list[HeadingCandidate]:
    """legacy 후보에서는 페이지별로 가장 강한 근거 하나만 남긴다."""

    strongest_by_page: dict[int, HeadingCandidate] = {}
    for candidate in candidates:
        current = strongest_by_page.get(candidate.pdf_page)
        if current is None or _heading_candidate_rank(
            candidate
        ) < _heading_candidate_rank(current):
            strongest_by_page[candidate.pdf_page] = candidate
    return [strongest_by_page[page] for page in sorted(strongest_by_page)]


def _heading_candidate_rank(
    candidate: HeadingCandidate,
) -> tuple[bool, bool, bool, float, float, str]:
    """동점에서도 입력 순서에 의존하지 않는 legacy 후보 우선순위다."""

    return (
        candidate.numbering_depth is None,
        "top_page_position" not in candidate.evidence,
        "bold" not in candidate.evidence,
        -candidate.confidence,
        candidate.y0,
        normalize_text(candidate.title).casefold(),
    )


def _legacy_heading_candidates_to_bpe_headings(
    candidates: list[HeadingCandidate],
) -> list[BpeHeading]:
    """legacy ``HeadingCandidate``를 ``BookmarkInferenceResult.heading_candidates``
    계약(``list[BpeHeading]``)에 맞춰 변환한다.

    ``source``는 ``infer_outline()``이 만드는 plan item의 ``source="typography"``와
    일관되게 유지하면서도, strict geometry 경로가 쓰는 ``"geometry_typography"``와는
    구분된다. ``font_tier``/``height_tier`` 중 적어도 하나는 항상 채워져 있다 -
    ``extract_heading_candidates()``가 둘 중 하나에 대한 ``large_*`` evidence가
    없는 후보는 걸러내기 때문이다.
    """

    bpe_headings: list[BpeHeading] = []
    for candidate in candidates:
        tiers = [
            tier
            for tier in (candidate.font_tier, candidate.height_tier)
            if tier is not None
        ]
        bpe_headings.append(
            BpeHeading(
                title=candidate.title,
                pdf_page=candidate.pdf_page,
                tier=min(tiers),
                y0=candidate.y0,
                y1=candidate.y1,
                merged_line_count=1,
                confidence=candidate.confidence,
                source="typography",
                evidence=tuple(candidate.evidence),
            )
        )
    return bpe_headings


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
