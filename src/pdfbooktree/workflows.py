"""CLI와 Python이 공유하는 재현 가능한 단일 PDF workflow다."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import fitz

from pdfbooktree.artifacts import write_artifact, write_inference_artifacts
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.config_io import ResolvedConfig, resolve_config_input
from pdfbooktree.export.markdown import plan_markdown_dir_path
from pdfbooktree.export.pdf import plan_bookmarked_pdf_path
from pdfbooktree.models import (
    BookmarkPlanValidation,
    BookmarkPlanItem,
    ConfidenceSummary,
    ProcessingResult,
)
from pdfbooktree.outline.plan_io import load_bookmark_plan_json
from pdfbooktree.outline.validate import validate_bookmark_plan
from pdfbooktree.pdf.outline import outline_to_plan
from pdfbooktree.pipeline import (
    analyze_pdf,
    apply_plan,
    confidence_summary_for_inference,
    infer_bookmarks,
    resolve_existing_outline_action,
    validate_plan,
)
from pdfbooktree.processing_logger import (
    NullProcessingLogger,
    ProcessingLogEvent,
    ProcessingLogLevel,
    ProcessingLogger,
)
from pdfbooktree.processor import Processor
from pdfbooktree.report import write_processing_report
from pdfbooktree.run import RunManifest, create_run_context
from pdfbooktree.utils.hashing import file_sha256


WorkflowCommand = Literal["process", "infer", "apply"]


@dataclass(frozen=True)
class ProcessingRunResult:
    """immutable run identity와 실제 처리 결과를 함께 반환한다."""

    command: WorkflowCommand
    run_id: str
    run_dir: Path
    manifest_path: Path
    config_hash: str
    manifest: RunManifest
    result: ProcessingResult


@dataclass(frozen=True)
class ApplyPreview:
    """파일 생성 없이 plan 적용 결과 경로와 구조 검증을 예측한다."""

    status: Literal["valid", "failed"]
    dry_run: Literal[True]
    input_pdf: Path
    input_sha256: str
    plan_path: Path
    plan_sha256: str
    total_pages: int
    bookmark_count: int
    validation: BookmarkPlanValidation
    planned_output_pdf: Path
    planned_output_markdown_dir: Path
    config_hash: str


def process_pdf(
    input_pdf: Path | str,
    output_root: Path | str,
    config: ProcessingConfig | ResolvedConfig | None = None,
    log: ProcessingLogger | None = None,
) -> ProcessingRunResult:
    """단일 PDF를 immutable run에서 끝까지 처리한다."""

    resolved = resolve_config_input(config)
    run = create_run_context(
        input_pdf,
        output_root,
        resolved,
        repository_root=Path.cwd(),
    )
    run.start()
    try:
        result = Processor(
            input_pdf,
            run.run_dir,
            resolved.config,
            log=log,
        ).run()
        manifest = run.complete(result)
    except Exception as error:
        run.fail(error)
        raise
    return _processing_run_result("process", run.manifest_path, manifest, result)


def infer_pdf(
    input_pdf: Path | str,
    output_root: Path | str,
    config: ProcessingConfig | ResolvedConfig | None = None,
    log: ProcessingLogger | None = None,
) -> ProcessingRunResult:
    """bookmark plan과 review artifact를 immutable run에 생성한다."""

    resolved = resolve_config_input(config)
    run = create_run_context(
        input_pdf,
        output_root,
        resolved,
        repository_root=Path.cwd(),
    )
    run.start()
    try:
        result = infer_to_directory(
            Path(input_pdf),
            run.run_dir,
            resolved.config,
            log,
        )
        manifest = run.complete(result)
    except Exception as error:
        run.fail(error)
        raise
    return _processing_run_result("infer", run.manifest_path, manifest, result)


def preview_apply_plan(
    input_pdf: Path | str,
    plan_path: Path | str,
    output_root: Path | str,
    config: ProcessingConfig | ResolvedConfig | None = None,
) -> ApplyPreview:
    """외부 plan의 구조와 예상 output을 파일 생성 없이 확인한다."""

    resolved = resolve_config_input(config)
    pdf = Path(input_pdf).resolve()
    plan_file = Path(plan_path).resolve()
    output_dir = Path(output_root)
    plan = load_bookmark_plan_json(plan_file)
    validation = validate_plan(pdf, plan)
    with fitz.open(pdf) as document:
        total_pages = document.page_count
    return ApplyPreview(
        status="valid" if validation.valid else "failed",
        dry_run=True,
        input_pdf=pdf,
        input_sha256=file_sha256(pdf),
        plan_path=plan_file,
        plan_sha256=file_sha256(plan_file),
        total_pages=total_pages,
        bookmark_count=len(plan),
        validation=validation,
        planned_output_pdf=plan_bookmarked_pdf_path(pdf, output_dir),
        planned_output_markdown_dir=plan_markdown_dir_path(pdf, output_dir),
        config_hash=resolved.config_hash,
    )


def apply_plan_file(
    input_pdf: Path | str,
    plan_path: Path | str,
    output_root: Path | str,
    config: ProcessingConfig | ResolvedConfig | None = None,
) -> ProcessingRunResult:
    """외부 bookmark plan을 immutable run에서 적용한다."""

    resolved = resolve_config_input(config)
    plan_file = Path(plan_path).resolve()
    plan = load_bookmark_plan_json(plan_file)
    run = create_run_context(
        input_pdf,
        output_root,
        resolved,
        repository_root=Path.cwd(),
    )
    run.start()
    run.record_plan_source(plan_file, file_sha256(plan_file))
    try:
        result = apply_plan_to_directory(
            Path(input_pdf),
            run.run_dir,
            plan,
            resolved.config,
        )
        manifest = run.complete(result)
    except Exception as error:
        run.fail(error)
        raise
    return _processing_run_result("apply", run.manifest_path, manifest, result)


def infer_to_directory(
    pdf: Path,
    output_dir: Path,
    config: ProcessingConfig,
    log: ProcessingLogger | None = None,
) -> ProcessingResult:
    """기존 outline 정책을 적용해 plan과 근거만 지정 directory에 쓴다."""

    logger = log or NullProcessingLogger()
    started_at = time.perf_counter()
    total_pages = 0

    def emit(
        event: str,
        message: str,
        *,
        level: ProcessingLogLevel = "info",
        completed_pages: int = 0,
        bookmark_count: int = 0,
    ) -> None:
        logger.emit(
            ProcessingLogEvent(
                event=event,
                level=level,
                input_pdf=pdf,
                completed_pages=completed_pages,
                total_pages=total_pages,
                bookmark_count=bookmark_count,
                elapsed_sec=time.perf_counter() - started_at,
                message=message,
            )
        )

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with fitz.open(pdf) as document:
            total_pages = document.page_count

        emit("existing_outline_check_started", "기존 outline 확인 시작")
        decision = resolve_existing_outline_action(pdf, total_pages, config)
        emit(
            "existing_outline_check_completed",
            f"기존 outline 확인 완료: items={len(decision.existing_outline)}",
        )
        if decision.reuse_existing:
            plan = outline_to_plan(decision.existing_outline)
            validation = validate_bookmark_plan(plan, total_pages)
            artifacts: dict[str, Path] = {
                "bookmark_plan": write_artifact(output_dir, "bookmark_plan", plan),
            }
            if config.write_artifacts:
                artifacts["existing_outline_plan"] = write_artifact(
                    output_dir, "existing_outline_plan", plan
                )
                artifacts["bookmark_plan_validation"] = write_artifact(
                    output_dir, "bookmark_plan_validation", validation
                )
                if decision.quality is not None:
                    artifacts["existing_outline_quality"] = write_artifact(
                        output_dir, "existing_outline_quality", decision.quality
                    )
            warnings = [
                f"기존 outline {len(plan)}개를 재사용했고 typography 추론은 실행하지 않았다."
            ] + validation.warnings
            if decision.quality is not None and decision.quality.is_low_quality:
                warnings.append(
                    "기존 outline이 low quality로 판정됐다: "
                    f"reasons={decision.quality.reasons}. "
                    "outline_quality.replace_when_low_quality=true로 재추론할 수 있다."
                )
            result = ProcessingResult(
                status="skipped",
                input_pdf=pdf,
                bookmark_count=len(plan),
                confidence_summary=ConfidenceSummary(outline=1.0),
                warnings=warnings,
                artifact_paths=artifacts,
                existing_outline_quality=decision.quality,
            )
            emit(
                "artifacts_written",
                f"기존 outline artifact 기록 완료: count={len(artifacts)}",
                completed_pages=total_pages,
                bookmark_count=len(plan),
            )
        else:
            analysis = analyze_pdf(pdf, config.typography, log=logger)
            emit("inference_started", "bookmark 추론 시작", completed_pages=total_pages)
            inference = infer_bookmarks(analysis, config.typography)
            emit(
                "inference_completed",
                f"bookmark 추론 완료: items={len(inference.plan)}, "
                f"valid={inference.validation.valid}",
                completed_pages=total_pages,
                bookmark_count=len(inference.plan),
            )
            artifacts = (
                write_inference_artifacts(
                    output_dir,
                    inference,
                    decision.quality,
                    input_pdf=pdf,
                    total_pages=analysis.total_pages,
                    existing_outline=decision.existing_outline,
                )
                if config.write_artifacts
                else {}
            )
            if "bookmark_plan" not in artifacts:
                artifacts["bookmark_plan"] = write_artifact(
                    output_dir, "bookmark_plan", inference.plan
                )
            emit(
                "artifacts_written",
                f"추론 artifact 기록 완료: count={len(artifacts)}",
                completed_pages=total_pages,
                bookmark_count=len(inference.plan),
            )
            warnings = list(inference.validation.warnings)
            if decision.quality is not None and decision.quality.is_low_quality:
                warnings.append(
                    "기존 outline이 low quality로 판정돼 typography 추론 결과로 "
                    f"교체했다: reasons={decision.quality.reasons}"
                )
            result = ProcessingResult(
                status="processed" if inference.validation.valid else "failed",
                input_pdf=pdf,
                bookmark_count=len(inference.plan),
                confidence_summary=confidence_summary_for_inference(inference),
                warnings=warnings,
                artifact_paths=artifacts,
                existing_outline_quality=decision.quality,
            )
        report_path = write_processing_report(result, output_dir)
        final_result = replace(result, report_path=report_path)
        emit(
            "done",
            "bookmark plan 추론 완료",
            completed_pages=total_pages,
            bookmark_count=result.bookmark_count,
        )
        return final_result
    except Exception as error:
        emit("failed", f"bookmark plan 추론 실패: {error}", level="error")
        raise
    finally:
        logger.close()


def apply_plan_to_directory(
    pdf: Path,
    output_dir: Path,
    plan: list[BookmarkPlanItem],
    config: ProcessingConfig,
) -> ProcessingResult:
    """검증된 plan으로 PDF와 Markdown을 지정 directory에 생성한다."""

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, Path] = {
        "bookmark_plan": write_artifact(output_dir, "bookmark_plan", plan),
    }
    with fitz.open(pdf) as document:
        total_pages = document.page_count
    apply_result = apply_plan(
        pdf,
        output_dir,
        plan,
        total_pages,
        config.markdown_split,
        config.markdown_content_mode,
    )
    if config.write_artifacts:
        artifacts["bookmark_plan_validation"] = write_artifact(
            output_dir, "bookmark_plan_validation", apply_result.validation
        )
    if (
        apply_result.markdown_export is not None
        and apply_result.markdown_export.manifest_path is not None
    ):
        artifacts["markdown_manifest"] = apply_result.markdown_export.manifest_path
    result = ProcessingResult(
        status="processed" if apply_result.validation.valid else "failed",
        input_pdf=pdf,
        output_pdf=apply_result.output_pdf,
        output_markdown_dir=apply_result.output_markdown_dir,
        markdown_export=apply_result.markdown_export,
        bookmark_count=len(plan),
        confidence_summary=ConfidenceSummary(outline=1.0),
        warnings=list(apply_result.validation.warnings),
        artifact_paths=artifacts,
    )
    report_path = write_processing_report(result, output_dir)
    return replace(result, report_path=report_path)


def _processing_run_result(
    command: WorkflowCommand,
    manifest_path: Path,
    manifest: RunManifest,
    result: ProcessingResult,
) -> ProcessingRunResult:
    return ProcessingRunResult(
        command=command,
        run_id=manifest.run_id,
        run_dir=manifest.run_dir,
        manifest_path=manifest_path,
        config_hash=manifest.config_hash,
        manifest=manifest,
        result=result,
    )
