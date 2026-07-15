# pdfbooktree 패키지 인터페이스 평가

## 1. 문서 정보

- 평가일: 2026-07-15
- 평가 대상: `pdfbooktree`의 Python public interface, CLI, config, artifact, report, metric 및 agent workflow
- 기준 브랜치와 커밋: `develop`, `06f214f`
- 검토 자료:
  - `git log --oneline --decorate -n 40`
  - `experiments/experiments.json`
  - `docs/vibe/prd.md`
  - `src/pdfbooktree/`
  - `tests/`, `showcase/`, 최근 implementation note
  - 실제 `uv run pdfbooktree ... --help` 출력
- 평가 범위: 분석과 설계 제안만 포함한다. 이 문서 작성 시점에는 `src/`와 `tests/`를 변경하지 않았다.

## 2. 결론

현재 패키지는 단일 PDF를 한 번 처리하는 library/CLI와 읽기 전용 inspection 도구로서는 좋은 기반을 갖췄다. 설치형 CLI, 1-based page convention, typed dataclass, 중간 artifact, OCR cache와 progress, 기존 bookmark 보호 같은 핵심 토대가 이미 구현되어 있다.

그러나 PRD가 요구하는 agent-friendly interface, 특히 책마다 여러 config를 바꿔가며 bookmark plan을 만들고 평가한 뒤 가장 적절한 결과를 선택하는 workflow는 아직 public interface로 모델링되지 않았다.

현재 구조는 대체로 다음 한 단계에 머문다.

```text
process(pdf, config) -> PDF + Markdown + report
```

Agent가 실제로 필요로 하는 구조는 다음과 같다.

```text
inspect -> infer -> evaluate -> sweep/compare -> apply
```

따라서 다음 작업의 중심은 옵션을 더 추가하는 것이 아니라, 이미 검증된 production pipeline을 재사용 가능한 단계와 안정된 실행 계약으로 분리하는 refactoring이어야 한다.

## 3. 현재 구현과 최근 변화

### 3.1 주요 public interface

현재 top-level CLI는 다음 명령을 제공한다.

- `ocr-overlay`
- `ocr-overlay-batch`
- `process`
- `batch`
- `classify-scan`
- `inspect`

`inspect` 하위에는 다음 명령이 있다.

- `page-count`
- `text`
- `bookmarks`
- `ocr`
- `plan`

Python package root는 다음 범주의 public symbol을 제공한다.

- `Processor`, `BatchProcessor`
- `ProcessingConfig`, `TypographyConfig`, `MarkdownSplitConfig`
- `ProcessingResult`, `BatchResult`, bookmark/typography/result dataclass
- `inspect_page_count`, `inspect_text`, `inspect_bookmarks`, `inspect_ocr_artifact`, `inspect_plan_artifact`

### 3.2 관련 git 이력

최근 구현 흐름은 PRD의 우선순위를 잘 따라가고 있다.

- `2506da2 feat: add agent inspection CLI`
  - 읽기 전용 Python inspection API와 `pdfbooktree inspect`를 추가했다.
- `9b301d7 feat: add geometry outline and markdown fallback`
  - geometry/font 기반 후보 추출과 Markdown coverage fallback을 public pipeline에 연결했다.
- `a59def0 fix: rescue body-tier heading via position fallback`
  - font 골격을 유지하면서 body-tier에 흡수된 heading을 반복 위치로 복구했다.
- `06f214f exp: evaluate engine against 300STUDY embedded bookmarks`
  - production pipeline을 400권에 평가해 책별 품질 편차와 튜닝 필요성을 수치로 확인했다.

### 3.3 최근 평가 결과

실험 `102_engine_bookmark_fuzzy_eval`은 `data/300STUDY` 아래 page count가 100보다 크고 embedded bookmark가 있는 PDF 400권을 대상으로 production 기본 pipeline을 평가했다.

- 전체 400권:
  - mean precision: 0.3393
  - mean recall: 0.6932
  - mean F1: 0.4089
  - mean Jaccard accuracy: 0.3046
- clean gold 312권:
  - mean precision: 0.3801
  - mean recall: 0.7985
  - mean F1: 0.4662
- junk gold 88권:
  - mean F1: 0.2057
- text layer가 사실상 없어 predicted bookmark가 0개였던 책: 6권, 1.5%

최고 사례는 F1 0.9 이상이지만, OCR 수식/기호가 font 골격을 오염시키거나 gold 자체가 부정확한 책은 매우 낮은 결과를 보였다. 이 편차는 단일 기본 config만 제공해서는 충분하지 않으며, reference 품질 판정과 책별 config 비교 workflow가 필요하다는 근거다.

## 4. 잘 되어 있는 점

### 4.1 설치형 CLI와 명령 구조

`pyproject.toml`의 `pdfbooktree = "pdfbooktree.cli:main"` entry point로 패키지 설치 후 일관된 명령을 사용할 수 있다. OCR, 분류, process, inspection이 한 root command 아래 있어 발견성이 좋다.

### 4.2 1-based page convention

CLI page range, inspection result, bookmark plan 등 public interface가 1-based PDF page를 사용한다. `inspect text`는 범위를 검증하고 잘못된 page에 `page_count`를 포함한 오류를 제공한다. 이는 PRD의 page convention 요구와 일치한다.

### 4.3 읽기 전용 inspection API

`2506da2`에서 추가된 inspection interface는 agent가 전체 pipeline을 실행하기 전에 다음을 확인할 수 있게 한다.

- page count
- 지정 page text
- 기존 bookmark
- OCR artifact의 complete/partial/missing 상태
- raw/insertable cache 수, 중복 page, 첫 미처리 page
- bookmark plan validation과 Markdown export 요약

특히 inspection 명령은 기본 Rich 출력과 `--json`을 모두 제공한다.

### 4.4 typed config와 result

`TypographyConfig`, `ProcessingConfig`는 frozen dataclass이고, pipeline 사이의 주요 데이터도 dataclass로 정의되어 있다. Python 사용자에게 명시적인 타입과 기본값을 제공하고 CLI와 Python 구현이 같은 개념을 공유할 수 있는 기반이다.

### 4.5 검토 가능한 중간 artifact

`Processor`는 다음 artifact를 저장한다.

- `whole_book_lines.jsonl`
- `font_size_tiers.json`
- `height_tiers.json`
- `heading_candidates.json`
- `position_fallback_candidates.json`
- `bookmark_plan.json`
- `bookmark_plan_validation.json`
- processing report

이는 pipeline의 근거를 숨기지 않고 agent가 사후 검토할 수 있게 한다.

### 4.6 안전한 output 정책

- 원본 PDF를 직접 덮어쓰지 않는다.
- 기본적으로 기존 bookmark가 있으면 typography 추론과 outline overwrite를 건너뛴다.
- OCR overwrite에는 명시적 확인 flag가 있다.
- PDF와 Markdown 결과 경로를 별도로 만든다.

### 4.7 OCR의 cache와 runtime logging

OCR interface는 cache policy, engine option, 진행률, JSONL log와 progress snapshot을 지원한다. 긴 실행을 resume하거나 partial artifact를 검사하는 agent workflow에 적합한 부분이다.

## 5. 발견 사항

### F-01. `Processor.run()`이 추론과 적용을 모두 수행한다

- 우선순위: 최상
- 근거: `src/pdfbooktree/processor.py:47-136`

현재 `Processor.run()`은 다음을 한 번에 수행한다.

1. line 추출
2. margin 제거
3. font/height tier 계산
4. geometry heading 후보 선택
5. BPE hierarchy 추론
6. position fallback 삽입
7. plan validation
8. artifact 기록
9. bookmarked PDF 생성
10. Markdown export
11. report 기록

이 구조에서는 plan만 빠르게 생성하거나, 같은 분석 결과에 config만 바꿔 재추론하거나, 선택한 plan만 나중에 export하기 어렵다. 튜닝 중에도 매번 PDF/Markdown을 만들게 된다.

권장 조치:

- 분석, 추론, 평가, 적용 단계를 public API로 분리한다.
- `process`는 이 단계들을 조립하는 convenience facade로 유지한다.

### F-02. production plan-only API가 없다

- 우선순위: 최상
- 근거: `experiments/102_engine_bookmark_fuzzy_eval.py:163-176`

실험 102는 production과 같은 plan을 얻기 위해 `extract_typography_lines`, `exclude_margin_artifacts`, `compute_geometry_font_tier_set`, `build_geometry_context`, `select_geometry_headings`, `infer_bpe_outline`, `select_body_tier_position_fallback`, `insert_position_fallback`을 직접 다시 조립한다.

이는 다음을 의미한다.

- public `Processor`가 평가/실험에 필요한 최소 결과를 제공하지 않는다.
- production pipeline 변경 시 evaluator가 쉽게 drift할 수 있다.
- agent나 외부 사용자가 내부 module 조립 순서를 알아야 한다.

권장 조치:

- `infer_bookmarks()` 또는 `BookmarkInferencer.infer()`를 public API로 만든다.
- `Processor`와 evaluator가 반드시 이 API를 사용하도록 한다.

### F-03. evaluator와 metric이 experiment에만 있다

- 우선순위: 최상
- 근거: `experiments/102_engine_bookmark_fuzzy_eval.py:108-160`

실험에는 fuzzy title + page tolerance 기반 1:1 matching과 precision, recall, F1, Jaccard, exact-page-match 계산이 있지만 `src/`에는 없다.

그 결과 agent는 다음을 할 수 없다.

- 현재 plan을 embedded bookmark와 비교
- 외부 JSON reference와 비교
- 두 config의 metric을 동일 기준으로 비교
- matched/missed/extra item을 조사

권장 조치:

- evaluator를 `src/pdfbooktree/evaluation/`으로 승격한다.
- matching threshold와 page tolerance를 명시적 config로 만든다.
- summary뿐 아니라 match detail artifact를 저장한다.

### F-04. 현재 `confidence`는 품질 metric으로 해석하기 어렵다

- 우선순위: 높음
- 근거:
  - `src/pdfbooktree/processor.py:124-131`
  - `src/pdfbooktree/processor.py:243-251`
  - `src/pdfbooktree/typography/position_fallback.py:117`

현재 confidence summary는 다음 heuristic을 섞는다.

- line 존재 여부를 1.0/0.0으로 표현
- font/height tier 수를 4로 나눈 tiering confidence
- candidate confidence 평균
- plan item confidence 평균
- fallback 후보의 고정 confidence 0.6

이는 reference 기반 precision/recall이나 calibration된 확률이 아니다. Agent가 `outline=0.8`을 “80% 정확도”로 오해할 위험이 있다.

권장 조치:

- `confidence`를 근거 점수인 `heuristic_score` 또는 `signal_score`로 명확히 명명한다.
- `reference_metrics`와 `structural_quality`를 별도 namespace로 둔다.
- calibration 전에는 확률처럼 보이는 표현을 피한다.

### F-05. config가 재현 가능한 실행 단위로 저장되지 않는다

- 우선순위: 최상
- 근거:
  - `src/pdfbooktree/config.py`
  - `src/pdfbooktree/report.py`

Processing report는 result만 저장하고 실제 resolved config를 포함하지 않는다. 다음 정보도 없다.

- config schema version
- config source file
- CLI override
- resolved config
- config hash
- input PDF hash
- package version/git revision
- run ID

따라서 나중에 어떤 설정으로 plan이 생성됐는지 완전히 재현하기 어렵다.

권장 조치:

- versioned config file을 도입한다.
- 매 실행마다 `config.resolved.json`과 config hash를 저장한다.
- run manifest에 input fingerprint와 tool version을 기록한다.

### F-06. artifact가 고정 이름으로 저장되어 실행 간 충돌한다

- 우선순위: 최상
- 근거:
  - `src/pdfbooktree/artifacts.py:12-27`
  - `src/pdfbooktree/utils/paths.py:41-56`

같은 output directory에서 config를 바꿔 다시 실행하면 `bookmark_plan.json`, `heading_candidates.json`, report, PDF와 Markdown 경로가 이전 실행과 충돌한다. Markdown 디렉터리에는 이전 실행에서만 존재했던 파일이 stale artifact로 남을 가능성도 있다.

권장 조치:

- book/workspace 아래에 immutable run directory를 만든다.
- 예: `runs/<book-id>/<run-id>/...`
- 동일 input/config hash는 resume 또는 cache hit로 처리한다.
- final apply 결과는 선택된 run ID를 기록한다.

### F-07. CLI와 Python config의 노출 범위가 다르다

- 우선순위: 높음
- 근거:
  - `src/pdfbooktree/config.py:13-38`
  - `src/pdfbooktree/cli.py:388-523`

`TypographyConfig`에는 26개 field가 있지만 `process` CLI에는 약 절반만 노출된다. 다음과 같은 설정은 Python에서만 변경할 수 있다.

- `line_y_tolerance_ratio`
- `min_tier_gap`
- `max_heading_length`
- `min_heading_confidence`
- `heading_merge_gap_ratio`
- `bpe_min_pair_count`
- `bpe_max_iterations`
- margin position/repeated-line 관련 설정
- fallback body-font ratio low/high
- fallback title dedupe threshold

모든 field를 CLI flag로 늘리는 것도 해결책은 아니다. 이미 `process --help`가 길고 복잡하다.

권장 조치:

- 공통적인 설정만 short CLI option으로 제공한다.
- 전체 설정은 `--config FILE`과 반복 가능한 `--set key=value`로 제공한다.
- `config schema/defaults/explain/validate` 명령을 추가한다.

### F-08. 실제 `--help` 출력에서 긴 option 이름이 잘린다

- 우선순위: 높음
- 근거: 실제 `uv run pdfbooktree process --help` 실행

기본 terminal 폭에서 다음과 같이 긴 option 이름이 생략된다.

- `--heading-candi...`
- `--position-fall...`
- `--body-font-tex...`

Agent는 `--help`만 보고 정확한 flag를 구성해야 하므로 option 이름 생략은 실질적인 인터페이스 오류다.

권장 조치:

- top-level flag 수와 길이를 줄인다.
- advanced setting은 config file로 이동한다.
- Rich help width와 option rendering을 조정한다.
- command별 runnable example을 help footer에 넣는다.

### F-09. machine-readable output이 명령마다 다르다

- 우선순위: 최상
- 근거: `src/pdfbooktree/cli.py`

`inspect`는 `json.dumps()`를 사용한 실제 JSON 한 줄을 제공하지만 `process`, `batch`, OCR summary, classify summary는 `rich_print(to_jsonable(...))`를 사용한다.

문제점:

- `process --json`이 없다.
- Rich 출력은 안정적인 parser contract가 아니다.
- schema version이 없다.
- progress와 최종 result의 stream 분리가 일관되지 않는다.
- 오류도 동일한 JSON envelope로 반환되지 않는다.

권장 조치:

- 모든 command에 공통 `--format human|json`을 제공한다.
- stdout에는 final result 하나만 출력한다.
- progress/event는 stderr 또는 별도 JSONL stream으로 출력한다.
- result/error envelope에 schema version을 넣는다.

### F-10. process 실패가 exit code에 반영되지 않는다

- 우선순위: 최상
- 근거:
  - `src/pdfbooktree/processor.py:94-113`
  - `src/pdfbooktree/cli.py:522-523`

Plan validation이 실패하면 `ProcessingResult.status="failed"`가 되지만 CLI는 result를 출력한 뒤 정상 반환한다. 코드상 `typer.Exit`이나 다른 non-zero exit 처리가 없다.

Agent는 exit code를 자동 분기 조건으로 사용하므로 이것은 중요한 계약 결함이다.

권장 조치:

- failed result는 documented non-zero exit code를 반환한다.
- usage/config/input/quality/execution failure를 구분한다.
- batch는 전체 command exit와 item별 status의 의미를 별도로 정의한다.

### F-11. process 실행에는 단계/page progress가 없다

- 우선순위: 높음
- 근거: `src/pdfbooktree/processor.py`와 typography module에 logger/event interface가 없음

OCR과 classify는 runtime logger가 있지만 typography process는 긴 실행 중 현재 stage, page, artifact를 terminal에 알리지 않는다.

권장 조치:

- core pipeline에서 presentation과 분리된 event callback/protocol을 정의한다.
- 최소 event: `run_started`, `stage_started`, `page_progress`, `artifact_written`, `warning`, `run_finished`, `run_failed`.
- human renderer와 JSONL renderer가 같은 event를 소비하게 한다.

### F-12. 일반 process 오류가 agent용 error로 정규화되지 않는다

- 우선순위: 높음

Inspection은 일부 `FileNotFoundError`와 `ValueError`를 `BadParameter`로 바꾸지만 process와 OCR의 일반 실패는 공통 error envelope가 없다. PRD가 요구하는 원인, 위치, 관련 artifact, 다음 확인 작업을 보장하지 않는다.

권장 조치:

- `PdfBookTreeError` 계층과 stable error code를 정의한다.
- 기본 모드에서는 stack trace를 숨긴다.
- `--debug`에서만 exception chain과 stack trace를 보인다.
- error payload에 `stage`, `input`, `artifact_paths`, `next_actions`를 포함한다.

### F-13. `inspect plan`은 실제 plan을 조사하기에 부족하다

- 우선순위: 높음
- 근거: `src/pdfbooktree/inspection.py:158-202`

현재 반환하는 정보는 plan path, item count, level 목록, validation, report/Markdown summary다. 실제 plan item과 evidence를 보여주지 않는다.

필요한 기능:

- plan item preview/list
- `--level`, `--pages`, `--source`, `--min-score`, `--limit`
- fallback item만 보기
- duplicate/long/formula-like/body-like suspicious item 보기
- 같은 page 내 순서 확인
- JSONL 출력

### F-14. plan compare interface가 없다

- 우선순위: 높음

Config 두 개를 실행해도 agent가 결과 차이를 구조적으로 비교할 수 없다. 파일 두 개를 직접 읽고 fuzzy matching을 다시 구현해야 한다.

권장 조치:

- `compare` 명령과 Python API를 제공한다.
- added, removed, title-changed, page-moved, level-changed, source-changed를 구분한다.
- metric delta와 suspicious item delta를 함께 보여준다.

### F-15. batch CLI가 process config를 전달하지 못한다

- 우선순위: 높음
- 근거: `src/pdfbooktree/cli.py:526-539`

`batch` CLI option은 input, output, recursive뿐이다. `BatchProcessor` Python API는 `ProcessingConfig`를 받을 수 있지만 CLI에서는 config를 전달할 수 없다.

권장 조치:

- single과 batch가 같은 `--config`, `--set`, output format 계약을 사용하게 한다.
- item별 run directory와 batch summary를 연결한다.

### F-16. expensive analysis 재사용 계약이 없다

- 우선순위: 최상

Config sweep에서 가장 비싼 whole-book line extraction과 geometry context 계산을 매번 다시 수행할 가능성이 높다. 현재 artifact는 저장되지만 다음 run의 입력 cache로 읽는 public 계약이 없다.

권장 조치:

- raw PDF feature extraction과 config-dependent inference를 분리한다.
- input hash + extraction config hash로 analysis cache key를 만든다.
- sweep는 동일 analysis를 재사용한다.

### F-17. embedded bookmark reference 품질을 명시하지 않는다

- 우선순위: 최상
- 근거:
  - `src/pdfbooktree/pdf/bookmarks.py:55-79`
  - 실험 102의 junk gold 88권

Embedded bookmark가 실제 목차가 아니라 page별 scan filename 또는 placeholder일 수 있다. Reference 품질을 보지 않고 F1을 최적화하면 잘못된 gold에 과적합할 수 있다.

권장 조치:

- evaluator output에 `reference_quality`와 reason을 넣는다.
- `clean`, `suspicious`, `unusable`을 구분한다.
- suspicious reference를 자동 sweep objective로 사용할 때는 명시적 override를 요구한다.

### F-18. gold가 없는 책의 선택 기준이 없다

- 우선순위: 최상

실제 목표 문서는 bookmark가 없는 경우가 많으므로 reference F1을 사용할 수 없다. 단순히 heuristic confidence 평균이 높은 config를 “best”라고 부르면 안 된다.

권장 조치:

Reference가 없을 때 다음 structural quality를 별도 계산한다.

- bookmark plan validation
- bookmark 수와 page당 밀도
- level 분포와 level jump
- duplicate title 비율
- 지나치게 긴 제목 비율
- 수식/LaTeX/기호 중심 제목 비율
- body-like candidate 비율
- fallback 비율
- same-page order ambiguity
- Markdown coverage와 overflow

이 경우 CLI는 `best` 대신 `recommended_candidate` 또는 `review_priority`를 사용하고, 선택 근거와 불확실성을 출력해야 한다.

### F-19. `ProcessingConfig.ocr_policy`가 실제 pipeline에 연결되지 않았다

- 우선순위: 중간
- 근거: `src/pdfbooktree/processor.py:88-92`

`ocr_policy`는 config에 있지만 `Processor`가 사용하지 않고 warning만 남긴다. Public config에 존재하는 값과 실제 동작이 다르다.

권장 조치:

- end-to-end process에 실제 연결하거나,
- 연결 전까지 public config에서 experimental/unsupported 상태를 명확히 표시한다.

### F-20. 실패 result가 존재하지 않는 예정 output 경로를 포함할 수 있다

- 우선순위: 중간
- 근거: `src/pdfbooktree/processor.py:115-122`

Validation 실패로 export하지 않았어도 `output_pdf`와 `output_markdown_dir`에 planned path가 채워질 수 있다. Agent는 경로가 존재한다고 오해할 수 있다.

권장 조치:

- 실제 생성된 artifact와 planned artifact를 분리한다.
- 예: `artifacts.output_pdf={path, exists, state}` 또는 `planned_outputs` 별도 field.

### F-21. Python config validation이 충분하지 않다

- 우선순위: 중간

CLI에서 노출된 일부 값은 Typer range로 검증하지만 Python에서 dataclass를 직접 만들 때는 동일한 validation이 보장되지 않는다. 일부 오류는 pipeline 내부에 도달한 후 발생한다.

권장 조치:

- config construction 시 공통 validation을 수행한다.
- CLI와 Python이 동일한 validator를 사용한다.
- field 간 제약도 검증한다.

### F-22. machine-readable artifact에 schema version이 없다

- 우선순위: 높음

JSON/JSONL artifact는 향후 dataclass field 변경에 따라 형태가 바뀔 수 있지만 schema version이 없다. Inspection code도 특정 파일명과 현재 shape에 의존한다.

권장 조치:

- run manifest, result envelope, plan, evaluation, event에 version을 둔다.
- 모든 내부 artifact에 version을 중복할 필요는 없지만 최소한 run manifest가 artifact schema set을 선언해야 한다.

### F-23. README가 비어 있다

- 우선순위: 높음
- 근거: `README.md`

현재는 `--help` 외에 설치, 기본 workflow, Python 예, config, artifact, exit code를 학습할 문서가 없다.

권장 조치:

- CLI quick start
- Python quick start
- inspect/infer/evaluate/apply workflow
- config precedence
- stdout/stderr와 exit code 계약
- artifact directory 구조
- embedded gold 주의사항

## 6. 목표 interface

### 6.1 권장 CLI lifecycle

```text
pdfbooktree inspect
pdfbooktree infer
pdfbooktree evaluate
pdfbooktree sweep
pdfbooktree compare
pdfbooktree apply
pdfbooktree process
pdfbooktree batch
pdfbooktree config
```

각 명령의 책임은 다음과 같다.

| 명령 | 책임 | final PDF/Markdown 변경 |
| --- | --- | --- |
| `inspect` | PDF와 artifact를 값싸게 읽기 전용 조사 | 없음 |
| `infer` | plan과 근거 artifact 생성 | 없음 |
| `evaluate` | plan과 reference 또는 structural rule 비교 | 없음 |
| `sweep` | config 조합 실행, 평가, 후보 ranking | 없음 |
| `compare` | 두 run/plan의 차이 설명 | 없음 |
| `apply` | 선택한 plan으로 PDF/Markdown 생성 | 있음 |
| `process` | inspect/OCR/infer/validate/apply convenience workflow | 있음 |
| `batch` | 동일 config 계약으로 여러 PDF 처리 | 있음 |
| `config` | defaults/schema/init/explain/validate | config 파일만 생성 가능 |

### 6.2 사용 예

```powershell
uv run pdfbooktree inspect summary "book.pdf" --format json

uv run pdfbooktree infer "book.pdf" `
  --config configs/default.toml `
  --run-dir runs/base `
  --format json

uv run pdfbooktree evaluate runs/base `
  --reference embedded `
  --format json

uv run pdfbooktree sweep "book.pdf" `
  --matrix configs/book-sweep.toml `
  --reference embedded `
  --run-dir runs/sweep-001 `
  --format json

uv run pdfbooktree compare runs/base runs/sweep-001/candidates/003 `
  --format json

uv run pdfbooktree apply "book.pdf" `
  --plan runs/sweep-001/candidates/003/bookmark_plan.json `
  --output-dir output `
  --format json
```

### 6.3 config 형식

권장 형식은 다음과 같다.

- 입력 config: TOML
- final result와 manifest: JSON
- 대량 row/event: JSONL

TOML을 권장하는 이유:

- 사람이 읽고 수정하기 쉽다.
- 주석을 쓸 수 있다.
- bool, number, string, array 타입이 명확하다.
- 이 프로젝트가 이미 `pyproject.toml`을 사용한다.
- YAML의 암묵적 타입 변환 문제를 피할 수 있다.

예시:

```toml
schema_version = 1

[processing]
skip_existing_bookmarks = true
ocr_policy = "never"

[typography]
heading_candidate_mode = "font"
body_font_text_coverage = 0.95
body_font_max_words = 20
position_min_repeated_pages = 5
position_fallback_enabled = true
position_fallback_tolerance = 2.0
position_fallback_min_isolation_ratio = 1.0

[markdown]
max_words = 10000
max_words_coverage = 0.95

[sweep]
"typography.body_font_text_coverage" = [0.90, 0.95, 0.98]
"typography.position_fallback_tolerance" = [1.0, 2.0, 3.0]
"typography.position_min_repeated_pages" = [3, 5, 8]

[objective]
metric = "reference.f1"
min_precision = 0.40
min_recall = 0.60
```

Config precedence는 다음처럼 단순하게 고정한다.

```text
package defaults < config file < --set overrides
```

### 6.4 공통 result envelope

모든 `--format json` command는 stdout에 final JSON object 하나를 출력한다.

```json
{
  "schema_version": "1",
  "command": "infer",
  "status": "succeeded",
  "run_id": "20260715-153314-a83f21",
  "input": {
    "path": "book.pdf",
    "sha256": "...",
    "page_count": 481
  },
  "config": {
    "resolved_path": "config.resolved.json",
    "hash": "..."
  },
  "summary": {
    "bookmark_count": 69,
    "level_counts": {"1": 21, "2": 48},
    "fallback_count": 5,
    "validation_valid": true
  },
  "warnings": [],
  "artifacts": {
    "plan": {
      "path": "bookmark_plan.json",
      "exists": true
    }
  },
  "next_actions": [
    {
      "command": "pdfbooktree evaluate ...",
      "reason": "embedded bookmark reference를 사용할 수 있다"
    }
  ]
}
```

권장 출력 원칙:

- stdout: final result 또는 error envelope 하나
- stderr: human progress 또는 JSONL event
- `--debug`: stack trace 활성화
- `--quiet`: progress 비활성화
- 모든 artifact path에 실제 존재 여부 표시

### 6.5 exit code

초기에는 지나치게 세분화하지 않고 다음 정도로 시작하는 것이 적절하다.

| 코드 | 의미 |
| --- | --- |
| 0 | 성공 |
| 2 | CLI usage/config 오류 |
| 3 | 입력 PDF/artifact 오류 |
| 4 | quality/validation 실패로 apply하지 않음 |
| 5 | 실행 중 내부 또는 외부 provider 실패 |

Batch는 item별 status를 summary에 저장하고, command exit 정책은 별도로 문서화한다.

### 6.6 Python API

CLI와 같은 단계가 Python에서도 public이어야 한다.

```python
analysis = analyze_pdf("book.pdf", cache_dir="cache")

run = infer_bookmarks(
    analysis,
    config=TypographyConfig(...),
    run_dir="runs/base",
)

evaluation = evaluate_plan(
    run.plan,
    reference="embedded",
)

result = apply_plan(
    "book.pdf",
    run.plan,
    output_dir="output",
)
```

`Processor`는 이 API를 다시 구현하지 않고 조립만 해야 한다.

## 7. 평가 모델

### 7.1 reference 기반 metric

Embedded 또는 외부 reference가 신뢰 가능할 때 다음을 계산한다.

- ground truth count
- predicted count
- true positive count
- precision
- recall
- F1
- Jaccard
- exact page match rate
- level accuracy
- parent accuracy
- matched items
- missed gold items
- extra predicted items

Matching 설정도 결과에 기록한다.

- title similarity 방식과 threshold
- page tolerance
- level/parent를 matching gate로 사용할지 여부

### 7.2 reference quality

최소 상태:

- `clean`: 자동 비교/최적화에 사용 가능
- `suspicious`: 결과 표시 가능, 자동 최적화는 명시적 override 필요
- `unusable`: reference objective 사용 불가

품질 판정 reason도 구조화한다.

- `per_page_scan_filenames`
- `placeholder_or_tiny`
- `flat_tool_generated_outline`
- `non_monotonic_pages`
- `missing_target_pages`
- `unknown`

### 7.3 structural quality

Gold가 없을 때는 정답 metric처럼 표현하지 않고 검토 우선순위를 정하는 signal로만 사용한다.

권장 signal:

- plan valid
- bookmark density
- level distribution
- duplicate title ratio
- formula-like title ratio
- long title ratio
- body-like candidate ratio
- fallback ratio
- same-page ambiguity count
- Markdown coverage
- overflow file count

각 signal과 통합 score를 모두 남겨 score의 이유를 설명할 수 있어야 한다.

## 8. 권장 refactoring 계획

### Phase 0. 현재 계약 고정

목표:

- refactoring 전에 현재 동작을 회귀 기준으로 고정한다.

작업:

1. 실제 public CLI와 Python API의 golden/contract test를 추가한다.
2. default `Processor` 결과와 실험 102 `_predict_plan()` 결과가 동일한지 검증한다.
3. 대표 native/OCR PDF에 대한 artifact shape를 fixture로 고정한다.
4. 현재 config field와 CLI 노출 표를 문서화한다.

완료 조건:

- 이후 단계가 bookmark plan을 의도치 않게 바꾸면 테스트가 실패한다.

### Phase 1. config와 run manifest 기반 만들기

목표:

- 모든 실행을 재현 가능한 단위로 만든다.

작업:

1. 공통 config validation을 구현한다.
2. TOML load와 `--set` override를 구현한다.
3. `config defaults/schema/init/explain/validate`를 추가한다.
4. `RunManifest`를 정의한다.
5. input hash, resolved config, config hash, package/git version을 기록한다.
6. immutable run directory 정책을 도입한다.

완료 조건:

- final result만으로 동일 config와 input을 식별할 수 있다.
- 같은 output directory에서 여러 run이 충돌하지 않는다.

### Phase 2. core pipeline을 analyze/infer/apply로 분리

목표:

- production algorithm을 한 곳에서만 조립한다.

작업:

1. PDF feature extraction 결과를 담는 `PdfAnalysis`를 정의한다.
2. `analyze_pdf()`를 추출한다.
3. `infer_bookmarks(analysis, config)`를 추출한다.
4. `validate_plan()`과 `apply_plan()`을 명확히 분리한다.
5. 기존 `Processor.run()`은 새 함수들을 순서대로 호출하게 한다.
6. `infer`와 `apply` CLI를 추가한다.

완료 조건:

- `infer`는 PDF/Markdown을 생성하지 않는다.
- `apply`는 typography를 다시 계산하지 않는다.
- 기존 default `process`의 plan과 결과가 동일하다.

### Phase 3. 공통 result/error/event 계약

목표:

- 사람이 읽을 수 있고 agent가 안정적으로 파싱할 수 있는 CLI를 만든다.

작업:

1. versioned result/error envelope를 정의한다.
2. 모든 command에 `--format human|json`을 적용한다.
3. pipeline event protocol을 추가한다.
4. human renderer와 JSONL renderer를 구현한다.
5. documented exit code를 적용한다.
6. 기본 오류에서는 stack trace를 숨기고 `--debug`에서만 보인다.

완료 조건:

- 모든 JSON output을 `json.loads()`로 읽을 수 있다.
- failed process가 non-zero exit code를 반환한다.
- stdout과 progress stream이 섞이지 않는다.

### Phase 4. evaluator를 production으로 승격

목표:

- 책별 config를 동일 기준으로 평가할 수 있게 한다.

작업:

1. 실험 102의 fuzzy matcher를 `src/pdfbooktree/evaluation/`으로 옮긴다.
2. reference loader와 quality classifier를 구현한다.
3. level/parent accuracy와 match detail을 추가한다.
4. `evaluate` Python API와 CLI를 추가한다.
5. matched/missed/extra artifact를 저장한다.
6. structural quality evaluator를 별도 구현한다.

완료 조건:

- 실험 102가 production evaluator를 호출하도록 단순화된다.
- 동일 plan/reference/config에서 같은 metric이 재현된다.
- junk gold가 자동 objective로 사용되지 않는다.

### Phase 5. inspect/compare 개선

목표:

- agent가 plan 품질을 terminal에서 직접 조사할 수 있게 한다.

작업:

1. `inspect summary`를 추가한다.
2. `inspect plan-items`에 filter/limit/JSONL을 추가한다.
3. suspicious item inspection을 추가한다.
4. `compare` API와 CLI를 추가한다.
5. plan diff와 metric delta를 함께 출력한다.

완료 조건:

- agent가 artifact 파일을 직접 파싱하지 않고 후보의 근거와 변경점을 조사할 수 있다.

### Phase 6. cache-aware sweep

목표:

- 같은 책에 여러 config를 효율적으로 적용하고 후보를 비교한다.

작업:

1. analysis cache key를 정의한다.
2. sweep matrix parser와 조합 제한을 구현한다.
3. `--max-runs`, `--resume`, `--jobs` 정책을 정의한다.
4. reference metric 또는 structural signal로 후보를 ranking한다.
5. guardrail을 적용한다.
6. candidate별 resolved config, metric, plan, diff를 저장한다.

완료 조건:

- whole-book extraction을 candidate마다 반복하지 않는다.
- ranking 근거가 machine-readable artifact로 남는다.
- gold가 없을 때 결과를 정답처럼 표현하지 않는다.

### Phase 7. end-to-end와 batch 정리

목표:

- 새 단계형 API 위에서 convenience workflow를 완성한다.

작업:

1. `ProcessingConfig.ocr_policy`를 실제로 연결하거나 public contract에서 제거한다.
2. `process`를 inspect/OCR/infer/evaluate/apply 조립기로 정리한다.
3. `batch`가 single과 동일 config/output 계약을 사용하게 한다.
4. batch item별 run manifest를 summary와 연결한다.
5. README와 `--help` 예제를 작성한다.

완료 조건:

- single, batch, Python API가 같은 config/result semantics를 공유한다.
- `--help`에서 정확한 option과 다음 명령을 발견할 수 있다.

## 9. 구현 순서에 대한 판단

권장 순서는 `config/run 기반 -> pipeline 분리 -> result/error 계약 -> evaluator -> sweep`이다.

Evaluator나 sweep부터 만들면 현재 experiment처럼 내부 pipeline을 다시 조립하게 되고, run directory와 resolved config가 없어 결과 비교도 재현하기 어렵다. 반대로 result envelope만 먼저 전면 도입하면 곧 pipeline 단계가 분리될 때 schema를 다시 크게 바꿔야 한다.

따라서 먼저 재현 가능한 실행 단위와 public plan-only API를 만들고, 그 위에 evaluator와 sweep를 올리는 것이 가장 안전하다.

## 10. 호환성 전략

- 기존 `Processor`, `BatchProcessor`, `ProcessingConfig`는 즉시 제거하지 않는다.
- 기존 `process` CLI도 유지한다.
- 내부 구현만 새 단계형 API를 사용하도록 바꾼다.
- 새 config loader가 없을 때는 현재 dataclass default와 동일하게 동작한다.
- 기존 flat output 경로는 한 release 동안 compatibility mode로 제공할 수 있다.
- artifact schema 변경은 run manifest version으로 구분한다.

## 11. 비목표

이번 refactoring의 목표가 아닌 것:

- bookmark engine algorithm 자체를 다시 설계하는 것
- 새로운 OCR provider를 추가하는 것
- visual editor를 만드는 것
- gold가 없는 책의 완전 자동 정답 판정을 주장하는 것
- 모든 config field를 CLI flag로 노출하는 것

## 12. 최종 권고

현재 엔진 구현을 유지하면서 interface의 중심 개념을 `Processor` 한 번 실행에서 `Run`으로 옮기는 것이 가장 중요하다.

`Run`은 최소한 다음을 소유해야 한다.

- input identity
- resolved config와 hash
- analysis cache identity
- bookmark plan과 validation
- reference/structural evaluation
- warnings와 events
- artifact paths와 실제 존재 상태
- 선택된 apply 결과

이 구조가 생기면 agent는 `--help`와 structured output만으로 안전하게 조사하고, config를 바꾸고, 결과를 평가하고, 최종 plan을 선택할 수 있다.
