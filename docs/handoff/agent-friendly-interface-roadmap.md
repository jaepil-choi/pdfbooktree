# Agent-friendly interface 로드맵 handoff

## 1. 문서 목적

- 기준일: 2026-07-16
- 목적: `pdfbooktree`의 agent-friendly interface refactoring에서 원래 계획, 현재 완료 범위, 남은 작업과 다음 구현 순서를 한곳에 기록한다.
- 상세 평가 근거: `docs/review/pkg-evaluation-20260715.md`
- Phase 1 구현 커밋: `ea4d4fd` (`feat: add reproducible config and run interface`)
- Phase 1 구현 노트: `docs/vibe/implementations/046_ea4d4fd6289e.md`

이 handoff의 핵심 판단은 기존 bookmark engine algorithm을 다시 설계하지 않고, 이미 검증된 production pipeline을 agent가 단계별로 실행·검토·비교할 수 있는 public interface로 재구성하는 것이다.

목표 lifecycle은 다음과 같다.

```text
inspect -> infer -> evaluate -> sweep/compare -> apply
```

기존 `process`와 `batch`는 이 단계들을 조립하는 convenience workflow로 유지한다.

## 2. 원래 로드맵과 현재 상태

| Phase | 목표 | 상태 | 비고 |
| --- | --- | --- | --- |
| Phase 0 | 현재 public contract와 결과 고정 | 부분 완료 | 일반 회귀 테스트는 있으나 pipeline parity와 대표 artifact golden contract가 부족하다. |
| Phase 1 | versioned config와 immutable run 기반 | 완료 | TOML, `--set`, config CLI, config/input hash, run manifest를 구현했다. |
| Phase 2 | core pipeline을 analyze/infer/apply로 분리 | 완료 (2026-07-16) | `pipeline.py`(analyze_pdf/infer_bookmarks/apply_plan/resolve_existing_outline_action), `infer`/`apply` CLI, 로드맵에 없던 existing-outline quality policy까지 추가. 구현 노트 047~049 참고. |
| Phase 3 | 공통 result/error/event 계약 | 미착수 | 일부 명령만 JSON을 제공하며 exit code와 progress stream이 통일되지 않았다. |
| Phase 4 | evaluator를 production으로 승격 | 미착수 | fuzzy evaluator는 `experiments/102_engine_bookmark_fuzzy_eval.py`에만 있다. |
| Phase 5 | inspect/compare 개선 | 부분 기반 존재 | 기본 inspect API/CLI는 있으나 plan filter, suspicious item, compare가 없다. |
| Phase 6 | cache-aware sweep | 미착수 | analysis cache, matrix parser, ranking이 없다. |
| Phase 7 | process/batch/OCR 통합과 문서화 | 미착수 | 기존 workflow는 존재하지만 새 단계형 계약을 공유하지 않는다. |

## 3. Phase 0 진행 상태

Phase 0의 목적은 refactoring 전후의 bookmark plan과 artifact가 의도치 않게 달라지는 것을 자동으로 탐지하는 것이다.

현재 확보된 기반:

- 전체 테스트 148개가 통과한다.
- 기존 outline 처리와 Markdown export에 대한 `Processor` 테스트가 있다.
- Phase 1에서 config validation, config CLI, process run integration, manifest lifecycle 테스트를 추가했다.
- package root import contract 테스트가 있다.

아직 필요한 항목:

1. 현재 `Processor.run()` 조립과 실험 102의 `_predict_plan()` 조립이 같은 plan을 만드는 parity test
2. 기본 config에서 refactoring 전후 plan item의 title, page, level, source가 완전히 같은지 검증하는 characterization test
3. 기존 outline fast path가 typography extraction을 실행하지 않는다는 회귀 테스트
4. 대표 native/OCR PDF의 주요 artifact 이름과 shape를 고정하는 contract 검증
5. `process`의 기존 Python/CLI 결과 계약을 고정하는 golden test

Phase 0 전체를 별도 프로젝트로 다시 시작하지 않는다. Phase 2에서 실제로 건드리는 계약에 필요한 항목을 Phase 2의 첫 작업 단위로 보완한다.

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

## 5. 다음 작업: Phase 2 범위

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

- versioned result/error envelope
- 모든 command의 `--format human|json`
- stdout final result와 stderr progress 분리
- pipeline event protocol과 JSONL renderer
- documented exit code와 `--debug`

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

1. `develop`에서 `feat/pipeline-stages` 같은 Phase 2 feature branch를 만든다.
2. Phase 2 진입 parity/characterization test부터 추가한다.
3. `PdfAnalysis`, `BookmarkInferenceResult`, `ApplyResult`의 최소 public shape를 확정한다.
4. `analyze_pdf()`와 `infer_bookmarks()`를 추출한 뒤 기존 `Processor`가 이를 사용하게 한다.
5. `apply_plan()`과 plan loader를 분리한다.
6. `infer`/`apply` CLI와 help/contract test를 추가한다.
7. `uv run pytest`, `uv run ruff check src tests`, `uv run ruff format --check src tests`를 실행한다.
8. 실제 PDF로 showcase를 실행하고 결과를 기록한다.
9. 구현 커밋 뒤 implementation note를 별도 커밋한다.

## 9. 알려진 주의사항

- 기존 긴 `process` option은 Rich help의 기본 폭에서 일부 이름이 생략된다.
- `ProcessingConfig.ocr_policy`는 아직 `Processor`에 연결되지 않았다.
- failed `ProcessingResult`의 CLI exit code는 아직 공통 규칙으로 정규화되지 않았다.
- run manifest는 versioned이지만 기존 plan과 모든 중간 artifact가 독립 schema version을 가진 것은 아니다.
- 동일 input/config라도 timestamp가 다르면 새 run이 생성되며 cache hit/resume는 아직 없다.
- corporate PC에서는 권한 상승 shell의 원래 Codex 실행 파일 접근이 거부될 수 있으므로 `AGENTS.md`의 `C:\tmp\codex-apply-patch.exe --codex-run-as-apply-patch` 우회 규칙을 따른다.

## 10. 2026-07-16 갱신: Phase 2 완료, 다음 작업 제안

Phase 2 완료 조건(§5.8) 6개를 모두 충족했다. `feat/pipeline-stages` 브랜치, 커밋:

- `cfb8eaed` analyze/infer/apply 분리 (노트 `047_cfb8eaed0dd3.md`)
- `f2d80167` existing-outline quality policy 추가 — 로드맵에 없던 스코프. 기존 bookmark가 있으면 기본적으로 skip하는 canonical 동작은 유지하되, 실험 102 기준(item ≤3개, item 수가 page 수의 0.9배 이상) + numeric-only title 신호로 low quality를 항상 판정해 표시하고, `outline_quality.replace_when_low_quality`로만 opt-in 교체한다 (노트 `048_f2d801675acc.md`)
- `0757e094` `infer`/`apply` CLI를 이 policy 위에 추가 (노트 `049_0757e09437b4.md`)

각 노트의 "남은 리스크"에 다음이 남아 있다:

1. `numeric_only_title`/임계값(`min_item_count=4`, `max_item_to_page_ratio=0.9`)이 실제 300STUDY 코퍼스로 검증되지 않았다 — showcase 2권만 확인함.
2. Phase 0 잔여 항목(§3) 중 대표 native/OCR PDF artifact contract 고정, `process` CLI/Python 결과 golden test가 여전히 없다.
3. `experiments/102_engine_bookmark_fuzzy_eval.py::_predict_plan()`이 `infer_bookmarks()`를 호출하도록 단순화되지 않아 production과 갈라질 수 있다.

**다음 작업 우선순위 제안**: (1) 300STUDY 전체로 새 `assess_outline_quality()` 임계값 실측 검증 실험 → (2) Phase 0 golden/contract test 보강 → (3) Phase 3(공통 result/error/event 계약, `infer`/`apply` exit code 정규화 포함) 착수.
