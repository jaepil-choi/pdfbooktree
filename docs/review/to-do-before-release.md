# pdfbooktree 릴리스 전 TODO

## 1. 문서 목적

이 문서는 `pdfbooktree`를 PyPI에 공개하기 전에 완료해야 할 기능과 사용성 작업을
우선순위별로 정리한다. 내부 구조를 정리하는 리팩터링보다 사용자가 실제로 받는
artifact, agent review 흐름, 성능과 배포 경험을 기준으로 한다.

가장 중요한 제품 원칙은 다음과 같다.

1. bookmark 품질을 단일 heuristic score로 자동 판정하지 않는다.
2. 구조적으로 잘못된 plan만 기계적으로 거부하고, 내용 품질은 충분한 근거와
   review artifact를 남겨 agent나 사람이 eye check할 수 있게 한다.
3. Markdown은 한 번에 모든 본문을 읽게 하지 않고, TOC와 metadata에서 시작해
   필요한 node와 근거만 차례로 여는 progressive disclosure 구조여야 한다.
4. 생성된 Markdown은 단순 파일 묶음이 아니라 parent, children, previous, next를
   따라 이동할 수 있는 문서 graph여야 한다.

## 2. 릴리스 판단 기준

### 2.1 `0.1.0` 전에 반드시 완료할 범위

- [x] Markdown front matter를 표준 YAML parser로 읽을 수 있게 만든다.
- [x] 모든 node Markdown에 고유하고 의미 있는 파일명을 부여한다.
- [x] 모든 node 사이에 parent, children, previous, next wiki link를 생성한다.
- [x] root TOC에서 모든 root node로 이동할 수 있게 한다.
- [x] parent 문서는 child 전체 본문을 기본으로 중복 저장하지 않고 child link를
      통해 점진적으로 내려가게 한다.
- [x] bookmark plan의 source, confidence, evidence를 Markdown과 review artifact에서
      잃지 않는다.
- [x] agent가 bookmark를 eye check할 수 있는 plan summary, item detail, 주변 text와
      근거 artifact 탐색 흐름을 제공한다.
- [x] 현재 동작하지 않는 `processing.ocr_policy=auto|always` 계약을 실제로
      구현하거나 설정 단계에서 명시적으로 거부한다.
- [x] MIT LICENSE를 추가하고 `pyproject.toml`에 license와 license file을 선언한다.
- [x] clean wheel 설치 smoke test를 자동화한다.
- [x] 전체 test와 release Ruff lint/format 검증을 통과한다.

2026-07-17 현재 codebase 동기화:

- Markdown graph 구현은 `tests/test_markdown_graph_export.py`,
  `tests/test_bpe_markdown_split.py`와 실제 Shreve PDF를 사용한 showcase 028에서
  YAML, node identity, wiki relation, page coverage, source/confidence/evidence
  보존을 검증했다.
- bookmark review 구현은 `tests/test_bookmark_review.py`,
  `tests/test_inspection.py`와 실제 native/OCR PDF를 사용한 showcase 029에서
  summary → attention item → item detail → 원문 page 흐름을 검증했다.
- OCR overlay 장시간 작업이 종료되어 project environment를 다시 sync했다. 현재
  개발·검증 명령은 `uv run ...`을 사용하고 OCR 구현 전체가 필요하면 먼저
  `uv sync --extra ocr --dev`를 실행한다. 2026-07-18 기준 전체 334개 테스트와
  release Ruff lint/format 검증이 통과한다.
- 별도 Python 3.12 clean venv에 새 wheel을 설치하고 `--help`, `--version`,
  config schema, Unicode·Windows 예약 이름·특수문자 outline을 가진 생성 2-page
  PDF의 inspect/process, YAML/wiki graph validation과 package skill 파일 5개
  설치를 검증했다. project `.venv`는 사용하거나 동기화하지 않았다.
- `experiments/`와 `references/`는 역사적 PoC와 외부 비교 자료이므로 release Ruff
  scope에서 제외한다. 나머지 151개 파일은 `ruff check .`와
  `ruff format --check .`을 통과한다. 변경한 실험 파일은 별도 명시 경로로 Ruff를
  실행한다.
- Obsidian GUI 수동 확인은 릴리스 acceptance에 포함하지 않는다. 표준 YAML parse,
  wiki link 무결성, 관계 대칭성, TOC 도달성의 자동 validation과 실제 PDF showcase를
  acceptance 근거로 사용한다.
- MIT LICENSE/PyPI metadata와 Windows clean-wheel smoke test를 완료했다.

### 2.2 릴리스 후로 미뤄도 되는 범위

- bookmark 품질의 자동 합격/불합격 판정
- calibration되지 않은 종합 quality score
- visual editor
- 완전한 semantic table, figure, equation 복원
- 대규모 config sweep과 자동 best-plan 선택

자동 품질 판정은 이번 릴리스 목표가 아니다. 잘못된 확신을 주는 score보다
누락 없는 근거와 빠른 review 동선이 우선이다.

## 3. P0: Markdown artifact를 progressive disclosure graph로 변경

### 3.1 YAML front matter 계약

현재 node Markdown은 제목 뒤에 `---`가 나오므로 일반 YAML front matter로
인식되지 않는다. 모든 node 파일은 첫 줄부터 다음 형태의 front matter를 가져야
한다.

```yaml
---
schema_version: 1
node_id: "n0001"
order: 1
title: "Chapter 1"
level: 1
pdf_start_page: 10
pdf_end_page: 42
source: "typography"
confidence: 0.8
evidence_count: 3
parent_id: null
parent: null
previous_id: null
previous: null
next_id: "n0002"
next: "[[0002_L2_p0015_First-section|First section]]"
children:
  - "[[0002_L2_p0015_First-section|First section]]"
evidence_ref: "../../bookmark_plan.json#n0001"
---
```

구현 체크리스트:

- [x] front matter가 파일의 첫 줄에서 시작하게 한다.
- [x] title과 문자열 값은 YAML escaping을 적용한다.
- [x] `null`, boolean, number, list가 문자열로 변형되지 않게 한다.
- [x] `yaml.safe_load()` 같은 표준 parser로 모든 생성 파일을 검증한다.
- [x] `schema_version`을 넣어 향후 metadata 변경을 구분한다.
- [x] 1-based PDF page convention을 유지한다.
- [x] `source`, `confidence`, `evidence_count`, `evidence_ref`를 보존한다.
- [x] 기존 outline에서 온 node도 `source=existing_outline`을 명시한다.
- [x] tree export와 length-limited split export가 같은 metadata 이름과 의미를
      사용한다.

`confidence`는 정확도 확률이 아니라 현재 pipeline이 남긴 heuristic evidence
값이다. 문서와 schema에서 이 점을 명확히 설명하고 자동 합격 판정에는 사용하지
않는다.

### 3.2 node 파일명

모든 node가 `index.md`이면 검색 결과, wiki link, terminal 출력과 agent context에서
서로 구분하기 어렵다. 파일명은 document 전체에서 유일하고 plan 순서와 page를
바로 읽을 수 있어야 한다.

권장 기본 형식:

```text
0001_L1_p0010_Chapter-1.md
0002_L2_p0015_First-section.md
0003_L2_p0027_Second-section.md
```

구현 체크리스트:

- [x] 1-based global `order`를 zero padding한 prefix로 사용한다.
- [x] `L<level>`과 `p<pdf_page>`를 파일명에 포함한다.
- [x] 사람이 알아볼 수 있는 sanitize된 title slug를 포함한다.
- [x] 같은 title과 같은 page가 반복되어도 global order로 충돌하지 않게 한다.
- [x] Windows reserved name, trailing dot/space, 너무 긴 경로를 안전하게 처리한다.
- [x] 실제 title은 파일명이 아니라 front matter에 손실 없이 보존한다.
- [x] rename 규칙과 node ID가 실행 중 결정론적이어야 한다.
- [x] `markdown_manifest.json`에 `node_id -> relative_path` mapping을 기록한다.

directory hierarchy는 유지할 수 있지만 Markdown basename은 전체 vault에서
유일해야 한다. 그래야 Obsidian의 shortest-path wiki link와 agent 검색 결과가
모호하지 않다.

### 3.3 Obsidian style wiki link

각 node는 계층 관계와 읽기 순서를 모두 표현해야 한다.

- `parent`: 직계 부모 node
- `children`: 직계 자식 node 목록
- `previous`: plan 순서상 바로 이전 node
- `next`: plan 순서상 바로 다음 node
- root TOC: root node와 전체 flat outline

본문 상단 또는 하단에 사람이 바로 볼 수 있는 navigation block도 만든다.

```markdown
## Navigation

- Parent: [[0001_L1_p0010_Chapter-1|Chapter 1]]
- Previous: [[0002_L2_p0015_First-section|First section]]
- Next: [[0004_L3_p0031_Detail|Detail]]
- Children:
  - [[0004_L3_p0031_Detail|Detail]]
```

구현 체크리스트:

- [x] YAML metadata와 Markdown navigation block 양쪽에 동일한 관계를 기록한다.
- [x] 없는 관계는 `null` 또는 빈 list로 일관되게 표현한다.
- [x] link target은 생성된 실제 파일과 정확히 일치해야 한다.
- [x] link label은 원본 bookmark title을 사용한다.
- [x] `toc.md`의 모든 항목을 실제 node wiki link로 만든다.
- [x] parent/children link가 서로 대칭인지 검증한다.
- [x] previous/next가 전체 plan 순서에서 서로 대칭인지 검증한다.
- [x] dangling link, duplicate node ID, duplicate output path가 0개인지 검증한다.
- [x] Obsidian-compatible wiki link의 target, 관계와 backlink 방향을 실제 PDF
      output과 graph validator로 검증한다.

### 3.4 본문 중복 제거와 progressive disclosure

기본 tree export에서 parent node가 모든 descendant page text를 다시 포함하면
계층이 깊을수록 같은 본문이 여러 파일에 중복된다. 이는 output 크기를 키우고
agent retrieval 결과에 같은 문장이 반복되는 원인이 된다.

기본 동작은 다음과 같이 바꾼다.

1. `toc.md`에서 책 전체 구조와 root node만 확인한다.
2. node front matter에서 page 범위, 관계, source와 evidence 위치를 확인한다.
3. node 본문에는 해당 node가 직접 소유한 page text만 둔다.
4. 하위 내용은 children wiki link를 따라가서 읽는다.
5. 더 자세한 추론 근거는 `evidence_ref`가 가리키는 artifact에서 확인한다.

구현 체크리스트:

- [x] direct child가 시작하기 전까지의 text를 parent의 직접 본문으로 정의한다.
- [x] 같은 PDF page에 parent와 child가 함께 시작하는 경우의 소유 규칙을 문서화한다.
- [x] 기본 export에서 동일 page text가 여러 node에 반복되지 않게 한다.
- [x] 기존처럼 subtree 전체를 포함하는 결과가 필요하면 명시적
      `content_mode="inclusive"` 호환 option으로 제공한다.
- [x] 본문이 없는 parent도 children navigation만 가진 유효한 문서로 생성한다.
- [x] 첫 bookmark 이전 page를 front matter node로 만들지, unassigned page로
      manifest에 남길지 정책을 정한다.
- [x] 누락 page, 빈-text page, 중복 page, unassigned page 수를 manifest에 기록한다.
- [x] `toc.md`와 node metadata만 먼저 읽어도 전체 구조를 파악할 수 있게 한다.

### 3.5 Markdown graph manifest

agent가 모든 Markdown을 열지 않고도 output을 조사할 수 있도록 root에
`markdown_manifest.json`을 만든다.

최소 field:

- schema version
- input PDF path/hash/page count
- plan path/hash
- node count와 root count
- node ID, order, title, level, page range, relative path
- parent/children/previous/next node ID
- source, confidence, evidence reference
- assigned, unassigned, empty-text, duplicated page 통계
- dangling link와 validation warning

구현 체크리스트:

- [x] `inspect plan`이 manifest 존재 여부와 graph validation 결과를 보여준다.
- [x] run manifest가 `markdown_manifest.json`을 output artifact로 연결한다.
- [x] tree와 split output을 구분하는 export mode를 기록한다.
- [x] node 파일을 전부 읽지 않고도 relation과 coverage를 JSON으로 조사할 수 있다.

## 4. P0: bookmark eye-check를 위한 review evidence 강화

### 4.1 자동 품질 판정을 하지 않는 원칙

- [x] bookmark plan의 내용 품질을 단일 score로 합격/불합격 처리하지 않는다.
- [x] `confidence`를 정확도 확률로 설명하지 않는다.
- [x] `process`가 heuristic score만으로 plan을 자동 거부하지 않는다.
- [x] 빈 plan, page 범위 오류, level jump 같은 구조적 오류는 기존처럼 validation
      실패로 처리한다.
- [x] attention signal은 판정이 아니라 review 우선순위를 정하는 정보로만 쓴다.

### 4.2 agent가 먼저 읽을 review summary

`infer` run에 `bookmark_review_summary.json`을 추가한다.

필요한 정보:

- plan item 수와 level별 수
- source별 수와 비율
- page 구간별 bookmark 밀도
- title 길이, 숫자-only, 반복 title 통계
- heading candidate 수와 최종 plan 수
- position fallback candidate 수
- text가 없는 page와 typography line 수가 매우 적은 page
- 기존 outline 존재 여부와 기존/추론 plan 경로
- 확인 우선순위가 높은 item 목록과 각 signal
- 다음에 실행할 수 있는 `inspect` 명령 예시

여기서 `확인 우선순위가 높다`는 품질이 낮다는 판정이 아니다. 예를 들어 지나치게
많은 bookmark, 같은 title 반복, 긴 page 공백, fallback source는 agent가 먼저 볼
지점을 고르는 attention signal이다.

구현 체크리스트:

- [x] summary가 항상 JSON으로 저장된다.
- [x] human CLI 완료 출력에 summary 경로와 핵심 count를 표시한다.
- [x] JSON CLI result가 summary 경로를 반환한다.
- [x] run manifest가 summary를 artifact로 연결한다.

### 4.3 item 단위 review detail

`bookmark_review_items.jsonl`에 plan item별로 다음 정보를 남긴다.

- node ID와 plan order
- title, level, PDF page
- source와 confidence
- evidence 원문
- font/height tier와 geometry 요약
- 같은 page의 앞뒤 typography line
- 이전/다음 bookmark
- 해당 page text preview
- 관련 heading/fallback candidate artifact 위치
- attention signals

구현 체크리스트:

- [x] item 한 개를 읽기 위해 전체 `whole_book_lines.jsonl`을 scan하지 않아도 된다.
- [x] preview 길이는 제한하되 원본 artifact 위치를 함께 제공한다.
- [x] JSONL 한 줄이 독립적으로 parse 가능하다.
- [x] source/evidence가 plan과 review detail 사이에서 손실되지 않는다.

### 4.4 inspection CLI

agent가 terminal에서 필요한 만큼만 열 수 있도록 다음 기능을 추가한다.

- [x] `inspect plan <RUN> --summary`
- [x] `inspect plan <RUN> --items --limit N`
- [x] `inspect plan <RUN> --item-id n0001`
- [x] `inspect plan <RUN> --page-range 100-120`
- [x] `inspect plan <RUN> --level 1`
- [x] `inspect plan <RUN> --source geometry_position_fallback`
- [x] `inspect plan <RUN> --attention-only`
- [x] item 상세에서 주변 page text와 evidence artifact 경로를 함께 출력한다.
- [x] 모든 option이 `--format json` 계약을 지킨다.

권장 eye-check 흐름:

```powershell
uv run pdfbooktree infer $pdf -o .\runs --format json
uv run pdfbooktree inspect plan $runDir --summary --format json
uv run pdfbooktree inspect plan $runDir --attention-only --limit 20 --format json
uv run pdfbooktree inspect plan $runDir --item-id n0042 --format json
uv run pdfbooktree inspect text $pdf --pages 120-122 --format json
```

### 4.5 실제 데이터 showcase

- [x] bookmark 수가 적은 책, 많은 책, OCR 책, native 책을 각각 사용한다.
- [x] summary만 읽고 review할 item을 선택할 수 있음을 보여준다.
- [x] item detail에서 원문 page와 후보 근거까지 추적할 수 있음을 보여준다.
- [x] agent가 plan을 수정한 뒤 `apply`할 수 있는 전체 흐름을 보여준다.
- [x] 자동 품질 판정이나 synthetic data로 성공을 주장하지 않는다.

## 5. P0: 공개 설정과 실제 동작 일치

### 5.1 OCR policy

`processing.ocr_policy`는 실행 가능한 값과 public schema를 일치시키기 위해
현재 `never`만 허용한다. OCR은 별도 `ocr-overlay` 또는
`ocr-overlay-batch` 전처리로 실행한다.

릴리스 전 선택 결과:

- [ ] `auto|always`를 실제 OCR overlay workflow에 연결한다.
- [x] 또는 `never` 이외의 값을 config validation에서 명시적으로 거부한다.

`auto|always`는 direct Python config, TOML, `--set`과 JSON Schema에서 지원하지
않으며 CLI는 `ConfigError`와 exit 2로 조기 종료한다. 따라서 PDF 분석, output
생성과 외부 API 호출 전에 실패한다. 향후 자동 연결을 다시 도입한다면 credential,
API 비용, cache, 기존 bookmark 보호와 원본 비파괴 정책을 함께 설계해야 한다.

### 5.2 output 계약 동기화

- [x] `.agents/skills/use-pdfbooktree/references/contracts.md`의 Markdown 계약을
      새 파일명, front matter, wiki link, manifest 기준으로 갱신한다.
- [x] package에 번들된 skill template도 byte-identical하게 갱신한다.
- [x] Python API와 CLI reference에 새 config와 결과 field를 추가한다.
- [x] `agents/openai.yaml`의 설명과 예시를 갱신한다.
- [x] README quick start에서 progressive disclosure review 흐름을 설명한다.

### 5.3 릴리스 안전성과 장시간 작업

- [x] OCR input/output 동일 경로를 `--force`와 무관하게 거부한다.
- [x] OCR PDF를 sibling temporary file에 완전히 저장한 뒤 atomic replace하고,
      실패 시 원본과 기존 output을 보존한다.
- [x] Python OCR config가 engine, DPI, page, cache policy와 boolean 타입을
      CLI와 같은 기준으로 검증한다.
- [x] directory command가 `.PDF`를 대소문자와 무관하게 찾고 input 하위의 output
      subtree를 자동 제외한다.
- [x] 실패한 `ProcessingResult`가 존재하지 않는 예정 output 경로를 반환하지
      않는다.
- [x] `validate_plan()`과 `apply --dry-run`으로 plan을 파일 생성 없이 검증한다.
- [x] process/infer가 page 추출과 단계별 progress를 rich/plain/JSONL로 제공하고
      비TTY auto mode는 기존 무출력 계약을 유지한다.
- [x] PDF 본문의 `[[...]]` 원문을 생성된 wiki navigation link로 오인하지 않는다.
- [x] 실제 637-page OCR plan에서 false positive를 제거하고 dry-run과 실제 apply,
      Markdown graph validation까지 showcase 032로 검증한다.

## 6. P1: 성능과 반복 작업 편의

### 6.1 analysis cache

- [ ] input PDF hash와 extraction config hash 기반 cache key를 정의한다.
- [ ] `PdfAnalysis`를 disk artifact로 저장하고 다시 읽을 수 있게 한다.
- [ ] 같은 PDF의 config A/B infer가 typography extraction을 재실행하지 않게 한다.
- [ ] cache hit/miss와 사용한 artifact를 run manifest에 기록한다.
- [ ] cache schema/version 불일치를 안전하게 무효화한다.

### 6.2 batch resume와 제한된 병렬 실행

- [ ] `batch --resume`으로 완료 item을 재사용한다.
- [ ] `batch --retry-failed`로 실패 item만 다시 실행한다.
- [ ] `batch --jobs N`을 제공하되 결과 순서와 manifest는 결정론적으로 유지한다.
- [ ] 동일 input/config hash의 성공 run을 재사용할지 명시적으로 선택할 수 있게 한다.
- [ ] 병렬 실행에서도 item별 오류와 progress event를 잃지 않는다.

### 6.3 OCR runtime

- [ ] 중단 후 cache에서 이어가기 위한 명시적 `--resume` 동작을 문서화한다.
- [ ] provider rate limit을 고려한 제한된 page concurrency를 검토한다.
- [ ] 예상 호출 page 수와 cache hit 수를 실행 전에 확인할 수 있게 한다.

## 7. P1: CLI와 Python 사용성

- [x] `pdfbooktree --version`을 제공한다.
- [ ] `pdfbooktree doctor`로 PDF library, optional OCR credential과 output 쓰기 권한을
      확인한다.
- [ ] terminal 폭이 좁아도 option 이름이 잘리지 않는 plain help를 제공한다.
- [ ] encrypted PDF를 위한 password 입력 방식을 검토한다.
- [x] batch include/exclude glob을 제공한다.
- [x] Python result에서 plan, validation, review summary/items, Markdown manifest와
      기존 outline quality 경로에 typed property로 바로 접근할 수 있게 한다.
- [ ] 예외 메시지에 다음 확인 명령과 관련 artifact 경로를 포함한다.

## 8. P0: PyPI 배포 준비

### 8.1 package metadata

- [x] MIT `LICENSE` 파일을 추가한다.
- [x] `pyproject.toml`에 `license = "MIT"`와 `license-files = ["LICENSE"]`를 선언한다.
- [x] project URLs(repository, documentation, issue tracker)를 추가한다.
- [x] classifiers와 keywords를 추가한다.
- [x] README 설치 예시를 `pip install pdfbooktree` 기준으로 바꾼다.
- [x] 지원 Python과 운영체제를 명시한다.
- [x] OCR 기능에는 Upstage credential과 외부 비용이 필요하다는 점을 명시한다.
- [x] OCR 전용 dependency를 `pdfbooktree[ocr]` extra로 분리하고 `tqdm`은 core에
      유지한다.
- [x] `Typing :: Typed`와 `py.typed`를 wheel/sdist에 포함한다.

### 8.2 배포 검증

- [x] production release는 항상 `master`의 검증된 commit에서 만든다.
- [ ] `develop`의 green commit을 원격 `master`에 반영하고 release tag를
      `master`의 해당 commit에 생성한다.
- [x] `uv build`로 sdist와 wheel을 생성한다.
- [x] 깨끗한 virtual environment에 wheel을 설치한다.
- [x] `pdfbooktree --help`, `--version`, config와 inspect smoke test를 실행한다.
- [x] package에 skill template 전체가 포함되고 설치된 Python API reference가
      공개 import, 직렬화와 Upstage-only 계약을 포함하는지 검사한다.
- [x] source checkout이 아닌 설치 wheel에서 작은 실제 PDF를 처리한다.
- [x] core-only clean 환경에서 OCR dependency가 설치되지 않고 일반
      process/inspect/classify, OCR help와 batch dry-run이 동작하는지 확인한다.
- [x] live OCR은 output 생성 전에 `missing_optional_dependency`와 `[ocr]` 설치
      명령으로 실패한다.
- [ ] Windows와 Linux에서 파일명, YAML, wiki link를 검증한다.
- [x] `uv run pytest`, `uv run ruff check`,
      `uv run ruff format --check`를 통과한다.

`.github/workflows/ci.yml`은 `windows-latest`와 `ubuntu-latest` matrix에서 locked
dependency 설치, 전체 pytest/Ruff와 cross-platform clean-wheel smoke를 실행한다.
Windows에서는 같은 Python smoke script로 실제 PDF process까지 통과했다. Linux
항목은 workflow를 remote에서 실제 실행해 성공한 뒤 완료 처리한다.

### 8.3 공개 문서

- [x] 한국어 README와 영어 README 또는 영어 section을 제공한다.
- [x] 입력 PDF 요구사항과 지원하지 않는 문서 유형을 설명한다.
- [x] OCR 전처리와 bookmark 추론이 별도 단계임을 설명한다.
- [x] `infer -> review -> apply`를 기본 quick start로 유지한다.
- [x] Markdown graph를 Obsidian vault로 여는 예시를 추가한다.
- [x] generated file tree와 각 artifact의 역할을 예시로 보여준다.
- [x] CHANGELOG, CONTRIBUTING, SECURITY 문서를 추가한다.
- [x] 루트와 공개 subpackage의 `__all__`을 지원 API surface로 명시한다.
- [x] Python 결과용 `to_jsonable()`과 `to_json()` 직렬화 계약을 제공한다.
- [x] 전체 Python API reference를 project skill과 wheel에 함께 배포한다.
- [x] v0.1.0 OCR provider가 Upstage 전용이고 custom provider 등록 API가 없음을
      명시한다.

## 9. 구현 순서

저장소의 experiment-driven development 규칙에 따라 다음 순서로 진행한다.

1. 실제 output 하나를 사용해 YAML front matter와 wiki link 파일 구조를
   `experiments/`에서 검증한다.
2. 같은 책으로 현재 `index.md` 방식과 새 graph 방식의 파일 수, 중복 text 양,
   dangling link와 agent 탐색 단계를 비교한다.
3. public Markdown export에 node ID, 고유 파일명, 관계 link와 manifest를 추가한다.
4. 실제 책으로 Markdown graph와 progressive disclosure showcase를 만든다.
5. review summary/item JSONL과 inspection CLI를 실제 plan에 연결한다.
6. skill, README와 artifact 계약을 동기화한다.
7. OCR policy 계약을 정리한다.
8. package metadata와 CI/smoke test를 완료한다.
9. analysis cache와 batch resume/jobs는 P0 완료 후 진행한다.

`src/`와 `tests/`를 변경하는 각 구현 단위는 별도 구현 커밋과 implementation
note 흐름을 따른다. 실험과 showcase는 해당 디렉터리의 기록 JSON도 함께
갱신한다.

## 10. 최종 release checklist

- [x] 모든 Markdown front matter가 표준 YAML로 parse된다.
- [x] 모든 Markdown 파일명이 전체 output에서 유일하다.
- [x] dangling wiki link가 없다.
- [x] parent/children 및 previous/next 관계가 대칭이다.
- [x] root TOC에서 모든 node에 도달할 수 있다.
- [x] 기본 export에 descendant 본문 중복이 없다.
- [x] source, confidence와 evidence reference가 plan에서 Markdown까지 보존된다.
- [x] agent가 summary에서 item detail과 원문 page까지 점진적으로 조사할 수 있다.
- [x] bookmark 내용 품질을 근거 없는 자동 score로 판정하지 않는다.
- [x] 공개 config에 동작하지 않는 값이 없다.
- [x] run manifest가 review와 Markdown graph artifact를 연결한다.
- [x] skill과 package bundle의 계약이 일치한다.
- [x] MIT LICENSE와 PyPI metadata가 완성됐다.
- [x] Windows clean venv wheel 설치 smoke test가 통과한다.
- [x] OCR output 원본 보존, plan dry-run과 batch output subtree 제외가 검증됐다.
- [x] process/infer progress JSONL과 stdout 결과가 분리된다.
- [x] 실제 수정 plan의 dry-run과 apply showcase가 통과한다.
- [x] `__version__`, PEP 561, 고수준 Python workflow와 canonical run-owned
      `bookmark_plan.json` 계약을 제공한다.
- [x] 공개 결과 직렬화와 설치 skill의 Python API reference 계약을 제공한다.
- [ ] `master`의 검증된 commit에 release tag를 생성한다.
- [ ] GitHub Actions의 Windows/Linux matrix가 실제로 통과한다.
- [x] `uv run pytest -q`가 통과한다.
- [x] release Ruff scope의 lint와 format check가 통과한다.
- [x] 실제 PDF showcase 결과가 기록됐다.
