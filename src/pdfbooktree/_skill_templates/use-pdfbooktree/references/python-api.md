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
- [결과 직렬화](#결과-직렬화)
- [공개 결과 모델과 오류](#공개-결과-모델과-오류)

## 공개 import 기준

일반 기능은 package root에서 import하라.

```python
from pdfbooktree import (
    __version__,
    ProcessingConfig,
    package_version,
    process_pdf,
)
```

`__version__`과 `package_version()`은 설치 package metadata version을 반환한다.

OCR, scan 분류, 낮은 수준 typography 기능은 각각의 공개 subpackage에서 import하라.

```python
from pdfbooktree.ocr import OcrOverlayBuilder, OcrOverlayConfig
from pdfbooktree.classify import ClassifyBatchConfig, ScanBookmarkClassifier
from pdfbooktree.typography import build_geometry_context
```

root와 공개 subpackage의 `__all__`에 포함된 symbol은 의도적으로 지원하는 공개
API다. root가 고수준 workflow뿐 아니라 단계형 API, 결과 모델과 lifecycle
타입까지 다시 export하는 것은 편의 facade 계약이다. 공개 API 여부를 module
깊이나 이름만으로 추측하지 말고 다음 `__all__`을 기준으로 판단하라.

- `pdfbooktree.__all__`
- `pdfbooktree.ocr.__all__`
- `pdfbooktree.classify.__all__`
- `pdfbooktree.typography.__all__`

그 밖의 직접 module import와 underscore-prefixed helper에는 호환성을 기대하지
마라.

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

Python에서 package에 번들된 skill을 설치하려면 `install_project_skill(project_dir=".", force=False) -> SkillInstallResult`를, 제거하려면 `uninstall_project_skill(project_dir=".") -> SkillUninstallResult`를 사용하라.

```python
from pathlib import Path

from pdfbooktree import install_project_skill, uninstall_project_skill

result = install_project_skill(Path("my-project"))
print(result.status, result.skill_dir, result.files)

removed = uninstall_project_skill(Path("my-project"))
print(removed.status, removed.removed_skill_dirs)
```

기본 target은 `<project_dir>/.agents/skills/use-pdfbooktree`다. 기존 target은 `SkillInstallError`로 보호하며, 전체 교체를 명시할 때만 `force=True`를 사용하라. `PROJECT_SKILL_NAME`, `PROJECT_SKILL_RELATIVE_PATH`, `SkillInstallResult`도 공개 계약으로 사용할 수 있다.

설치는 `AGENTS.md`와 `CLAUDE.md`에 marker로 감싼 짧은 pointer block도 심어서 skill을 discoverable하게 만든다. 다시 설치하면 그 block만 그 자리에서 교체한다. `uninstall_project_skill`은 install의 정확한 역이다. 두 skill directory는 `SKILL.md` frontmatter의 `name`이 `use-pdfbooktree`일 때만 지우고, `AGENTS.md`/`CLAUDE.md`에서는 marker block만 제거하며 block 제거로 파일이 비면 파일 자체를 지운다. 아무것도 설치돼 있지 않으면 오류 대신 `status="not_installed"`를 반환하고, 반복 호출도 안전하다.

## 단일 PDF 고수준 처리

CLI와 같은 immutable run, resolved config와 manifest lifecycle이 필요하면 다음
고수준 workflow를 사용하라.

- `process_pdf(input_pdf, output_root, config=None, log=None, *, in_place=False) -> ProcessingRunResult`
- `infer_pdf(input_pdf, output_root, config=None, log=None) -> ProcessingRunResult`
- `preview_apply_plan(input_pdf, plan_path, output_root, config=None, *, in_place=False) -> ApplyPreview`
- `apply_plan_file(input_pdf, plan_path, output_root, config=None, *, in_place=False) -> ProcessingRunResult`

```python
from pathlib import Path

from pdfbooktree import (
    apply_plan_file,
    infer_pdf,
    preview_apply_plan,
)

pdf = Path("book.pdf")
inferred = infer_pdf(pdf, Path("runs"))
plan = inferred.result.bookmark_plan_path
assert plan is not None

preview = preview_apply_plan(pdf, plan, Path("runs"))
assert preview.validation.valid
applied = apply_plan_file(pdf, plan, Path("runs"))
print(applied.run_id, applied.manifest_path, applied.result.output_pdf)
```

`ProcessingRunResult`는 `command`, `run_id`, `run_dir`, `manifest_path`,
`config_hash`, 최종 `manifest`, 실제 `result`를 제공한다. plain
`ProcessingConfig` 입력은 `sources=[{"kind": "python_api"}]`와 안정된 hash로
정규화되며 `ResolvedConfig` 입력은 기존 source/hash를 보존한다.

`ApplyPreview`는 input/plan path와 SHA-256, page/bookmark 수, validation, 예상
PDF/Markdown 경로를 반환하며 output root나 run directory를 만들지 않는다.
`apply_plan_file()`은 외부 plan path/hash를 manifest `plan_source`에 기록하고
동일 내용을 run root `bookmark_plan.json`에 복사한다.

flat directory에 직접 쓰는 호환 흐름이 필요할 때만
`Processor(input_pdf, output_dir, config=None, log=None).run()`을 사용하라.

`ProcessingResult`에서 `status`, `input_pdf`, `output_pdf`,
`output_markdown_dir`, `markdown_export`, `bookmark_count`,
`confidence_summary`, `warnings`, `artifact_paths`, `report_path`,
`existing_outline_quality`를 검사하라. 다음 typed property는 기존 mapping key의
`Path`를 반환하고 artifact가 없으면 `None`이다.

- `bookmark_plan_path`
- `bookmark_validation_path`
- `review_summary_path`
- `review_items_path`
- `markdown_manifest_path`
- `existing_outline_quality_path`

모든 non-dry-run `process`, `infer`, `apply` run은 선택·적용한 plan을 run root
`bookmark_plan.json`에 보존한다. 기존 outline 재사용도 예외가 아니다. 기존
outline 근거용 `existing_outline_plan.json`은 별도 artifact로 유지한다.

기존 outline 재사용 경로에서는 `output_pdf`가 `None`일 수 있다.

기본 tree에서도 `markdown_export`는 `None`이 아니며 `export_mode="tree_graph"`, `output_dir`, `file_count`, `manifest_path`를 제공한다. graph manifest는 `artifact_paths["markdown_manifest"]`에도 연결된다.

`MarkdownSplitConfig`를 사용한 결과도 같은 `toc.md`, `bookmark_plan.json`, `nodes/`, `markdown_manifest.json` graph 계약을 쓴다. 이때 `markdown_export.export_mode="split"`, manifest의 `content_mode="bounded"`이며 선택된 boundary는 원래 plan order 기반 node ID를 유지한다. `inspect_plan_artifact()` 결과의 `markdown_manifest_path`와 `markdown_manifest`에서 validation, coverage, 선택 level과 fallback 여부를 node 파일 없이 확인할 수 있다.

`ProcessingConfig.ocr_policy`는 현재 `never`만 지원한다. `auto|always`는
`ConfigError`로 조기 거부된다. OCR overlay를 먼저 별도 실행하고 생성된 PDF를
`process_pdf()` 또는 단계형 API에 전달하라. 실제 OCR API에는
`python -m pip install "pdfbooktree[ocr]"`가 필요하고 extra가 없으면
`OptionalDependencyError`가 `extra`, `missing_packages`, `install_command`를
보존한다.

## 분석·추론·적용 단계

다음 공개 함수를 단계별로 조합하라.

- `analyze_pdf(input_pdf: Path, config: TypographyConfig | None = None, *, log=None) -> PdfAnalysis`: PDF의 raw `TypographyLine`과 총 page 수를 추출하고 optional page progress를 전달한다.
- `infer_bookmarks(analysis: PdfAnalysis, config: TypographyConfig | None = None) -> BookmarkInferenceResult`: margin 제거, tiering, geometry, heading, BPE, position fallback, normalize, validation을 실행한다.
- `write_inference_artifacts(output_dir, inference, quality=None, *, input_pdf=None, total_pages=None, existing_outline=None) -> dict[str, Path]`: 원시 추론 근거와 `bookmark_review_summary.json`, `bookmark_review_items.jsonl`을 저장한다.
- `apply_plan(input_pdf, output_dir, plan, total_pages, markdown_split=None, markdown_content_mode="direct", *, in_place=False) -> ApplyResult`: plan을 다시 검증하고 Markdown `chosen_level` 이하만 PDF outline에 적용한다. `in_place=True`면 검증된 sibling temporary PDF로 입력을 atomic 교체한다.
- `validate_plan(input_pdf, plan) -> BookmarkPlanValidation`: PDF page 수를 직접 읽고 외부 plan을 쓰기 없이 검증한다.
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
- `TypographyConfig`: heading 후보, body font coverage, tier/BPE, margin, position fallback 값을 제어한다. `max_headings_per_page`(기본 `0`=비활성화)는 한 page의 top-size-class heading 후보 수가 이 값을 넘으면 그 page 전체를 후보에서 제외한다. `size_class_depth`(기본 `0`=비활성화)는 책 내부에서 큰 순서로 상위 몇 번째 font-size class까지 heading 후보로 볼지 정하는 책 상대값이다. 두 값 모두 절대 font size/tier 번호가 아니라 책 내부에서만 비교하는 상대값이며(OCR overlay가 책마다 다른 지점에서 font size를 clamp하기 때문), corpus 6권 실측에서 책마다 다른 설정이 필요해 단일 정답 기본값이 없다.
- `MarkdownSplitConfig(enabled=True, max_words=10000, max_words_coverage=0.95, prefer="coarsest")`: 기본 활성화되는 길이 coverage 기반 Markdown split이다. `enabled=False`면 full tree graph를 사용한다.
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
- `inspect_heading_sweep(pdf_path, *, size_class_depths=(1, 2, 3), max_headings_per_page_values=(1, 2, 3, 5, 8, 999), min_word_counts=(1, 2), base_config=None) -> dict`: typography를 정확히 한 번만 분석(`analyze_pdf`)하고 이후 `size_class_depth` x `max_headings_per_page` x 최소 단어 수 조합을 이미 추출한 line에 대해 메모리 안에서만 재평가한다. `process`의 output artifact는 만들지 않는다. 결과는 `settings`(조합별 `candidate_count`, `pages_with_candidate_count`, `pages_per_candidate`)와 `summary`(`plausible_settings`, knob별 `*_direction`: `increases_candidates`/`decreases_candidates`/`mixed`/`no_effect`)를 담는다. `max_headings_per_page`를 올리면 candidate가 줄지 않으므로 이 방향은 항상 단조 hill-climb 가능하다.
- `inspect_markdown_tree(target, *, limit=20) -> dict`: Markdown tree manifest(`markdown_manifest.json` 경로 또는 process output directory)를 조사해 `graph`, `levels`, `words_per_node`, `pages_per_node`, `coverage`, `sources`, `titles`, `validation`과 함께 `findings`, `verdict`, `retry`를 반환한다. `verdict`는 `findings`가 비어 있으면 `"ok"`이고, 그렇지 않으면 severity 순서(`invalid_graph`, `uncovered`, `duplicated`, `thin`, `over_split`, `fragmented`) 상 가장 먼저 오는 finding의 `code`다. blocking severity는 `invalid_graph`, `uncovered`뿐이고 나머지는 advisory다. 각 finding은 `code`, `severity`, `detail`, `cause`를 가지며 `cause`는 `graph_contract_violation`, `pages_outside_any_node`, `pages_owned_by_multiple_nodes`, `reused_existing_outline`, `sparse_heading_candidates`, `heading_candidates_too_permissive`, `non_heading_text_selected` 중 하나다. `retry`의 각 항목은 `cause`, `overrides`, 사람이 읽는 `command`(재실행 가능한 `pdfbooktree process ...` 문자열, override가 없으면 `None`), shell 없이 그대로 실행 가능한 `command_argv`(argv 문자열 list, override가 없으면 `None`), 실측 근거를 담은 `reason`을 담으며 항상 보장이 아닌 재시도 후보로만 제시한다. `command`는 POSIX single-quoting(`shlex.quote`)을 써서 bash/zsh와 PowerShell에서는 그대로 실행되지만, cmd.exe는 작은따옴표를 quoting으로 취급하지 않아 공백/괄호가 섞인 경로에서 실패할 수 있다. shell 없이 실행하거나 cmd.exe에서 실행할 때는 `command_argv`를 써라.
- `inspect_compare_markdown(manifest_a, manifest_b) -> dict`: 두 Markdown manifest를 `(level, pdf_start_page, normalized title)` 키로 비교해 `before`, `after`, `delta`를 반환한다. `before`/`after`는 각각 `node_count`, `chosen_level`, `words_per_node_median`(word_count signal이 없는 export에서는 `None`), `words_per_node_has_data`, `pages_per_node_mean`, `unassigned_ratio`, `fragment_ratio`, `verdict`를 담고, `delta`는 그 수치 차이와 `verdict_changed`, `added_node_count`, `removed_node_count`를 담는다. `words_per_node_median`의 delta는 양쪽 다 word_count signal이 있을 때만 계산하고, 한쪽이라도 없으면 `None`이다.

두 in-memory plan을 비교하려면 `compare_bookmark_plans(before, after, page_tolerance=0, title_similarity_threshold=0.7) -> PlanDiffResult`를 사용하라. gold/predicted 품질 지표가 필요하면 `match_bookmark_plans(gold, predicted, page_tolerance=1, title_similarity_threshold=0.7) -> PlanMatchResult`를 사용하라.

비교 결과에서는 added/removed/matched/unchanged/moved/level changed/source changed 수와 item 상세를 확인하라. 평가 결과에서는 precision, recall, F1, Jaccard, exact-page-match rate를 확인하라.

```python
from pdfbooktree import (
    inspect_compare_markdown,
    inspect_heading_sweep,
    inspect_markdown_tree,
)

sweep = inspect_heading_sweep("book.pdf")
print(sweep["summary"]["plausible_settings"])
print(sweep["summary"]["max_headings_per_page_direction"])

inspection = inspect_markdown_tree("runs/book/book_markdown_split", limit=20)
if inspection["verdict"] != "ok":
    for candidate in inspection["retry"]:
        print(candidate["cause"], candidate["command"], candidate["reason"])

comparison = inspect_compare_markdown(
    "runs/book/book_markdown_split/markdown_manifest.json",
    "runs/book-retry/book_markdown_split/markdown_manifest.json",
)
print(comparison["delta"]["verdict_changed"], comparison["delta"]["node_count"])
```

## Batch와 실행 manifest

`BatchProcessor(input_dir, output_dir, config=None, recursive=False, log=None, *, include_globs=(), exclude_globs=()).run() -> BatchResult`로 directory를 처리하라. `config`에는 `ProcessingConfig` 또는 `ResolvedConfig`를 전달할 수 있다. glob은 상대 POSIX 경로에 case-insensitive로 적용되고 output subtree는 자동 제외된다.

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

**v0.1.0은 Upstage Document Parse 전용이다.** `engine="upstage"`만 지원하며
custom OCR provider 등록·주입 API는 없다. 다른 engine 이름은 실행 시
`ValueError`로 거부된다. provider 확장성을 추측해 private registry나 engine
Protocol을 import하지 마라.

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

디렉터리에는 `OcrOverlayBatchConfig`와 `OcrOverlayBatchRunner.run() -> OcrOverlayBatchResult`를 사용하라. batch config는 추가로 `recursive`, `dry_run`, `min_page_count`, `max_sample_pages`, `include_globs`, `exclude_globs`를 제공한다. runner는 `log_mode`, `enable_log_file`, `command`를 받을 수 있다.

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

`ClassifyBatchConfig`와 `ScanBookmarkClassifier.run() -> ClassifyBatchResult`를 사용하라. directory selection에는 `include_globs`와 `exclude_globs`를 사용할 수 있다.

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

## 결과 직렬화

공개 dataclass 결과, manifest와 중첩 모델을 JSON API, message queue 또는 저장소로
전달할 때 root의 두 함수를 사용하라.

- `to_jsonable(value) -> JsonValue`: Python JSON 호환 값으로 변환한다.
- `to_json(value, *, ensure_ascii=False, indent=None) -> str`: 표준 JSON 문자열로
  직렬화한다.

```python
import json

from pdfbooktree import process_pdf, to_json, to_jsonable

result = process_pdf("book.pdf", "runs")
payload = to_jsonable(result)
assert json.loads(to_json(result)) == payload
```

변환 규칙은 다음과 같다.

- dataclass → field 이름을 key로 갖는 object
- `Path` → 문자열
- tuple/list → array
- dict key → 문자열
- `Enum` → 해당 value를 같은 규칙으로 재귀 변환
- `None`, boolean, int, finite float, string → 같은 JSON scalar

지원하지 않는 객체는 `TypeError`, `NaN`과 Infinity는 `ValueError`로 거부한다.
조용한 `str()` fallback은 없으므로 계약 밖의 값을 놓치지 않는다. 결과 schema가
필요하면 변환된 top-level field와 함께 해당 model 및 manifest의
`schema_version` 계약을 사용하라.

## 공개 결과 모델과 오류

root package는 다음 model 계열을 공개한다.

- 계획/outline: `BookmarkPlanItem`, `BookmarkPlanValidation`, `BookmarkTreeNode`, `ExistingOutlineItem`, `OutlineQualityAssessment`.
- 분석/추론: `PdfAnalysis`, `TypographyLine`, `Tier`, `TierSet`, `HeadingCandidate`, `BookmarkInferenceResult`, `ConfidenceSummary`.
- 적용/Markdown: `ApplyResult`, `MarkdownExportResult`, `MarkdownFileStat`, `ProcessingResult`.
- batch/run: `BatchItemResult`, `BatchResult`, `RunManifest`, `RunContext`, `InputIdentity`, `ToolIdentity`, `BatchRunManifest`, `BatchRunContext`, `BatchRunSummary`, `BatchItemRunReference`.
- progress: `ProcessingLogEvent`, `ProcessingLogger`, `ProcessingLogMode`, `build_processing_logger`, `default_processing_log_mode`.
- 비교/평가: `PlanDiffEntry`, `PlanDiffResult`, `MatchedPair`, `MatchMetrics`, `PlanMatchResult`.
- CLI envelope: `CommandResultEnvelope`, `CommandErrorEnvelope`, `CommandError`.

입력과 설정 오류는 `ConfigError`, `PlanError`, `RunError`, `BatchRunError`를 구분하라. pipeline이 예외 없이 끝났지만 유효한 결과를 만들지 못한 경우는 `ProcessingFailedError`로 다루라.
