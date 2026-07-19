# pdfbooktree

[English](https://github.com/jaepil-choi/pdfbooktree/blob/master/README.en.md) ·
[문서 색인](https://github.com/jaepil-choi/pdfbooktree/blob/master/docs/reference.md) ·
[변경 기록](https://github.com/jaepil-choi/pdfbooktree/blob/master/CHANGELOG.md) ·
[보안 정책](https://github.com/jaepil-choi/pdfbooktree/blob/master/SECURITY.md)

`pdfbooktree`는 텍스트를 추출할 수 있는 PDF 책의 typography를 분석해 검토 가능한
북마크 계획, 북마크 PDF와 계층형 Markdown graph를 만드는 Python 라이브러리이자
CLI다.

이 프로젝트는 **review-assisted Alpha 도구**다. 구조 후보와 근거를 만들고 사람이
검토하는 시간을 줄이지만, 책의 올바른 목차를 자동으로 보장하는 정답 생성기가
아니다. 권장 기본 흐름은 `infer → review → apply`이며, `confidence`와 attention
signal은 검토 우선순위를 위한 heuristic이지 정확도 확률이나 합격 판정이 아니다.

## 왜 만들었나

수백~수천 쪽짜리 책을 일정한 길이로만 자르면 장·절 경계와 문맥이 끊어진다.
`pdfbooktree`는 목차 페이지만 파싱하는 대신 모든 페이지에서 반복되는 글자 크기,
텍스트 영역 높이, 위치, 여백과 고립 패턴을 사용해 책의 시각적 제목 계층을
복원한다. 잘 구성된 기존 outline이 있으면 새로 추론하지 않고 이를 재사용한다.

## 품질 근거와 한계

2026-07-15에 `develop`의 `06f214f` 기준으로, 100쪽을 넘고 embedded outline이 있는
`300STUDY` PDF 400권을 평가했다. 전체 평균 precision 0.3393, recall 0.6932,
F1 0.4089였고, clean reference로 분류한 312권의 평균 F1은 0.4662였다. 최고 사례는
F1 0.9 이상이었지만 OCR 수식·기호가 typography를 오염시킨 책과 reference 자체가
부정확한 책은 매우 낮았다.

이 수치는 제품 정확도 보증이 아니다. embedded outline은 책마다 상세도와 품질이
다른 **weak reference**이고, outline이 없는 책은 평가에서 제외됐다. 평가 시점
이후 구현도 바뀌었다. 결과는 “기본 설정 하나로 모든 책을 처리할 수 없다”는
책별 품질 편차의 근거로 사용해야 한다. 상세한 평가 조건은
[패키지 인터페이스 평가](https://github.com/jaepil-choi/pdfbooktree/blob/master/docs/review/pkg-evaluation-20260715.md)에
있다.

실제 PDF release evidence로는 2026-07-17의 showcase 031에서 source wheel을 별도
Python 3.12 환경에 설치해 2쪽 PDF 처리와 Markdown manifest를 확인했고,
2026-07-18의 showcase 033에서
`infer_pdf → preview_apply_plan → apply_plan_file`을 확인했다. 이 기록은 제한된
표본에 대한 실행 증거이지 다양한 책의 내용 품질 보증이 아니다.

## 지원 범위

- Python 3.12, 3.13, 3.14
- Windows와 Linux
- 추출 가능한 text layer가 있는 PDF
- 기존 outline 재사용 또는 typography 기반 outline 추론
- 표준 YAML front matter와 wiki navigation을 가진 Markdown graph
- 선택적인 Upstage Document Parse OCR overlay

현재 다음은 지원하지 않는다.

- password 입력이 필요한 encrypted PDF
- text layer가 없는 scan PDF의 자동 처리. 먼저 OCR overlay가 필요하다.
- 복잡한 표, 수식, figure의 의미 구조 복원
- 목차 내용의 자동 정답 판정
- `processing.ocr_policy=auto|always`. 현재 `never`만 유효하다.

PDF의 추출 가능한 text를 page 단위로 보존하므로 text layer가 깨졌거나 reading
order가 잘못된 문서는 Markdown에도 같은 문제가 남을 수 있다.

## 설치

```powershell
python -m pip install pdfbooktree
pdfbooktree --help
pdfbooktree --version
```

OCR overlay까지 사용하려면 OCR extra를 설치한다.

```powershell
python -m pip install "pdfbooktree[ocr]"
```

Codex가 새 project에서 전체 CLI와 Python API reference를 읽게 하려면 package에
번들된 project scope skill을 설치할 수 있다.

```powershell
pdfbooktree skill install
```

현재 디렉터리의 `.agents/skills/use-pdfbooktree`에 설치한다. 기존 skill은
보호되며 package의 번들로 전체 교체할 때만 `--force`를 사용한다.

## 빠른 시작: infer → review → apply

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

`infer`는 `bookmark_plan.json`, `bookmark_review_summary.json`과
`bookmark_review_items.jsonl`을 만든다. summary에서 level/source 분포와 attention
signal을 확인한 뒤 필요한 item만 열면 전체 line artifact를 읽지 않고도 후보
geometry, 주변 typography line, page preview와 evidence 위치를 확인할 수 있다.

`apply --dry-run`은 plan의 page 범위와 level 구조를 검증하지만 파일을 만들지
않는다. 실제 `apply`는 같은 plan snapshot을 북마크 PDF와 Markdown에 적용한다.

한 번에 처리하거나 디렉터리를 batch 처리할 수도 있다.

```powershell
pdfbooktree process "book.pdf" -o .\runs --format json
pdfbooktree batch .\books -o .\runs --recursive `
  --include-glob "*.pdf" --exclude-glob "archive/*" `
  --log-mode json --format json
```

## Markdown graph

기본 tree와 길이 제한 split은 다음 구조를 사용한다.

```text
<input-stem>_markdown[_split]/
├── toc.md
├── bookmark_plan.json
├── markdown_manifest.json
└── nodes/
    ├── 0001_L1_p0010_Chapter-1.md
    └── 0002_L2_p0015_First-section.md
```

모든 node는 첫 줄부터 표준 YAML front matter를 가지며 `parent`, `children`,
`previous`, `next` wiki link로 이동할 수 있다. 기본
`content_mode=direct`는 다음 bookmark 전까지 해당 node가 직접 소유하는 page만
담는다. 길이 제한 split은 `export_mode=split`, `content_mode=bounded`를 사용하고
원래 plan의 node ID, source, confidence와 evidence reference를 보존한다.

Obsidian에서는 `<input-stem>_markdown` 디렉터리를 vault로 열고 `toc.md`에서
시작한다. `markdown_manifest.json`은 node path, 관계, page coverage, dangling
link와 validation 결과를 제공하므로 GUI 없이도 graph 무결성을 검사할 수 있다.

```powershell
pdfbooktree process "book.pdf" -o .\runs `
  --max-words 10000 --max-words-coverage 0.95 --format json
```

## OCR과 개인정보

**v0.1.0의 OCR provider는 Upstage Document Parse 전용**이며 custom provider
등록 API를 제공하지 않는다. live OCR은 각 PDF 페이지를 PNG로 렌더링해 Upstage로
전송한다. 원본 문서에 개인정보, 계약 정보, 영업 비밀 또는 저작권상 외부 전송이
제한된 내용이 있다면 실행 전에 조직 정책과 Upstage의 처리 조건을 확인해야 한다.
외부 API 비용도 발생할 수 있다.

```powershell
$env:UPSTAGE_API_KEY = "<upstage-api-key>"
pdfbooktree ocr-overlay "scan.pdf" -o ".\scan_ocr.pdf"
```

credential은 먼저 현재 process environment에서 읽는다. `[ocr]` extra가 설치된
경우 현재 작업 디렉터리부터 상위 디렉터리로 `.env`를 검색하며, 기존 환경 변수를
덮어쓰지 않는다. `.env`를 저장소에 commit하지 말아야 한다.

OCR raw cache에는 provider 응답과 추출 text/geometry가, review preview에는 원문
일부가 포함될 수 있다. output 디렉터리를 민감 정보로 취급하고 공유·보존·삭제
정책을 정해야 한다. `--cache-policy reuse`는 기존 cache를 재사용하고,
`refresh`는 다시 호출하며, `only`는 외부 호출 없이 cache만 사용한다.

`--output-dir`을 생략하면 OCR cache와 stats는 출력 PDF 옆의
`<output-stem>_artifacts` 디렉터리에 저장된다. 입력과 출력 PDF는 같은 경로일 수
없으며 `--force`도 이 보호를 우회하지 않는다.

```powershell
pdfbooktree ocr-overlay-batch .\books `
  -o .\runs\ocr --recursive --min-page-count 101 --dry-run
```

live OCR 전에 `--dry-run`으로 대상과 예상 page 수를 확인한다. 기존 outline이 있는
PDF의 text layer를 교체하려면 별도 확인 옵션이 필요하다.

## 기존 outline 정책

기본 `processing.skip_existing_bookmarks=true`에서는 의미 있는 기존 outline을
재사용해 Markdown을 만들고 PDF outline을 덮어쓰지 않는다. 기존 outline이 너무
작거나 숫자 제목뿐이거나 page 수에 비해 지나치게 많아 low quality로 판정돼도
기본값은 재사용이다.

typography 결과로 교체하려는 경우에만 명시적으로 설정한다.

```powershell
pdfbooktree batch .\books -o .\runs `
  --set outline_quality.replace_when_low_quality=true
```

자동 교체는 원래 outline을 잃을 수 있으므로 먼저 `inspect bookmarks`와 dry-run
결과를 검토한다.

## Python API

immutable run과 manifest가 필요하면 고수준 workflow API를 사용한다.
`preview_apply_plan()`은 어떤 output도 만들지 않는다.

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

공개 결과를 JSON API나 저장소로 전달할 때는 `to_jsonable()` 또는 `to_json()`을
사용한다. dataclass는 object, `Path`는 문자열, tuple은 array로 변환되며 지원하지
않는 객체는 오류로 거부한다.

```python
from pdfbooktree import process_pdf, to_json

result = process_pdf("book.pdf", "runs")
payload = to_json(result, ensure_ascii=False, indent=2)
```

공개 import, signature와 결과 model은
[Python API reference](https://github.com/jaepil-choi/pdfbooktree/blob/master/.agents/skills/use-pdfbooktree/references/python-api.md)를,
명령은 [CLI reference](https://github.com/jaepil-choi/pdfbooktree/blob/master/.agents/skills/use-pdfbooktree/references/cli.md)를,
artifact와 stream 의미는
[계약과 artifact](https://github.com/jaepil-choi/pdfbooktree/blob/master/.agents/skills/use-pdfbooktree/references/contracts.md)를
따른다. 한·영 진입점은
[문서 색인](https://github.com/jaepil-choi/pdfbooktree/blob/master/docs/reference.md)에
있다.

## 출력과 자동화 계약

- 외부 PDF page 번호는 1부터 시작한다.
- `--format json`의 최종 envelope는 stdout 한 줄이다.
- `--log-mode json`의 progress event는 stderr JSONL이다.
- 성공 exit code는 `0`, runtime 오류는 `1`, 입력·설정·plan 오류는 `2`,
  구조적으로 유효한 결과를 만들지 못한 경우는 `3`이다.
- non-dry-run `process`, `infer`, `apply`는 확정 설정, 입력 identity, artifact
  path와 immutable `bookmark_plan.json` snapshot을 run 디렉터리에 남긴다.

## 기여와 보안

개발과 Pull Request 절차는
[CONTRIBUTING.md](https://github.com/jaepil-choi/pdfbooktree/blob/master/CONTRIBUTING.md),
취약점의 비공개 제보 절차는
[SECURITY.md](https://github.com/jaepil-choi/pdfbooktree/blob/master/SECURITY.md),
배포 운영 절차는
[RELEASING.md](https://github.com/jaepil-choi/pdfbooktree/blob/master/RELEASING.md)를
따른다.

## 라이선스

MIT License로 배포한다. 상업적 이용, 수정과 재배포가 가능하며 저작권 고지와
라이선스 고지를 유지해야 한다. 자세한 조건은
[LICENSE](https://github.com/jaepil-choi/pdfbooktree/blob/master/LICENSE)에 있다.
