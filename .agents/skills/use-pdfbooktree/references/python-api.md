# pdfbooktree Python API 레퍼런스

## 목차

- [공개 import 기준](#공개-import-기준)
- [Project skill 설치](#project-skill-설치)
- [단일 PDF 고수준 처리](#단일-pdf-고수준-처리)
- [분석·추론·적용 단계](#분석추론적용-단계)
- [설정과 기존 outline](#설정과-기존-outline)
- [조사·비교·평가](#조사비교평가)
- [Batch와 실행 manifest](#batch와-실행-manifest)
- [OCR API](#ocr-api)
- [Scan 분류 API](#scan-분류-api)
- [낮은 수준 typography API](#낮은-수준-typography-api)
- [공개 결과 모델과 오류](#공개-결과-모델과-오류)

## 공개 import 기준

일반 기능은 package root에서 import하라.

```python
from pdfbooktree import Processor, ProcessingConfig
```

OCR, scan 분류, 낮은 수준 typography 기능은 각각의 공개 subpackage에서 import하라.

```python
from pdfbooktree.ocr import OcrOverlayBuilder, OcrOverlayConfig
from pdfbooktree.classify import ClassifyBatchConfig, ScanBookmarkClassifier
from pdfbooktree.typography import build_geometry_context
```

현재 공개 symbol은 각 `__init__.py`의 `__all__`을 기준으로 확인하라.

```powershell
uv run python -c "import pdfbooktree; print(*pdfbooktree.__all__, sep='`n')"
```

private module helper보다 공개 root/subpackage import를 우선하라.

공개 schema/default 상수도 외부 계약을 해석할 때 사용하라.

- `CLI_RESULT_SCHEMA_VERSION = 1`: CLI 성공/오류 envelope schema다.
- `BATCH_RUN_MANIFEST_SCHEMA_VERSION = 1`: batch run manifest schema다.
- `DEFAULT_COMPARE_PAGE_TOLERANCE = 0`: plan diff의 기본 page 허용치다.
- `DEFAULT_PAGE_TOLERANCE = 1`: gold/predicted plan match의 기본 page 허용치다.
- `DEFAULT_TITLE_SIMILARITY_THRESHOLD = 0.7`: plan 비교·평가의 기본 title 유사도다.

## Project skill 설치

Python에서 package에 번들된 skill을 설치하려면 `install_project_skill(project_dir=".", force=False) -> SkillInstallResult`를 사용하라.

```python
from pathlib import Path

from pdfbooktree import install_project_skill

result = install_project_skill(Path("my-project"))
print(result.status, result.skill_dir, result.files)
```

기본 target은 `<project_dir>/.agents/skills/use-pdfbooktree`다. 기존 target은 `SkillInstallError`로 보호하며, 전체 교체를 명시할 때만 `force=True`를 사용하라. `PROJECT_SKILL_NAME`, `PROJECT_SKILL_RELATIVE_PATH`, `SkillInstallResult`도 공개 계약으로 사용할 수 있다.

## 단일 PDF 고수준 처리

`Processor(input_pdf, output_dir, config=None).run() -> ProcessingResult`를 사용해 기존 outline 정책부터 PDF/Markdown/report 생성까지 한 번에 실행하라.

```python
from pathlib import Path

from pdfbooktree import (
    MarkdownSplitConfig,
    OutlineQualityConfig,
    ProcessingConfig,
    Processor,
)

pdf = Path("book.pdf")
config = ProcessingConfig(
    outline_quality=OutlineQualityConfig(replace_when_low_quality=True),
    markdown_split=MarkdownSplitConfig(
        max_words=10_000,
        max_words_coverage=0.95,
    ),
)
result = Processor(pdf, Path("output"), config).run()

if result.status == "failed":
    raise RuntimeError(result.warnings)
print(result.output_pdf, result.output_markdown_dir, result.bookmark_count)
```

`ProcessingResult`에서 `status`, `input_pdf`, `output_pdf`, `output_markdown_dir`, `markdown_export`, `bookmark_count`, `confidence_summary`, `warnings`, `artifact_paths`, `report_path`, `existing_outline_quality`를 검사하라. 기존 outline 재사용 경로에서는 `output_pdf`가 `None`일 수 있다.

기본 tree에서도 `markdown_export`는 `None`이 아니며 `export_mode="tree_graph"`, `output_dir`, `file_count`, `manifest_path`를 제공한다. graph manifest는 `artifact_paths["markdown_manifest"]`에도 연결된다.

`MarkdownSplitConfig`를 사용한 결과도 같은 `toc.md`, `bookmark_plan.json`, `nodes/`, `markdown_manifest.json` graph 계약을 쓴다. 이때 `markdown_export.export_mode="split"`, manifest의 `content_mode="bounded"`이며 선택된 boundary는 원래 plan order 기반 node ID를 유지한다. `inspect_plan_artifact()` 결과의 `markdown_manifest_path`와 `markdown_manifest`에서 validation, coverage, 선택 level과 fallback 여부를 node 파일 없이 확인할 수 있다.

`ProcessingConfig.ocr_policy`는 현재 `never`만 지원한다. `auto|always`는
`ConfigError`로 조기 거부된다. OCR overlay를 먼저 별도 실행하고 생성된 PDF를
`Processor` 또는 단계형 API에 전달하라.

## 분석·추론·적용 단계

다음 공개 함수를 단계별로 조합하라.

- `analyze_pdf(input_pdf: Path, config: TypographyConfig | None = None) -> PdfAnalysis`: PDF의 raw `TypographyLine`과 총 page 수를 추출한다.
- `infer_bookmarks(analysis: PdfAnalysis, config: TypographyConfig | None = None) -> BookmarkInferenceResult`: margin 제거, tiering, geometry, heading, BPE, position fallback, normalize, validation을 실행한다.
- `write_inference_artifacts(output_dir, inference, quality=None, *, input_pdf=None, total_pages=None, existing_outline=None) -> dict[str, Path]`: 원시 추론 근거와 `bookmark_review_summary.json`, `bookmark_review_items.jsonl`을 저장한다.
- `apply_plan(input_pdf, output_dir, plan, total_pages, markdown_split=None, markdown_content_mode="direct") -> ApplyResult`: plan을 다시 검증한 뒤 bookmarked PDF와 Markdown을 만든다.
- `confidence_summary_for_inference(inference) -> ConfidenceSummary`: 단계 신뢰도 요약을 만든다.

```python
from pathlib import Path

from pdfbooktree import (
    TypographyConfig,
    analyze_pdf,
    apply_plan,
    infer_bookmarks,
    write_inference_artifacts,
)

pdf = Path("book.pdf")
output = Path("output")
config = TypographyConfig(position_fallback_enabled=True)

analysis = analyze_pdf(pdf, config)
inference = infer_bookmarks(analysis, config)
artifacts = write_inference_artifacts(
    output,
    inference,
    input_pdf=pdf,
    total_pages=analysis.total_pages,
)

if not inference.validation.valid:
    raise RuntimeError(inference.validation.warnings)
applied = apply_plan(pdf, output, inference.plan, analysis.total_pages)
print(artifacts["bookmark_plan"], applied.output_pdf)
```

외부 JSON plan은 `load_bookmark_plan_json(path: Path) -> list[BookmarkPlanItem]`으로 읽어 필수 field와 타입을 검증하라.

## 설정과 기존 outline

공개 config dataclass를 조합하라.

- `ProcessingConfig`: 기존 bookmark, artifact, typography, Markdown content mode/split, outline 품질 설정을 묶는다. `ocr_policy`는 현재 `never`만 지원하고 OCR은 별도 전처리한다. `markdown_content_mode` 기본값은 `direct`이며 기존 subtree 본문 포함은 `inclusive`다.
- `TypographyConfig`: heading 후보, body font coverage, tier/BPE, margin, position fallback 값을 제어한다.
- `MarkdownSplitConfig(max_words=10000, max_words_coverage=0.95, prefer="coarsest")`: 길이 coverage 기반 Markdown split을 활성화한다.
- `OutlineQualityConfig(min_item_count=4, max_item_to_page_ratio=0.9, flag_numeric_only_titles=True, replace_when_low_quality=False)`: 기존 outline 품질과 교체 policy를 정한다.

TOML과 override가 필요하면 다음을 사용하라.

```python
from pdfbooktree import resolve_processing_config

resolved = resolve_processing_config(
    "pdfbooktree.toml",
    set_overrides=[
        "outline_quality.replace_when_low_quality=true",
        "markdown.max_words=10000",
    ],
)
print(resolved.config_hash, resolved.sources)
```

`ResolvedConfig`는 최종 `config`, JSON 가능 `data`, `config_hash`, `sources`, `source_path`를 보관한다. 병합 순서는 defaults, TOML, `cli_overrides`, `set_overrides`다.

`assess_outline_quality(items, total_pages, config=None) -> OutlineQualityAssessment`로 기존 outline 자체를 평가하라. `resolve_existing_outline_action(input_pdf, total_pages, config)`으로 실제 재사용/재추론 결정을 구하라.

## 조사·비교·평가

CLI와 같은 읽기 전용 조사 함수를 사용하라.

- `inspect_page_count(pdf_path) -> dict`
- `inspect_text(pdf_path, pages: list[int]) -> dict`
- `inspect_bookmarks(pdf_path) -> dict`
- `inspect_ocr_artifact(artifact_dir) -> dict`
- `inspect_plan_artifact(output_dir, include_items=False, limit=20, item_id=None, page_range=None, level=None, source=None, attention_only=False) -> dict`: plan/review summary와 Markdown manifest를 반환하고 요청할 때만 제한된 review item을 filter한다.
- `inspect_compare_plans(plan_a, plan_b, page_tolerance=None, title_similarity_threshold=None) -> dict`

두 in-memory plan을 비교하려면 `compare_bookmark_plans(before, after, page_tolerance=0, title_similarity_threshold=0.7) -> PlanDiffResult`를 사용하라. gold/predicted 품질 지표가 필요하면 `match_bookmark_plans(gold, predicted, page_tolerance=1, title_similarity_threshold=0.7) -> PlanMatchResult`를 사용하라.

비교 결과에서는 added/removed/matched/unchanged/moved/level changed/source changed 수와 item 상세를 확인하라. 평가 결과에서는 precision, recall, F1, Jaccard, exact-page-match rate를 확인하라.

## Batch와 실행 manifest

`BatchProcessor(input_dir, output_dir, config=None, recursive=False, log=None).run() -> BatchResult`로 directory를 처리하라. `config`에는 `ProcessingConfig` 또는 `ResolvedConfig`를 전달할 수 있다.

```python
from pathlib import Path

from pdfbooktree import BatchProcessor, resolve_processing_config

resolved = resolve_processing_config(
    set_overrides=["processing.write_artifacts=false"]
)
result = BatchProcessor(
    Path("books"),
    Path("runs"),
    resolved,
    recursive=True,
).run()
print(result.batch_run_id, result.batch_manifest_path, result.failed_count)
```

`BatchResult`의 집계와 `results: list[BatchItemResult]`를 함께 검사하라. 각 item은 `run_id`, `run_dir`, `manifest_path`, `config_hash`를 가진다.

낮은 수준 lifecycle 제어가 꼭 필요할 때만 다음을 사용하라.

- `create_run_context(input_pdf, output_root, resolved, ...) -> RunContext`
- `RunContext.start()`, `record_plan_source()`, `complete(result)`, `fail(error)`
- `create_batch_run_context(input_dir, output_root, resolved, recursive=..., pdf_paths=...) -> BatchRunContext`

일반 처리에서는 CLI, `Processor`, `BatchProcessor`가 lifecycle을 대신 관리하게 하라.

## OCR API

단일 PDF에는 `OcrOverlayConfig`와 `OcrOverlayBuilder.run() -> OcrOverlayResult`를 사용하라.

```python
from pathlib import Path

from pdfbooktree.ocr import OcrOverlayBuilder, OcrOverlayConfig

config = OcrOverlayConfig(
    input_pdf=Path("scan.pdf"),
    output_pdf=Path("output/scan_ocr.pdf"),
    output_dir=Path("output/scan_ocr_artifacts"),
    engine="upstage",
    render_dpi=300,
    pages=None,
    cache_policy="reuse",
)
result = OcrOverlayBuilder(config).run()
print(result.status, result.processed_pages, result.cache_hit_count)
```

`OcrOverlayConfig`의 핵심 field는 `input_pdf`, `output_pdf`, `output_dir`, `engine`, `engine_options`, `render_dpi`, `pages`, `force`, `confirm_bookmark_ocr_overwrite`, `cache_policy`, `stats_word_level`이다.

디렉터리에는 `OcrOverlayBatchConfig`와 `OcrOverlayBatchRunner.run() -> OcrOverlayBatchResult`를 사용하라. batch config는 추가로 `recursive`, `dry_run`, `min_page_count`, `max_sample_pages`를 제공한다. runner는 `log_mode`, `enable_log_file`, `command`를 받을 수 있다.

```python
from pathlib import Path

from pdfbooktree.ocr import OcrOverlayBatchConfig, OcrOverlayBatchRunner

config = OcrOverlayBatchConfig(
    input_dir=Path("data/300STUDY"),
    output_dir=Path("runs/300study-ocr"),
    recursive=True,
    dry_run=True,
    min_page_count=101,
)
result = OcrOverlayBatchRunner(config).run()
print(result.target_count, result.dry_run_count, result.skipped_count)
```

`min_page_count` 기본값은 `1`이고 1 이상의 정수여야 한다. `page_count >= min_page_count`인 PDF만 scanned + no meaningful bookmark 조건과 함께 OCR target이 되며, 더 짧은 PDF는 `below_min_page_count` 사유로 skip한다.

공개 OCR 결과/삽입 모델은 `OcrOverlayResult`, `OcrOverlayBatchFileResult`, `OcrOverlayBatchResult`, `OcrBox`, `InsertableOcrWord`, `InsertableOcrLine`, `InsertableOcrElement`, `InsertableOcrPage`다. 기존 bookmark overwrite 확인이 없으면 `ExistingBookmarkConfirmationRequired`가 발생할 수 있다.

## Scan 분류 API

`ClassifyBatchConfig`와 `ScanBookmarkClassifier.run() -> ClassifyBatchResult`를 사용하라.

```python
from pathlib import Path

from pdfbooktree.classify import ClassifyBatchConfig, ScanBookmarkClassifier

config = ClassifyBatchConfig(
    input_dir=Path("books"),
    output_dir=Path("classification"),
    recursive=True,
    write_report=True,
    max_sample_pages=50,
)
result = ScanBookmarkClassifier(config).run()
targets = [item for item in result.results if item.is_ocr_overwrite_target]
print(result.scanned_count, result.target_count, len(targets))
```

공개 분류 모델은 `ClassifyBatchResult`, `ClassifyFileResult`다. 진행 관찰이 필요하면 `ClassifyLogger` protocol, `ClassifyLogEvent`, `ClassifyLogMode`, `build_classify_logger`, `default_classify_log_mode`를 사용하라. `ClassifyLogMode`는 CLI와 같은 auto/rich/plain/json/none 선택을 표현한다.

## 낮은 수준 typography API

custom 분석 또는 실험에서만 `pdfbooktree.typography`를 직접 사용하라.

- `build_geometry_context`
- `classify_font_tiers_by_text_coverage`
- `compute_geometry_font_tier_set`
- `extract_geometry_headings`
- `select_geometry_headings`
- `select_body_tier_position_fallback`
- `FontCoverageProfile`, `GeometryContext`, `PositionFallbackCandidate`

일반 사용에서는 `analyze_pdf()`와 `infer_bookmarks()`가 이 순서와 불변식을 관리하게 하라.

## 공개 결과 모델과 오류

root package는 다음 model 계열을 공개한다.

- 계획/outline: `BookmarkPlanItem`, `BookmarkPlanValidation`, `BookmarkTreeNode`, `ExistingOutlineItem`, `OutlineQualityAssessment`.
- 분석/추론: `PdfAnalysis`, `TypographyLine`, `Tier`, `TierSet`, `HeadingCandidate`, `BookmarkInferenceResult`, `ConfidenceSummary`.
- 적용/Markdown: `ApplyResult`, `MarkdownExportResult`, `MarkdownFileStat`, `ProcessingResult`.
- batch/run: `BatchItemResult`, `BatchResult`, `RunManifest`, `RunContext`, `InputIdentity`, `ToolIdentity`, `BatchRunManifest`, `BatchRunContext`, `BatchRunSummary`, `BatchItemRunReference`.
- 비교/평가: `PlanDiffEntry`, `PlanDiffResult`, `MatchedPair`, `MatchMetrics`, `PlanMatchResult`.
- CLI envelope: `CommandResultEnvelope`, `CommandErrorEnvelope`, `CommandError`.

입력과 설정 오류는 `ConfigError`, `PlanError`, `RunError`, `BatchRunError`를 구분하라. pipeline이 예외 없이 끝났지만 유효한 결과를 만들지 못한 경우는 `ProcessingFailedError`로 다루라.
