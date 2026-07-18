# 계약과 artifact

## 목차

- [Page와 bookmark plan](#page와-bookmark-plan)
- [단일 실행 디렉터리](#단일-실행-디렉터리)
- [추론 artifact](#추론-artifact)
- [최종 PDF와 Markdown](#최종-pdf와-markdown)
- [Batch와 분류 report](#batch와-분류-report)
- [OCR artifact와 cache](#ocr-artifact와-cache)
- [설정 계약](#설정-계약)
- [CLI stream과 종료 코드](#cli-stream과-종료-코드)

## Page와 bookmark plan

- 외부 PDF page는 항상 1-based로 해석하라. `inspect text --pages`, `BookmarkPlanItem.pdf_page`, Markdown metadata, OCR `pages`가 모두 같은 convention을 사용한다.
- plan JSON 항목의 필수 field는 `title: str`, `level: int`, `pdf_page: int`다.
- `level`은 1 이상의 계층 깊이로 사용하고 plan 순서를 문서 순서로 유지하라.
- 추가 근거인 `source`, `confidence`, `evidence`를 보존하라. 수동 수정 과정에서 버리지 마라.
- 외부 plan은 `load_bookmark_plan_json()` 또는 `apply`로 검증하라.
- 파일 생성 전에는 `validate_plan()` 또는 `apply --dry-run`으로 PDF page 범위와 level 구조를 쓰기 없이 검증하라.

## 단일 실행 디렉터리

기본 `process`, `infer`, `apply`는 output root 아래 입력 identity와 run identity가 포함된 immutable directory를 만든다. 명령이 반환한 절대 `run_dir`과 `manifest_path`를 사용하고 경로를 추측하지 마라.

주요 파일은 다음과 같다.

- `run_manifest.json`: created → running → succeeded/failed lifecycle, 입력 SHA-256/크기/page 수, package/git identity, config hash, artifact/output/report path, warning, 오류를 기록한다.
- `config.resolved.json`: 실제 실행에 사용한 최종 versioned config다.
- `<input-stem>_report.json`: `ProcessingResult` 직렬화 결과다.
- `bookmark_plan.json`: 해당 run이 선택·적용한 plan의 immutable canonical
  snapshot이다. non-dry-run `process`, `infer`, `apply`에 항상 존재한다.
- `apply` manifest의 `plan_source`: plan path와 SHA-256이다.

재현 가능한 실행에는 기본 mode를 사용하라. `--flat-output`은 기존 flat path가 필요한 호환 작업에만 사용하라.

## 추론 artifact

`infer`, `Processor`, `write_inference_artifacts()`는 다음 근거를 같은 이름으로 저장한다.

| Key | 파일 | 의미 |
| --- | --- | --- |
| `whole_book_lines` | `whole_book_lines.jsonl` | 모든 추출 typography line |
| `font_size_tiers` | `font_size_tiers.json` | font size tier 계산 결과 |
| `height_tiers` | `height_tiers.json` | bbox height tier 계산 결과 |
| `heading_candidates` | `heading_candidates.json` | BPE/geometry heading 후보 |
| `position_fallback_candidates` | `position_fallback_candidates.json` | body-tier 위치 rescue 후보 |
| `bookmark_plan` | `bookmark_plan.json` | 적용 가능한 계층 plan |
| `bookmark_plan_validation` | `bookmark_plan_validation.json` | valid, item count, warning |
| `existing_outline_quality` | `existing_outline_quality.json` | 기존 outline이 있을 때의 품질 판단 |
| `bookmark_review_summary` | `bookmark_review_summary.json` | level/source 분포, candidate mapping, text 통계와 attention 우선순위 |
| `bookmark_review_items` | `bookmark_review_items.jsonl` | plan item별 candidate geometry, 주변 line, page preview와 evidence 위치 |

plan이 의심스러우면 review summary를 먼저 읽고 `inspect plan --attention-only --limit N`, `--item-id`, `--page-range`, `--level`, `--source`로 필요한 item만 연 뒤 heading/fallback 후보, tier와 원문 page를 확인하라. attention signal과 confidence는 내용 품질 판정이나 정확도 확률이 아니다.

같은 source/page/title candidate가 여러 개면 plan normalization이 보존한 첫 후보가 canonical `candidate_ref`가 되고 나머지는 `candidate_alternative_refs`에 남는다. `duplicate_candidates_collapsed` signal은 근거 손실 없는 eye-check 지점이다.

`ProcessingResult`는 기존 `artifact_paths` mapping을 유지하면서
`bookmark_plan_path`, `bookmark_validation_path`, `review_summary_path`,
`review_items_path`, `markdown_manifest_path`, `existing_outline_quality_path`
typed property를 제공한다. 없는 artifact의 property는 `None`이다.

## 최종 PDF와 Markdown

- typography plan을 적용한 PDF는 `<input-stem>_bookmarked.pdf`다.
- 기본 Markdown tree는 `<input-stem>_markdown/` progressive graph이며 root에 `toc.md`, `bookmark_plan.json`, `markdown_manifest.json`, `nodes/`를 둔다.
- 각 node는 `NNNN_L<level>_p<page>_<title>.md` 고유 파일이며 표준 YAML front matter와 parent/children/previous/next wiki link를 포함한다.
- 기본 `processing.markdown_content_mode=direct`에서는 다음 bookmark 전까지의 page만 node 본문에 둔다. 같은 page의 여러 bookmark는 plan상 마지막 item이 page를 소유하고 앞선 item은 navigation-only node가 된다.
- 기존 subtree 본문 중복이 필요할 때만 `processing.markdown_content_mode=inclusive`를 명시한다.
- `markdown_manifest.json`에서 node mapping, source/confidence/evidence reference, assigned/unassigned/empty/duplicated page와 graph validation을 확인하라.
- `MarkdownExportResult.export_mode=tree_graph`이며 `manifest_path`가 graph manifest를 가리킨다. run manifest도 이를 `artifact_paths.markdown_manifest`로 연결한다.
- length coverage split도 `<input-stem>_markdown_split/` 아래 `toc.md`, `bookmark_plan.json`, `markdown_manifest.json`, `nodes/`를 가진 graph다. 선택된 boundary 파일은 원래 plan의 global order를 유지한 `NNNN_L<level>_p<page>_<title>.md`이며 `export_mode=split`, `content_mode=bounded`를 사용한다.
- split node의 `contained_plan_node_ids`로 해당 segment에 포함된 plan 범위를 확인하라. 같은 page의 연속 boundary는 마지막 export node만 본문을 소유하고 앞선 node는 navigation-only가 된다.
- split manifest의 `chosen_level`, `constraint_satisfied`, `fallback_used`, `fallback_reason`, word-count statistics, overflow file과 graph validation을 함께 확인하라. word count는 본문과 plan heading을 포함하고 front matter, navigation, page marker는 제외한다.
- `inspect plan <RUN_OR_OUTPUT_DIR> --summary --format json`은 review summary와 `markdown_manifest_path`, schema/export mode, validation, coverage, manifest warning을 반환한다. item selector/filter를 쓰면 `bookmark_review_items.jsonl`만 읽어 제한된 item detail을 반환하며 `whole_book_lines.jsonl` 전체 scan은 필요하지 않다.
- 기존 outline 재사용 경로는 Markdown을 만들지만 outline을 덮어쓴 PDF는 만들지 않는다.

## Batch와 분류 report

구조화 `batch`는 batch 자체의 immutable directory와 manifest를 만들고 item run을 연결한다.

- `batch_run_id`, selection hash, config hash, discovered PDF 목록을 확인하라.
- manifest의 include/exclude glob과 자동 제외된 output subtree를 함께 확인하라. `.PDF` 확장자는 대소문자를 구분하지 않는다.
- `summary.completed_count`와 processed/skipped/failed 집계를 확인하라.
- 각 `item_runs[]`의 `run_id`, `manifest_path`, `output_paths`를 따라가라.

`classify-scan`은 다음 report를 만든다.

- `classification_report.csv`: spreadsheet 친화 요약이다.
- `classification_detail.jsonl`: 파일별 상세와 sampled page signal이다.
- `classification_summary.json`: native/scanned/target/error 집계다.

PDF 하나의 오류가 batch 전체를 멈추지 않을 수 있으므로 최종 exit뿐 아니라 item/error count를 검사하라.

## OCR artifact와 cache

실제 OCR overlay에는 `pdfbooktree[ocr]` extra가 필요하다. extra가 없어도 OCR
config/result model import, command help와 batch dry-run은 가능하며 실제
single/batch overlay는 side effect 전에 `OptionalDependencyError`로 실패한다.

단일 OCR artifact directory에는 raw/insertable cache, page·element·line 통계, 선택적 word 통계, 진행 상태와 JSONL log가 들어간다. 정확한 상태는 `inspect ocr <ARTIFACT_DIR>`로 읽으라.

- `reuse`: raw/insertable cache hit를 사용하고 miss만 API 호출한다.
- `refresh`: 모든 대상 page를 다시 API 호출하고 cache를 갱신한다.
- `only`: cache만 사용하고 miss에서 실패한다.
- `--no-log-file`: `ocr_log.jsonl`, `ocr_progress.json` 기록을 끈다.
- `--stats-word-level`: 기본 page/element/line 통계에 word 통계를 추가한다.

OCR batch는 output root 아래 원본 상대 경로를 보존한 `pdfs/`와 `artifacts/`를 만들며 다음 report를 쓴다.

- `ocr_overlay_batch_report.csv`
- `ocr_overlay_batch_detail.jsonl`
- `ocr_overlay_batch_summary.json`

- `min_page_count`는 inclusive target gate다. `page_count >= min_page_count`인 PDF만 후속 scanned/bookmark 조건을 만족할 때 target이 되고, 더 짧은 PDF의 `target_reject_reason`은 `below_min_page_count: page_count=... < min_page_count=...`다.
- `--dry-run`에서도 page 수와 target 판정 report를 생성하되 OCR API와 PDF 생성을 실행하지 않는다.
- OCR output은 sibling temporary PDF를 완전히 저장한 뒤 atomic replace한다. input/output 동일 경로는 거부하고 실패 시 기존 output을 보존한다.
- PDF별 MuPDF parser·font·resource·ICC 복구 진단은 raw stderr로 반복 출력하지 않고 `mupdf_warning_count`, `mupdf_warnings`로 CSV와 detail JSONL에 보존한다. summary의 `mupdf_warning_pdf_count`, `mupdf_warning_count`로 전체 규모를 확인하라. 경고가 있어도 PDF 작업이 결과를 만들면 성공을 유지하고, 실제 예외는 `failed`로 구분한다.
- summary의 `target_page_count`, `will_process_count`, `will_process_page_count`를 사용해 filter target 전체와 기존 output 제외 후 실제 OCR 실행 규모를 구분하라.
- `processed_count`, `dry_run_count`, `skipped_count`, `failed_count`, cache hit/miss를 모두 확인하라.

## 설정 계약

versioned TOML의 top-level은 `schema_version`, `[processing]`, `[typography]`, `[outline_quality]`, 선택적 `[markdown]`이다. 알 수 없는 section/key와 잘못된 타입·범위를 거부한다.

설정 병합 순서는 다음과 같다.

1. package defaults
2. TOML file
3. 명시적 CLI option에 해당하는 override
4. 반복 가능한 `--set dotted.key=value`

`--set` 값은 TOML scalar 문법으로 먼저 해석한다. boolean은 `true`/`false`, string은 필요할 때 따옴표로 표현하라. 지원 field를 기억에 의존하지 말고 `config explain`으로 확인하라.

`processing.ocr_policy`의 지원 enum은 현재 `never` 하나다. `auto|always`는
실행되지 않는 warning 계약으로 남기지 않고 config 입력 오류로 조기 거부한다.
OCR credential, 비용, cache와 overwrite policy는 별도 `ocr-overlay` workflow에서
명시적으로 선택한다.

`config_hash`는 최종 resolved config에서 계산된다. 결과 비교 시 입력 PDF hash와 config hash를 함께 기록하라.

## CLI stream과 종료 코드

`--format json` 성공 envelope는 stdout 한 줄이다.

```json
{"schema_version":1,"command":"process","ok":true,"result":{}}
```

오류 envelope는 stderr 한 줄이고 `error.code`, `error.type`, `error.message`, 선택적 `error.details`를 가진다. process/infer/batch/OCR/classify의 `--log-mode json` 진행 event도 stderr JSONL이므로 마지막 줄만 오류라고 가정하지 말고 `ok` 또는 event schema로 구분하라.

Markdown graph validation은 생성기가 소유한 front matter와 navigation link만
검사한다. PDF 본문이나 OCR title에 들어 있는 `[[object Object]]` 같은 원문은
사용자 content이며 dangling wiki link로 오인하지 않는다.

| Exit | 의미 | 처리 |
| --- | --- | --- |
| `0` | 성공 | result와 item 실패 집계를 확인 |
| `1` | 예상 runtime 오류 | stderr error를 보고 재시도/환경 수정 판단 |
| `2` | 입력, config, plan 오류 | 사용자 입력과 schema를 수정 |
| `3` | pipeline은 끝났으나 유효 결과 없음 | validation details와 artifact를 조사 |

일반 실행에서 traceback을 기대하지 마라. traceback이 필요한 진단 실행에서만 `--debug`를 추가하라.
