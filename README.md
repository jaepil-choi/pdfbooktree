# pdfbooktree

OCR 텍스트가 있는 PDF 책의 시각적 제목 구조를 분석해 계층형 북마크, 북마크가 포함된 PDF와 Markdown 문서 트리를 만드는 Python 라이브러리이자 CLI다.

## 왜 만들었나

수백~수천 쪽짜리 책은 AI 에이전트가 한 번에 읽거나 필요한 부분을 정확히 찾기 어렵다. 일정한 길이로 나누면 문맥과 장·절의 경계가 끊어진다. 그래서 책이 이미 갖고 있는 목차 구조에 따라 본문을 Markdown으로 나누기 위해 이 라이브러리를 만들었다.

사람처럼 목차 페이지만 읽어 구조를 복원하는 방식은 목차 위치 탐지, OCR 품질, 들여쓰기와 다단 구성에 크게 좌우된다. 대신 모든 페이지를 읽고 책 전체에 반복되는 시각적 패턴에서 제목과 계층을 추론한다.

## 핵심 가정

`pdfbooktree`는 목차 페이지를 찾아 파싱하는 도구가 아니다. 책 전체에서 반복되는 시각적 제목 규칙을 복원한다.

1. **글자 크기 계층**: 장·절·소절은 본문과 다른 글자 크기와 텍스트 영역 높이를 반복해서 사용한다.
2. **위치와 배치**: 제목은 페이지 안의 위치, 여백, 주변 간격, 반복 위치와 고립 정도에서도 공통 패턴을 가진다.

두 신호를 함께 사용해 특정 책에만 맞춘 규칙이 아니라 여러 스캔·OCR PDF에 적용할 수 있는 방법을 지향한다. 모든 페이지의 텍스트 줄을 분석하고 머리말·꼬리말 같은 여백 요소를 제거한 뒤, 글자 크기 계층과 위치 관계를 바탕으로 제목 후보와 북마크 계층을 계산한다. 글자 크기만으로 놓치는 제목은 위치 패턴으로 보완한다.

입력 PDF에는 추출 가능한 텍스트가 있어야 한다. Upstage Document Parse를 이용해
OCR 텍스트를 입히는 기능도 제공하지만 이는 선택적인 전처리다. 핵심 기능은
OCR된 책에서 북마크 구조를 복원하는 것이다.

기존 북마크가 잘 구성된 일반 PDF는 새로 추론하지 않고 그 계층을 그대로 사용해 본문이 들어 있는 Markdown 디렉터리와 파일을 만든다.

현재 지원 경계는 다음과 같다.

- Python 3.12 이상과 Windows 환경에서 검증했다. Linux wheel smoke test는
  0.1.0 배포 gate에 남아 있다.
- password가 필요한 encrypted PDF는 현재 password 입력 인터페이스를 제공하지
  않는다.
- text layer가 없는 scan PDF는 먼저 `ocr-overlay` 또는 `ocr-overlay-batch`로
  별도 OCR PDF를 만들어야 한다.
- 복잡한 표, 수식, figure의 semantic 구조를 복원하지 않는다. Markdown 본문은
  PDF의 추출 가능 text를 page 단위로 보존한다.

## 설치

Python 3.12 이상이 필요하다.

```powershell
python -m pip install pdfbooktree
pdfbooktree --help
pdfbooktree --version
```

OCR overlay까지 사용하려면 OCR 전용 extra를 설치한다. 일반 PDF 처리, inspect,
scan 분류와 `ocr-overlay-batch --dry-run`에는 이 extra가 필요하지 않다.

```powershell
python -m pip install "pdfbooktree[ocr]"
```

source checkout에서 개발할 때만 `python -m pip install .`을 사용한다.

Codex가 현재 project에서 `pdfbooktree`의 전체 CLI와 Python API 사용법을 알 수 있도록 package에 번들된 project scope skill을 설치할 수 있다.

```powershell
pdfbooktree skill install
```

현재 directory의 `.agents/skills/use-pdfbooktree`에 설치한다. 기존 skill은 기본적으로 보호하며, package의 최신 번들로 전체 교체할 때만 `--force`를 사용한다.

## English quick start

`pdfbooktree` turns a text-searchable PDF into a reviewed bookmark plan, a
bookmarked PDF, and an Obsidian-friendly Markdown graph. Python 3.12 or newer is
required.

```powershell
python -m pip install pdfbooktree
$pdf = "book.pdf"
pdfbooktree infer $pdf -o .\runs --format json
pdfbooktree inspect plan "<infer run_dir>" --attention-only --limit 20 --format json
pdfbooktree apply $pdf --plan "<infer run_dir>\bookmark_plan.json" `
  -o .\runs --dry-run --format json
pdfbooktree apply $pdf --plan "<infer run_dir>\bookmark_plan.json" `
  -o .\runs --format json
```

The input must have an extractable text layer. For scanned PDFs, run
`python -m pip install "pdfbooktree[ocr]"`, then run `ocr-overlay` first. The
built-in Upstage provider requires
`UPSTAGE_API_KEY` and may incur external API charges. `--format json` writes
one final envelope to stdout; `--log-mode json` writes progress events as
JSONL to stderr. Exit codes are `0` for success, `1` for runtime errors, `2`
for invalid input/config/plan, and `3` for a structurally invalid processing
result. Password-protected PDFs and semantic reconstruction of complex tables,
figures, or equations are not currently supported.

## 사용

북마크 계획을 먼저 만들고 검토한 뒤 PDF와 Markdown에 적용하는 흐름을 권장한다.

```powershell
$pdf = "book.pdf"

pdfbooktree infer $pdf -o .\runs --format json
pdfbooktree inspect plan "<infer 결과의 run_dir>" --summary --format json
pdfbooktree inspect plan "<infer 결과의 run_dir>" `
  --attention-only --limit 20 --format json
pdfbooktree inspect plan "<infer 결과의 run_dir>" `
  --item-id n0042 --format json
pdfbooktree apply $pdf `
  --plan "<infer 결과의 run_dir>\bookmark_plan.json" `
  -o .\runs --dry-run --format json
pdfbooktree apply $pdf `
  --plan "<infer 결과의 run_dir>\bookmark_plan.json" `
  -o .\runs --format json
```

`infer`는 `bookmark_review_summary.json`과 `bookmark_review_items.jsonl`을 만든다. summary에서 level/source 분포와 attention signal을 확인한 뒤 필요한 item만 열면 전체 `whole_book_lines.jsonl`을 scan하지 않고도 후보 geometry, 주변 typography line, page preview와 원본 evidence 위치를 확인할 수 있다. attention signal과 `confidence`는 검토 순서를 위한 heuristic evidence이며 품질 합격/불합격 판정이나 정확도 확률이 아니다.

`apply` 또는 `process`가 만든 output은 node 파일을 전부 열기 전에 `inspect plan`으로 조사할 수 있다. 결과의 `markdown_manifest`에는 export mode, node/root 수, link와 관계 validation, assigned/unassigned/duplicated page 통계가 포함된다.

## Markdown graph

기본 tree와 길이 제한 split은 모두 다음 graph 구조를 사용한다.

```text
<input-stem>_markdown[_split]/
├── toc.md
├── bookmark_plan.json
├── markdown_manifest.json
└── nodes/
    ├── 0001_L1_p0010_Chapter-1.md
    └── 0002_L2_p0015_First-section.md
```

모든 Markdown은 첫 줄부터 표준 YAML front matter를 가지며 parent, children, previous, next wiki link로 이동할 수 있다. 기본 tree의 `content_mode=direct`는 다음 bookmark 전까지의 page만 node에 넣는다. length-limited split은 `export_mode=split`, `content_mode=bounded`를 사용하고 선택된 boundary가 원래 plan의 node ID, source, confidence와 evidence reference를 유지한다.

Obsidian에서 사용할 때는 `<input-stem>_markdown` 또는
`<input-stem>_markdown_split` directory를 vault로 지정한다. `toc.md`에서 시작하면
wiki link와 backlink 방향이 `markdown_manifest.json`의
parent/children/previous/next 관계와 동일하다. 릴리스 acceptance는 GUI 수동 확인이
아니라 표준 YAML parse, link target, 관계 대칭성과 TOC 도달성의 자동 validation을
기준으로 한다.

```powershell
pdfbooktree process "book.pdf" -o .\runs `
  --max-words 10000 --max-words-coverage 0.95 --format json
pdfbooktree inspect plan "<process 결과의 run_dir>" --format json
```

한 번에 처리하거나 폴더 전체를 일괄 처리할 수도 있다.

```powershell
pdfbooktree process "book.pdf" -o .\runs --format json
pdfbooktree batch .\books -o .\runs --recursive `
  --include-glob "*.pdf" --exclude-glob "archive/*" `
  --log-mode json --format json
```

OCR overlay batch는 최소 PDF page 수를 inclusive 기준으로 제한할 수 있다. 예를 들어 100쪽을 초과하는 PDF만 먼저 확인하려면 최소값을 101로 지정한다.

```powershell
pdfbooktree ocr-overlay-batch .\data\300STUDY `
  -o .\runs\300study-ocr `
  --recursive `
  --min-page-count 101 `
  --dry-run
```

`processing.ocr_policy`는 현재 `never`만 지원한다. `auto|always`는 config
validation에서 exit 2로 거부한다. OCR이 필요하면 위 `ocr-overlay-batch` 또는
단일 PDF용 `ocr-overlay`를 먼저 실행하고 생성된 OCR PDF를 `infer`/`process`에
전달한다. 이렇게 해야 credential, API 비용, cache와 기존 bookmark overwrite를
명시적으로 통제할 수 있다.

**v0.1.0의 OCR provider는 Upstage Document Parse 전용이다.** custom provider
등록·주입 API는 제공하지 않으며 `engine="upstage"`만 지원한다. live OCR 전에
API key를 환경 변수로 설정해야 하며 외부 API 호출 비용이 발생할 수 있다. core
설치에서는 도움말과 dry-run까지만 사용할 수 있고, live overlay는 `[ocr]` extra가
없으면 `OptionalDependencyError`와 설치 명령을 반환한다.

```powershell
$env:UPSTAGE_API_KEY = "<upstage-api-key>"
pdfbooktree ocr-overlay "scan.pdf" -o ".\scan_ocr.pdf"
```

`--output-dir`을 생략하면 OCR cache와 stats는 출력 PDF 옆의
`scan_ocr_artifacts` 디렉터리에 저장된다. 입력 PDF와 출력 PDF는 같은 경로일 수
없으며 `--force`도 이 보호를 우회하지 않는다.

## 라이선스

MIT License로 배포한다. 상업적 이용, 수정, 재배포를 포함해 누구나 사용할 수
있으며 저작권 고지와 라이선스 고지를 유지해야 한다.

기존 북마크가 있는 PDF는 기본적으로 새 구조 추론에서 제외한다. 기존 북마크의 품질이 낮을 때만 교체하려면 다음 설정을 사용한다.

```powershell
pdfbooktree batch .\books -o .\runs `
  --set outline_quality.replace_when_low_quality=true
```

## AI 에이전트용 인터페이스

전체 처리뿐 아니라 AI 에이전트가 PDF를 조사하고 여러 설정을 시도할 수 있도록 작은 CLI 명령으로 나뉘어 있다.

```powershell
pdfbooktree inspect page-count "book.pdf" --format json
pdfbooktree inspect text "book.pdf" --pages 10-12 --format json
pdfbooktree inspect bookmarks "book.pdf" --format json
pdfbooktree inspect plan ".\runs\<run-dir>" --summary --format json
pdfbooktree inspect plan ".\runs\<run-dir>" `
  --page-range 100-120 --source geometry_position_fallback --format json
pdfbooktree inspect compare "plan-a.json" "plan-b.json" --format json
pdfbooktree infer "book.pdf" --set typography.position_fallback_enabled=false
```

실제 OCR 책에서 기본 설정은 북마크 171개를 만들었고, 위치 패턴 보완을 끈 실행은 154개를 만들었다. 두 결과를 비교하면 공통 항목 154개는 유지되고 위치 패턴으로 찾은 17개만 제거됐다.

```json
{"schema_version":1,"command":"inspect.compare","ok":true,"result":{"plan_a_item_count":171,"plan_b_item_count":154,"added_count":0,"removed_count":17,"unchanged_count":154}}
```

## Python API

CLI와 같은 immutable run·manifest 계약이 필요하면 고수준 workflow API를
사용한다. `preview_apply_plan()`은 어떤 파일도 만들지 않는다.
전체 공개 import, 함수 signature, 결과 모델과 artifact 계약은
[Python API reference](https://github.com/jaepil-choi/pdfbooktree/blob/master/.agents/skills/use-pdfbooktree/references/python-api.md)를
기준으로 한다. 이 reference는 wheel의 project skill에도 함께 들어가므로
`pdfbooktree skill install`로 설치한 agent가 같은 계약을 읽는다.

```python
from pathlib import Path
from pdfbooktree import (
    __version__,
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
print(__version__, applied.run_dir, applied.result.markdown_manifest_path)
```

공개 결과를 API 응답이나 저장소로 전달할 때는 `to_jsonable()` 또는
`to_json()`을 사용한다. dataclass는 object, `Path`는 문자열, tuple은 array로
변환되며 지원하지 않는 객체는 오류로 거부한다.

```python
from pdfbooktree import process_pdf, to_json

result = process_pdf("book.pdf", "runs")
payload = to_json(result, ensure_ascii=False, indent=2)
```

한 번에 처리하려면 `process_pdf()`를 사용한다. `Processor`, `analyze_pdf()`,
`infer_bookmarks()`, `apply_plan()`은 명시적 flat output이나 중간 모델 조합이
필요한 저수준 API로 유지한다.

## 출력 계약

- 외부에 표시되는 페이지 번호는 모두 1부터 시작한다.
- `--format json`의 최종 결과는 stdout 한 줄이다.
- `--log-mode json`의 진행 상황은 stderr JSONL로 출력한다.
- 실행마다 확정된 설정과 실행 기록을 남겨 입력, 설정, 결과와 오류를 추적할 수 있다.
- non-dry-run `process`, `infer`, `apply` run은 적용한 plan의 immutable snapshot을
  run root의 `bookmark_plan.json`으로 보존한다.
- 종료 코드는 성공 `0`, 실행 오류 `1`, 입력·설정·북마크 계획 오류 `2`, 처리 검증 실패 `3`이다.
