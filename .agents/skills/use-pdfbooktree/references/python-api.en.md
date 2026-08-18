# pdfbooktree Python API reference

[한국어](python-api.md)

## Contents

1. [Supported imports](#supported-imports)
2. [Project skill](#project-skill)
3. [High-level single-PDF workflows](#high-level-single-pdf-workflows)
4. [Analysis, inference, and application](#analysis-inference-and-application)
5. [Configuration and existing outlines](#configuration-and-existing-outlines)
6. [Inspection, comparison, and evaluation](#inspection-comparison-and-evaluation)
7. [Batch runs and manifests](#batch-runs-and-manifests)
8. [OCR](#ocr)
9. [Scan classification](#scan-classification)
10. [Typography](#typography)
11. [Serialization](#serialization)
12. [Models and errors](#models-and-errors)

## Supported imports

The supported surface is `pdfbooktree.__all__` plus `__all__` in
`pdfbooktree.ocr`, `pdfbooktree.classify`, and `pdfbooktree.typography`.
Private modules and helpers may change without compatibility guarantees.

Package/version and skill:

- `__version__`, `package_version`
- `PROJECT_SKILL_NAME`, `PROJECT_SKILL_RELATIVE_PATH`
- `SkillInstallResult`, `SkillInstallError`, `install_project_skill`

High-level workflows and core pipeline:

- `process_pdf`, `infer_pdf`, `preview_apply_plan`, `apply_plan_file`
- `ProcessingRunResult`, `ApplyPreview`
- `Processor`, `BatchProcessor`
- `analyze_pdf`, `infer_bookmarks`, `write_inference_artifacts`
- `validate_plan`, `apply_plan`, `confidence_summary_for_inference`
- `resolve_existing_outline_action`

Configuration:

- `ProcessingConfig`, `TypographyConfig`, `MarkdownSplitConfig`
- `OutlineQualityConfig`, `ResolvedConfig`
- `resolve_processing_config`, `ConfigError`

Inspection/evaluation:

- `inspect_page_count`, `inspect_text`, `inspect_bookmarks`
- `inspect_ocr_artifact`, `inspect_plan_artifact`, `inspect_compare_plans`
- `inspect_markdown_tree`, `inspect_compare_markdown`, `inspect_heading_sweep`
- `match_bookmark_plans`, `compare_bookmark_plans`
- `MatchedPair`, `MatchMetrics`, `PlanMatchResult`
- `PlanDiffEntry`, `PlanDiffResult`
- `DEFAULT_PAGE_TOLERANCE`, `DEFAULT_COMPARE_PAGE_TOLERANCE`
- `DEFAULT_TITLE_SIMILARITY_THRESHOLD`
- `assess_outline_quality`, `load_bookmark_plan_json`, `PlanError`

Run, batch, CLI, logging, and serialization:

- `create_run_context`, `RunContext`, `RunManifest`, `RunError`
- `InputIdentity`, `ToolIdentity`
- `create_batch_run_context`, `BatchRunContext`, `BatchRunManifest`
- `BatchRunSummary`, `BatchItemRunReference`, `BatchRunError`
- `BATCH_RUN_MANIFEST_SCHEMA_VERSION`
- `CLI_RESULT_SCHEMA_VERSION`, `CommandResultEnvelope`
- `CommandErrorEnvelope`, `CommandError`, `ProcessingFailedError`
- `ProcessingLogMode`, `ProcessingLogEvent`, `ProcessingLogger`
- `build_processing_logger`, `default_processing_log_mode`
- `JsonValue`, `to_jsonable`, `to_json`

Public result/model classes:

- `ProcessingResult`, `ApplyResult`, `BatchResult`, `BatchItemResult`
- `BookmarkInferenceResult`, `BookmarkPlanItem`, `BookmarkPlanValidation`
- `BookmarkTreeNode`, `ExistingOutlineItem`, `OutlineQualityAssessment`
- `PdfAnalysis`, `HeadingCandidate`, `ConfidenceSummary`
- `TypographyLine`, `Tier`, `TierSet`
- `MarkdownExportResult`, `MarkdownFileStat`
- `OptionalDependencyError`

## Project skill

```python
from pathlib import Path
from pdfbooktree import install_project_skill

result = install_project_skill(Path("."), force=False)
print(result.status, result.skill_dir, result.file_count)
```

Installation is project-scoped and refuses an existing target unless `force` is
true. The complete bundled tree is replaced atomically at the target.

## High-level single-PDF workflows

```python
process_pdf(
    input_pdf,
    output_root,
    config=None,
    log=None,
    *,
    in_place=False,
) -> ProcessingRunResult
```

This is the immutable-run facade for analysis through final PDF/Markdown
output. The returned result exposes `run_dir`, `manifest_path`, resolved
configuration, and typed artifact paths.

```python
infer_pdf(
    input_pdf,
    output_root,
    config=None,
    log=None,
) -> ProcessingRunResult
```

Inference writes a canonical plan and review artifacts but no final bookmarked
PDF or Markdown graph.

```python
preview_apply_plan(
    input_pdf,
    plan_path,
    output_root,
    config=None,
    *,
    in_place=False,
) -> ApplyPreview
```

Preview validates without creating an output root. `ApplyPreview.validation`
contains structural errors and warnings.

```python
apply_plan_file(
    input_pdf,
    plan_path,
    output_root,
    config=None,
    *,
    in_place=False,
) -> ProcessingRunResult
```

Application preserves a run-owned plan snapshot and identifies the source plan
by path and hash. Use `preview_apply_plan()` for the no-write validation path.

## Analysis, inference, and application

- `analyze_pdf(input_pdf, config=None, *, log=None) -> PdfAnalysis`
  extracts normalized typography and existing-outline context.
- `infer_bookmarks(analysis, config) -> BookmarkInferenceResult` builds a plan
  without writing final outputs.
- `write_inference_artifacts(...)` persists analysis, candidates, plan,
  validation, and review artifacts.
- `validate_plan(input_pdf, plan) -> BookmarkPlanValidation` performs no writes.
- `apply_plan(input_pdf, output_dir, plan, total_pages, markdown_split=None,
  markdown_content_mode="direct", *, in_place=False) -> ApplyResult` filters
  the embedded outline to the Markdown `chosen_level`; in-place mode atomically
  replaces the input after validating a sibling temporary PDF.
- `Processor.run()` composes the lower-level functions for compatibility.

All public pages are 1-based. Content correctness still requires review even
when structural validation succeeds.

## Configuration and existing outlines

Configuration dataclasses are frozen. Resolve from defaults/TOML/overrides with
`resolve_processing_config()`. The merge order is defaults, TOML, explicit
values, then dotted overrides. Unsupported keys/types/ranges raise
`ConfigError`.

`ProcessingConfig.ocr_policy` accepts only `never`. OCR is an explicit
preprocessing step.

`TypographyConfig.max_headings_per_page` (default `0`, disabled) drops a whole
page from heading candidates once its top-size-class candidate count exceeds
the value. `TypographyConfig.size_class_depth` (default `0`, disabled) caps
heading candidates to the top N font-size classes ranked largest-first,
within that book only. Both are book-relative on purpose: OCR overlay clamps
font size to fit each bounding box, so absolute font sizes and tier indices
mean different things across books, but "Nth largest class in this book" does
not. Measured across 6 sampled books, every book had a workable setting but
no two books needed the same one, so both knobs default to off and preserve
existing behavior.

`assess_outline_quality()` returns evidence about tiny, numeric-only, or
page-dense outlines. `resolve_existing_outline_action()` applies the policy:
meaningful outlines are reused by default, and low-quality outlines are still
reused unless `OutlineQualityConfig.replace_when_low_quality` is true.

## Inspection, comparison, and evaluation

The `inspect_*` functions are read-only and mirror the CLI:

- page count and bounded page text
- existing bookmarks
- OCR cache completeness
- plan/run/Markdown manifest review with filters
- plan-to-plan differences
- heading knob response surface (`inspect_heading_sweep`)

`match_bookmark_plans()` compares a predicted and reference plan with title
similarity and page tolerance, returning matched/missed/extra entries and
metrics. `compare_bookmark_plans()` returns a deterministic A/B diff. Embedded
outlines are weak references; metrics do not establish ground truth.

`inspect_markdown_tree(target, *, limit=20) -> dict` reads a Markdown tree
manifest (a `markdown_manifest.json` path, or a process output directory that
contains one) and returns `graph`, `levels`, `words_per_node`,
`pages_per_node`, `coverage`, `sources`, `titles`, `validation`, `findings`,
`verdict`, and `retry`. `verdict` is `"ok"` when `findings` is empty,
otherwise the `code` of the highest-severity finding, in order `invalid_graph`,
`uncovered`, `duplicated`, `thin`, `over_split`, `fragmented`. Only
`invalid_graph` and `uncovered` are `blocking`; the rest are `advisory`. Each
`retry` entry carries `cause`, `overrides`, a human-facing re-runnable
`command` string (or `None` when no config override applies), a shell-free
`command_argv` list of argv tokens (or `None` under the same condition), and a
`reason` grounded in measured corpus behavior — retries are candidates, never
guarantees. `command` is quoted with POSIX single-quoting (`shlex.quote`): it
runs as-is under bash/zsh and PowerShell, but `cmd.exe` does not treat single
quotes as quoting and can fail on paths with spaces or brackets. To run a
candidate without a shell, or under `cmd.exe`, use `command_argv` instead.

```
inspect_heading_sweep(
    pdf_path,
    *,
    size_class_depths=(1, 2, 3),
    max_headings_per_page_values=(1, 2, 3, 5, 8, 999),
    min_word_counts=(1, 2),
    base_config=None,
) -> dict
```

`inspect_heading_sweep()` runs `analyze_pdf()` exactly once, then re-evaluates
every combination of `size_class_depth` x `max_headings_per_page` x minimum
word count against the already-extracted lines, entirely in memory — no
`process` output artifact is written. This lets an agent see the parameter
response surface without repeating full `process` runs. The result carries
`settings` (per-combination `candidate_count`, `pages_with_candidate_count`,
`pages_per_candidate`) and `summary` (`plausible_settings` within a sensible
pages-per-candidate range, and a `*_direction` per knob:
`increases_candidates`, `decreases_candidates`, `mixed`, or `no_effect`).
Raising `max_headings_per_page` never decreases the candidate count, so that
direction is safe to hill-climb.

```python
from pdfbooktree import inspect_heading_sweep

sweep = inspect_heading_sweep("book.pdf")
print(sweep["summary"]["plausible_settings"])
print(sweep["summary"]["max_headings_per_page_direction"])
```

`inspect_compare_markdown(manifest_a, manifest_b) -> dict` compares two
Markdown manifests by `(level, pdf_start_page, normalized title)` node keys
and returns `before`, `after` (each with `node_count`, `chosen_level`,
`words_per_node_median` (`None` when the export has no word_count signal),
`words_per_node_has_data`, `pages_per_node_mean`, `unassigned_ratio`,
`fragment_ratio`, `verdict`), and `delta` (the numeric differences plus
`verdict_changed`, `added_node_count`, `removed_node_count`).
`words_per_node_median` in `delta` is only computed when both sides have a
word_count signal; otherwise it is `None`.

## Batch runs and manifests

`BatchProcessor.run()` processes a directory and returns `BatchResult`.
`create_run_context()` and `create_batch_run_context()` create immutable
contexts that own resolved configuration, input identity, status, summaries,
errors, and artifact references. Always complete or fail a context through its
public methods so manifests remain internally consistent.

Batch resume, persistent analysis cache, and parallel jobs are outside the
v0.1.0 scope.

## OCR

Install `pdfbooktree[ocr]` for live use. Public imports from
`pdfbooktree.ocr` are:

- `OcrOverlayConfig`, `OcrOverlayBuilder`, `OcrOverlayResult`
- `OcrOverlayBatchConfig`, `OcrOverlayBatchRunner`
- `OcrOverlayBatchFileResult`, `OcrOverlayBatchResult`
- `OcrBox`, `InsertableOcrWord`, `InsertableOcrLine`
- `InsertableOcrElement`, `InsertableOcrPage`
- `ExistingBookmarkConfirmationRequired`

The v0.1.0 engine is Upstage Document Parse only. Each page is rendered to PNG
and sent externally on a live call. The configured environment variable
defaults to `UPSTAGE_API_KEY`; `.env` is searched upward from the working
directory without overriding existing environment variables. Charges apply and
raw cache may contain sensitive content.

Input and output must differ. Existing output and PDFs with bookmarks require
their explicit confirmation controls. Cache policies are `reuse`, `refresh`,
and `only`.

## Scan classification

Public imports from `pdfbooktree.classify`:

- `ClassifyBatchConfig`, `ScanBookmarkClassifier`
- `ClassifyBatchResult`, `ClassifyFileResult`
- `ClassifyLogMode`, `ClassifyLogEvent`, `ClassifyLogger`
- `build_classify_logger`, `default_classify_log_mode`

Classification uses visible-image/text and bookmark evidence to select OCR
candidates. It does not initiate paid OCR calls.

## Typography

Public imports from `pdfbooktree.typography`:

- `FontCoverageProfile`, `GeometryContext`, `PositionFallbackCandidate`
- `build_geometry_context`
- `classify_font_tiers_by_text_coverage`
- `compute_geometry_font_tier_set`
- `extract_geometry_headings`, `select_geometry_headings`
- `select_body_tier_position_fallback`

These are lower-level geometry APIs. Prefer high-level workflows unless
intermediate typography objects are required.

## Serialization

```python
to_jsonable(value) -> JsonValue
to_json(value, *, ensure_ascii=True, indent=None, sort_keys=False) -> str
```

Dataclasses become objects, `Path` becomes a string, tuples/lists become arrays,
and mappings require string keys. Unsupported values and non-finite floats are
rejected rather than silently converted.

## Models and errors

Public models are frozen dataclasses unless documented otherwise. Treat result
paths as optional when an operation can legitimately skip an artifact—for
example, existing-outline reuse may create Markdown without a rewritten PDF.

Catch narrow public errors:

- `ConfigError` for configuration
- `PlanError` for plan loading
- `OptionalDependencyError` for missing extras
- `SkillInstallError` for project skill installation
- `RunError` and `BatchRunError` for manifest lifecycle
- `CommandError`/`ProcessingFailedError` when composing CLI contracts
- `ExistingBookmarkConfirmationRequired` for OCR overwrite protection

Use `to_jsonable()` when transporting result dataclasses and follow manifest
artifact paths instead of relying on internal module layouts.
