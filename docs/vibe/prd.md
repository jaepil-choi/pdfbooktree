# PRD: `pdfbooktree`

## 1. 배경

`pdfbooktree`는 scanned PDF book에서 PDF bookmark와 Markdown tree를 자동 생성하는 Python library다.

이 프로젝트가 다루는 핵심 문제는 다음 두 가지다.

1. PDF 내부에서 Table of Contents page range를 찾는다.
2. 찾은 TOC page에서 hierarchical bookmark tree를 복원한다.

입력 PDF는 다음 두 부류를 모두 고려한다.

- 기존 bookmark가 있는 PDF
- 기존 bookmark가 없는 scanned PDF

기존 bookmark가 있는 PDF는 runtime 처리 대상이라기보다 학습과 평가를 위한 answer reference로 사용한다.
단, 여기서 answer reference인 것은 bookmark tree의 title, target PDF page, hierarchy level이다.
bookmark를 이용해 역추정한 TOC page range는 정답이 아니라 pseudo label이다.
기존 bookmark가 없는 scanned PDF는 최종 runtime 대상이다.

이 프로젝트는 experiment driven development 방식으로 진행한다.
따라서 PRD는 곧바로 production 구현을 고정하는 문서가 아니라, 실험에서 검증할 알고리즘 축과 그 결과를 library 설계로 승격시키는 기준을 정의한다.

---

## 2. 제품 목표

`pdfbooktree`의 목표는 PDF book을 입력받아 다음 산출물을 만드는 것이다.

```text
input:
  book.pdf

output:
  book_bookmarked.pdf
  book_markdown/
  book_report.json
```

최종 출력은 단순 JSON이 아니라 실제 bookmark가 삽입된 PDF 파일이어야 한다.

생성해야 하는 구조는 다음과 같다.

```text
Bookmark tree:
  Chapter 1 Introduction -> PDF page 17
    1.1 Motivation -> PDF page 19
    1.2 Background -> PDF page 27
  Chapter 2 Probability -> PDF page 43
```

Markdown export는 bookmark hierarchy를 directory tree로 반영한다.

---

## 3. 핵심 알고리즘 방향

이 프로젝트의 핵심 알고리즘은 크게 두 단계로 나눈다.

```text
PDF
→ TOC page detection
→ TOC pages to TOC extraction
→ page alignment
→ bookmark insertion
→ Markdown export
```

현재 설계의 중심은 다음이다.

1. **TOC page detection**
   - 기존 bookmark가 있는 PDF에서 TOC page pseudo label을 복원한다.
   - pseudo label과 random non-TOC page를 1:1로 섞어 balanced page dataset을 만든다.
   - per-page feature로 ML model을 학습한다.
   - 학습된 model을 bookmark 없는 scanned PDF에 적용해 TOC page를 추론한다.

2. **TOC pages to TOC extraction**
   - LLM-driven extraction을 우선 실험 축으로 둔다.
   - 먼저 TOC page가 1-pane인지 2-pane인지 판정한다.
   - pane-adjusted reading order와 pane-adjusted feature를 LLM에 제공해 hierarchical bookmark item을 추출한다.
   - 별도 LLM 또는 deterministic validator로 추출 결과를 검증한다.
   - 이후 ML/DL-driven extraction을 별도 연구 축으로 확장한다.

---

## 4. 범위

### 4.1 포함

다음 기능은 project scope에 포함한다.

- PDF text, word, block, layout feature 추출
- 기존 bookmark 추출
- 기존 bookmark 기반 TOC page pseudo label 생성
- TOC page feature dataset 생성
- TOC page classifier 학습
- bookmark 없는 scanned PDF의 TOC page inference
- TOC page 1-pane / 2-pane 판정
- pane-adjusted text order 생성
- TOC item title / level / printed page 추출
- 추출된 TOC item validation
- printed page와 PDF page alignment
- PDF bookmark 삽입
- Markdown directory export
- 모든 중간 artifact 저장

### 4.2 제외

다음 기능은 기본 scope에서 제외한다.

- OCR text layer 자체를 PDF에 새로 입히는 기능
- 수식 LaTeX 복원
- table / figure 구조화 추출
- 기존 bookmark가 있는 PDF를 runtime에서 기본적으로 다시 bookmark하는 기능

단, 실험 단계에서 외부 Document Parse 또는 OCR API를 feature source로 사용하는 것은 허용한다.
이 경우 목적은 OCR layer를 생성하는 것이 아니라 TOC detection/extraction에 필요한 text, word box, html/category feature를 얻는 것이다.

---

## 5. Page Number Convention

library public interface와 저장 artifact는 모두 1-based PDF page number를 사용한다.

이유:

- 사용자가 보는 PDF page와 자연스럽게 대응된다.
- TOC printed page number도 1-based다.
- bookmark 삽입과 report 해석에서 off-by-one 오류를 줄인다.

예:

```json
{
  "pdf_page": 105,
  "printed_page": 87,
  "title": "2.3 Markov Chains"
}
```

내부 라이브러리가 사용하는 PDF engine이 0-based page index를 요구하더라도, public object와 intermediate artifact에는 1-based 값을 기록한다.

---

## 6. 기존 Bookmark와 TOC Page Label의 역할

기존 bookmark와 bookmark-guided TOC page label은 서로 다르게 취급한다.

bookmark-embedded PDF에서 기존 bookmark tree는 다음 항목의 answer reference로 사용한다.

- chapter / section title
- target PDF page
- hierarchy level

즉, TOC extraction과 page alignment, hierarchy evaluation에서는 기존 bookmark를 정답 기준으로 볼 수 있다.
다만 PDF 제작 도구나 출판사 bookmark 자체에 오류가 있을 수 있으므로, report에는 reference source와 matching confidence를 함께 남긴다.

반대로 기존 bookmark가 직접 알려주지 않는 것은 다음이다.

- PDF 내부 TOC page의 위치
- TOC page range의 정확한 시작과 끝
- TOC page text의 실제 reading order
- TOC page에 표시된 printed page number의 OCR 품질

따라서 bookmark를 page text와 matching해 복원한 TOC page range는 ground truth가 아니라 pseudo label이다.

정리하면 다음과 같다.

```text
기존 bookmark tree:
  title / target PDF page / hierarchy level의 answer reference

bookmark-guided TOC page range:
  TOC page detector 학습 후보로 쓰는 pseudo label
```

기존 bookmark는 다음 용도로 사용한다.

```text
1. TOC page pseudo label 후보 생성
2. TOC extraction 결과의 title/page/hierarchy 평가
3. page alignment 결과 평가
4. generated bookmark와 answer bookmark tree 비교
```

bookmark-guided TOC page range는 다음 용도로 사용하지 않는다.

```text
1. 검수 없는 TOC page ground truth
2. 검수 없는 TOC page detector test label
3. runtime 대상 PDF의 입력 조건
```

300study manual audit 결과, bookmark-guided TOC page label은 크게 틀릴 수 있음이 확인되었다.
따라서 bookmark-guided TOC page label은 반드시 `label_source`, `confidence`, `detector_version`, `audit_status`를 함께 저장한다.

---

## 7. 전체 Pipeline

### 7.1 Training / Experiment Pipeline

기존 bookmark가 있는 PDF를 사용해 TOC page detector와 TOC extraction 방식을 연구한다.

```text
bookmarked PDFs
→ bookmark tree quality filter
→ bookmark title/page/hierarchy extraction
→ bookmark-guided TOC page candidate detection
→ pseudo label confidence scoring
→ manual audit queue
→ clean or pseudo-clean TOC page label set
→ per-page feature extraction
→ balanced page dataset
→ ML TOC page classifier training
→ held-out PDF evaluation
```

이 pipeline의 목적은 runtime을 직접 처리하는 것이 아니라 detector와 extractor를 설계하는 것이다.

### 7.2 Runtime Pipeline

bookmark 없는 scanned PDF를 처리한다.

```text
PDF input
→ existing bookmark check
→ TOC page feature extraction
→ ML TOC page inference
→ TOC range smoothing
→ TOC page pane classification
→ pane-adjusted text/feature construction
→ TOC item extraction
→ TOC item validation
→ printed page to PDF page alignment
→ bookmark plan generation
→ bookmarked PDF save
→ Markdown export
→ report save
```

기존 bookmark가 있는 PDF는 기본 runtime에서 skip한다.
강제 재처리 옵션은 MVP 이후 기능으로 둔다.

---

## 8. TOC Page Detection

### 8.1 목표

PDF 앞부분에서 TOC page range를 찾는다.

예:

```text
TOC pages = 7-16
```

TOC는 한 page일 수도 있고 여러 page일 수도 있다.
runtime detector는 page-level probability와 최종 contiguous range를 모두 제공해야 한다.

### 8.2 Bookmark-embedded PDF에서 pseudo label 만들기

기존 bookmark가 있는 PDF에서는 answer bookmark tree를 기준으로 page text를 탐색해 TOC page 후보를 찾는다.

사용할 수 있는 신호:

- bookmark title이 page text에 밀집해 등장하는 정도
- bookmark title 등장 순서가 bookmark order와 일치하는 정도
- page text 안의 page number 후보와 bookmark target page 사이 offset이 일관적인 정도
- TOC-like line-final number sequence
- Contents / Table of Contents / 목차 / 차례 같은 lexical anchor
- page range가 앞부분에 위치하는 정도

중요한 정책:

- 이 결과는 pseudo label이다.
- confidence가 낮으면 학습에 사용하지 않는다.
- 수동 검수 또는 별도 quality gate를 통과한 label만 detector evaluation에 사용한다.

### 8.3 Per-page Feature Dataset

TOC page detector 학습을 위해 page 단위 dataset을 만든다.

positive sample:

```text
pseudo-clean 또는 manual audited TOC page
```

negative sample:

```text
같은 PDF 또는 다른 PDF에서 뽑은 non-TOC page
```

초기 dataset은 positive와 negative를 1:1로 섞어 balanced dataset으로 만든다.

negative sampling은 두 단계로 둔다.

1. random negative
2. hard negative

hard negative 후보:

- front matter page
- chapter start page
- index page
- bibliography page
- dense table page
- page number가 많이 등장하는 exercise page
- list of figures / list of tables

### 8.4 Feature Source

feature source는 pluggable해야 한다.

지원 후보:

```text
fitz_text:
  PyMuPDF text extraction 기반 line/text feature

fitz_geometry:
  PyMuPDF word/block bbox 기반 layout feature

document_parse_text:
  외부 Document Parse text output

document_parse_html:
  html tag, font-size, element boundary, category feature

document_parse_words:
  word box coordinate 기반 line reconstruction

hybrid:
  fitz geometry와 Document Parse text/page-number 신호를 결합
```

모든 feature row에는 `feature_source`와 `feature_version`을 기록한다.

### 8.5 Page-level Features

초기 feature는 다음을 포함한다.

텍스트 통계:

- `line_count`
- `word_count`
- `mean_line_length`
- `line_length_std`
- `short_line_ratio`

TOC 숫자 신호:

- `line_final_number_count`
- `line_final_number_ratio`
- `line_final_number_monotonicity`
- `line_final_number_gap_mean`
- `line_final_number_gap_median`
- `trailing_page_ratio`
- `numbering_any_ratio`

lexical 신호:

- `toc_keyword_presence`
- `contents_keyword_presence`
- `index_keyword_presence`

layout / parse 신호:

- `category_index_ratio`
- `category_table_ratio`
- `category_footer_ratio`
- `line_index_ratio`
- `paragraph_ratio`
- `element_count`
- `mean_element_line_count`
- `font_tier_count`
- `indent_tier_count`
- `pane_balance_score`
- `gutter_score`

page context:

- `page_position`
- `prev_page_feature_delta`
- `next_page_feature_delta`

### 8.6 ML Model

TOC page detector의 기본 학습 문제는 page-level binary classification이다.

출력:

```text
P(is_toc_page | page_features)
```

초기 후보 모델:

- Logistic Regression
- Random Forest
- HistGradientBoosting
- LightGBM 또는 CatBoost

데이터가 작을 때는 shallow tree와 logistic baseline을 반드시 같이 둔다.
고성능 모델만 보지 않고 feature leakage와 PDF layout memorization을 확인한다.

### 8.7 Train / Test Split

page 단위 random split은 금지한다.

같은 PDF의 page가 train과 test에 동시에 들어가면 layout leakage가 발생한다.

split 기준:

```text
GroupKFold by PDF
```

평가 지표:

- page-level ROC-AUC
- average precision
- precision / recall / F1
- range-level IoU
- start page error
- end page error

### 8.8 Range Smoothing

classifier는 page probability를 낸다.
runtime에는 contiguous TOC range가 필요하다.

따라서 후처리 단계가 필요하다.

후처리 후보:

- threshold 기반 contiguous segment 선택
- hysteresis threshold
- max segment score
- segment length prior
- 앞부분 page prior
- HMM/CRF 스타일 smoothing

최종 output:

```json
{
  "toc_pages": [7, 8, 9, 10],
  "start_page": 7,
  "end_page": 10,
  "page_scores": [
    {"pdf_page": 7, "toc_probability": 0.98},
    {"pdf_page": 8, "toc_probability": 0.96}
  ],
  "confidence": 0.93,
  "method": "ml_classifier_v1+hysteresis"
}
```

---

## 9. TOC Pages to TOC Extraction

### 9.1 목표

탐지된 TOC page에서 hierarchical bookmark item을 추출한다.

입력:

```text
TOC pages = 7-16
```

출력:

```json
[
  {
    "title": "Chapter 1 Introduction",
    "level": 1,
    "printed_page": 3,
    "source_pdf_page": 7,
    "confidence": 0.94
  },
  {
    "title": "1.1 Motivation",
    "level": 2,
    "printed_page": 7,
    "source_pdf_page": 7,
    "confidence": 0.91
  }
]
```

### 9.2 Pane Classification

TOC extraction 전에 page 또는 range가 1-pane인지 2-pane인지 판정한다.

이유:

- 2-pane TOC를 일반 y-order로 읽으면 왼쪽과 오른쪽 column 항목이 섞인다.
- 잘못된 reading order는 hierarchy와 printed page monotonicity를 망가뜨린다.

판정 방식 후보:

1. deterministic feature
   - page 중앙 gutter
   - 좌우 content balance
   - gutter straddle ratio
   - word box x distribution

2. LLM A/B 판정
   - A: page 전체를 한 단으로 읽은 markdown
   - B: 좌우 pane으로 나누어 왼쪽 먼저, 오른쪽 나중에 읽은 markdown
   - LLM이 더 자연스러운 reading order를 선택한다.

판정 output:

```json
{
  "pdf_page": 7,
  "pane_count": 2,
  "reading_order": "left_then_right",
  "confidence": 0.89,
  "evidence": {
    "gutter_score": 0.81,
    "left_right_balance": 0.74
  }
}
```

### 9.3 Pane-adjusted Feature Table

TOC extraction 입력은 raw text만 주지 않는다.
pane-adjusted text와 pane-adjusted feature를 함께 만든다.

line feature 후보:

- `source_pdf_page`
- `pane_id`
- `line_order`
- `raw_text`
- `normalized_text`
- `x0`
- `x1`
- `y0`
- `y1`
- `pane_local_x0`
- `pane_indent_tier`
- `font_tier`
- `category`
- `element_id`
- `element_position`
- `numbering_depth`
- `trailing_page`
- `prev_line_delta_y`
- `next_line_delta_y`

이 feature table은 LLM-driven extraction과 ML/DL-driven extraction이 공유하는 중간 표현이다.

### 9.4 LLM-driven Extraction

LLM-driven extraction은 이 프로젝트의 핵심 실험 축이다.

단계:

```text
1. pane classification
2. pane-adjusted reading order 생성
3. pane-adjusted line feature table 생성
4. LLM에게 text + feature를 제공
5. title / level / printed_page 구조화 출력
6. validation call 또는 deterministic validator로 결과 검증
```

LLM에게 제공하는 정보:

- pane-adjusted line order
- line text
- source page
- pane id
- indent tier
- font tier
- numbering depth
- trailing page 후보
- category / element hint

LLM은 다음 역할을 한다.

- 여러 line에 걸친 item 병합
- 깨진 OCR title 복원
- title과 printed page 분리
- hierarchical level 추론
- appendix, part, chapter, section 등 semantic cue 반영

LLM output schema:

```json
{
  "items": [
    {
      "title": "Chapter 1 Introduction",
      "level": 1,
      "printed_page": 3,
      "source_lines": [12, 13],
      "source_pdf_page": 7,
      "confidence": 0.94
    }
  ],
  "warnings": []
}
```

### 9.5 LLM Validation

추출 LLM의 결과는 바로 bookmark로 쓰지 않는다.
별도 validator를 통과해야 한다.

validator는 LLM일 수도 있고 deterministic rule일 수도 있다.
초기에는 둘을 모두 실험한다.

검증 항목:

- JSON schema validity
- source line coverage
- duplicate item 여부
- printed page monotonicity
- level jump 여부
- parent 없는 child 여부
- title이 너무 짧거나 숫자뿐인지 여부
- TOC page text에 title 근거가 있는지 여부
- printed page가 PDF page로 align 가능한지 여부

validator output:

```json
{
  "status": "accepted",
  "confidence": 0.88,
  "issues": [],
  "repair_suggestions": []
}
```

가능한 status:

```text
accepted
accepted_with_warnings
needs_repair
manual_review
failed
```

### 9.6 ML/DL-driven Extraction

ML/DL-driven extraction은 LLM-driven extraction 이후의 연구 축이다.

목표:

```text
extracted feature + text를 사용해 hierarchical bookmark tree를 직접 구성한다.
```

문제는 다음 하위 task로 나눌 수 있다.

1. line이 TOC item인지 분류한다.
2. 여러 line이 하나의 item인지 segment한다.
3. title span과 printed page span을 분리한다.
4. item level을 예측한다.
5. item sequence를 tree로 변환한다.

학습 label 후보:

- 기존 bookmark와 TOC line fuzzy match로 만든 weak label
- manual audited TOC item label
- LLM extraction 결과 중 validator를 통과한 self-training label

중요한 연구 질문:

```text
eval metric을 loss로 그대로 쓰지 않는다.
ML/DL model이 학습하기 좋은 proper loss를 설계해야 한다.
```

loss 후보:

- line item binary cross entropy
- BIO sequence tagging loss
- title span / page span token classification loss
- level classification loss
- level transition penalty
- parent-before-child constraint loss
- printed page monotonicity penalty
- differentiable tree edit distance surrogate
- contrastive loss for title/bookmark matching

초기 목표는 production 승격이 아니라 small clean dataset에서 overfit 가능한지 확인하는 것이다.

---

## 10. Page Alignment

TOC item의 `printed_page`는 실제 PDF page와 다를 수 있다.
따라서 offset을 추정한다.

예:

```text
printed page 1 = PDF page 18
offset = 17

TOC item printed page 87
→ estimated PDF page 104
```

offset 추정 신호:

- 본문 footer/header의 printed page number
- TOC item의 printed page sequence
- 기존 bookmark answer reference가 있는 실험 PDF의 target page
- estimated page 주변 heading title fuzzy match

runtime에서는 기존 bookmark를 사용할 수 없으므로, printed page number와 body heading matching을 우선 사용한다.

alignment output:

```json
{
  "title": "2.3 Markov Chains",
  "printed_page": 87,
  "estimated_pdf_page": 104,
  "matched_pdf_page": 105,
  "alignment_method": "offset+heading_fuzzy",
  "confidence": 0.91
}
```

---

## 11. Bookmark Generation

validated TOC item과 aligned page를 사용해 bookmark plan을 만든다.

bookmark plan:

```json
[
  {
    "title": "Chapter 1 Introduction",
    "level": 1,
    "pdf_page": 17
  },
  {
    "title": "1.1 Motivation",
    "level": 2,
    "pdf_page": 19
  }
]
```

PDF output은 원본을 직접 덮어쓰지 않는다.

```text
book.pdf
→ book_bookmarked.pdf
```

bookmark insertion 이후에는 roundtrip 검증을 수행한다.

검증 항목:

- bookmark count
- level sequence
- target page range
- output PDF open 가능 여부
- 원본 page count 유지 여부

---

## 12. Markdown Export

Markdown export는 bookmark hierarchy를 directory tree로 변환한다.

예:

```text
book_markdown/
  metadata.json
  toc.json
  toc.md
  01_Chapter_1_Introduction/
    index.md
    01_1_1_Motivation.md
    02_1_2_Background.md
```

각 Markdown file에는 source metadata를 포함한다.

```text
title: 1.1 Motivation
level: 2
pdf_start_page: 19
pdf_end_page: 26
printed_page: 7
alignment_confidence: 0.91
```

본문 text extraction 품질이 낮으면 Markdown export는 warning을 기록하고 가능한 범위만 저장한다.

---

## 13. Intermediate Artifacts

모든 단계는 재현 가능한 artifact를 저장한다.

예:

```text
existing_bookmarks.json
bookmark_quality_report.json
toc_page_candidates.json
toc_page_labels.json
page_features.csv
toc_page_model_report.json
toc_page_predictions.json
toc_range.json
pane_classification.json
pane_adjusted_lines.csv
toc_items_raw.json
toc_items_validated.json
page_alignment.json
bookmark_plan.json
bookmark_roundtrip_report.json
markdown_export_log.json
book_report.json
```

artifact에는 최소한 다음 metadata를 포함한다.

- input PDF path
- page number convention
- feature source
- model version
- prompt version
- detector version
- created_at
- confidence
- warning

---

## 14. Evaluation

### 14.1 TOC Page Detection Evaluation

TOC page detector 평가는 manual audited label 또는 confidence gate를 통과한 pseudo-clean label에서만 수행한다.

지표:

- page precision
- page recall
- page F1
- range IoU
- start page error
- end page error
- false positive page count
- false negative page count

기존 bookmark-guided range를 수동 검수 없이 GT로 쓰지 않는다.

### 14.2 TOC Item Extraction Evaluation

bookmark가 있는 PDF에서는 generated TOC item을 기존 bookmark answer reference와 비교할 수 있다.

지표:

- title match rate
- item precision
- item recall
- item F1
- printed page extraction accuracy
- source line coverage

title matching은 exact match뿐 아니라 normalized fuzzy match를 같이 기록한다.

### 14.3 Page Alignment Evaluation

item title이 match된 pair에 대해 page alignment를 평가한다.

지표:

- exact page accuracy
- ±1 page accuracy
- ±2 page accuracy
- mean absolute page error
- median absolute page error
- missing page count

### 14.4 Hierarchy Evaluation

hierarchy는 level과 parent relation을 모두 본다.

지표:

- absolute level accuracy
- relative depth transition accuracy
- parent match accuracy
- tree edit distance

기존 bookmark의 hierarchy는 answer reference로 사용한다.
다만 bookmark 자체가 잘못 제작된 예외 사례를 추적하기 위해 reference source와 manual override 여부를 구분한다.

### 14.5 End-to-end Evaluation

최종 end-to-end 평가는 다음을 모두 포함한다.

- TOC range 탐지 성공 여부
- TOC item 추출 품질
- page alignment 품질
- hierarchy 품질
- bookmark 삽입 성공 여부
- Markdown export 성공 여부
- cost / latency
- manual review 필요 비율

---

## 15. Public Interface

### 15.1 단일 PDF 처리

사용 흐름:

```python
from pdfbooktree import Processor

processor = Processor(
    input_pdf="book.pdf",
    output_dir="outputs/book",
    use_llm=True,
    skip_existing_bookmarks=True,
)

result = processor.run()
```

반환 객체:

```text
status:
  processed / skipped / failed / manual_review_required

input_pdf
output_pdf
output_markdown_dir
toc_pages
bookmark_count
confidence_summary
warnings
artifact_paths
```

### 15.2 Batch Processing

사용 흐름:

```python
from pdfbooktree import BatchProcessor

batch = BatchProcessor(
    input_dir="pdfs",
    output_dir="outputs",
    recursive=True,
    use_llm=False,
)

summary = batch.run()
```

summary:

```text
total_pdf_count
processed_count
skipped_existing_bookmark_count
failed_count
manual_review_required_count
created_bookmarked_pdf_paths
created_markdown_dirs
```

### 15.3 Dataset Builder

TOC page detector 학습용 dataset을 만든다.

```python
from pdfbooktree.training import TocPageDatasetBuilder

builder = TocPageDatasetBuilder(
    pdf_paths=[...],
    output_path="toc_page_dataset.parquet",
)

dataset = builder.build()
```

dataset row:

```text
pdf_id
pdf_path
pdf_page
is_toc_page
label_source
label_confidence
audit_status
feature_source
features...
```

### 15.4 Trainer

```python
from pdfbooktree.training import TocPageTrainer

trainer = TocPageTrainer(
    dataset_path="toc_page_dataset.parquet",
    model_type="lightgbm",
)

report = trainer.train_group_kfold()
```

결과:

```text
trained_model_path
cv_report
feature_importance
range_iou_report
```

### 15.5 Evaluator

```python
from pdfbooktree.evaluation import Evaluator

evaluator = Evaluator(
    reference_pdf="book_with_bookmarks.pdf",
    prediction_path="bookmark_plan.json",
)

report = evaluator.run()
```

---

## 16. CLI

단일 PDF 처리:

```powershell
uv run pdfbooktree process book.pdf --output outputs/book
```

batch 처리:

```powershell
uv run pdfbooktree batch .\pdfs --output .\outputs
```

TOC page dataset 생성:

```powershell
uv run pdfbooktree build-toc-page-dataset .\pdfs --output .\outputs\toc_page_dataset.parquet
```

TOC page detector 학습:

```powershell
uv run pdfbooktree train-toc-page-detector .\outputs\toc_page_dataset.parquet
```

평가:

```powershell
uv run pdfbooktree evaluate .\book_with_bookmarks.pdf .\prediction\bookmark_plan.json
```

---

## 17. Dependency

### 17.1 Core

```text
pymupdf
rapidfuzz
numpy
scikit-learn
joblib
typer
rich
```

### 17.2 Data / Experiment

```text
pandas
matplotlib
pyarrow
```

### 17.3 Optional ML

```text
lightgbm
catboost
```

### 17.4 Optional LLM / Parse Provider

```text
openai
pillow
```

provider-specific SDK는 core dependency에 넣지 않고 adapter 또는 optional extra로 둔다.
LLM과 Document Parse 호출은 반드시 provider, model, prompt version, input hash, output hash를 artifact에 기록한다.

---

## 18. Experiment Roadmap

### 18.1 TOC Page Detection

다음 실험을 우선 진행한다.

```text
052_bookmark_to_toc_label_quality_benchmark
053_pseudo_label_confidence_filter
054_manual_audit_queue_for_toc_ranges
055_parse_page_feature_dataset_v1
056_negative_sampling_strategy
057_toc_page_classifier_v2
058_toc_range_sequence_smoothing
059_scanned_no_bookmark_toc_detection_eval
060_feature_source_cost_ablation
```

목표:

- bookmark-guided TOC label의 신뢰 조건을 찾는다.
- balanced page dataset을 만든다.
- runtime-compatible ML detector를 학습한다.
- bookmark 없는 scanned PDF에서 TOC page를 찾는다.

### 18.2 Pane-aware TOC Extraction

다음 실험을 진행한다.

```text
061_pane_classifier_generalization
062_pane_adjusted_line_order_quality
063_minimal_feature_table_multibook
064_llm_pane_adjusted_toc_extraction
065_llm_bookmark_validation_pass
066_llm_extraction_prompt_ablation
```

목표:

- 1-pane / 2-pane 판정을 일반화한다.
- pane-adjusted reading order가 실제 TOC item 순서를 보존하는지 검증한다.
- LLM이 pane-adjusted text와 feature를 이용해 bookmark tree를 추출할 수 있는지 확인한다.
- validation call이 오류를 줄이는지 확인한다.

### 18.3 ML/DL TOC Extraction

다음 실험을 연구 축으로 둔다.

```text
067_toc_line_label_dataset_from_bookmarks
068_toc_line_sequence_tagging_baseline
069_hierarchy_loss_design_probe
070_neural_toc_parser_smallset_overfit
```

목표:

- line-level weak label dataset을 만든다.
- sequence tagging baseline을 만든다.
- hierarchy-aware loss 후보를 검증한다.
- 작은 clean set에서 neural parser가 overfit 가능한지 확인한다.

### 18.4 End-to-end

다음 실험을 진행한다.

```text
071_detection_to_extraction_end_to_end_v2
072_public_api_shape_showcase_precheck
```

목표:

- detector, pane classifier, extractor, validator, alignment, bookmark insertion을 하나의 flow로 연결한다.
- public API에 필요한 object shape를 확정한다.

---

## 19. Development Roadmap

### v0.1: Experiment-backed TOC Page Detector

포함:

- bookmark quality filter
- pseudo label confidence scoring
- page feature dataset builder
- balanced dataset generation
- ML page classifier
- range smoothing
- detector report

### v0.2: Pane-aware LLM TOC Extractor

포함:

- pane classifier
- pane-adjusted line reconstruction
- minimal feature table
- LLM structured extraction
- LLM/deterministic validation
- extraction report

### v0.3: Page Alignment and Bookmark Output

포함:

- printed page offset estimation
- heading fuzzy grounding
- bookmark plan generation
- PDF bookmark insertion
- bookmark roundtrip validation

### v0.4: Markdown Export and Batch Runtime

포함:

- Markdown tree export
- batch processor
- runtime report
- skipped existing bookmark report

### v0.5: ML/DL Extraction Research

포함:

- line-level dataset
- sequence tagging baseline
- hierarchy-aware loss experiments
- neural parser overfit probe

---

## 20. Success Criteria

### 20.1 TOC Page Detection

수동 검수 label 또는 pseudo-clean label 기준:

```text
range IoU >= 0.8
page F1 >= 0.85
start page absolute error <= 1 median
end page absolute error <= 1 median
```

### 20.2 TOC Extraction

기존 bookmark answer reference 또는 manual item label 기준:

```text
item F1 >= 0.85
printed page extraction accuracy >= 0.9
hierarchy relative depth accuracy >= 0.85
```

### 20.3 Page Alignment

title matched item 기준:

```text
page ±1 accuracy >= 0.9
median absolute page error <= 1
```

### 20.4 Runtime Output

```text
_bookmarked.pdf 생성 성공
bookmark roundtrip 검증 성공
Markdown tree 생성 성공
book_report.json 생성 성공
모든 중간 artifact 저장
```

---

## 21. 최종 요약

`pdfbooktree`는 scanned PDF book에서 TOC page를 찾고, TOC page를 hierarchical bookmark tree로 변환해 실제 PDF bookmark와 Markdown directory를 생성하는 library다.

현재 구현 방향은 다음 순서다.

```text
1. 기존 bookmark가 있는 PDF에서 TOC page pseudo label 생성 알고리즘을 찾는다.
2. pseudo-clean TOC page와 random/hard negative page를 1:1로 섞어 balanced page dataset을 만든다.
3. per-page feature로 ML TOC page detector를 학습한다.
4. 학습된 detector를 bookmark 없는 scanned PDF에 적용한다.
5. 탐지된 TOC page를 1-pane / 2-pane으로 판정한다.
6. pane-adjusted order와 feature를 만들어 LLM이 hierarchical bookmark item을 추출한다.
7. 별도 validation 단계로 LLM output을 검증한다.
8. printed page를 PDF page에 align한다.
9. bookmark가 삽입된 PDF와 Markdown tree를 생성한다.
```

ML/DL-driven TOC extraction은 별도 연구 축이다.
이 축에서는 text와 feature로 hierarchical bookmark를 직접 구성하되, 단순 evaluation metric이 아니라 model이 학습하기 좋은 hierarchy-aware loss를 설계하는 것을 핵심 문제로 둔다.
