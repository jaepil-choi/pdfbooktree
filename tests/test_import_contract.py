"""공개 import 계약을 검증한다."""

from __future__ import annotations

import pdfbooktree


def test_public_import_contract() -> None:
    assert pdfbooktree.Processor is not None
    assert pdfbooktree.BatchProcessor is not None
    assert pdfbooktree.ProcessingConfig is not None
    assert pdfbooktree.TypographyConfig is not None
    assert pdfbooktree.resolve_processing_config is not None
    assert pdfbooktree.create_run_context is not None
    assert pdfbooktree.create_batch_run_context is not None
    assert pdfbooktree.BatchItemResult is not None
    assert pdfbooktree.BatchRunManifest is not None
    assert pdfbooktree.BATCH_RUN_MANIFEST_SCHEMA_VERSION == 1
    assert pdfbooktree.RunManifest is not None
    assert pdfbooktree.analyze_pdf is not None
    assert pdfbooktree.infer_bookmarks is not None
    assert pdfbooktree.apply_plan is not None
    assert pdfbooktree.PdfAnalysis is not None
    assert pdfbooktree.BookmarkInferenceResult is not None
    assert pdfbooktree.ApplyResult is not None
    assert pdfbooktree.CLI_RESULT_SCHEMA_VERSION == 1
    assert pdfbooktree.CommandError is not None
    assert pdfbooktree.CommandErrorEnvelope is not None
    assert pdfbooktree.CommandResultEnvelope is not None
    assert pdfbooktree.ProcessingFailedError is not None
    assert pdfbooktree.OutlineQualityConfig is not None
    assert pdfbooktree.OutlineQualityAssessment is not None
    assert pdfbooktree.assess_outline_quality is not None
    assert pdfbooktree.resolve_existing_outline_action is not None
    assert pdfbooktree.load_bookmark_plan_json is not None
    assert pdfbooktree.PlanError is not None
    assert pdfbooktree.write_inference_artifacts is not None
    assert pdfbooktree.confidence_summary_for_inference is not None
    assert pdfbooktree.install_project_skill is not None
    assert pdfbooktree.SkillInstallResult is not None
    assert pdfbooktree.SkillInstallError is not None
    assert pdfbooktree.PROJECT_SKILL_NAME == "use-pdfbooktree"
    assert str(pdfbooktree.PROJECT_SKILL_RELATIVE_PATH).replace("\\", "/") == (
        ".agents/skills/use-pdfbooktree"
    )
