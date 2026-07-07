# PRD: pdfbooktree

## 1. 제품 요약

`pdfbooktree`는 PDF 책을 읽어 계층형 bookmark를 만들고, 그 결과를 탐색 가능한 PDF와 구조화된 Markdown tree로 내보내는 Python library이자 CLI tool이다.

제품의 핵심은 책 전체에서 반복되는 시각적 제목 계층을 찾아 사람과 AI agent가 함께 사용하기 쉬운 outline을 복원하는 것이다. 목차 페이지를 먼저 찾고 파싱하는 방식은 현재 기본 방향이 아니다.

## 2. 문제 정의

많은 PDF 책은 bookmark가 없거나, 기존 OCR text layer가 깨져 있어 검색과 구조 탐색이 어렵다. 특히 scanned PDF에서는 기존 OCR text가 불안정하면 제목 탐지, page matching, Markdown export가 모두 흔들린다.

AI agent가 PDF 책을 다룰 때도 비슷한 문제가 생긴다. agent는 PDF viewer를 눈으로 오래 확인하기보다 terminal output, structured result, 작은 inspection command를 통해 판단한다. 따라서 이 제품은 end-to-end 변환 도구이면서, PDF의 일부 정보를 빠르게 조사하는 agent-friendly tool이어야 한다.

`pdfbooktree`는 이 문제를 다음 방식으로 해결한다.

1. 필요한 경우 신뢰할 수 있는 searchable PDF를 만든다.
2. 책 전체의 글자 크기와 시각적 계층을 바탕으로 bookmark tree를 만든다.
3. 생성된 구조를 PDF bookmark, Markdown directory/file tree, 실행 report로 제공한다.
4. Python import interface와 CLI interface를 모두 제공해 AI agent가 도구처럼 사용할 수 있게 한다.
5. 처리 중간 결과와 warning을 terminal에서 확인하기 쉽게 보여준다.

## 3. 목표

사용자는 PDF 책 하나를 입력해 다음 결과를 얻을 수 있어야 한다.

- 필요한 경우 새 OCR text layer가 포함된 searchable PDF
- 계층형 bookmark가 삽입된 PDF
- bookmark 구조를 반영한 Markdown directory/file tree
- 처리 과정, 근거, warning을 담은 report
- 재현 가능한 중간 산출물
- Python 코드와 terminal CLI 양쪽에서 사용할 수 있는 public interface
- AI agent가 중간 결과를 쉽게 확인할 수 있는 terminal output

최종 사용자는 PDF viewer에서 장과 절을 바로 탐색할 수 있어야 하며, 같은 구조를 Markdown directory/file tree에서도 확인할 수 있어야 한다.

## 4. 핵심 기능

### 4.1 OCR 전처리

OCR 품질이 낮은 PDF에 대해 searchable PDF를 생성한다.

필수 요구사항은 다음이다.

- 기존 PDF의 깨진 OCR text layer를 무조건 신뢰하지 않는다.
- 외부 document parse 결과는 재사용할 수 있도록 cache한다.
- page image 위에 invisible text layer를 올려 searchable PDF를 만든다.
- OCR 결과와 overlay 결과에 대한 검증 정보를 남긴다.
- OCR 단계는 단독 실행할 수 있어야 하며, 전체 처리 앞단에서도 사용할 수 있어야 한다.

### 4.2 Typography 기반 bookmark 생성

책 전체를 읽어 제목 후보를 찾고 계층형 bookmark plan을 만든다.

필수 요구사항은 다음이다.

- 책 전체 page의 text와 geometry를 사용한다.
- TOC page 탐지에 의존하지 않는다.
- font size와 bbox height를 모두 계산한다.
- 같은 시각적 줄이 여러 조각으로 나뉜 경우 다시 하나의 line으로 묶는다.
- line 대표값은 극단값보다 중앙값을 우선한다.
- 본문, 제목, 장 표제, 부록, front matter를 구분할 수 있는 근거를 남긴다.
- 제목 후보마다 page, text, 계층 근거, confidence를 남긴다.
- 최종 bookmark는 1-based PDF page number를 사용한다.

### 4.3 Bookmark PDF 생성

검증된 bookmark plan을 PDF outline으로 삽입한다.

필수 요구사항은 다음이다.

- 원본 PDF를 직접 덮어쓰지 않는다.
- output PDF의 page count는 원본과 같아야 한다.
- bookmark target page는 PDF 범위 안에 있어야 한다.
- bookmark 삽입 후 다시 읽어 검증할 수 있어야 한다.
- 기존 bookmark가 있는 PDF는 기본적으로 자동 overwrite하지 않는다.

### 4.4 Markdown tree export

bookmark tree를 LLM이 구조적으로 읽기 쉬운 Markdown directory/file tree로 내보낸다.

이 export는 책 전체를 하나의 거대한 Markdown 파일로 만드는 기능이 아니다. bookmark hierarchy의 각 노드는 독립적으로 읽을 수 있는 Markdown 단위가 되어야 하며, 부모-자식 관계는 결과 tree 구조에 보존되어야 한다.

필수 요구사항은 다음이다.

- Markdown 결과는 bookmark hierarchy의 순서와 부모-자식 관계를 보존해야 한다.
- 각 항목은 독립적으로 읽을 수 있는 Markdown 단위여야 한다.
- 각 항목에는 title, level, page range, source, confidence를 기록한다.
- 상위 항목은 자식 항목으로 이동할 수 있는 목차 정보를 제공해야 한다.
- LLM이 특정 장이나 절만 선택해 읽을 수 있도록 항목 경계가 명확해야 한다.
- 본문 text 품질이 낮으면 가능한 범위만 export하고 warning을 남긴다.

### 4.5 Report와 중간 산출물

각 실행은 처리 과정을 검토하고 재현할 수 있는 정보를 남긴다.

필수 요구사항은 다음이다.

- 입력 PDF 식별 정보와 page number convention을 기록한다.
- OCR 사용 여부와 OCR 품질 판단을 기록한다.
- typography 신호와 제목 후보 추출 근거를 기록한다.
- bookmark plan과 검증 결과를 기록한다.
- Markdown export 결과와 warning을 기록한다.
- 실패한 경우에도 어느 단계에서 왜 실패했는지 확인할 수 있어야 한다.

### 4.6 AI agent friendly interface

`pdfbooktree`는 사람이 직접 쓰는 library일 뿐 아니라 AI agent가 terminal과 Python runtime에서 skill처럼 호출하기 쉬운 도구여야 한다.

필수 요구사항은 다음이다.

- 주요 기능은 Python import interface와 CLI interface 양쪽에서 사용할 수 있어야 한다.
- CLI는 긴 end-to-end 처리뿐 아니라 작은 inspection 작업도 지원해야 한다.
- AI agent는 PDF의 특정 page text 읽기, page 범위 text 읽기, 기존 bookmark 확인, page count 확인, OCR 품질 확인, bookmark plan 확인 같은 작업을 terminal에서 빠르게 수행할 수 있어야 한다.
- CLI output은 사람이 읽기 쉬우면서도 agent가 파싱하기 쉬운 형태를 제공해야 한다.
- 긴 처리 중에도 현재 단계, 처리 중인 page, 생성된 artifact, warning, 다음 확인 지점을 terminal output으로 확인할 수 있어야 한다.
- 실패 시에는 stack trace만 보여주지 말고 agent가 다음 행동을 결정할 수 있는 원인, 위치, 관련 산출물을 알려줘야 한다.

## 5. 비목표

다음은 현재 제품 목표가 아니다.

- 범용 OCR engine 자체 개발
- 사람이 직접 OCR 결과를 수정하는 visual editor
- TOC page parsing을 기본 bookmark 생성 방식으로 사용하는 것
- table, figure, equation을 완전한 semantic document model로 복원하는 것
- 출판 품질의 EPUB 생성

## 6. Page Number Convention

public interface, report, 중간 산출물, bookmark plan은 모두 1-based PDF page number를 사용한다.

내부 PDF library가 0-based index를 사용하더라도 외부로 드러나는 값은 항상 1-based여야 한다.

## 7. 사용자 흐름

### 7.1 OCR overlay

사용자는 OCR 품질이 낮은 PDF에 대해 searchable PDF를 먼저 생성할 수 있어야 한다.

결과에는 처리 상태, 입력 PDF, 출력 PDF, page 수, provider, cache 사용 여부, warning이 포함되어야 한다.

### 7.2 단일 PDF 처리

사용자는 PDF 하나를 처리해 bookmarked PDF, Markdown directory/file tree, report를 얻을 수 있어야 한다.

처리 결과에는 상태, 입력 PDF, OCR PDF 여부, bookmarked PDF, Markdown tree 결과, bookmark 수, confidence 요약, warning, 중간 산출물 위치가 포함되어야 한다.

### 7.3 Batch processing

사용자는 여러 PDF를 한 번에 처리할 수 있어야 한다.

Batch summary에는 전체 PDF 수, 처리 수, 실패 수, 기존 bookmark skip 수, 생성된 결과 수가 포함되어야 한다.

### 7.4 PDF inspection

사용자와 AI agent는 전체 processing을 실행하지 않고도 PDF의 일부 정보를 빠르게 확인할 수 있어야 한다.

지원해야 하는 inspection 흐름은 다음이다.

- PDF page count 확인
- 특정 page 또는 page 범위의 text 확인
- 기존 bookmark 확인
- OCR text layer 품질에 대한 빠른 진단
- 생성된 bookmark plan 또는 Markdown tree 결과 확인

### 7.5 Terminal-first workflow

AI agent는 terminal output을 보며 다음 행동을 결정하므로, CLI는 중간 결과를 숨기지 않아야 한다.

필수 요구사항은 다음이다.

- 기본 출력은 현재 단계와 핵심 요약을 보여준다.
- 필요하면 machine-readable output을 선택할 수 있다.
- 긴 작업은 진행률과 현재 처리 대상을 보여준다.
- 생성된 주요 산출물 위치를 실행 중과 완료 시점에 알려준다.
- warning은 조용히 report에만 묻히지 않고 terminal에도 드러나야 한다.

## 8. 품질 기준

### 8.1 OCR overlay

- overlay PDF 생성 성공률이 충분히 높아야 한다.
- page count는 원본과 같아야 한다.
- 재추출한 text가 OCR provider 결과를 충분히 보존해야 한다.
- 실패 또는 낮은 품질은 report에 warning으로 남긴다.

### 8.2 Bookmark 생성

- 주요 장과 절 제목을 높은 recall로 찾아야 한다.
- bookmark target page는 실제 제목 page와 일치하거나 매우 가까워야 한다.
- level jump와 page 역전이 없어야 한다.
- 생성된 PDF outline은 다시 읽었을 때 bookmark plan과 일치해야 한다.

### 8.3 Markdown tree export

- Markdown 결과는 단일 대형 파일이 아니라 bookmark hierarchy 기반 tree여야 한다.
- 각 Markdown 항목은 독립적으로 읽을 수 있어야 한다.
- 부모-자식 관계, 항목 순서, page range가 보존되어야 한다.
- 각 Markdown 항목은 source metadata를 포함해야 한다.
- text extraction 품질 문제가 있으면 누락 없이 warning을 남긴다.

### 8.4 Public interface and terminal usability

- Python interface와 CLI interface는 같은 개념과 page number convention을 공유해야 한다.
- CLI는 agent가 필요한 작은 inspection 작업을 빠르게 수행할 수 있어야 한다.
- Terminal output은 처리 상태, 핵심 수치, warning, 산출물 위치를 명확히 보여줘야 한다.
- Machine-readable output을 사용할 때도 사람이 원인을 추적할 수 있는 메시지를 함께 남길 수 있어야 한다.
- 실패한 명령은 다음 확인 작업을 선택할 수 있을 만큼 구체적인 오류 정보를 제공해야 한다.

## 9. 현재 우선순위

1. OCR overlay 안정화
2. 책 전체 typography 기반 heading 후보 추출
3. bookmark plan 생성과 검증
4. PDF bookmark 삽입과 검증
5. Markdown tree export
6. AI agent용 inspection CLI와 terminal output 정리
7. batch 처리와 report 정리

## 10. 성공 기준

`pdfbooktree`는 사용자가 bookmark 없는 PDF 책을 입력했을 때, 별도 수작업 없이 탐색 가능한 bookmarked PDF와 LLM이 구조적으로 읽기 쉬운 Markdown tree를 얻을 수 있으면 성공이다. 또한 AI agent가 terminal과 Python interface를 통해 PDF를 조사하고, 중간 결과를 확인하고, 다음 작업을 결정하기 쉬워야 한다.

결과가 확실하지 않은 경우에도 실패를 숨기지 않고, 어떤 단계에서 어떤 근거와 warning이 있었는지 확인할 수 있어야 한다.

