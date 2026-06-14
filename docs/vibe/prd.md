# PRD: `pdfbooktree`

## 1. 배경

OCR text layer가 overlay되어 있는 scanned PDF textbook은 사람이 읽기에는 충분하지만, 구조화된 디지털 활용에는 한계가 있다.

대표적인 문제는 다음과 같다.

* PDF bookmark / outline이 없어 chapter, section 단위 이동이 어렵다.
* Table of Contents는 PDF 내부에 존재하지만, 실제 PDF bookmark와 연결되어 있지 않다.
* text extraction은 가능하지만, chapter / section 단위로 분할되어 있지 않다.
* Obsidian, Markdown archive, LLM/RAG pipeline에서 활용하려면 책 내용을 계층적 text tree로 분리할 필요가 있다.

따라서 이 프로젝트의 핵심 문제는 다음과 같다.

> PDF 내부 Table of Contents 항목을 실제 PDF page에 align하고, 이를 이용해 PDF bookmark와 hierarchical Markdown directory를 생성하는 것.

OCR 자체는 이 프로젝트의 범위가 아니다. 입력 PDF에는 이미 OCR text overlay가 존재한다고 가정한다.

---

## 2. 목적

`pdfbooktree`는 OCR text layer가 있는 scanned textbook PDF를 입력받아 다음 작업을 수행하는 Python package다.

1. PDF 내부 Table of Contents page를 탐지한다.
2. TOC 항목을 파싱해 chapter / section hierarchy를 복원한다.
3. TOC의 printed page number와 실제 PDF page를 align한다.
4. 본문 heading과 fuzzy matching하여 page alignment를 검증 / 보정한다.
5. 기존 PDF 파일을 기반으로 bookmark가 삽입된 `_bookmarked.pdf` 파일을 생성한다.
6. chapter / section 단위 Markdown directory를 생성한다.
7. 기존 bookmark가 있는 PDF는 기본 처리 대상에서 skip한다.
8. 기존 bookmark가 있는 PDF는 검수 전 ground truth가 아니라 weak reference로만 사용한다.
9. TOC page ground truth는 수동 검수 또는 별도 검증 절차를 통과한 range만 사용한다.
10. TOC page 탐지가 불안정한 경우를 대비해 word box 좌표 기반 body-first bookmark 생성도 실험한다.
11. LLM API는 low-confidence case에 대한 cross-check / repair / fallback으로만 선택적으로 사용한다.

---

## 3. 핵심 설계 원칙

### 3.1 Page number convention은 1-based로 통일한다

이 package 내부에서는 page number를 모두 1-based로 사용한다.

이유:

* PDF bookmark / outline은 사용자가 보는 page number와 자연스럽게 연결되어야 한다.
* TOC의 printed page number도 1-based다.
* 내부적으로 0-based와 1-based를 혼용하면 page off-by-one bug 가능성이 높아진다.

따라서 모든 public interface, intermediate JSON, evaluation report에서는 1-based PDF page number를 사용한다.

예:

```json
{
  "pdf_page": 105,
  "printed_page": 87,
  "title": "2.3 Markov Chains"
}
```

---

### 3.2 OCR은 수행하지 않는다

포함:

* OCR text layer가 있는 PDF에서 text / line / block 추출
* TOC page detection
* TOC item parsing
* heading matching
* bookmark insertion
* Markdown export

제외:

* scanned image에 대한 OCR 생성
* Tesseract / PaddleOCR / EasyOCR integration
* OCR text layer 생성
* 수식 LaTeX 복원
* table / figure extraction

---

### 3.3 기존 bookmark는 skip 대상이지만 ground truth는 아니다

이미 깔끔한 bookmark가 있는 PDF는 처리 대상이 아니다.

처리 정책:

* 기존 bookmark가 없거나 비어 있는 PDF만 bookmark generation 대상이다.
* 기존 bookmark가 충분히 깔끔한 PDF는 자동 처리에서 skip한다.
* skip된 PDF의 bookmark는 generated bookmark 평가용 weak reference로 사용할 수 있다.
* 기존 bookmark에서 복원한 TOC page range는 검수 전 ground truth로 사용하지 않는다.
* 이미 bookmark가 있는 PDF를 강제로 다시 처리하는 기능은 MVP 범위 밖이다.

“깔끔한 bookmark”의 최소 판단 기준:

* bookmark item 수가 충분히 많다.
* bookmark title이 비어 있지 않다.
* page number가 대체로 증가한다.
* level structure가 존재한다.
* chapter / section으로 보이는 항목들이 포함되어 있다.

중요한 한계:

* 기존 bookmark는 각 chapter / section이 실제로 시작되는 본문 page를 알려줄 수 있지만, PDF 내부의 TOC page 위치를 직접 알려주지는 않는다.
* bookmark title을 TOC page text와 matching해 TOC page range를 복원하는 방식은 PDF layout, OCR 품질, 숫자 noise, front matter 구조에 크게 흔들린다.
* 따라서 bookmark-guided TOC page label은 수동 검수 전에는 학습용 정답 label이 아니라 noisy weak label이다.
* weak label로 학습한 ML 모델의 점수는 실제 TOC 탐지 성능이 아니라 해당 heuristic을 얼마나 모방했는지를 보여줄 수 있다.

---

### 3.4 Output은 실제 PDF 파일이어야 한다

이 package는 단순히 bookmark JSON만 생성하고 끝나면 안 된다.

기본 output 정책:

```text
input:
  book.pdf

output:
  book_bookmarked.pdf
  book_markdown/
  book_report.json
```

즉, 원본 PDF를 읽고 bookmark가 삽입된 새 PDF를 저장한다.
파일명에는 `_bookmarked` suffix를 붙여 bookmark가 추가된 파일임을 명확히 표시한다.

---

### 3.5 Heuristic-first, LLM-backup

기본 pipeline은 deterministic heuristic과 classical ML로 완결되어야 한다.

LLM은 다음 경우에만 사용한다.

* TOC page detection confidence가 낮은 경우
* TOC item parsing 결과가 불안정한 경우
* page offset 추정이 여러 후보로 갈리는 경우
* TOC item과 본문 heading matching이 애매한 경우
* OCR text가 깨져 제목 복원이 필요한 경우

LLM은 primary engine이 아니라 backup / cross-check 단계다.

---

### 3.6 모든 중간 결과를 저장한다

디버깅과 평가를 위해 intermediate artifact를 저장한다.

예:

```text
toc_page_candidates.json
toc_raw.json
page_offset.json
toc_aligned.json
ranges.json
bookmark_plan.json
markdown_export_log.json
eval_report.json
```

각 단계에는 confidence와 method를 기록한다.

---

## 4. 문제 정의

전체 문제는 네 단계로 나뉜다.

---

### 4.1 TOC page detection

PDF 안에서 Table of Contents가 들어 있는 page range를 찾는다.

예:

```text
TOC pages = 5-7
```

TOC는 한 page일 수도 있고 여러 page에 걸쳐 있을 수도 있다.

---

### 4.2 TOC item parsing

탐지된 TOC page에서 chapter / section 항목을 추출한다.

예:

```text
2.3 Markov Chains ............ 87
```

파싱 결과:

```text
title: 2.3 Markov Chains
level: 2
printed_page: 87
source_pdf_page: 6
```

---

### 4.3 TOC item to PDF page alignment

TOC의 printed page number를 실제 PDF page와 연결한다.

핵심은 offset을 찾는 것이다.

예:

```text
printed page 1 = PDF page 18
offset = 17

TOC item printed page 87
→ estimated PDF page 104
```

이후 estimated page 주변에서 실제 본문 heading을 fuzzy search하여 최종 page를 확정한다.

---

### 4.4 Output generation

최종 output은 두 가지다.

#### 1. Bookmarked PDF

```text
book_bookmarked.pdf
```

PDF outline / bookmark가 삽입된 파일이다.

#### 2. Markdown tree

```text
book_markdown/
  metadata.json
  toc.json
  toc.md
  01_Introduction/
    index.md
    01_1_1_Motivation.md
    02_1_2_Background.md
```

---

## 5. 고려한 알고리즘과 최종 결정

## 5.1 TOC-first + page offset 방식

### 설명

PDF 내부 TOC를 먼저 찾고, 각 TOC item에서 printed page number를 추출한다.
그 다음 printed page number와 실제 PDF page 사이의 offset을 추정한다.

예:

```text
Chapter 1 Introduction ............ 3
Chapter 2 Probability ............. 25
```

본문 page number 탐지 결과:

```text
printed page 1 = PDF page 18
offset = 17
```

따라서:

```text
printed page 3  -> PDF page 20
printed page 25 -> PDF page 42
```

### 장점

* 가장 단순하고 explainable하다.
* TOC와 page number가 정상적인 textbook에서는 매우 강력하다.
* 빠른 성공 경로로 적합하다.

### 단점

* offset 추정이 틀리면 전체 bookmark가 밀릴 수 있다.
* TOC page number와 실제 heading 위치가 1~2 page 다를 수 있다.
* 본문 heading을 직접 확인하지 않으면 위험하다.

### 결정

이 방식은 반드시 먼저 시도한다.
다만 이것만으로 끝내지 않고, 이후 hybrid TOC-body alignment의 초기 추정값으로 사용한다.

---

## 5.2 Hybrid TOC-body alignment 방식

### 설명

TOC-first + page offset 방식으로 각 item의 예상 page를 구한 뒤, 본문 heading 후보와 fuzzy matching하여 최종 page를 확정한다.

전체 흐름:

```text
TOC item
→ printed page
→ offset 기반 estimated PDF page
→ estimated page 주변 ±N pages search
→ body heading candidate 추출
→ TOC title과 heading fuzzy matching
→ 최종 matched page 확정
```

예:

```text
TOC:
  2.3 Markov Chains ........ 87

Offset result:
  estimated PDF page = 104

Search window:
  PDF pages 101-107

Body heading match:
  PDF page 105: "2.3 Markov Chains"

Final:
  matched PDF page = 105
```

### 장점

* offset-only 방식보다 안정적이다.
* 실제 본문 heading 위치를 확인하므로 bookmark 품질이 좋아진다.
* OCR title이 약간 깨져도 fuzzy matching으로 보정 가능하다.
* TOC가 있는 textbook에 대해 단순성과 성능의 균형이 좋다.

### 단점

* heading candidate extraction이 필요하다.
* fuzzy threshold와 confidence 설계가 필요하다.
* 본문 heading이 OCR에서 깨진 경우 fallback이 필요할 수 있다.

### 결정

이 프로젝트의 기본 알고리즘으로 채택한다.

정확히는:

> TOC-first + page offset을 먼저 수행하고, 이를 기반으로 hybrid TOC-body alignment를 기본 page matching 방식으로 사용한다.

---

## 5.3 Body-first heading detection 방식

### 설명

TOC를 신뢰하지 않고 본문 전체에서 heading 후보를 직접 찾아 synthetic TOC를 만드는 방식이다.

특히 text line만 보지 않고 PyMuPDF의 word / block box 좌표를 함께 사용한다.
chapter 시작 page에서는 대개 다음 신호가 반복될 수 있다.

```text
상단 또는 일정한 여백 아래에 있는 짧은 제목 block
본문보다 큰 font size 또는 다른 bbox 높이
chapter number와 title이 분리된 반복 layout
새 chapter 시작 전후의 큰 vertical whitespace
같은 책 안에서 반복되는 heading 좌표와 text density 패턴
```

이 방식은 TOC page 자체를 찾지 않고 다음 결과를 직접 만든다.

```text
chapter title 후보
chapter start PDF page
heading bbox
layout cluster
confidence
```

### 장점

* TOC가 없거나 TOC OCR이 망가진 경우에도 가능성이 있다.
* TOC page ground truth가 부정확해도 본문 구조에서 직접 bookmark 후보를 만들 수 있다.
* chapter-level bookmark 생성에는 TOC item parsing보다 더 직접적인 신호가 될 수 있다.

### 단점

* running header, figure caption, exercise title 등을 heading으로 오인할 수 있다.
* layout heuristic tuning이 많다.
* section-level까지 확장하면 후보가 급격히 늘어난다.
* 책마다 heading design이 달라 unsupervised clustering과 confidence 설계가 필요하다.

### 결정

초기 MVP의 단일 primary algorithm으로 고정하지 않는다.
다만 300study 수동 검수에서 bookmark-guided TOC page label이 크게 틀린 사례가 확인되었으므로, 이 방식은 더 이상 후순위 아이디어가 아니라 별도 실험 축으로 다룬다.

우선 chapter-level top heading discovery를 목표로 실험한다.
TOC page 탐지와 TOC item parsing이 실패하거나 label이 불확실한 PDF에서는 body-first 결과를 bookmark 생성 후보로 사용할 수 있어야 한다.

---

## 5.4 LLM-heavy image parsing 방식

### 설명

TOC page image 또는 본문 candidate page image를 LLM API에 보내 판단하게 하는 방식이다.

### 장점

* OCR이 깨진 경우에 강할 수 있다.
* TOC hierarchy 복원이나 애매한 page 판단에 도움을 줄 수 있다.

### 단점

* 비용이 크다.
* 속도가 느리다.
* 재현성이 낮다.
* batch processing에 부적합하다.

### 결정

primary algorithm으로 사용하지 않는다.
low-confidence case의 optional fallback으로만 사용한다.

---

## 6. 현재 기본 알고리즘과 보완 축

현재 기본 알고리즘 가설은 다음이다.

> TOC-first page offset estimation을 먼저 수행하고, hybrid TOC-body alignment를 통해 최종 bookmark page를 확정한다.

흐름:

```text
PDF 입력
→ 기존 bookmark 존재 여부 확인
→ 이미 깔끔한 bookmark가 있으면 skip
→ text layer 추출
→ TOC page detection
→ TOC item parsing
→ printed page number 추출
→ printed page to PDF page offset 추정
→ 각 TOC item의 estimated PDF page 계산
→ estimated page 주변에서 body heading fuzzy search
→ aligned TOC 생성
→ bookmark plan 생성
→ input PDF 기반으로 *_bookmarked.pdf 저장
→ Markdown tree export
→ report 저장
```

LLM은 다음 조건에서만 개입한다.

```text
TOC detection confidence 낮음
TOC parsing confidence 낮음
offset confidence 낮음
heading matching confidence 낮음
```

다만 이 알고리즘은 TOC page를 안정적으로 찾는다는 전제에 의존한다.
300study 검수 결과 기존 bookmark를 이용해 복원한 TOC page label이 매우 부정확한 사례가 다수 확인되었다.
따라서 다음 보완 축을 병렬로 실험한다.

```text
PDF 입력
→ page별 word / block box 좌표 추출
→ 상단 heading 후보 추출
→ layout similarity와 text pattern으로 chapter 시작 page clustering
→ chapter title과 start page 후보 생성
→ 기존 bookmark 또는 수동 검수 label과 비교
→ bookmark plan 생성 후보로 승격
```

이 body-first 축은 TOC page를 먼저 찾지 않는다.
목표는 최소한 top-level chapter bookmark를 unsupervised하게 생성하는 것이다.

---

## 7. TOC page detection 설계

TOC page detection은 너무 많은 noisy feature를 쓰지 않는다.
초기 feature는 최대한 objective하고 robust한 것 위주로 제한한다.

---

### 7.1 기본 탐색 범위

TOC는 대부분 책 앞부분에 있다.

기본 탐색 범위:

```text
PDF 앞부분 N pages
예: first 80 pages
```

단, page count가 작은 PDF에서는 전체 page 수에 따라 자동 조정한다.

---

### 7.2 Page-level objective features

각 page에서 다음 feature를 추출한다.

#### 1. `line_count`

해당 page의 non-empty line 개수.

TOC page는 일반 본문보다 짧은 line이 여러 개 나열되는 경우가 많다.

---

#### 2. `word_count`

해당 page의 총 word 개수.

TOC page는 본문 page보다 paragraph density가 낮을 가능성이 있다.

---

#### 3. `mean_line_length`

line당 평균 character 수 또는 word 수.

TOC page는 일반 본문보다 line 길이가 짧고 균일한 경우가 많다.

---

#### 4. `line_final_number_count`

line의 마지막 token이 숫자인 line의 개수.

예:

```text
1.1 Motivation ............ 7
2.3 Markov Chains ........ 87
```

이 feature는 TOC page detection에서 가장 중요한 objective feature 중 하나다.

---

#### 5. `line_final_number_monotonicity`

line-final number들만 모아서 almost monotonically increasing한지 측정한다.

예:

```text
3, 7, 14, 25, 31, 44
```

TOC page에서는 이 숫자들이 대체로 증가한다.

중요한 점:

* page 내부의 모든 숫자를 쓰지 않는다.
* line 끝에 있는 숫자만 사용한다.
* chapter number, section number, equation number, year 등을 최대한 배제한다.

---

#### 6. `line_final_number_gap_stats`

line-final number sequence의 gap 통계.

예:

```text
numbers = 3, 7, 14, 25, 31, 44
gaps = 4, 7, 11, 6, 13
```

사용 가능한 값:

```text
mean gap
median gap
max gap
number of negative gaps
```

---

#### 7. `page_position`

PDF 내 page 위치.

예:

```text
page_position = current_page / total_pages
```

TOC는 보통 앞부분에 있으므로 유용하다.
다만 이 feature만으로 판단하지 않고 ML model이 다른 feature와 함께 학습하게 한다.

---

#### 8. `toc_keyword_presence`

`Contents`, `Table of Contents`, `목차`, `차례` 같은 keyword 존재 여부.

이 feature는 유용하지만 language-dependent하고 OCR 품질에 영향을 받으므로 weak feature로만 사용한다.

---

### 7.3 제외할 feature

초기 설계에서는 다음 feature를 핵심 feature로 쓰지 않는다.

```text
toc_like_line_ratio
dotted_leader_ratio
right_aligned_number_ratio
complex layout score
font score
```

이유:

* OCR text layer에서는 dot leader가 깨질 수 있다.
* scanned PDF에서는 right alignment 정보가 불안정할 수 있다.
* layout score는 PDF마다 편차가 크다.
* noisy feature가 많으면 작은 label set에서 overfitting될 수 있다.

---

### 7.4 ML-based scorer

fixed weight aggregate score는 사용하지 않는다.

대신 feature extraction만 deterministic하게 수행하고, 제한된 수동 label을 이용해 ML model을 fitting한다.

초기 모델 후보:

```text
DecisionTreeRegressor
RandomForestRegressor
HistGradientBoostingRegressor
```

데이터가 적을 때는 shallow tree 또는 random forest를 우선 사용한다.

---

### 7.5 Label과 loss

TOC page detector 학습에는 일부 PDF에 대한 수동 TOC page range label이 필요하다.

예:

```json
{
  "pdf": "book_a.pdf",
  "toc_start": 5,
  "toc_end": 7
}
```

기존 bookmark는 TOC page 위치를 알려주지 않기 때문에 TOC page detector 학습 label로 직접 사용할 수 없다.
bookmark-guided heuristic으로 복원한 TOC page range도 수동 검수 전에는 학습용 ground truth로 사용하지 않는다.
이런 range는 후보 생성, error discovery, manual labeling queue 구성에만 사용한다.

---

### 7.6 Page-level soft label regression

초기 학습 방식은 page-level soft label regression으로 한다.

GT TOC segment:

```text
pages 5-7
```

soft label:

```text
page 5: 1.0
page 6: 1.0
page 7: 1.0
page 4: 0.5
page 8: 0.5
page 3: 0.2
page 9: 0.2
others: 0.0
```

모델은 각 page가 TOC page일 가능성을 연속값으로 예측한다.

---

### 7.7 Segment-level IoU regression

이후에는 segment-level IoU regression으로 확장한다.

candidate segment:

```text
pages 5-6
```

GT segment:

```text
pages 5-7
```

target:

```text
IoU = overlap / union = 2 / 3 = 0.667
```

모델은 candidate segment의 predicted IoU를 예측한다.

최종 선택:

```text
여러 candidate TOC segments 중 predicted IoU가 가장 높은 segment를 선택한다.
```

---

### 7.8 Train / test split

page 단위 random split은 사용하지 않는다.

같은 책의 layout이 train과 test에 동시에 들어가면 leakage가 발생한다.

따라서 반드시 PDF 단위로 split한다.

```text
train: book A, book B, book C
test: book D, book E
```

권장 방식:

```text
GroupKFold by PDF
```

---

## 8. TOC item parsing 설계

TOC page가 탐지되면 line 단위로 TOC item을 파싱한다.

지원할 기본 패턴:

```text
Chapter 1 Introduction ........ 3
1. Introduction ............... 3
1.1 Motivation ................ 7
1.1.1 Details ................. 12
Appendix A .................... 251
A.1 Proofs .................... 255
```

추출 필드:

```text
title
level
printed_page
raw_text
source_pdf_page
confidence
```

level 추론 기준:

```text
Chapter 1        -> level 1
1 Introduction   -> level 1
1.1 Motivation   -> level 2
1.1.1 Details    -> level 3
Appendix A       -> level 1
A.1 Proofs       -> level 2
```

indentation은 보조 신호로만 사용한다.

---

## 9. Page offset estimation 설계

TOC의 printed page number와 실제 PDF page는 다를 수 있다.

따라서 본문 page에서 printed page number를 탐지해 offset을 추정한다.

예:

```text
PDF page 18 contains printed page number 1
PDF page 19 contains printed page number 2
PDF page 20 contains printed page number 3
```

offset:

```text
offset = PDF page - printed page
offset = 18 - 1 = 17
```

여러 evidence를 모아 가장 일관적인 offset을 선택한다.

출력:

```text
offset: 17
confidence: 0.96
evidence:
  - pdf_page: 18, printed_page: 1
  - pdf_page: 19, printed_page: 2
  - pdf_page: 20, printed_page: 3
```

offset 추정은 이 package의 핵심 heuristic 중 하나다.

---

## 10. Hybrid TOC-body alignment 설계

offset 기반 estimated page를 그대로 사용하지 않고, 반드시 본문 heading fuzzy search를 수행한다.

절차:

```text
1. TOC item의 printed page를 가져온다.
2. offset으로 estimated PDF page를 계산한다.
3. estimated page 주변 ±N pages를 search window로 설정한다.
4. 각 page의 상단 line / heading candidate를 추출한다.
5. TOC title과 candidate heading을 fuzzy match한다.
6. 가장 그럴듯한 page를 matched page로 선택한다.
7. confidence가 낮으면 LLM fallback 후보로 표시한다.
```

matching 요소:

```text
title similarity
numbering similarity
page distance from estimated page
line position on page
line length
heading-like pattern
```

최종 aligned item:

```text
title: 2.3 Markov Chains
level: 2
printed_page: 87
estimated_pdf_page: 104
matched_pdf_page: 105
confidence: 0.91
method: offset_plus_heading_match
```

---

## 11. Range calculation 설계

각 TOC item의 Markdown export range를 계산한다.

규칙:

* 같은 level의 다음 항목 또는 상위 level의 다음 항목이 나오기 전까지를 현재 항목의 범위로 본다.
* chapter-level `index.md`는 해당 chapter 전체를 포함할 수 있다.
* section-level file은 다음 section 또는 다음 chapter 전까지를 포함한다.

예:

```text
1 Introduction
  1.1 Motivation
  1.2 Background
2 Probability
  2.1 Random Variables
```

range:

```text
1 Introduction:
  start = page(1)
  end = page(2) - 1

1.1 Motivation:
  start = page(1.1)
  end = page(1.2) - 1

1.2 Background:
  start = page(1.2)
  end = page(2) - 1

2 Probability:
  start = page(2)
  end = book_end
```

---

## 12. PDF bookmark output 설계

bookmark insertion은 실제 PDF 파일에 반영되어야 한다.

기본 정책:

```text
input:
  book.pdf

output:
  book_bookmarked.pdf
```

원본 파일은 기본적으로 보존한다.
새 output 파일에는 `_bookmarked` suffix를 붙인다.

bookmark plan 예:

```text
level 1 | Chapter 1 Introduction | PDF page 19
level 2 | 1.1 Motivation         | PDF page 23
level 2 | 1.2 Background         | PDF page 31
level 1 | Chapter 2 Probability  | PDF page 42
```

이미 깔끔한 bookmark가 있는 PDF는 bookmark insertion 대상에서 제외한다.

---

## 13. Markdown export 설계

Markdown export는 TOC hierarchy를 directory structure로 반영한다.

예:

```text
book_markdown/
  metadata.json
  toc.json
  toc.md
  01_Introduction/
    index.md
    01_1_1_Motivation.md
    02_1_2_Background.md
  02_Probability/
    index.md
    01_2_1_Random_Variables.md
```

각 Markdown file에는 source metadata를 포함한다.

예:

```text
title: 2.3 Markov Chains
level: 2
pdf_start_page: 105
pdf_end_page: 119
printed_page: 87
alignment_confidence: 0.91
```

---

## 14. Evaluation 설계

기존 PDF bookmark가 있는 파일은 processing 대상이 아니라 generated bookmark 평가용 reference 후보이다.
다만 기존 bookmark는 gold label도 아니고, TOC page range ground truth도 아니다.
사용 목적을 다음처럼 분리한다.

```text
generated bookmark item/page 평가:
  기존 bookmark를 weak reference로 사용할 수 있다.

TOC page detector 학습/평가:
  수동 검수된 TOC start/end page만 ground truth로 사용한다.

bookmark-guided TOC page 복원:
  ground truth 생성이 아니라 manual review 후보 생성으로만 사용한다.
```

### 14.1 Item-level evaluation

정의:

```text
TP_item:
  prediction이 GT bookmark와 title / numbering / level 기준으로 matching됨

FP_item:
  prediction이 어떤 GT bookmark와도 matching되지 않음

FN_item:
  GT bookmark가 어떤 prediction과도 matching되지 않음

TN_item:
  기본적으로 정의하지 않음
```

지표:

```text
item precision
item recall
item F1
```

---

### 14.2 Page-level evaluation

item-level matching pair에 대해 page alignment를 평가한다.

지표:

```text
exact page accuracy
±1 page accuracy
±2 page accuracy
mean absolute page error
median absolute page error
```

분류:

```text
TP_page:
  item도 matching되고 page error가 tolerance 안에 있음

PageMismatch:
  item은 matching되었지만 page error가 tolerance 밖임

MissingPage:
  GT item을 찾지 못해 page prediction이 없음

ExtraPage:
  GT에 없는 item에 page를 예측함
```

---

### 14.3 Hierarchy evaluation

bookmark는 tree 구조이므로 hierarchy도 평가한다.

지표:

```text
level accuracy
parent match accuracy
optional tree edit distance
```

### 14.4 Existing bookmark 기반 TOC page 복원 feature

기존 bookmark가 있는 PDF는 처리 대상이 아니라 evaluation용 silver label이다.
이때 TOC page 위치를 사람이 전부 직접 지정하지 않도록, bookmark와 page text를 함께 사용해 TOC page 후보를 복원한다.

핵심 feature:

```text
bookmark title anchor density:
  한 page 안에 bookmark title과 fuzzy match되는 text window가 얼마나 많이 있는지 측정한다.

bookmark order density:
  match된 bookmark order가 page 안에서 얼마나 조밀하게 이어지는지 측정한다.

bookmark target offset consistency:
  page text에서 regex로 추출한 숫자들과 bookmark target PDF page의 offset이
  여러 bookmark 항목에서 얼마나 비슷하게 반복되는지 측정한다.
```

중요한 점:

* offset consistency는 line-final page number만 보지 않는다.
* TOC line 끝 숫자가 OCR/layout 때문에 깨질 수 있으므로 page text window 안의 standalone 숫자 후보도 함께 본다.
* chapter/section 번호처럼 noise가 섞일 수 있지만, 여러 bookmark 항목에서 같은 offset이 반복되면 강한 신호로 본다.
* 이 feature는 bookmark가 있는 PDF의 TOC page 후보 생성과 detector error discovery 보조용이다.
* bookmark가 없는 일반 처리 경로의 TOC detection primary feature로 사용하지 않는다.
* 수동 검수 없이 생성된 range는 ground truth로 저장하지 않는다.
* ML 학습에 사용할 경우 label_source에 `manual_reviewed` 같은 검수 상태를 반드시 포함한다.

현재 판단:

* 300study dataset의 bookmark-guided TOC page label을 랜덤 검수한 결과, 시작 page와 끝 page가 크게 틀린 사례가 다수 확인되었다.
* 특히 `Gilbert Strang - Introduction to Linear Algebra`는 기존 label이 2-80이었지만 실제 TOC는 3-4였고, `주식투자 무작정 따라하기`는 기존 label 7-13 대비 실제 TOC가 15-26이었다.
* 따라서 300study bookmark-guided dataset으로 학습한 tree classifier 결과는 폐기하거나 weak-label imitation 결과로 재해석해야 한다.

---

## 15. LLM fallback 설계

LLM fallback은 optional이다.

호출 조건:

```text
TOC detection confidence < threshold
TOC parsing confidence < threshold
offset confidence < threshold
heading match confidence < threshold
```

LLM에 보내는 입력은 항상 작게 제한한다.

가능한 입력:

```text
TOC page OCR text
TOC page image
특정 TOC item
estimated page 주변 3-5 page의 text
estimated page 주변 3-5 page의 image crop
```

LLM 출력은 반드시 validation을 거친다.

검증 절차:

```text
LLM output
→ JSON parse
→ schema validation
→ page range validation
→ monotonicity validation
→ heuristic result와 비교
→ accept / reject
```

---

## 16. Public interface 설계

이 package는 CLI뿐 아니라 Python library로도 사용 가능해야 한다.

구체적인 코드가 아니라, 사용 흐름은 다음과 같은 형태를 목표로 한다.

---

### 16.1 단일 PDF 처리 flow

```text
사용자는 Processor 객체를 생성한다.

Processor 설정:
  - input PDF path
  - output directory
  - use_llm 여부
  - skip_existing_bookmarks 여부
  - heading search window
  - confidence threshold

Processor 실행:
  - PDF를 분석한다.
  - 기존 bookmark가 깔끔하면 skip result를 반환한다.
  - bookmark가 없으면 TOC detection을 수행한다.
  - TOC item parsing을 수행한다.
  - page offset을 추정한다.
  - hybrid TOC-body alignment를 수행한다.
  - bookmark plan을 만든다.
  - *_bookmarked.pdf를 저장한다.
  - Markdown tree를 저장한다.
  - processing report를 반환한다.
```

반환 객체는 다음 정보를 포함해야 한다.

```text
status:
  processed / skipped / failed

input_pdf:
  원본 PDF path

output_pdf:
  생성된 *_bookmarked.pdf path

output_markdown_dir:
  Markdown export directory

toc_pages:
  탐지된 TOC page range

bookmark_count:
  생성된 bookmark item 수

confidence_summary:
  TOC detection confidence
  offset confidence
  alignment confidence

warnings:
  low-confidence items
  skipped items
  ambiguous matches
```

---

### 16.2 Batch processing flow

```text
사용자는 BatchProcessor 객체를 생성한다.

BatchProcessor 설정:
  - input directory
  - output directory
  - recursive 여부
  - skip_existing_bookmarks 여부
  - use_llm 여부

BatchProcessor 실행:
  - directory를 순회한다.
  - PDF별로 기존 bookmark 여부를 검사한다.
  - bookmark가 깔끔한 PDF는 skip하고 silver label 후보로 기록한다.
  - bookmark가 없는 PDF만 processing한다.
  - 전체 processing summary를 반환한다.
```

summary에는 다음이 포함된다.

```text
total_pdf_count
processed_count
skipped_existing_bookmark_count
failed_count
silver_label_candidate_count
created_bookmarked_pdf_paths
created_markdown_dirs
```

---

### 16.3 TOC detector training flow

```text
사용자는 TOC page label dataset을 준비한다.

Label format:
  - pdf path
  - toc_start_page
  - toc_end_page

Trainer 객체를 생성한다.

Trainer 실행:
  - 각 PDF에서 page-level objective feature를 추출한다.
  - page-level soft label을 만든다.
  - 또는 segment-level IoU target을 만든다.
  - PDF 단위 GroupKFold로 평가한다.
  - 학습된 model artifact를 저장한다.
```

반환 결과:

```text
trained_model_path
cross_validation_score
feature_importance
toc_detection_iou
start_page_error
end_page_error
```

---

### 16.4 Evaluation flow

```text
사용자는 기존 bookmark가 있는 PDF를 silver label로 사용한다.

Evaluator 실행:
  - 기존 bookmark를 GT로 읽는다.
  - model prediction 또는 generated bookmark plan을 읽는다.
  - item-level matching을 수행한다.
  - page-level error를 계산한다.
  - hierarchy metric을 계산한다.
  - evaluation report를 저장한다.
```

결과:

```text
item precision / recall / F1
page exact / ±1 / ±2 accuracy
mean absolute page error
level accuracy
parent accuracy
```

---

## 17. Dependency

### 17.1 Core runtime dependency

```text
pymupdf
rapidfuzz
numpy
scikit-learn
joblib
typer
rich
```

용도:

```text
pymupdf:
  PDF text extraction, existing bookmark extraction, bookmark insertion, PDF saving

rapidfuzz:
  TOC title과 body heading fuzzy matching

numpy:
  feature vector, page error, IoU, numeric calculation

scikit-learn:
  Decision tree / random forest / gradient boosting based TOC detector

joblib:
  trained model save / load

typer:
  CLI interface

rich:
  progress bar, logging, console summary
```

---

### 17.2 Development dependency

```text
pytest
ruff
```

용도:

```text
pytest:
  unit test, integration test

ruff:
  linting, formatting
```

---

### 17.3 Optional dependency

Evaluation / analysis:

```text
pandas
matplotlib
```

LLM fallback:

```text
openai
pillow
```

---

## 18. CLI requirements

### Single PDF processing

```text
pdfbooktree process book.pdf
```

기본 결과:

```text
book_bookmarked.pdf
book_markdown/
book_report.json
```

---

### Batch processing

```text
pdfbooktree batch ./pdfs
```

기본 동작:

```text
bookmark가 없는 PDF만 처리
bookmark가 깔끔한 PDF는 skip
skip된 PDF는 silver label 후보로 기록
```

---

### TOC detector training

```text
pdfbooktree train-toc-detector labels.json
```

입력:

```text
PDF path
TOC start page
TOC end page
```

출력:

```text
trained model artifact
training report
```

---

### Evaluation

```text
pdfbooktree evaluate book.pdf prediction.json
```

입력:

```text
기존 bookmark가 있는 PDF
prediction artifact
```

출력:

```text
eval_report.json
```

---

## 19. Development roadmap

### v0.1: Heuristic + offset + hybrid alignment MVP

목표:

```text
OCR text layer가 있는 PDF에서 TOC를 찾고, offset과 heading fuzzy search로 bookmark를 삽입한 *_bookmarked.pdf를 생성한다.
```

포함:

```text
PDF text extraction
existing bookmark detection
skip clean bookmarked PDF
objective TOC page feature extraction
heuristic TOC page detection
TOC item parsing
page offset estimation
local heading fuzzy verification
bookmark insertion
*_bookmarked.pdf saving
Markdown tree export
processing report
```

---

### v0.2: Evaluation module

목표:

```text
기존 bookmark가 있는 PDF를 silver label로 사용해 성능 평가를 수행한다.
```

포함:

```text
GT bookmark extraction
item-level matching
page-level evaluation
hierarchy evaluation
batch evaluation report
```

---

### v0.3: ML-based TOC page detector

목표:

```text
수동 검수된 TOC page range label만 사용해 objective feature 기반 ML scorer를 학습한다.
```

포함:

```text
manual TOC page range label format
manual review status tracking
page-level soft label regression
segment-level IoU regression
GroupKFold by PDF
model save/load
feature importance report
```

---

### v0.3b: Word box 기반 chapter heading discovery

목표:

```text
TOC page 탐지를 거치지 않고 page word/block 좌표에서 top-level chapter 시작 page와 title 후보를 찾는다.
```

포함:

```text
PyMuPDF word/block bbox extraction
page 상단 heading candidate extraction
font size, bbox 위치, whitespace, text length feature
layout pattern clustering
chapter start page candidate ranking
기존 bookmark와 수동 label 비교 report
top-level bookmark plan 생성 PoC
```

---

### v0.4: LLM fallback

목표:

```text
low-confidence case에 대해 LLM API로 cross-check / repair를 수행한다.
```

포함:

```text
LLM TOC repair
LLM candidate page selection
LLM output validation
LLM call logging
```

---

### v0.5: Robust alignment

목표:

```text
TOC-body full sequence alignment를 통해 더 다양한 textbook layout에 대응한다.
```

포함:

```text
full body heading candidate extraction
TOC-body sequence alignment
appendix handling
front matter handling
roman numeral page support
```

---

## 20. 성공 기준

### 기능적 성공 기준

```text
OCR text layer가 있는 PDF에서 TOC page를 자동 탐지한다.
TOC item을 title / level / printed page 구조로 추출한다.
page offset을 추정한다.
offset 주변 heading fuzzy search로 bookmark page를 확정한다.
*_bookmarked.pdf를 생성한다.
Markdown tree를 생성한다.
기존 bookmark가 있는 PDF는 skip한다.
기존 bookmark를 generated bookmark 평가용 weak reference로 사용한다.
수동 검수된 TOC page label만 detector ground truth로 사용한다.
word box 좌표 기반으로 chapter-level bookmark 후보를 생성하는 fallback 경로를 실험한다.
```

---

### 초기 성능 목표

```text
TOC page detection segment IoU: 0.8 이상
item-level F1: 0.85 이상
page ±1 accuracy: 0.9 이상
hierarchy level accuracy: 0.9 이상
```

기존 bookmark는 gold label이 아니라 weak reference이므로 strict / relaxed evaluation mode를 구분한다.
TOC page detector 성능 목표는 수동 검수 label에서만 계산한다.

---

## 21. 최종 요약

`pdfbooktree`는 OCR text layer가 있는 scanned textbook PDF를 구조화하기 위한 Python package다.

핵심 문제는 다음이다.

```text
Table of Contents 항목을 실제 PDF page에 align하고,
이를 바탕으로 PDF bookmark와 Markdown hierarchy를 생성하는 것.
```

최종 기본 알고리즘은 다음으로 결정한다.

```text
TOC-first page offset estimation
→ hybrid TOC-body alignment
→ local heading fuzzy verification
→ bookmark insertion
→ Markdown export
```

기존 bookmark가 있는 PDF는 처리하지 않고 skip한다.
다만 기존 bookmark는 generated bookmark 평가용 weak reference일 뿐이며, TOC page ground truth로 직접 사용하지 않는다.

TOC page detection은 지나치게 noisy한 handcrafted score를 쓰지 않는다. 대신 line count, word count, line-final number count, line-final number monotonicity 같은 objective feature를 추출하고, 수동 검수된 label을 이용해 decision tree / random forest 계열 모델로 확장한다.

300study 검수 결과 bookmark-guided TOC label이 ground truth로 쓰기에는 매우 부정확하다는 점이 확인되었다.
따라서 TOC-first 접근만 고집하지 않고, word / block box 좌표를 활용해 본문 chapter heading을 직접 찾는 unsupervised bookmark 생성 접근을 별도 실험 축으로 둔다.

LLM API는 primary engine이 아니라 low-confidence case의 backup으로만 사용한다.
