# Agent-friendly interface 로드맵 handoff

## 1. 문서 목적

- 기준일: 2026-07-17
- 목적: `pdfbooktree`의 agent-friendly interface refactoring에서 원래 계획, 현재 완료 범위, 남은 작업과 다음 구현 순서를 한곳에 기록한다.
- 상세 평가 근거: `docs/review/pkg-evaluation-20260715.md`
- Phase 1 구현 커밋: `ea4d4fd` (`feat: add reproducible config and run interface`)
- Phase 1 구현 노트: `docs/vibe/implementations/046_ea4d4fd6289e.md`
- Phase 0 contract 커밋: `7ceaa53` (`test: pin process golden contracts`)
- Phase 0 contract 구현 노트: `docs/vibe/implementations/050_7ceaa53bdd91.md`
- Phase 3A 구현 커밋: `65598b4` (`feat: add versioned CLI result contracts`)
- Phase 3A 구현 노트: `docs/vibe/implementations/051_65598b424d93.md`
- Phase 3B 구현 커밋: `29a15ec` (`feat: add config and inspect result contracts`)
- Phase 3B 구현 노트: `docs/vibe/implementations/052_29a15ec50dd6.md`
- Phase 3C OCR 구현 커밋: `a9649ef` (`feat: add versioned OCR event contract`)
- Phase 3C OCR 구현 노트: `docs/vibe/implementations/053_a9649efeabcf.md`
- Phase 3C classify 구현 커밋: `308b3c1` (`feat: add classify result and event contracts`)
- Phase 3C classify 구현 노트: `docs/vibe/implementations/054_308b3c11ea5e.md`
- Phase 3C ocr-overlay-batch 구현 커밋: `6dc71cf` (`feat: add ocr-overlay-batch event contract`)
- Phase 3C ocr-overlay-batch 구현 노트: `docs/vibe/implementations/055_6dc71cf39714.md`
- Phase 4 1차 증분 구현 커밋: `0d66ba3` (`feat: add bookmark plan evaluation module`)
- Phase 4 1차 증분 구현 노트: `docs/vibe/implementations/056_0d66ba365dae.md`
- Phase 5 1차 증분 구현 커밋: `7ac5f61` (`feat: add inspect compare command for bookmark plan diff`)
- Phase 5 1차 증분 구현 노트: `docs/vibe/implementations/057_7ac5f610657e.md`
- Phase 7 1차 증분(`batch` 계약) 구현 커밋: `b815316` (`feat: add batch result/error/event contract`)
- Phase 7 1차 증분 구현 노트: `docs/vibe/implementations/058_b815316c007e.md`
- Phase 7 2차 증분(item run manifest) 구현 커밋: `ea3082d` (`feat: add batch item run manifests`)
- Phase 7 2차 증분 구현 노트: `docs/vibe/implementations/059_ea3082d3183e.md`
- Phase 7 3차 증분(batch run manifest) 구현 커밋: `0c7ce00` (`feat: add batch run manifest`)
- Phase 7 3차 증분 구현 노트: `docs/vibe/implementations/060_0c7ce009c489.md`
- OCR batch 최소 page 수 구현 커밋: `722e9c9` (`feat: add ocr batch min page count`)
- OCR batch 최소 page 수 구현 노트: `docs/vibe/implementations/061_722e9c98bea5.md`
- project skill installer 구현 커밋: `dc72096` (`feat: add project skill installer`)
- project skill installer 구현 노트: `docs/vibe/implementations/062_dc7209667ebb.md`
- OCR batch 준비 progress 구현 커밋: `4b3c3cf` (`feat: expose OCR batch preparation progress`)
- OCR batch 준비 progress 구현 노트: `docs/vibe/implementations/063_4b3c3cf157a7.md`
- Markdown progressive graph 구현 커밋: `5ffeed1` (`feat: export markdown as progressive graph`)
- Markdown progressive graph 구현 노트: `docs/vibe/implementations/064_5ffeed171c63.md`
- length-limited Markdown graph 구현 커밋: `32c9ea1` (`feat: export length-limited markdown as graph`)
- length-limited Markdown graph 구현 노트: `docs/vibe/implementations/065_32c9ea154ab0.md`
- Phase 5 2차 증분 구현 커밋: `fd90662` (`feat: add bookmark review evidence workflow`)
- Phase 5 2차 증분 구현 노트: `docs/vibe/implementations/066_fd9066243611.md`

이 handoff의 핵심 판단은 기존 bookmark engine algorithm을 다시 설계하지 않고, 이미 검증된 production pipeline을 agent가 단계별로 실행·검토·비교할 수 있는 public interface로 재구성하는 것이다.

목표 lifecycle은 다음과 같다.

```text
inspect -> infer -> review/evaluate -> sweep/compare -> apply
```

기존 `process`와 `batch`는 이 단계들을 조립하는 convenience workflow로 유지한다.

## 2. 원래 로드맵과 현재 상태

| Phase | 목표 | 상태 | 비고 |
| --- | --- | --- | --- |
| Phase 0 | 현재 public contract와 결과 고정 | 완료 (2026-07-16) | pipeline parity, fast path, process Python/CLI result, artifact JSON shape와 manifest-to-file golden contract를 고정했다. |
| Phase 1 | versioned config와 immutable run 기반 | 완료 | TOML, `--set`, config CLI, config/input hash, run manifest를 구현했다. |
| Phase 2 | core pipeline을 analyze/infer/apply로 분리 | 완료 (2026-07-16) | `pipeline.py`(analyze_pdf/infer_bookmarks/apply_plan/resolve_existing_outline_action), `infer`/`apply` CLI, 로드맵에 없던 existing-outline quality policy까지 추가. 구현 노트 047~049 참고. |
| Phase 3 | 공통 result/error/event 계약 | practical complete (2026-07-16) | `process`/`infer`/`apply`, config, inspect, 단일 OCR, classify, `ocr-overlay-batch`에 schema v1 계약을 적용했다. Typer parser-level error는 `--format` 파싱 전 시점이라 공통 envelope에 넣지 않기로 결정했다. `batch`도 Phase 7 1차 증분에서 같은 계약으로 전환됐다. |
| Phase 4 | evaluator를 production으로 승격 | 1차 증분 완료 (2026-07-16) | `src/pdfbooktree/evaluation.py`로 fuzzy matcher와 matched/missed/extra detail을 승격했다. external reference loader, 3단계 reference quality, structural quality signal은 미착수. |
| Phase 5 | inspect/compare 개선 | 2차 증분 완료 (2026-07-17) | `inspect compare`와 review summary/items artifact를 구현했다. `inspect plan`은 item ID/page/level/source/attention/limit 필터를 제공한다. metric/structural signal delta와 compare output directory 자동 탐색은 미착수다. |
| Phase 6 | cache-aware sweep | 미착수 | analysis cache, matrix parser, ranking이 없다. |
| Phase 7 | process/batch/OCR 통합과 문서화 | 주요 증분 완료 (2026-07-17) | `batch` 공통 계약과 durable manifest, OCR batch 최소 page/progress, project skill installer, README의 quick start·artifact·stdout/stderr·exit-code 문서화를 완료했다. `processing.ocr_policy=auto|always` 계약 정리가 남았다. |

## 3. Phase 0 진행 상태

Phase 0의 목적은 refactoring 전후의 bookmark plan과 artifact가 의도치 않게 달라지는 것을 자동으로 탐지하는 것이다.

완료된 안전망:

- 전체 테스트 193개가 통과한다.
- `test_pipeline_parity.py`가 refactoring 전 plan의 title, page, level, source를
  golden 값으로 고정하고, existing-outline fast path가 typography extraction을
  실행하지 않는지 검증한다.
- `test_process_golden_contract.py`가 inference와 existing-outline 경로의
  `ProcessingResult`, artifact 이름과 JSON/JSONL shape, report, 실제 `process` CLI의
  immutable run manifest-to-file 연결을 고정한다.
- `test_process_cli.py`, `test_run.py`가 config precedence, flat output, manifest
  lifecycle과 exception error shape를 검증한다.
- 실제 native/OCR 및 existing-outline 동작은 showcase 019~021이 보완한다.

Phase 0은 agent-friendly interface refactoring에 필요한 자동 회귀 계약을 확보한
것으로 완료 처리한다. PDF binary나 Markdown 본문 전체의 byte-for-byte snapshot은
불안정성이 커서 계약 대상에 넣지 않았다.

## 4. 완료된 Phase 1

### 4.1 Versioned config

- `schema_version = 1`인 TOML config를 도입했다.
- 외부 section은 `[processing]`, `[typography]`, `[markdown]`으로 제한한다.
- 설정 우선순위는 다음과 같다.

```text
package defaults < TOML < 명시적 legacy CLI option < --set
```

- Python dataclass 생성과 CLI가 같은 validation을 사용한다.
- 알 수 없는 field, 잘못된 타입, 범위와 field 간 제약을 조기에 거부한다.

### 4.2 Config CLI

다음 명령을 추가했다.

```text
pdfbooktree config defaults
pdfbooktree config schema
pdfbooktree config init
pdfbooktree config explain
pdfbooktree config validate
```

`process`에는 `--config`, 반복 가능한 `--set`, 호환용 `--flat-output`을 추가했다.

### 4.3 Immutable run과 manifest

- input PDF SHA-256, size, page count를 기록한다.
- resolved config와 stable config hash를 기록한다.
- package version, git revision, dirty 여부를 기록한다.
- 같은 output root에서도 실행별 immutable run directory를 만든다.
- `created -> running -> succeeded/failed` manifest lifecycle을 기록한다.
- 성공 manifest에는 실제로 존재하는 output과 artifact만 기록한다.
- `--flat-output`은 기존 고정 output directory 동작을 명시적으로 보존한다.

### 4.4 검증 결과

- `uv run pytest`: 148 passed
- `uv run ruff check src tests`: 통과
- `uv run ruff format --check src tests`: 통과
- 실제 entry point의 `config --help`, `process --help`: 정상 동작

저장소 전체 Ruff에는 이번 변경과 무관한 `experiments/`, `references/`의 기존 오류 18개가 남아 있다. 현재 구현 검증 기준은 `src tests` 범위다.

## 5. 완료된 Phase 2 구현 범위

Phase 2의 목표는 production bookmark algorithm을 한 곳에서만 조립하고, plan 생성과 최종 파일 생성을 독립 실행할 수 있게 만드는 것이다.

### 5.1 진입 계약 고정

- Phase 0의 미완료 항목 중 pipeline 분리에 직접 필요한 parity test를 먼저 추가한다.
- refactoring 전 조립 코드는 production에 복제하지 않고 테스트용 characterization helper로만 둔다.
- 기존 outline이 있을 때의 빠른 경로와 output semantics를 고정한다.

### 5.2 Public data model

권장 모델:

- `PdfAnalysis`
  - input PDF, page count, raw typography line, extraction config identity
  - PyMuPDF document/page 같은 열린 runtime 객체는 포함하지 않는다.
- `BookmarkInferenceResult`
  - filtered line, tier, heading/fallback candidate, plan, validation, warning
- `ApplyResult`
  - 실제 생성된 PDF/Markdown 경로와 validation 결과

모델은 직렬화 가능한 dataclass로 만들고 package root에서 public export한다.

### 5.3 `analyze_pdf()`

- PDF를 읽어 raw `TypographyLine`을 만드는 expensive extraction만 담당한다.
- 현재 raw line extraction은 주로 `line_y_tolerance_ratio`에 의존한다.
- margin exclusion, tiering, heading selection, BPE와 fallback은 analysis에 넣지 않는다.
- Phase 6에서 같은 analysis를 여러 inference config가 재사용할 수 있도록 extraction config identity를 남긴다.
- disk cache, resume와 병렬 sweep 자체는 Phase 2 범위에 넣지 않는다.

### 5.4 `infer_bookmarks()`

다음 production 순서를 유일하게 조립한다.

```text
margin exclusion
-> font/height tier
-> geometry context
-> heading candidate
-> BPE outline
-> position fallback
-> normalize
-> validate
```

- Python 함수는 PDF/Markdown을 생성하지 않는다.
- 가능한 한 함수 결과와 artifact 쓰기를 분리한다.
- plan과 판단 근거를 `BookmarkInferenceResult`로 반환한다.
- 실험 102의 `_predict_plan()`은 이 public API를 호출하도록 단순화해 production drift를 막는다.

### 5.5 `apply_plan()`

- 입력 PDF와 plan을 받아 page, level, order validation을 먼저 수행한다.
- 검증된 plan으로 bookmarked PDF와 Markdown만 생성한다.
- typography extraction과 inference를 다시 실행하지 않는다.
- JSON plan loader는 필수 field와 타입을 검증한다.
- 명시적 apply에서는 plan source file의 경로와 SHA-256을 run manifest에 기록한다.

### 5.6 `Processor` 호환 facade

`Processor.run()`은 algorithm을 직접 조립하지 않고 다음 public 단계만 호출한다.

```text
existing-outline policy
-> analyze_pdf
-> infer_bookmarks
-> artifact write
-> apply_plan
-> ProcessingResult/report
```

- 기존 `Processor`, `ProcessingConfig`, `ProcessingResult`, `process` CLI를 제거하지 않는다.
- 기본 config의 plan과 output이 refactoring 전과 같아야 한다.
- existing outline fast path는 typography extraction을 건너뛰는 현재 동작을 유지한다.

### 5.7 `infer`와 `apply` CLI

예상 인터페이스:

```powershell
uv run pdfbooktree infer "book.pdf" `
  --config "configs/default.toml" `
  --set typography.body_font_text_coverage=0.98 `
  --output-dir "runs"

uv run pdfbooktree apply "book.pdf" `
  --plan "runs/book/run-id/bookmark_plan.json" `
  --config "configs/default.toml" `
  --output-dir "output"
```

- `infer`는 plan과 근거 artifact만 생성하고 bookmarked PDF와 Markdown은 생성하지 않는다.
- `apply`는 기존 plan을 읽어 최종 PDF/Markdown만 생성한다.
- 두 명령은 Phase 1의 resolved config와 immutable run을 사용한다.
- 전 명령 공통 JSON/error envelope와 exit code 정리는 Phase 3에서 수행한다.

### 5.8 Showcase와 완료 조건

실제 실험 데이터 한 권으로 `infer -> inspect -> apply` public workflow를 실행하고 `showcase/showcase.json`에 결과를 기록한다.

Phase 2 완료 조건:

1. production bookmark pipeline 조립 코드가 한 곳에만 존재한다.
2. 새 `infer_bookmarks()`가 기존 default pipeline과 같은 plan을 만든다.
3. `infer`가 bookmarked PDF와 Markdown을 생성하지 않는다.
4. `apply`가 typography extraction을 호출하지 않는다.
5. 기존 `process`와 existing outline 동작이 유지된다.
6. 실제 PDF를 사용한 showcase가 성공한다.

## 6. Phase 2의 비목표

- bookmark engine algorithm과 heuristic 자체 개선
- fuzzy metric과 reference quality evaluator의 production 승격
- plan compare와 candidate ranking
- analysis disk cache, sweep matrix, resume와 병렬 실행
- 모든 command의 공통 JSON/error/event/exit-code 전환
- OCR provider 추가 또는 batch workflow 전면 수정

이 항목들은 각각 Phase 3~7에서 수행한다.

## 7. Phase 2 이후 남은 로드맵

### Phase 3. 공통 result/error/event 계약

완료된 범위:

- Phase 3A: schema version 1의 public result/error envelope
- `process`/`infer`/`apply`의 `--format human|json`, `--debug`
- JSON final result는 stdout, error는 stderr로 분리
- exit code 0(success/skipped), 1(runtime), 2(input/config/plan),
  3(processing validation failure) 고정
- immutable run의 complete/fail manifest를 envelope 출력보다 먼저 기록
- Phase 3B: config와 inspect 전체 command에 같은 result/error 계약 적용
- inspect의 기존 `--json`은 호환 alias로 유지하고 `--format`을 canonical option으로 지정
- Phase 3C: `CommandEventEnvelope` schema version 1과 stderr JSONL renderer 추가
- 단일 `ocr-overlay`의 JSON final result는 stdout, OCR progress는 stderr로 분리
- `classify-scan`의 JSON final result는 stdout, file progress는 stderr로 분리
- OCR/classify의 기존 durable artifact JSONL 형식은 호환성을 위해 유지
- classify의 파일별 오류는 `error_count`와 detail artifact로 반환하고 batch 성공 exit 0 유지
- `ocr-overlay-batch`를 같은 result/error/event 계약으로 전환(`6dc71cf`, 노트 055).
  `JsonStderrOcrLogger`/`build_batch_ocr_progress`/`OcrOverlayBatchRunner`에
  `command` 파라미터를 추가해 batch 내부 책별 event는 `ocr-overlay-batch`,
  단일 실행은 `ocr-overlay`로 구분되게 만들었다. `failed_count > 0`인 부분
  실패는 classify와 동일하게 exit 0 + `failed_count`를 유지한다.
- Typer parser-level(callback 진입 전) usage error의 JSON envelope 처리는
  **하지 않기로 결정**했다. `--format` 자체가 아직 파싱되지 않은 시점에
  발생하는 오류라 "JSON으로 낼지 human으로 낼지"를 판단할 수 없는 순서
  문제가 있고, 이를 해결하려면 `app()` 실행 전체를 감싸 `click.UsageError`/
  `SystemExit`를 가로채야 해서 침습성 대비 실익이 낮다고 판단했다. 이
  결정으로 Phase 3을 practical complete로 닫는다.

남은 범위:

- 기존 `batch`(bookmark 처리 command)는 Phase 7의 config/run/item summary
  통합과 함께 전환한다.

### Phase 4. Production evaluator

완료된 범위(`0d66ba3`, 노트 056):

- 실험 102 fuzzy matcher 승격 - `src/pdfbooktree/evaluation.py`의
  `match_bookmark_plans()`. title 유사도 + page tolerance 그리디 1:1 매칭을
  그대로 승격했다.
- matched/missed/extra detail - `PlanMatchResult(metrics, matched, missed,
  extra)`. `MatchedPair`가 gold/predicted 쌍과 title_similarity,
  exact_page_match를 담는다.
- embedded reference loader - 새 wrapper를 만들지 않고 기존
  `pdfbooktree.pdf.outline.read_outline()` + `outline_to_plan()`을 그대로
  쓴다.
- reference quality 판정 - 새로 만들지 않고 기존
  `pdfbooktree.pdf.outline_quality.assess_outline_quality()`를 재사용한다.
  이 함수의 임계값이 이미 실험 102 결과에서 나왔다(Phase 2에서 먼저
  production에 들어간 것).
- title 유사도 함수는 `typography/position_fallback.py`의 private
  `_title_similarity`였으나, evaluation 모듈도 필요로 하게 돼
  `utils/text_normalize.py`의 공개 `title_similarity()`로 승격했다.
- showcase 022가 실제 책 3권(clean gold 고성능, junk gold + zero
  prediction, clean gold 저성능)으로 검증했고, 세 책 모두 실험 102의
  원래 400권 결과와 수치가 정확히 일치했다.

남은 범위:

- external reference loader(embedded TOC가 없는 책의 외부 정답 파일) -
  실제로 쓸 external gold 데이터가 아직 없어 미착수. 데이터가 생기면
  진행한다.
- reference quality `clean/suspicious/unusable` 3단계 - 현재
  `assess_outline_quality()`는 `is_low_quality: bool` + reasons(2가지
  사유)만 구분하는 2단계다. production existing-outline 정책이 이미 이
  이진 판정에 의존하고 있어, 3단계로 확장하려면 그 정책의 의미까지 함께
  재설계해야 한다. 실제 3단계가 필요한 소비자(Phase 5 compare 확장,
  Phase 6 ranking)가 생기면 진행한다.
- structural quality signal(레벨 역전, 중복 제목, page 비단조 등 gold
  없이도 계산 가능한 신호) - 미착수.

### Phase 5. Inspect와 compare

완료된 범위(`7ac5f61`, 노트 057; `fd90662`, 노트 066):

- 두 run/plan의 added/removed/moved/level/source diff -
  `compare_bookmark_plans()`(evaluation.py)가 `match_bookmark_plans()`를
  재사용해(before=gold 자리, after=predicted 자리) missed/extra를
  removed/added로 매핑하고, matched 쌍을 `page_changed`/`level_changed`/
  `source_changed` 독립 flag로 후처리한다. 세 flag가 모두 False면
  unchanged다. 같은 pipeline의 두 실행을 비교하는 용도라 page tolerance
  기본값을 gold matching(1)과 다르게 0으로 뒀다.
- CLI `inspect compare <plan_a> <plan_b>` - 기존 `inspect plan`과 같은
  `--format`/`--json`/`--debug` 계약, `--page-tolerance`/
  `--title-similarity-threshold` 옵션 노출.
- `inspection.py`의 `inspect_compare_plans()`가 기존
  `load_bookmark_plan_json()`으로 두 plan 파일을 읽어 JSON 친화적 dict로
  변환한다.
- showcase 023이 실제 책 한 권을 서로 다른 두 `TypographyConfig`(기본값,
  `position_fallback_enabled=False`)로 `infer`해 만든 실제
  `bookmark_plan.json` 두 개를 비교했다. `position_fallback_enabled=False`
  가 정확히 fallback이 찾은 17개 항목만 `removed`로 만들었다(added=0,
  unchanged=154) - config 옵션의 실제 효과와 compare 기능을 함께 검증했다.
- `infer`가 `bookmark_review_summary.json`과
  `bookmark_review_items.jsonl`을 생성하고 run manifest가 두 artifact를
  역할별로 연결한다.
- review summary는 level/source 분포, page 밀도, title/text 통계와 attention
  signal을 제공한다. item detail은 plan item, canonical/alternative candidate,
  geometry·typography, 제한된 주변 text와 원문 artifact 참조를 보존한다.
- `inspect plan`에 `--summary`, `--items`, `--limit`, `--item-id`,
  `--page-range`, `--level`, `--source`, `--attention-only`를 추가했다.
  인자 없는 기존 plan inspection과 JSON envelope 계약은 유지한다.
- showcase 029가 native, scanned-indexed, OCR PDF에서 summary → attention item →
  candidate evidence → 원문 page의 점진적 검토 흐름을 검증했다.

남은 범위:

- metric과 structural signal delta - Phase 4의 structural quality signal이
  선행돼야 한다.
- 두 output_dir을 받아 `bookmark_plan.json`을 자동으로 찾는 편의 기능
  (`inspect plan`처럼) - 이번 1차 증분은 plan 파일 경로 두 개를 직접
  받는 인터페이스로 좁혔다.
- agent가 review item을 수정한 plan으로 저장한 뒤 `apply`까지 수행하는 실제
  end-to-end showcase.

### Phase 6. Cache-aware sweep

- input hash와 extraction config 기반 analysis cache key
- TOML sweep matrix parser와 조합 제한
- `--max-runs`, `--resume`, `--jobs`
- reference metric 또는 structural signal ranking
- candidate별 config, plan, metric과 diff artifact

### Phase 7. End-to-end와 batch

완료된 범위:

- `process`는 Phase 2에서 existing-outline policy 이후
  `analyze_pdf -> infer_bookmarks -> apply_plan`을 호출하는 단계형 조립기로 전환했다.
- `batch`에 single command와 같은 versioned config, result/error/event와 exit-code
  의미를 적용했다(1차 증분, 노트 058).
- 각 item에 input/config identity, immutable run directory와 succeeded/failed
  manifest를 적용하고 `BatchItemResult`에서 직접 연결했다(2차 증분, 노트 059).
- batch 실행 자체에 `output_root/_batch_runs/<batch_run_id>/batch_manifest.json`을
  만들고, config/input selection, lifecycle, summary, item run과 실제 output을
  연결했다(3차 증분, 노트 060).
- OCR batch가 최소 page 수를 적용하고 준비 단계 progress를 event로 노출한다
  (노트 061, 063).
- project-local `use-pdfbooktree` skill installer와 패키지 번들 템플릿을 제공한다
  (노트 062).
- README에 `infer -> review -> apply` quick start, artifact 역할, 단일/item/batch
  run directory, stdout/stderr와 exit-code 계약을 문서화했다.

남은 범위:

- `ocr_policy`를 실제로 연결하거나 public contract에서 unsupported 상태로 정리

## 8. 다음 작업자 체크리스트 (완료: 2026-07-16, §13 참고)

이 체크리스트는 `ocr-overlay-batch` 계약 작업 계획으로 작성됐고 그대로 완료됐다.
아래 항목은 실행 기록으로 남기고, 완료 결과와 검증은 §13을 본다.

1. 현재 `feat/classify-event-contract` 브랜치의 `308b3c1`과 `0fbdd7e` 및 이 handoff
   문서 커밋을 확인한 뒤 `develop`에 fast-forward/merge한다.
2. `develop`에서 `feat/ocr-batch-event-contract` 브랜치를 만든다.
3. 첫 구현 범위는 `ocr-overlay-batch` 하나로 제한한다. 기존 `batch` command나
   parser-level Typer error까지 한 커밋에 포함하지 않는다.
4. `ocr-overlay-batch`에 `--format human|json`, `--debug`를 추가하고 final JSON result는
   stdout 한 줄, error와 progress event는 stderr로 고정한다.
5. `ocr/logger.py`의 JSON event renderer가 command 이름을 주입받게 만들어 단일 실행은
   `ocr-overlay`, batch 내부 책별 event는 `ocr-overlay-batch`로 표시한다. 책 식별은
   기존 `data.input_pdf`를 유지하고 durable `ocr_log.jsonl` 형식은 바꾸지 않는다.
6. batch result의 `failed_count > 0` 정책은 기존 `OcrOverlayBatchRunner` 의미를 먼저
   확인한다. 개별 책 실패를 report에 격리하고 batch가 끝나는 구조라면 classify와
   마찬가지로 exit 0 + `failed_count`를 유지하고, 명령 전체 중단만 exit 1로 둔다.
7. 최소 계약 테스트는 JSON stdout/stderr 분리, batch command event context, missing
   input, invalid log mode, runtime error/debug, 부분 실패 결과를 포함한다.
8. `uv run pytest`, `uv run ruff check src tests`,
   `uv run ruff format --check src tests`, 실제 command help를 실행한다.
9. 구현 커밋 직후 `scripts/create-implementation-note.ps1`을 실행하고 implementation
   note를 별도 `docs:` 커밋으로 남긴다.

## 9. 알려진 주의사항

- 기존 긴 `process` option은 Rich help의 기본 폭에서 일부 이름이 생략된다.
- `ProcessingConfig.ocr_policy`는 아직 `Processor`에 연결되지 않았다.
- `process`/`infer`/`apply`의 failed `ProcessingResult`는 exit 3으로 정규화됐다.
  `classify-scan`의 파일별 오류는 유효한 부분 report이므로 exit 0 + `error_count`다.
- `process`, `infer`, `apply`, config, inspect, 단일 `ocr-overlay`,
  `classify-scan`, `ocr-overlay-batch`, `batch` 모두 공통 result/error 계약을
  사용한다. 장시간 command의 progress는 stderr event로 분리한다.
- `batch`의 item 실패는 command 실패가 아니므로 exit 0 + `failed_count`와
  succeeded batch manifest를 유지한다. logger/infrastructure 같은 command 전체
  예외만 exit 1과 failed batch manifest를 만든다.
- Typer callback 진입 전 parser-level usage error(필수 옵션 누락, 타입
  변환 오류 등)는 공통 JSON envelope 대상이 **아니다** - `--format` 자체가
  파싱되기 전에 발생하는 오류라 침습적인 `app()` wrapper 없이는 처리할 수
  없고, 그 비용이 실익보다 크다고 판단해 의도적으로 범위에서 뺐다(Phase 3
  practical complete 결정, §13 참고).
- gold/reference 품질 판정(`assess_outline_quality()`)은 `is_low_quality:
  bool` + reasons 2가지(`too_few_items`, `near_one_bookmark_per_page`,
  `numeric_only_title`)만 구분하는 2단계다. 로드맵이 원래 그렸던
  `clean/suspicious/unusable` 3단계가 아니다 - 3단계가 필요한 실제
  소비자가 생기기 전까지는 확장하지 않기로 했다.
- `compare_bookmark_plans()`(두 plan 비교)의 기본 page tolerance는 0이다.
  `match_bookmark_plans()`(gold vs predicted 비교)의 기본값 1과 의도적으로
  다르다 - 같은 pipeline의 두 실행은 보통 정확히 같은 page가 나와야 정상이고,
  달라졌다면 그 자체가 `moved`로 보고할 신호이기 때문이다.
- run manifest는 versioned이지만 기존 plan과 모든 중간 artifact가 독립 schema version을 가진 것은 아니다.
- 동일 input/config라도 timestamp가 다르면 새 item/batch run이 생성되며 cache
  hit/resume는 아직 없다. batch selection hash는 입력 directory, recursive 여부,
  발견한 PDF 경로 목록을 고정하고 각 PDF content hash는 item manifest에 기록한다.
- corporate PC에서는 권한 상승 shell의 원래 Codex 실행 파일 접근이 거부될 수 있으므로 `AGENTS.md`의 `C:\tmp\codex-apply-patch.exe --codex-run-as-apply-patch` 우회 규칙을 따른다.

## 10. 2026-07-16 갱신: Phase 2 완료 기록

Phase 2 완료 조건(§5.8) 6개를 모두 충족했다. `feat/pipeline-stages` 브랜치, 커밋:

- `cfb8eaed` analyze/infer/apply 분리 (노트 `047_cfb8eaed0dd3.md`)
- `f2d80167` existing-outline quality policy 추가 — 로드맵에 없던 스코프. 기존 bookmark가 있으면 기본적으로 skip하는 canonical 동작은 유지하되, 실험 102 기준(item ≤3개, item 수가 page 수의 0.9배 이상) + numeric-only title 신호로 low quality를 항상 판정해 표시하고, `outline_quality.replace_when_low_quality`로만 opt-in 교체한다 (노트 `048_f2d801675acc.md`)
- `0757e094` `infer`/`apply` CLI를 이 policy 위에 추가 (노트 `049_0757e09437b4.md`)

이후 결정과 처리 상태:

1. `numeric_only_title`/기본 임계값은 합리적인 보수적 분류이며 자동 교체 기본값이
   꺼져 있으므로 추가 300STUDY 검증 실험은 진행하지 않기로 결정했다.
2. Phase 0 golden/contract는 `7ceaa53`과 구현 노트 050에서 완료했다.
3. 실험 102의 `_predict_plan()` public pipeline 전환은 `75b7e21`에서 완료했으며
   `fix/experiment-102-public-pipeline` 브랜치에 있다. `develop` 반영은 별도다.

## 11. 2026-07-16 갱신: Phase 3A 완료, 다음 작업 제안

`feat/cli-result-contract`에서 첫 공통 CLI 계약 수직 단위를 완료했다.

- `65598b4`: schema v1 `CommandResultEnvelope`/`CommandErrorEnvelope`, 공통 renderer,
  `process`/`infer`/`apply`의 human/JSON final result와 error, documented exit code,
  `--debug`를 구현했다.
- `4c326c7`: 구현 노트 051을 작성했다.
- 검증: `uv run pytest` 193 passed, `uv run ruff check src tests`와
  `uv run ruff format --check src tests` 통과, 세 command의 실제 help 확인.

Phase 3A에서 의도적으로 남긴 범위:

1. config/inspect/OCR/classify/batch의 공통 envelope와 canonical `--format`
2. Typer parser-level usage error의 JSON 처리
3. pipeline event protocol, JSONL renderer와 장시간 작업 progress 분리
4. report JSON의 `report_path=null`과 최종 result path 비대칭

**다음 작업 우선순위 제안**: Phase 3B로 production pipeline을 실행하지 않는
config/inspect command를 공통 envelope에 먼저 연결한다. 기존 config `--format`과
inspect `--json` 기반이 있어 pipeline algorithm을 건드리지 않고 contract 확장과
호환 검증을 한 작업 단위로 끝낼 수 있다. 그 다음 Phase 3C에서 event protocol과
OCR/batch progress를 다룬다.

위 제안은 이후 Phase 3B와 Phase 3C 구현으로 완료되었으며 최신 다음 작업은 §8과
§12를 따른다.

## 12. 2026-07-16 갱신: Phase 3B/3C 완료 범위와 handoff

Phase 3A 이후 다음 세 수직 단위를 완료했다.

- `29a15ec`: config/inspect result/error 계약. 구현 노트 052.
- `a9649ef`: 단일 `ocr-overlay` result/error/event와 stdout/stderr 분리. 구현 노트 053.
- `308b3c1`: `classify-scan` result/error/event와 stdout/stderr 분리. 구현 노트 054.

당시 branch 상태(현재 상태는 §15 참고):

- branch: `feat/classify-event-contract`
- 구현 커밋: `308b3c1`
- implementation note 커밋: `0fbdd7e`
- 검증: `uv run pytest -q` 209 passed, `uv run ruff check src tests` 통과,
  `uv run ruff format --check src tests` 100 files 통과,
  `uv run pdfbooktree classify-scan --help` 정상

이번 classify 계약에서 확정한 의미:

1. JSON final result는 stdout 한 줄, progress event와 error는 stderr다.
2. terminal JSONL event는 `CommandEventEnvelope` v1을 사용하지만 durable report
   JSONL은 기존 형식을 유지한다.
3. 개별 PDF 오류는 batch 전체 실패가 아니다. 완성된 report를 성공 result로 반환하고
   `error_count`, detail artifact와 stderr event로 오류를 노출한다.
4. callback 진입 전 Typer parser error는 아직 공통 envelope 대상이 아니다.

다음 권장 작업은 `ocr-overlay-batch` 계약이다. 이 작업에서 가장 중요한 설계점은
단일 OCR과 batch가 공유하는 logger에 command context를 주입하는 것이다. 현재
`JsonStderrOcrLogger`는 event command를 `ocr-overlay`로 고정하므로 batch에서 발생한
책별 event도 단일 command처럼 보인다. logger/batch progress 조립기가 command를
받도록 좁게 변경하고, batch final result를 공통 envelope로 전환한 뒤 다음 단계로
넘긴다.

그 이후 우선순위:

1. Typer parser-level JSON error 경계의 필요성과 구현 비용을 짧게 검토한다.
2. parser hook이 과도하게 침습적이면 Phase 3을 practical complete로 닫고 Phase 4
   production evaluator로 이동한다.
3. 기존 `batch` command는 Phase 7에서 config/run/item summary와 함께 다룬다.

위 세 우선순위가 모두 이후 작업으로 완료됐다. 진행 기록은 §13을 본다.

## 13. 2026-07-16 갱신: Phase 3 완료, Phase 4/5 1차 증분과 다음 작업

`develop`에서 순서대로 세 수직 단위를 완료하고 각각 바로 `develop`에
fast-forward 병합했다. 당시 모두 로컬에만 있었고 `develop`은
`origin/develop`보다 31 commit 앞서 있었다.

### 13.1 Phase 3 완료: `ocr-overlay-batch` 계약

- 구현 커밋: `6dc71cf` (`feat: add ocr-overlay-batch event contract`)
- implementation note 커밋: `843353b` (노트 055)
- `ocr-overlay-batch`에 `--format human|json`, `--debug`를 추가하고 최종
  결과를 stdout 한 줄로, event/progress를 stderr로 분리했다.
- `JsonStderrOcrLogger`/`build_ocr_logger`/`build_batch_ocr_progress`/
  `FlatBatchOcrProgress`/`OcrOverlayBatchRunner`에 `command` 파라미터를
  keyword-only로 추가해, 단일 실행은 `ocr-overlay`, batch 내부 책별
  event는 `ocr-overlay-batch`로 표시되게 만들었다. 기본값이 각각 달라
  기존 호출부는 수정 없이 그대로 동작한다.
- `failed_count > 0`인 부분 실패는 classify와 동일하게 exit 0을 유지한다
  - `OcrOverlayBatchRunner`가 이미 책별 실패를 report에 격리하고 계속
    진행하는 구조이기 때문이다.
- 검증: `uv run pytest -q` 217 passed, `uv run ruff check/format --check
  src tests` 통과, `ocr-overlay-batch --help`에서 `--format`/`--debug` 노출
  확인.
- 이 커밋을 끝으로 Phase 3의 "그 이후 우선순위" 1~2번(§12)을 처리했다:
  Typer parser-level usage error의 JSON envelope 처리는 **하지 않기로
  결정**했다(`--format` 파싱 전 시점이라 순서 문제가 있고, `app()` 전체를
  감싸야 해서 침습성 대비 실익이 낮음). 이 결정으로 **Phase 3을 practical
  complete로 닫는다**. 기존 `batch` command는 계획대로 Phase 7로 남긴다.

### 13.2 Phase 4 1차 증분: production evaluator

- 선행 작업: 실험 102의 `_predict_plan()`을 public 단계형 API
  (`analyze_pdf`/`infer_bookmarks`)로 전환한 `75b7e21`
  (`fix/experiment-102-public-pipeline` 브랜치, §10의 미반영 항목)을
  `develop`에 cherry-pick(`65beb2f`)했다. 순수 리팩터링이라 예측 결과는
  바뀌지 않았다.
- 구현 커밋: `0d66ba3` (`feat: add bookmark plan evaluation module`)
- implementation note 커밋: `6025ac3` (노트 056)
- 부수 커밋: `e5f0794`(`exp:` 실험 102 import 갱신), `c5f0a8d`
  (`showcase:` showcase 022)
- `src/pdfbooktree/evaluation.py`를 신설해 실험 102의 `MatchMetrics`/
  fuzzy matcher를 승격했다. `match_bookmark_plans()`는 집계 지표뿐 아니라
  `matched`/`missed`/`extra` item 상세를 반환한다(로드맵의 "matched/
  missed/extra detail").
- gold reference 품질 판정은 새로 안 만들고 기존
  `assess_outline_quality()`를 재사용했다 - 그 함수의 임계값이 이미
  실험 102 결과에서 나온 것이었다(Phase 2에서 먼저 production에 들어감).
- `_title_similarity()`가 `typography/position_fallback.py`의 private
  함수였는데 evaluation 모듈도 필요로 하게 돼
  `utils/text_normalize.py`의 공개 `title_similarity()`로 승격했다.
- 검증: `uv run pytest -q` 229 passed, ruff 통과. showcase 022가 실제 책
  3권(clean gold 고성능/junk gold+zero prediction/clean gold 저성능)으로
  검증했고, 세 책 모두 실험 102의 원래 400권 결과와 F1/count가 정확히
  일치했다 - public pipeline 전환과 evaluation 모듈 승격 둘 다 예측
  결과를 바꾸지 않았다는 것을 함께 확인했다.
- 의도적으로 미룬 것: external reference loader(실제 external gold 데이터
  없음), reference quality 3단계(실제 소비자 없음), structural quality
  signal(범위를 매칭 로직으로 좁게 유지).

### 13.3 Phase 5 1차 증분: `inspect compare`

- 구현 커밋: `7ac5f61` (`feat: add inspect compare command for bookmark
  plan diff`)
- implementation note 커밋: `fb1fc1f` (노트 057)
- showcase 커밋: `83ceeab` (showcase 023)
- `evaluation.py`에 `compare_bookmark_plans()`를 추가했다.
  `match_bookmark_plans()`를 그대로 재사용하되(`before`가 gold 자리,
  `after`가 predicted 자리) `missed`→`removed`, `extra`→`added`로
  매핑하고, matched 쌍은 `page_changed`/`level_changed`/`source_changed`
  독립 flag로 후처리한다(하나의 enum이 아니라 flag로 만든 이유: 한
  항목이 동시에 여러 변화를 가질 수 있어서).
- 같은 pipeline의 두 실행을 비교하는 용도라 page tolerance 기본값을
  gold matching(1)과 다르게 0으로 뒀다 - page가 달라졌다면 그 자체가
  `moved` 신호다.
- CLI `inspect compare <plan_a> <plan_b>`를 기존 inspect command와 같은
  `--format`/`--json`/`--debug` 계약으로 추가했다.
  `inspect_compare_plans()`(inspection.py)는 새 wrapper 없이 기존
  `load_bookmark_plan_json()`으로 plan 파일을 읽는다.
- 검증: `uv run pytest -q` 238 passed, ruff 통과. showcase 023이 실제 책
  한 권을 서로 다른 두 `TypographyConfig`(기본값,
  `position_fallback_enabled=False`)로 `infer`해 만든 실제
  `bookmark_plan.json` 두 개를 비교했다. fallback을 끄면 정확히 fallback이
  찾은 17개 항목만 `removed`되고(added=0, unchanged=154) 나머지는
  그대로였다 - config 옵션의 실제 효과와 compare 기능을 함께 검증했다.
- 의도적으로 미룬 것: `inspect summary`, plan item filter/limit/suspicious
  item/JSONL, metric과 structural signal delta(Phase 4의 structural
  signal이 선행돼야 함), output_dir 자동 탐색 편의 기능.

### 13.4 작업 중 발생한 실수와 수정

Phase 5 작업 중 `feat/inspect-compare` 브랜치를 만들지 않고 `develop`에
직접 커밋하는 실수가 있었다. 사용자 확인 후 `git branch feat/inspect-compare`
로 해당 커밋을 보존하고 `git branch -f develop <이전 커밋>`으로 `develop`
포인터만 되돌렸다(working tree나 커밋 내용에는 영향 없음). 이후 정상적으로
`feat/inspect-compare`에서 마무리하고 `develop`에 fast-forward 병합했다.
`develop`의 현재 히스토리에는 이 실수의 흔적이 남아 있지 않다.

### 13.5 당시 다음 작업 후보

당시 Phase 4/5의 남은 항목(external reference loader, 3단계 reference quality,
structural quality signal, `inspect summary`, plan filter/limit)은 대부분
실제 소비자나 실제 데이터가 생겨야 진행할 수 있는 상태라 지금 우선순위가
낮다. 아직 손대지 않은 Phase 6(cache-aware sweep)과 Phase 7(process/batch/
OCR 통합과 문서화) 중 하나로 넘어가는 것이 다음 자연스러운 단위다. 둘 다
범위가 커서, 착수 전에 첫 수직 단위를 좁게 정하는 논의가 먼저 필요하다.

이 판단에 따라 Phase 7의 `batch` command 계약을 첫 수직 단위로 선택해
완료했다. 이 후보는 이후 §14~15까지 진행됐으며 최신 우선순위는 §15.3을 본다.

## 14. 2026-07-16 갱신: Phase 7 1차 증분(`batch` 계약)과 다음 작업

`feat/batch-result-contract` 브랜치, `develop`에서 분기.

- 구현 커밋: `b815316` (`feat: add batch result/error/event contract`)
- implementation note 커밋: `bcb926d` (노트 058)
- `batch`에 `--config`/`--set`, `--log-mode`, `--format`, `--debug`를 추가하고
  다른 8개 command와 동일한 `CommandResultEnvelope`/`CommandErrorEnvelope`/
  `CommandEventEnvelope` 계약을 적용했다. 새 `src/pdfbooktree/batch_logger.py`가
  `classify/logger.py` 구조를 그대로 복제한다(rich/plain/json/none logger,
  PDF 단위 event).
- 개별 PDF 실패는 classify/ocr-batch와 동일하게 exit 0 + `failed_count` 유지.
  command 자체 예외만 exit 1(runtime)/2(input/config)다.
- 검증: `uv run pytest -q` 246 passed, ruff check/format 통과, 실제 책
  (`data/native-pdf-indexed/퀀트의 세계 - 홍창수.pdf`)으로 stdout/stderr 분리와
  existing-outline fast path를 확인했다.
- 이 단계에서 의도적으로 제외한 item별 immutable run manifest와 batch 전체
  manifest는 이후 2·3차 증분으로 완료됐다(§15). `ocr_policy`와 README 문서화만
  현재 Phase 7 잔여 범위다.

이 브랜치는 이후 `develop`에 반영됐고, 후속 item/batch manifest 작업도 같은 날
순서대로 진행됐다. 최신 상태는 §15를 따른다.

### 다음 작업 후보

이 후보 중 item run과 batch summary 연결은 이후 완료됐다. 최신 다음 작업은
§15.3을 따른다.

## 15. 2026-07-16 갱신: Phase 7 item/batch run manifest 완료와 다음 작업

### 15.1 2차 증분: item별 immutable run manifest

- 구현 커밋: `ea3082d` (`feat: add batch item run manifests`)
- implementation note 커밋: `677607d` (노트 059)
- showcase 커밋: `a28b9e4` (showcase 024)
- `BatchItemResult`가 기존 `ProcessingResult` shape를 유지하면서 `run_id`,
  `run_dir`, `manifest_path`, `config_hash`를 추가로 제공한다.
- `BatchProcessor`는 각 PDF마다 `create_run_context()`를 사용하고, 손상 PDF도
  `allow_unreadable_input=True`로 failed manifest와 nullable page count를 남긴다.
- 검증: `uv run pytest -q` 251 passed, ruff 통과, 실제 책 한 권으로 item과
  manifest의 ID/config/output 연결을 확인했다.

### 15.2 3차 증분: batch 전체 durable manifest

- branch: `feat/batch-run-manifest` (`develop`에서 분기)
- 구현 커밋: `0c7ce00` (`feat: add batch run manifest`)
- implementation note 커밋: `f13970b` (노트 060)
- showcase 커밋: `91aa2f5` (showcase 025)
- `src/pdfbooktree/batch_run.py`에 schema v1 `BatchRunManifest`/
  `BatchRunContext`를 추가했다. batch run은
  `output_root/_batch_runs/<batch_run_id>` 아래에 resolved config와 manifest를
  저장한다.
- manifest는 input directory, recursive 옵션, 발견한 PDF 목록과 selection hash,
  tool/config identity, summary, item `run_id`/manifest/status와 실제 output을
  연결한다.
- 부분 item 실패는 기존 의미대로 succeeded batch + `failed_count`이고, command
  전체 예외만 failed lifecycle과 error type/message를 기록한다.
- `BatchResult`와 CLI JSON result는 `batch_run_id`, `batch_run_dir`,
  `batch_manifest_path`, `config_hash`를 노출한다.
- 검증: `uv run pytest -q` 252 passed, `uv run ruff check src tests`,
  `uv run ruff format --check src tests` 통과. showcase 025가 실제 책 한 권으로
  succeeded batch manifest와 item run/실제 Markdown output 연결을 확인했다.

### 15.3 당시 다음 작업 우선순위

1. README quick start와 artifact/exit-code 문서화 - 현재 public interface와
   durable run 구조가 안정됐으므로 CLI/Python 시작 예제, stdout/stderr, 단일 run,
   item run, batch run directory 구조를 먼저 문서화한다.
2. `ocr_policy` contract 정리 - 현재 `never/auto/always`를 config가 허용하지만
   `Processor`는 `never` 이외 값을 실행하지 않고 warning만 남긴다. 자동 연결은
   Upstage credential/API 비용/cache/overwrite confirmation까지 요구하므로, 별도
   end-to-end 설계 전에는 unsupported 값을 조기 거부하는 방향을 우선 검토한다.
3. Phase 6 첫 수직 단위 - analysis cache key와 cache artifact read/write만 먼저
   구현한 뒤 sweep matrix, resume/jobs, ranking을 후속 증분으로 나눈다.
4. Phase 4/5 잔여 항목은 실제 external gold나 structural ranking 소비자가 생기기
   전까지 보류한다.

위 목록 중 README·artifact 문서화와 Phase 5 review evidence는 2026-07-17에
완료됐다. 최신 상태와 우선순위는 §16을 따른다.

## 16. 2026-07-17 갱신: Markdown graph와 bookmark review evidence

### 16.1 Markdown progressive disclosure graph

- 실험 커밋: `000ebcb` (`exp: validate markdown graph contract`)
- tree 구현 커밋: `5ffeed1` (`feat: export markdown as progressive graph`)
- tree implementation note 커밋: `7d52343` (노트 064)
- split 실험 커밋: `3f83ee6` (`exp: validate markdown split graph contract`)
- split 구현 커밋: `32c9ea1` (`feat: export length-limited markdown as graph`)
- split implementation note 커밋: `ff5ecc7` (노트 065)
- 실제 데이터 showcase 커밋: `1d748ce` (showcase 028)
- 계약 문서 커밋: `14aa122`
- tree와 length-limited split을 공통 `MarkdownExportResult`와
  `markdown_manifest.json` 계약으로 통합했다. 두 mode 모두 첫 줄 YAML front
  matter, 전역 node ID와 고유 파일명, parent/children/previous/next wiki link,
  source/confidence/evidence reference, page coverage와 graph validation을 제공한다.
- 기본 tree 본문은 `content_mode=direct`, split은 `content_mode=bounded`라
  descendant 또는 split boundary 사이의 page text를 중복 저장하지 않는다.
  호환이 필요한 tree 호출만 명시적 `inclusive` mode를 사용할 수 있다.
- run manifest와 `inspect plan`이 Markdown manifest, export mode, validation,
  coverage와 warning을 연결하므로 node 파일 전체를 먼저 읽지 않아도 된다.
- 실제 Shreve PDF showcase에서 tree 238개와 split 36개 node를 생성해 YAML,
  dangling link, 관계 대칭, root 도달성, page 중복, evidence 보존을 검증했다.
- 코드 계약은 구현됐지만 실제 Obsidian GUI에서 vault graph/backlink를 확인하는
  수동 acceptance와 Windows/Linux wheel 교차 검증은 아직 남아 있다.

### 16.2 Phase 5 2차 증분: bookmark review evidence

- 실험 커밋: `be8cb85` (`exp: validate bookmark review evidence contract`)
- 구현 커밋: `fd90662` (`feat: add bookmark review evidence workflow`)
- implementation note 커밋: `ca9ae83` (노트 066)
- 실제 데이터 showcase 커밋: `f13ebc2` (showcase 029)
- `infer`가 `bookmark_review_summary.json`과
  `bookmark_review_items.jsonl`을 항상 생성한다. summary는 전체 품질을 자동
  판정하지 않고 검토 우선순위를 고르는 집계만 제공한다.
- item detail은 plan의 source/confidence/evidence를 유지하면서 후보 좌표·글꼴,
  대체 후보, 주변 타이포그래피, 제한된 원문 preview와 원본 artifact 참조를
  제공한다. 동일 source/page/title 후보는 첫 후보를 canonical로 사용하고 나머지
  참조를 버리지 않는다.
- `inspect plan`의 summary/items/item-id/page-range/level/source/attention/limit
  조합으로 필요한 근거만 점진적으로 읽을 수 있다. 기존 no-option inspection은
  호환성을 유지한다.
- native Hull, scanned-indexed Shreve, OCR 수리통계 PDF에서 candidate mapping과
  원문 page 도달을 검증했다. 전체 테스트는 285개가 통과했다.
- 아직 남은 검토 기능은 수정한 plan을 저장해 `apply`하는 실제 end-to-end
  showcase다. metric이나 calibration되지 않은 종합 score는 릴리스 목표가 아니다.

### 16.3 현재 public surface 판단

- 기본 agent 흐름은 `inspect -> infer -> review -> apply`로 구체화됐다. 비교가
  필요하면 `inspect compare`, 반복 실행이 필요하면 `process`/`batch`를 사용한다.
- repo-local `use-pdfbooktree` skill과 package bundle template은 같은 review·graph
  계약을 설명한다. README도 quick start, artifact 탐색, stdout/stderr와 exit-code
  의미를 포함한다.
- Phase 5의 summary/filter/JSONL 공백은 해소됐다. structural quality signal과
  metric delta는 실제 ranking 소비자가 없으므로 자동 점수화와 함께 보류한다.
- 저장소 전체 Ruff는 기존 experiment/reference 파일의 lint 18건과 format 91건이
  남아 있어 아직 release acceptance를 통과하지 않는다. 변경 파일 검사는 통과했다.

### 16.4 다음 작업 우선순위

1. `processing.ocr_policy` 계약을 닫는다. `auto|always`를 실제 overlay workflow에
   연결하려면 credential, 비용, cache와 overwrite confirmation을 함께 설계해야
   한다. 그 범위를 이번 릴리스에 넣지 않으면 config validation에서 조기 거부하는
   것이 더 작은 안전한 단위다.
2. Markdown graph의 release acceptance를 닫는다. 실제 Obsidian vault에서 graph와
   backlink를 확인하고, `docs/review/to-do-before-release.md`의 구현·검증 항목을
   코드와 showcase 근거에 맞춰 최종 audit한다.
3. 배포 baseline을 완성한다. LICENSE/PyPI metadata, `uv build`, 깨끗한 wheel 설치,
   package skill 포함 여부, CLI smoke test와 전체 Ruff lint/format을 순서대로 처리한다.
4. review item을 수정한 plan으로 저장하고 `apply`하는 실제 end-to-end showcase를
   추가한다. 새 public API보다 현재 JSON 계약으로 충분한지 먼저 확인한다.
5. Phase 6 analysis cache는 위 0.1.0 blocker 이후 시작한다. 첫 수직 단위는
   input/extraction config hash 기반 `PdfAnalysis` cache read/write와 manifest
   hit/miss 기록으로 제한한다. sweep matrix와 자동 best-plan 선택은 후속이다.
