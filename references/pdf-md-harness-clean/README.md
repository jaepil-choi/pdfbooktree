# PDF Markdown Harness

PDF를 챕터·소챕터별 Markdown으로 변환한 결과와, 같은 작업을 다시 실행할 수 있는 도구를 함께 담은 클린 반환 묶음입니다.

이 패키지는 기존 결과를 그대로 덮어쓰지 않고 새로 복제해 정리한 버전입니다. 원본 PDF는 포함하지 않습니다.

## 포함된 내용

- `book-md/`: 세 권의 현재 변환 결과
  - `algorithms-nine/`: 미래를 바꾼 아홉 가지 알고리즘
  - `computer-science-human/`: 알고리즘 인생을 계산하다
  - `mathematical-statistics/`: 수리통계학 개정판
- 각 책의 `ch-XX.md`: 챕터별 Markdown
- `computer-science-human/`과 `mathematical-statistics/`에는 목차를 분석해 나눈 소챕터 Markdown
- `front-matter.md`, `detection-report.*`, `subsection-report.*`: 앞부분과 구조 감지 결과
- `detection-report.md`, `detection-report.json`: 챕터 감지 결과와 경계 확인 자료
- `pdf_to_chapters.py`: 챕터 자동 분리 도구
- `split_pdf_subsections.py`: 소챕터 분리 도구
- `pdf_toc.py`: 차례에서 이름형 소챕터와 페이지 번호를 읽는 도구
- `pdf_to_markdown.py`: PDF를 Markdown으로 변환하는 기본 도구
- `ocr_pdf_to_markdown.py`: 스캔 PDF용 Tesseract·macOS Vision OCR 도구
- `vision_ocr_batch.swift`: 한국어·영어 혼합 페이지를 배치 처리하는 Vision helper
- `paddle_ocr_runner.py`: PaddleOCR 한국어 모델 실행기
- `reocr_books.py`: 챕터 경계를 유지한 채 Vision OCR로 책 전체를 다시 생성하는 도구
- `split_vision_subsections.py`: Vision OCR 챕터 결과를 소챕터별 Markdown으로 분리하는 도구
- `benchmark_ocr.py`: OCR 엔진 비교와 검증 리포트 생성 도구
- `notion_upload.py`: Markdown을 Notion에 업로드하는 도구
- `notion_upload_catalog.py`: 책·챕터·소챕터 row 생성과 이전/이후 관계 연결 도구
- `.env.example`: Notion 업로드용 환경변수 예시. 실제 토큰은 포함하지 않음
- `HOW_IT_WORKS.md`: 처리 방식과 설계 이유
- `INSTALL.md`: macOS·Windows·Linux 설치 및 실행 안내
- `tests/`: PaddleOCR 설치, 목차 분할, Notion 관계 연결을 검증하는 표준 라이브러리 테스트
- `examples/`: 책별 경계·제목·소챕터 설정 예시

## 아키텍처

전체 흐름은 로컬 처리와 선택적 보정이 분리된 구조입니다.

```text
PDF
  -> 페이지 수·목차 확인
  -> 내장 텍스트 추출 또는 페이지 이미지 렌더링
  -> 로컬 OCR (macOS Vision / Tesseract / PaddleOCR)
  -> 페이지별 텍스트와 원본 페이지 번호 보존
  -> 목차·제목·페이지 위치 분석
  -> 챕터·소챕터 경계 확정
  -> Markdown 생성
  -> 선택적 이미지 대조 보정
  -> 선택적 Notion 업로드
```

챕터와 소챕터를 고정된 정규식 하나로 찾지 않습니다. 먼저 책의 목차를 분석하고, 다음 구조를 책에 맞게 선택합니다.

- `1장`, `제1장`, `Chapter 1` 같은 번호형 챕터
- `2.1`, `2-1` 같은 번호형 소챕터
- 목차에서 `|`로 나뉜 이름형 소챕터
- 목차 페이지와 본문 페이지의 차이를 보정한 경계 맵

알고리즘 책처럼 별도 소챕터가 없는 책은 챕터 단위로만 만들고, 나머지 책은 챕터 폴더 안에 소챕터 파일을 만듭니다.

## 토큰 사용 범위

기본 변환 경로는 LLM 토큰 없이 실행할 수 있습니다.

| 단계 | LLM 토큰 |
| --- | ---: |
| PDF 읽기·페이지 렌더링 | 없음 |
| 로컬 OCR | 없음 |
| 목차·챕터·소챕터 분할 | 없음 |
| Markdown 생성 | 없음 |
| 구조 감사·경계 리포트 | 없음 |
| 이미지 직접 보정 | 선택적으로 필요 |
| 요약·해설·질문 생성 | 필요 |
| Notion API 업로드 | LLM 토큰 없음 |

이미지 보정은 모든 페이지에 적용하지 않고, 챕터 첫 페이지·수식·표·그림·OCR 이상 징후가 있는 페이지만 대상으로 삼는 것을 권장합니다.

현재 `book-md/` 결과는 macOS Vision OCR을 기반으로 다시 생성한 결과입니다. 재실행할 때는 PDF의 텍스트 레이어가 충분하면 `pdftotext` 경로를 먼저 사용하고, 스캔 PDF나 품질이 낮은 페이지에만 OCR을 적용할 수 있습니다.

## 원본 PDF

이 묶음에는 원본 PDF 파일은 넣지 않고 변환 결과와 도구만 포함했습니다. 원본 PDF가 필요하면 기존 PDF 파일과 이 묶음을 함께 보관하면 됩니다.

## 빠른 확인

먼저 각 책 폴더의 `README.md`와 `detection-report.md`를 확인하면 생성된 파일과 챕터 경계를 볼 수 있습니다.

새 PDF를 변환하려면 다음처럼 실행합니다.

```bash
brew install poppler
python3 pdf_to_chapters.py book.pdf output --dry-run
python3 pdf_to_chapters.py book.pdf output
```

자세한 설명은 `HOW_IT_WORKS.md`와 `book-md/README.md`를 참고하세요.
설치가 필요한 경우 먼저 `INSTALL.md`를 확인하세요.

자동 설치 로직 테스트는 PaddleOCR을 실제로 내려받지 않고 실행할 수 있습니다.

```bash
python3 -m unittest discover -s tests -v
```

현재 9개 테스트가 있으며, 가상환경 생성 명령과 `paddleocr`·`paddlepaddle` 설치 명령,
목차 기반 소챕터 분할, Notion 관계 속성, 자동 설치를 끈 경우의 오류를 확인합니다.

## 한국어·영어 혼합 PDF OCR

현재 기본 OCR 엔진은 샘플 비교에서 가장 높은 점수를 기록한 `PaddleOCR`입니다.
PaddleOCR이 설치되어 있지 않으면 실행 시 `.venv-paddle` 가상환경을 만들고
`paddleocr`와 `paddlepaddle`을 자동으로 설치합니다. 첫 실행에는 인터넷 연결이 필요합니다.

```bash
python3 ocr_pdf_to_markdown.py /path/to/book.pdf output.md \
  --start-page 1 \
  --end-page 20
```

자동 설치를 원하지 않으면 다음 옵션을 사용합니다.

```bash
python3 ocr_pdf_to_markdown.py book.pdf output.md \
  --no-auto-install-paddle
```

### 권장 사양

아래 사양은 CPU로 한국어·영어 혼합 PDF를 처리하기 위한 현실적인 기준입니다.

| 항목 | 최소 | 권장 |
| --- | --- | --- |
| 운영체제 | macOS 12+ 또는 Windows 10/11 64-bit | 최신 안정 버전 |
| 프로세서 | 4코어 CPU | Apple Silicon 또는 Intel/AMD 6코어 이상 |
| 메모리 | 8GB RAM | 16GB RAM |
| 여유 저장공간 | 5GB | 10GB 이상 |
| Python | 3.10~3.12 64-bit | Python 3.11 |
| GPU | 없어도 실행 가능 | 있으면 처리 속도 향상 |

PaddleOCR 모델, Python 가상환경, PDF 렌더링 임시 이미지가 저장되므로 책 전체를 처리할 때는
여유 공간을 넉넉히 잡는 것이 좋습니다. CPU만 사용하면 수백 페이지 책은 오래 걸릴 수 있습니다.

macOS에서는 `Vision`의 `ko-KR`와 `en-US` 인식을 대안으로 사용할 수 있습니다.

```bash
python3 ocr_pdf_to_markdown.py /path/to/book.pdf output.md \
  --engine vision \
  --vision-languages ko-KR,en-US \
  --start-page 1 \
  --end-page 20
```

PaddleOCR을 비교하려면 `INSTALL.md`에서 Python 3.11 가상환경을 설치한 뒤 실행합니다.

```bash
python3 ocr_pdf_to_markdown.py /path/to/book.pdf output.md \
  --engine paddle \
  --paddle-python .venv-paddle/bin/python
```

`--vision-helper`를 생략하면 같은 폴더의 `vision_ocr_batch.swift`를 자동 컴파일합니다.
전체 책을 기존 챕터 경계에 맞춰 처리하려면 `reocr_books.py`를 사용합니다.

```bash
python3 reocr_books.py \
  --book "book-slug|/path/book.pdf|/path/detection-report.json" \
  --output-dir book-md-vision \
  --vision-helper /path/to/vision_ocr_batch \
  --dpi 220
```

본문 OCR은 개선되지만 수식과 복잡한 표의 기호는 원본 페이지와 대조해야 합니다.

Vision 결과를 소챕터로 나누려면 기존 `subsection-report.json`을 재사용합니다.

```bash
python3 split_vision_subsections.py \
  book-md-vision/computer-science-human \
  book-md/computer-science-human/subsection-report.json
```

## Notion 업로드

단순 Markdown 업로드는 `notion_upload.py`를 사용하고, 책별 row와 `챕터`, `이전 (소)챕터`,
`이후 (소)챕터` 속성까지 채우려면 `notion_upload_catalog.py`를 사용합니다.

```bash
cp .env.example .env
python3 notion_upload_catalog.py --book-dir book-md --dry-run
python3 notion_upload_catalog.py --book-dir book-md
```

실제 업로드 전에는 반드시 `--dry-run`으로 row 수와 파일 분할을 확인하세요.
Notion 관계형 속성은 대칭으로 표시될 수 있으므로, 스크립트는 `이전 (소)챕터`를 비워 두고
`이후 (소)챕터` 방향으로만 연결합니다. 속성명이 다르면 `.env`의 `NOTION_*_PROPERTY` 값을
변경하면 됩니다.
