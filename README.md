# pdfbooktree

[English](https://github.com/jaepil-choi/pdfbooktree/blob/master/README.en.md) ·
[문서](https://github.com/jaepil-choi/pdfbooktree/blob/master/docs/reference.md) ·
[변경 기록](https://github.com/jaepil-choi/pdfbooktree/blob/master/CHANGELOG.md)

`pdfbooktree`는 PDF 책에 북마크를 붙이고, 내용을 장·절 단위의 Markdown으로
정리하는 Python 도구다.

이미 북마크가 있으면 그대로 사용한다. 북마크가 없으면 페이지의 글자 크기와
배치를 살펴 목차 초안을 만든다. 초안을 확인한 뒤 북마크 PDF와 Markdown 폴더로
저장할 수 있다.

## 이런 경우에 유용하다

- 북마크가 없는 긴 PDF를 빠르게 탐색하고 싶을 때
- PDF의 장·절 구조를 Markdown이나 Obsidian으로 옮기고 싶을 때
- 여러 권의 PDF를 같은 방식으로 일괄 처리하고 싶을 때

## 설치

Python 3.12 이상이 필요하다.

```powershell
python -m pip install pdfbooktree
```

스캔 PDF에 OCR 텍스트를 넣으려면 OCR 기능을 함께 설치한다.

```powershell
python -m pip install "pdfbooktree[ocr]"
```

## 가장 간단한 사용법

```powershell
pdfbooktree process "book.pdf" -o .\runs
```

결과는 `runs` 아래의 새 실행 폴더에 저장된다.

```text
runs/
└── <책 이름>-<ID>/
    └── <실행 ID>/
        ├── bookmark_plan.json
        ├── <책 이름>_bookmarked.pdf
        └── <책 이름>_markdown/
            ├── toc.md
            └── nodes/
```

- `bookmark_plan.json`: 적용된 목차와 페이지 정보
- `*_bookmarked.pdf`: 북마크가 들어간 새 PDF
- `*_markdown/`: 장·절별 Markdown과 목차

원본 PDF는 바꾸지 않는다.

## 초안을 확인한 뒤 적용하기

자동으로 찾은 목차는 책의 편집 방식에 따라 달라질 수 있다. 중요한 문서는
`infer → inspect → apply` 순서로 확인하는 편이 안전하다.

```powershell
$pdf = "book.pdf"

pdfbooktree infer $pdf -o .\runs --format json
pdfbooktree inspect plan "<infer가 반환한 run_dir>" --summary
pdfbooktree apply $pdf `
  --plan "<run_dir>\bookmark_plan.json" `
  -o .\runs --dry-run
pdfbooktree apply $pdf `
  --plan "<run_dir>\bookmark_plan.json" `
  -o .\runs
```

`--dry-run`은 파일을 만들지 않고 페이지 범위와 목차 단계만 검사한다.

폴더 전체를 처리할 수도 있다.

```powershell
pdfbooktree batch .\books -o .\runs --recursive
```

## Markdown으로 내보내기

각 장과 절은 별도 Markdown 파일이 된다. 파일에는 상위·하위 항목과 이전·다음
항목으로 이동하는 링크가 들어간다. 생성된 Markdown 폴더를 Obsidian vault로
열고 `toc.md`부터 보면 된다.

파일이 너무 길어지는 것을 막으려면 길이를 제한할 수 있다.

```powershell
pdfbooktree process "book.pdf" -o .\runs `
  --max-words 10000 --max-words-coverage 0.95
```

## 스캔 PDF

검색하거나 복사할 수 있는 텍스트가 없는 PDF는 먼저 OCR 처리가 필요하다.
현재 내장 OCR은 Upstage Document Parse를 사용한다.

```powershell
$env:UPSTAGE_API_KEY = "<upstage-api-key>"
pdfbooktree ocr-overlay "scan.pdf" -o ".\scan_ocr.pdf"
pdfbooktree process ".\scan_ocr.pdf" -o .\runs
```

OCR을 실행하면 각 페이지 이미지가 Upstage로 전송되며 API 비용이 들 수 있다.
민감한 문서는 조직의 보안 정책과 Upstage의 처리 조건을 먼저 확인해야 한다.
API 키는 저장소에 커밋하지 않는다.

## 기존 북마크가 있는 PDF

의미 있는 북마크가 이미 있으면 기본적으로 이를 재사용한다. 원래 북마크를
자동 추론 결과로 바꾸려면 명시적으로 설정해야 한다.

```powershell
pdfbooktree batch .\books -o .\runs `
  --set outline_quality.replace_when_low_quality=true
```

교체하기 전에 기존 북마크와 `--dry-run` 결과를 확인하는 것이 좋다.

## Python에서 사용하기

```python
from pdfbooktree import process_pdf

result = process_pdf("book.pdf", "runs")
print(result.run_dir)
print(result.result.bookmarked_pdf_path)
print(result.result.markdown_manifest_path)
```

목차 생성과 적용을 나눠서 제어하려면 `infer_pdf()`,
`preview_apply_plan()`, `apply_plan_file()`을 사용할 수 있다.

## 알아둘 점

- 텍스트 추출 순서가 잘못된 PDF는 Markdown의 문장 순서도 어긋날 수 있다.
- 자동으로 만든 목차는 초안이다. 제목 모양이 일정하지 않은 책은 직접 확인해야
  한다.
- 표, 수식, 그림의 의미 구조까지 복원하지는 않는다.
- 암호 입력이 필요한 PDF는 지원하지 않는다.
- 공개 페이지 번호는 1부터 시작한다.

자세한 명령과 Python API는 [문서](https://github.com/jaepil-choi/pdfbooktree/blob/master/docs/reference.md)에서
확인할 수 있다.

## 라이선스

[MIT License](https://github.com/jaepil-choi/pdfbooktree/blob/master/LICENSE)
