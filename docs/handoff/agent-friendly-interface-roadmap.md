# Agent-friendly interface 로드맵 handoff

## 1. 문서 목적

- 기준일: 2026-07-16
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

이 handoff의 핵심 판단은 기존 bookmark engine algorithm을 다시 설계하지 않고, 이미 검증된 production pipeline을 agent가 단계별로 실행·검토·비교할 수 있는 public interface로 재구성하는 것이다.

목표 lifecycle은 다음과 같다.

```text
inspect -> infer -> evaluate -> sweep/compare -> apply
```

기존 `process`와 `batch`는 이 단계들을 조립하는 convenience workflow로 유지한다.

## 2. 원래 로드맵과 현재 상태

| Phase | 목표 | 상태 | 비고 |
| --- | --- | --- | --- |
| Phase 0 | 현재 public contract와 결과 고정 | 완료 (2026-07-16) | pipeline parity, fast path, process Python/CLI result, artifact JSON shape와 manifest-to-file golden contract를 고정했다. |
| Phase 1 | versioned config와 immutable run 기반 | 완료 | TOML, `--set`, config CLI, config/input hash, run manifest를 구현했다. |
| Phase 2 | core pipeline을 analyze/infer/apply로 분리 | 완료 (2026-07-16) | `pipeline.py`(analyze_pdf/infer_bookmarks/apply_plan/resolve_existing_outline_action), `infer`/`apply` CLI, 로드맵에 없던 existing-outline quality policy까지 추가. 구현 노트 047~049 참고. |
| Phase 3 | 공통 result/error/event 계약 | 대부분 완료 (2026-07-16) | `process`/`infer`/`apply`, config, inspect, 단일 OCR, classify에 schema v1 계약을 적용했다. `ocr-overlay-batch`, parser-level error와 기존 `batch`가 남았다. |
| Phase 4 | evaluator를 production으로 승격 | 미착수 | fuzzy evaluator는 `experiments/102_engine_bookmark_fuzzy_eval.py`에만 있다. |
| Phase 5 | inspect/compare 개선 | 부분 기반 존재 | 기본 inspect API/CLI는 있으나 plan filter, suspicious item, compare가 없다. |
| Phase 6 | cache-aware sweep | 미착수 | analysis cache, matrix parser, ranking이 없다. |
| Phase 7 | process/batch/OCR 통합과 문서화 | 미착수 | 기존 workflow는 존재하지만 새 단계형 계약을 공유하지 않는다. |

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

남은 범위:

- `ocr-overlay-batch`를 같은 result/error/event/stream 계약으로 전환
- OCR batch에서 책별 event의 command context를 `ocr-overlay`와 구분
- Typer callback 진입 전 parser-level 오류의 JSON envelope 처리 여부 결정
- 기존 `batch`는 Phase 7의 config/run/item summary 통합과 함께 전환

### Phase 4. Production evaluator

- 실험 102 fuzzy matcher 승격
- embedded/external reference loader
- reference quality `clean/suspicious/unusable`
- matched/missed/extra detail
- structural quality signal

### Phase 5. Inspect와 compare

- `inspect summary`
- plan item filter, limit, suspicious item, JSONL
- 두 run/plan의 added/removed/moved/level/source diff
- metric과 structural signal delta

### Phase 6. Cache-aware sweep

- input hash와 extraction config 기반 analysis cache key
- TOML sweep matrix parser와 조합 제한
- `--max-runs`, `--resume`, `--jobs`
- reference metric 또는 structural signal ranking
- candidate별 config, plan, metric과 diff artifact

### Phase 7. End-to-end와 batch

- `ocr_policy` 실제 연결 또는 public contract에서 정리
- `process`를 단계형 API 조립기로 마무리
- `batch`에 동일 config/result/run semantics 적용
- item run과 batch summary 연결
- README quick start, artifact 구조와 exit code 문서화

## 8. 다음 작업자 체크리스트

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
- 단일 `ocr-overlay`와 `classify-scan`의 progress는 stderr로 분리됐지만
  `ocr-overlay-batch`는 아직 공통 final result/event 계약을 사용하지 않는다.
- run manifest는 versioned이지만 기존 plan과 모든 중간 artifact가 독립 schema version을 가진 것은 아니다.
- 동일 input/config라도 timestamp가 다르면 새 run이 생성되며 cache hit/resume는 아직 없다.
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

현재 branch 상태:

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
