"""단일 PDF 처리 파이프라인을 조립한다."""

from __future__ import annotations

import time
from pathlib import Path

import fitz

from pdfbooktree.artifacts import write_artifact, write_inference_artifacts
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.export.markdown import export_markdown_split, export_markdown_tree
from pdfbooktree.models import (
    BookmarkInferenceResult,
    ConfidenceSummary,
    ExistingOutlineItem,
    OutlineQualityAssessment,
    ProcessingResult,
)
from pdfbooktree.outline.validate import validate_bookmark_plan
from pdfbooktree.pdf.outline import outline_to_plan
from pdfbooktree.pipeline import (
    analyze_pdf,
    apply_plan,
    confidence_summary_for_inference,
    existing_outline_check_message,
    existing_outline_replacement_warnings,
    infer_bookmarks,
    resolve_existing_outline_action,
)
from pdfbooktree.processing_logger import (
    NullProcessingLogger,
    ProcessingLogEvent,
    ProcessingLogLevel,
    ProcessingLogger,
)
from pdfbooktree.report import write_processing_report


class Processor:
    """단일 PDF를 typography 기반 bookmark/Markdown 생성 대상으로 처리한다."""

    def __init__(
        self,
        input_pdf: Path | str,
        output_dir: Path | str,
        config: ProcessingConfig | None = None,
        log: ProcessingLogger | None = None,
        *,
        in_place: bool = False,
    ) -> None:
        self.input_pdf = Path(input_pdf)
        self.output_dir = Path(output_dir)
        self.config = config or ProcessingConfig()
        self.log = log or NullProcessingLogger()
        self.in_place = in_place
        self._started_at = 0.0
        self._total_pages = 0

    def run(self) -> ProcessingResult:
        """geometry와 font coverage 기반 처리 파이프라인을 실행한다."""

        self._started_at = time.perf_counter()
        try:
            result = self._run()
            self._emit(
                "done",
                "처리 완료",
                completed_pages=self._total_pages,
                bookmark_count=result.bookmark_count,
            )
            return result
        except Exception as error:
            self._emit("failed", f"처리 실패: {error}", level="error")
            raise
        finally:
            self.log.close()

    def _run(self) -> ProcessingResult:
        """logger lifecycle과 분리된 실제 처리 흐름이다."""

        self.output_dir.mkdir(parents=True, exist_ok=True)
        with fitz.open(self.input_pdf) as document:
            total_pages = document.page_count
        self._total_pages = total_pages

        self._emit("existing_outline_check_started", "기존 outline 확인 시작")
        decision = resolve_existing_outline_action(
            self.input_pdf, total_pages, self.config
        )
        self._emit(
            "existing_outline_check_completed",
            existing_outline_check_message(decision),
        )
        if decision.reuse_existing:
            return self._export_existing_outline(
                decision.existing_outline, total_pages, decision.quality
            )

        analysis = analyze_pdf(self.input_pdf, self.config.typography, log=self.log)
        self._emit(
            "inference_started",
            "bookmark 추론 시작",
            completed_pages=total_pages,
        )
        inference = infer_bookmarks(analysis, self.config.typography)
        self._emit(
            "inference_completed",
            f"bookmark 추론 완료: items={len(inference.plan)}, "
            f"valid={inference.validation.valid}",
            completed_pages=total_pages,
            bookmark_count=len(inference.plan),
        )

        artifacts = self._write_artifacts(
            inference,
            analysis.total_pages,
            decision.quality,
            decision.existing_outline,
            decision.reuse_rejected_reason,
        )
        if "bookmark_plan" not in artifacts:
            artifacts["bookmark_plan"] = write_artifact(
                self.output_dir, "bookmark_plan", inference.plan
            )
        artifacts["bookmark_plan_full"] = write_artifact(
            self.output_dir, "bookmark_plan_full", inference.plan
        )
        artifacts["bookmark_plan_full_validation"] = write_artifact(
            self.output_dir,
            "bookmark_plan_full_validation",
            inference.validation,
        )
        self._emit(
            "artifacts_written",
            f"추론 artifact 기록 완료: count={len(artifacts)}",
            completed_pages=total_pages,
            bookmark_count=len(inference.plan),
        )
        warnings = list(inference.validation.warnings)
        warnings.extend(existing_outline_replacement_warnings(decision))
        apply_result = None
        status = "failed"
        if inference.validation.valid:
            self._emit(
                "apply_started",
                "bookmark PDF와 Markdown 생성 시작",
                completed_pages=total_pages,
                bookmark_count=len(inference.plan),
            )
            apply_result = apply_plan(
                self.input_pdf,
                self.output_dir,
                inference.plan,
                analysis.total_pages,
                self.config.markdown_split,
                self.config.markdown_content_mode,
                in_place=self.in_place,
            )
            artifacts["bookmark_plan"] = write_artifact(
                self.output_dir,
                "bookmark_plan",
                apply_result.applied_plan,
            )
            artifacts["bookmark_plan_validation"] = write_artifact(
                self.output_dir,
                "bookmark_plan_validation",
                apply_result.validation,
            )
            if apply_result.in_place:
                artifacts["pdf_overwrite"] = write_artifact(
                    self.output_dir,
                    "pdf_overwrite",
                    {
                        "input_pdf": self.input_pdf.resolve(),
                        "original_sha256": apply_result.original_pdf_sha256,
                        "final_sha256": apply_result.final_pdf_sha256,
                        "atomic_replace": True,
                    },
                )
            status = "processed" if apply_result.validation.valid else "failed"
            warnings.extend(apply_result.validation.warnings)
            self._emit(
                "apply_completed",
                "bookmark PDF와 Markdown 생성 완료",
                completed_pages=total_pages,
                bookmark_count=len(apply_result.applied_plan),
            )
            if (
                apply_result.markdown_export is not None
                and apply_result.markdown_export.manifest_path is not None
            ):
                artifacts["markdown_manifest"] = (
                    apply_result.markdown_export.manifest_path
                )

        result = ProcessingResult(
            status=status,
            input_pdf=self.input_pdf,
            output_pdf=apply_result.output_pdf if apply_result else None,
            output_markdown_dir=(
                apply_result.output_markdown_dir if apply_result else None
            ),
            markdown_export=apply_result.markdown_export if apply_result else None,
            bookmark_count=(
                len(apply_result.applied_plan) if apply_result is not None else 0
            ),
            confidence_summary=confidence_summary_for_inference(inference),
            warnings=warnings,
            artifact_paths=artifacts,
            existing_outline_quality=decision.quality,
        )
        return self._finalize(result)

    def _export_existing_outline(
        self,
        existing_outline: list[ExistingOutlineItem],
        total_pages: int,
        quality: OutlineQualityAssessment | None,
    ) -> ProcessingResult:
        plan = outline_to_plan(existing_outline)
        validation = validate_bookmark_plan(plan, total_pages)
        artifacts = self._write_existing_artifacts(plan, validation, quality)
        self._emit(
            "artifacts_written",
            f"기존 outline artifact 기록 완료: count={len(artifacts)}",
            completed_pages=total_pages,
            bookmark_count=len(plan),
        )
        self._emit(
            "apply_started",
            "기존 outline Markdown 생성 시작",
            completed_pages=total_pages,
            bookmark_count=len(plan),
        )
        if (
            self.config.markdown_split is not None
            and self.config.markdown_split.enabled
        ):
            markdown_export = export_markdown_split(
                self.input_pdf,
                self.output_dir,
                plan,
                total_pages,
                self.config.markdown_split,
            )
            markdown_dir = markdown_export.output_dir
        else:
            markdown_export = export_markdown_tree(
                self.input_pdf,
                self.output_dir,
                plan,
                total_pages,
                self.config.markdown_content_mode,
            )
            markdown_dir = markdown_export.output_dir
        if markdown_export.manifest_path is not None:
            artifacts["markdown_manifest"] = markdown_export.manifest_path
        self._emit(
            "apply_completed",
            "기존 outline Markdown 생성 완료",
            completed_pages=total_pages,
            bookmark_count=len(plan),
        )
        warnings = [
            f"기존 outline {len(plan)}개로 markdown을 export했고, PDF outline overwrite는 건너뛰었다."
        ] + validation.warnings
        if quality is not None and quality.is_low_quality:
            warnings.append(
                "기존 outline이 low quality로 판정됐다: "
                f"reasons={quality.reasons}. "
                "outline_quality.replace_when_low_quality=true로 재추론할 수 있다."
            )
        result = ProcessingResult(
            status="processed",
            input_pdf=self.input_pdf,
            output_pdf=None,
            output_markdown_dir=markdown_dir,
            markdown_export=markdown_export,
            bookmark_count=len(plan),
            confidence_summary=ConfidenceSummary(outline=1.0),
            warnings=warnings,
            artifact_paths=artifacts,
            existing_outline_quality=quality,
        )
        return self._finalize(result)

    def _write_artifacts(
        self,
        inference: BookmarkInferenceResult,
        total_pages: int,
        quality: OutlineQualityAssessment | None = None,
        existing_outline: list[ExistingOutlineItem] | None = None,
        reuse_rejected_reason: str | None = None,
    ) -> dict[str, Path]:
        if not self.config.write_artifacts:
            return {}
        return write_inference_artifacts(
            self.output_dir,
            inference,
            quality,
            input_pdf=self.input_pdf,
            total_pages=total_pages,
            existing_outline=existing_outline,
            reuse_rejected_reason=reuse_rejected_reason,
        )

    def _write_existing_artifacts(
        self, plan, validation, quality: OutlineQualityAssessment | None = None
    ) -> dict[str, Path]:
        artifacts = {
            "bookmark_plan": write_artifact(self.output_dir, "bookmark_plan", plan),
        }
        if not self.config.write_artifacts:
            return artifacts
        artifacts.update(
            {
                "existing_outline_plan": write_artifact(
                    self.output_dir, "existing_outline_plan", plan
                ),
                "bookmark_plan_validation": write_artifact(
                    self.output_dir, "bookmark_plan_validation", validation
                ),
            }
        )
        if quality is not None:
            artifacts["existing_outline_quality"] = write_artifact(
                self.output_dir, "existing_outline_quality", quality
            )
        return artifacts

    def _finalize(self, result: ProcessingResult) -> ProcessingResult:
        report_path = write_processing_report(result, self.output_dir)
        return ProcessingResult(
            status=result.status,
            input_pdf=result.input_pdf,
            output_pdf=result.output_pdf,
            output_markdown_dir=result.output_markdown_dir,
            markdown_export=result.markdown_export,
            ocr_pdf=result.ocr_pdf,
            bookmark_count=result.bookmark_count,
            confidence_summary=result.confidence_summary,
            warnings=result.warnings,
            artifact_paths=result.artifact_paths,
            report_path=report_path,
            existing_outline_quality=result.existing_outline_quality,
        )

    def _emit(
        self,
        event: str,
        message: str,
        *,
        level: ProcessingLogLevel = "info",
        completed_pages: int = 0,
        bookmark_count: int = 0,
    ) -> None:
        self.log.emit(
            ProcessingLogEvent(
                event=event,
                level=level,
                input_pdf=self.input_pdf,
                completed_pages=completed_pages,
                total_pages=self._total_pages,
                bookmark_count=bookmark_count,
                elapsed_sec=(
                    time.perf_counter() - self._started_at if self._started_at else 0.0
                ),
                message=message,
            )
        )
