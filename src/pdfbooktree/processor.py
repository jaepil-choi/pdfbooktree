"""단일 PDF 처리 파이프라인을 조립한다."""

from __future__ import annotations

from pathlib import Path

import fitz

from pdfbooktree.artifacts import write_artifact, write_jsonl_artifact
from pdfbooktree.config import ProcessingConfig
from pdfbooktree.export.markdown import (
    export_markdown_split,
    export_markdown_tree,
    plan_markdown_dir_path,
)
from pdfbooktree.export.pdf import plan_bookmarked_pdf_path
from pdfbooktree.models import (
    BookmarkInferenceResult,
    ConfidenceSummary,
    ProcessingResult,
)
from pdfbooktree.outline.validate import validate_bookmark_plan
from pdfbooktree.pdf.outline import outline_to_plan, read_outline
from pdfbooktree.pipeline import analyze_pdf, apply_plan, infer_bookmarks
from pdfbooktree.report import write_processing_report


class Processor:
    """단일 PDF를 typography 기반 bookmark/Markdown 생성 대상으로 처리한다."""

    def __init__(
        self,
        input_pdf: Path | str,
        output_dir: Path | str,
        config: ProcessingConfig | None = None,
    ) -> None:
        self.input_pdf = Path(input_pdf)
        self.output_dir = Path(output_dir)
        self.config = config or ProcessingConfig()

    def run(self) -> ProcessingResult:
        """geometry와 font coverage 기반 처리 파이프라인을 실행한다."""

        self.output_dir.mkdir(parents=True, exist_ok=True)
        with fitz.open(self.input_pdf) as document:
            total_pages = document.page_count

        existing_outline = read_outline(self.input_pdf)
        if existing_outline and self.config.skip_existing_bookmarks:
            return self._export_existing_outline(existing_outline, total_pages)

        analysis = analyze_pdf(self.input_pdf, self.config.typography)
        inference = infer_bookmarks(analysis, self.config.typography)

        artifacts = self._write_artifacts(inference)
        warnings = list(inference.validation.warnings)
        if self.config.ocr_policy != "never":
            warnings.append(
                "ocr_policy는 아직 Processor에 연결되지 않았고 OCR overlay CLI/API로 별도 실행한다."
            )

        apply_result = None
        status = "failed"
        if inference.validation.valid:
            apply_result = apply_plan(
                self.input_pdf,
                self.output_dir,
                inference.plan,
                analysis.total_pages,
                self.config.markdown_split,
            )
            status = "processed"

        result = ProcessingResult(
            status=status,
            input_pdf=self.input_pdf,
            output_pdf=(apply_result.output_pdf if apply_result else None)
            or plan_bookmarked_pdf_path(self.input_pdf, self.output_dir),
            output_markdown_dir=(
                apply_result.output_markdown_dir if apply_result else None
            )
            or plan_markdown_dir_path(self.input_pdf, self.output_dir),
            markdown_export=apply_result.markdown_export if apply_result else None,
            bookmark_count=len(inference.plan),
            confidence_summary=ConfidenceSummary(
                line_extraction=1.0 if inference.lines else 0.0,
                tiering=_tiering_confidence(
                    inference.font_tiers, inference.height_tiers
                ),
                heading_candidates=_mean(
                    [candidate.confidence for candidate in inference.heading_candidates]
                    + [
                        candidate.confidence
                        for candidate in inference.fallback_candidates
                    ]
                ),
                outline=_mean([item.confidence for item in inference.plan]),
            ),
            warnings=warnings,
            artifact_paths=artifacts,
        )
        return self._finalize(result)

    def _export_existing_outline(
        self, existing_outline, total_pages: int
    ) -> ProcessingResult:
        plan = outline_to_plan(existing_outline)
        validation = validate_bookmark_plan(plan, total_pages)
        artifacts = self._write_existing_artifacts(plan, validation)
        markdown_export = None
        if self.config.markdown_split is not None:
            markdown_export = export_markdown_split(
                self.input_pdf,
                self.output_dir,
                plan,
                total_pages,
                self.config.markdown_split,
            )
            markdown_dir = markdown_export.output_dir
        else:
            markdown_dir = export_markdown_tree(
                self.input_pdf, self.output_dir, plan, total_pages
            )
        result = ProcessingResult(
            status="processed",
            input_pdf=self.input_pdf,
            output_pdf=None,
            output_markdown_dir=markdown_dir,
            markdown_export=markdown_export,
            bookmark_count=len(plan),
            confidence_summary=ConfidenceSummary(outline=1.0),
            warnings=[
                f"기존 outline {len(plan)}개로 markdown을 export했고, PDF outline overwrite는 건너뛰었다."
            ]
            + validation.warnings,
            artifact_paths=artifacts,
        )
        return self._finalize(result)

    def _write_artifacts(self, inference: BookmarkInferenceResult) -> dict[str, Path]:
        if not self.config.write_artifacts:
            return {}
        return {
            "whole_book_lines": write_jsonl_artifact(
                self.output_dir, "whole_book_lines", inference.lines
            ),
            "font_size_tiers": write_artifact(
                self.output_dir, "font_size_tiers", inference.font_tiers
            ),
            "height_tiers": write_artifact(
                self.output_dir, "height_tiers", inference.height_tiers
            ),
            "heading_candidates": write_artifact(
                self.output_dir, "heading_candidates", inference.heading_candidates
            ),
            "position_fallback_candidates": write_artifact(
                self.output_dir,
                "position_fallback_candidates",
                inference.fallback_candidates,
            ),
            "bookmark_plan": write_artifact(
                self.output_dir, "bookmark_plan", inference.plan
            ),
            "bookmark_plan_validation": write_artifact(
                self.output_dir, "bookmark_plan_validation", inference.validation
            ),
        }

    def _write_existing_artifacts(self, plan, validation) -> dict[str, Path]:
        if not self.config.write_artifacts:
            return {}
        return {
            "existing_outline_plan": write_artifact(
                self.output_dir, "existing_outline_plan", plan
            ),
            "bookmark_plan_validation": write_artifact(
                self.output_dir, "bookmark_plan_validation", validation
            ),
        }

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
        )


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _tiering_confidence(font_tiers, height_tiers) -> float:
    counts = [
        tier_set.final_tier_count
        for tier_set in [font_tiers, height_tiers]
        if tier_set.final_tier_count
    ]
    if not counts:
        return 0.0
    return min(1.0, round(max(counts) / 4.0, 4))
