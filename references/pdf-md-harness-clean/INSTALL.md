# 설치 안내

이 도구는 PDF를 이미지로 렌더링할 때 Poppler가 필요합니다. OCR 엔진은 운영체제에 따라 선택합니다.

## 권장 사양

PaddleOCR을 기본 엔진으로 사용합니다. CPU만으로도 실행할 수 있지만, 책 전체를 처리할 때는
다음 정도를 기준으로 잡는 것이 좋습니다.

| 항목 | 최소 | 권장 |
| --- | --- | --- |
| macOS | macOS 12+, 4코어, 8GB RAM | Apple Silicon 또는 6코어 이상, 16GB RAM |
| Windows | Windows 10/11 64-bit, 4코어, 8GB RAM | Intel/AMD 6코어 이상, 16GB RAM |
| Python | 3.10~3.12 64-bit | 3.11 |
| 저장공간 | 5GB 여유 | 10GB 이상 |
| GPU | 선택 사항 | 있으면 처리 속도 향상 |

5GB에는 PaddleOCR 모델, 가상환경, PDF 렌더링 임시 이미지가 포함됩니다. 300dpi로 큰 책을
처리할 때는 더 많은 공간이 필요할 수 있습니다.

## macOS

macOS에서는 한국어·영어 본문에 `Vision`을 사용할 수 있습니다.

### 1. 기본 도구 설치

```bash
xcode-select --install
brew install poppler
```

Python은 macOS에 설치된 `python3`를 사용하면 됩니다. 별도 Python 패키지는 필요하지 않습니다.

### 2. 한 페이지 테스트

```bash
python3 ocr_pdf_to_markdown.py \
  ~/Downloads/book.pdf sample.md \
  --engine vision \
  --vision-languages ko-KR,en-US \
  --start-page 1 \
  --end-page 3
```

`--vision-helper`를 생략하면 같은 폴더의 `vision_ocr_batch.swift`를 자동으로 컴파일합니다.

### 3. Tesseract를 대안으로 설치

```bash
brew install tesseract tesseract-lang
```

```bash
python3 ocr_pdf_to_markdown.py book.pdf sample.md \
  --engine tesseract \
  --lang kor+eng
```

## Windows

Windows에서는 macOS Vision을 사용할 수 없으므로 Tesseract 경로를 사용합니다.

### 1. Tesseract 설치

Tesseract Windows 설치 파일에서 한국어 언어 데이터(`kor`)를 함께 선택합니다.

공식 안내: <https://tesseract-ocr.github.io/tessdoc/Installation.html>

설치 후 다음 파일이 있는지 확인합니다.

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
C:\Program Files\Tesseract-OCR\tessdata\kor.traineddata
```

### 2. Poppler 설치

Poppler Windows 빌드를 내려받아 압축을 풀고 `Library\bin`을 PATH에 추가합니다.

공식 저장소: <https://github.com/oschwartz10612/poppler-windows/releases>

PATH 설정이 어렵다면 실행할 때 경로를 직접 지정할 수 있습니다.

### 3. 실행

PowerShell에서:

```powershell
py ocr_pdf_to_markdown.py book.pdf sample.md `
  --engine tesseract `
  --lang kor+eng `
  --tesseract "C:\Program Files\Tesseract-OCR\tesseract.exe" `
  --pdftoppm "C:\poppler\Library\bin\pdftoppm.exe" `
  --start-page 1 `
  --end-page 3
```

Tesseract가 PATH에 등록되어 있다면 `--tesseract`는 생략할 수 있습니다.

## PaddleOCR (기본 엔진)

한국어 본문과 영어 용어가 섞인 PDF는 PaddleOCR을 기본으로 사용합니다. 별도 설치 없이
`ocr_pdf_to_markdown.py`를 실행하면, PaddleOCR이 없는 경우 현재 폴더에 `.venv-paddle`을
만들고 필요한 패키지를 자동 설치합니다.

```bash
python3 ocr_pdf_to_markdown.py book.pdf output.md \
  --start-page 1 \
  --end-page 3
```

첫 자동 설치에는 인터넷 연결이 필요합니다. Python 3.11이 없거나 자동 설치를 원하지 않으면
아래처럼 직접 가상환경을 만든 뒤 경로를 지정할 수 있습니다.

macOS/Linux:

```powershell
python3.11 -m venv .venv-paddle
.venv-paddle/bin/python -m pip install --upgrade paddleocr paddlepaddle
```

Windows PowerShell:

```bash
py -3.11 -m venv .venv-paddle
.\.venv-paddle\Scripts\python.exe -m pip install --upgrade paddleocr paddlepaddle
```

직접 설치한 환경으로 실행하려면:

```bash
python3 ocr_pdf_to_markdown.py book.pdf output.md \
  --engine paddle \
  --paddle-python .venv-paddle/bin/python
```

Windows에서는 `--paddle-python .venv-paddle\Scripts\python.exe`로 지정합니다.

자동 설치를 끄고 누락 여부만 확인하려면:

```bash
python3 ocr_pdf_to_markdown.py book.pdf output.md --no-auto-install-paddle --check-only
```

PaddleOCR은 첫 실행 때 한국어 모델을 자동으로 내려받습니다. 모델 파일이 크고
CPU 환경에서는 느릴 수 있으므로 먼저 1~3페이지로 테스트하세요.

## Linux

Ubuntu/Debian 기준:

```bash
sudo apt update
sudo apt install poppler-utils tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng
```

```bash
python3 ocr_pdf_to_markdown.py book.pdf sample.md \
  --engine tesseract \
  --lang kor+eng
```

## 챕터·소챕터 분리

먼저 OCR 결과를 만든 뒤 챕터 경계를 감지합니다.

```bash
python3 pdf_to_chapters.py book.pdf book-md --dry-run
python3 pdf_to_chapters.py book.pdf book-md
```

기존 소챕터 리포트가 있다면 Vision OCR 결과에도 그대로 적용할 수 있습니다.

```bash
python3 split_vision_subsections.py \
  book-md-vision/computer-science-human \
  book-md/computer-science-human/subsection-report.json
```

## Notion 업로드

OCR과 Markdown 변환이 끝난 뒤에만 Notion 업로드를 실행합니다.

```bash
cp .env.example .env
# .env에 Notion token과 부모 페이지 또는 data source ID 입력
python3 notion_upload.py output.md --title "책 제목" --dry-run
python3 notion_upload.py output.md --title "책 제목"
```

책·챕터·소챕터를 row로 만들고 `챕터`, `이전 (소)챕터`, `이후 (소)챕터`를 연결하려면:

```bash
python3 notion_upload_catalog.py --book-dir book-md --dry-run
python3 notion_upload_catalog.py --book-dir book-md
```

이 기능은 `NOTION_DATA_SOURCE_ID`가 필요합니다. 기본 속성명은 `이름`, `책 제목`, `챕터`,
`이전 (소)챕터`, `이후 (소)챕터`이며, `.env`에서 `NOTION_*_PROPERTY`로 바꿀 수 있습니다.

## 자주 발생하는 문제

- `pdftoppm was not found`: Poppler 설치 또는 `--pdftoppm` 경로 확인
- `kor.traineddata was not found`: Tesseract 한국어 언어 데이터 설치 확인
- Vision helper 컴파일 실패: macOS에서 `xcode-select --install` 실행
- 수식이 깨짐: 일반 OCR의 한계입니다. 수식 중심 문서는 원본 PDF와 대조해야 합니다.
