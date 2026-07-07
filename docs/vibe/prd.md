# PRD: `pdfbooktree`

## 1. 배경

`pdfbooktree`는 PDF book에서 구조화된 bookmark tree를 만들고, 그 결과를 PDF bookmark와 Markdown tree로 내보내는 Python library다.

초기 구상은 scanned PDF에서 Table of Contents page를 찾고, 그 TOC page를 parsing해서 bookmark를 복원하는 것이었다.
하지만 최근 실험에서 더 근본적인 병목이 확인되었다.

```text
garbage OCR text in
→ garbage TOC detection
→ garbage bookmark tree out
```

scanned PDF에 들어 있는 기존 OCR text layer가 깨져 있으면 다음 작업이 모두 불안정해진다.

- TOC page detection
- TOC item extraction
- book-wide font / height hierarchy inference
- heading title matching
- page alignment
- Markdown export

따라서 `pdfbooktree`는 bookmark 생성 library라는 정체성을 유지하되, supportive capability로 OCR / Document Parse 기반 searchable PDF 생성 기능을 제공한다.
이 기능은 core output 자체가 아니라 core 알고리즘이 신뢰할 수 있는 입력을 얻기 위한 전처리 단계다.

이 프로젝트는 experiment driven development 방식으로 진행한다.
PRD는 production 구현을 한 번에 고정하는 문서가 아니라, 실험에서 확인된 판단을 public interface와 roadmap으로 승격시키는 기준 문서다.

---

## 2. 제품 목표

`pdfbooktree`의 main goal은 PDF book을 입력받아 다음 산출물을 만드는 것이다.

```text
input:
  book.pdf

output:
  book_ocr.pdf              optional supportive output
  book_bookmarked.pdf       core output
  book_markdown/            core output
  book_report.json          core output
  artifacts/                reproducible intermediate artifacts
```

최종 core output은 단순 JSON이 아니라 실제 bookmark가 삽입된 PDF 파일이어야 한다.

생성해야 하는 bookmark tree 예시는 다음과 같다.

```text
Chapter 1 Introduction -> PDF page 17
  1.1 Motivation -> PDF page 19
  1.2 Background -> PDF page 27
Chapter 2 Probability -> PDF page 43
```

Markdown export는 bookmark hierarchy를 directory tree와 `toc.md`로 반영한다.

---

## 3. 제품 정체성

`pdfbooktree`의 core 기능은 다음이다.

1. book structure / heading hierarchy 추론
2. bookmark plan 생성
3. PDF bookmark embedding
4. Markdown tree 생성
5. 처리 결과와 중간 artifact 저장

`pdfbooktree`의 supportive 기능은 다음이다.

1. Upstage Document Parse 기반 text extraction
2. Document Parse 결과 cache 저장
3. scanned page image 위에 invisible text layer overlay
4. searchable OCR PDF 생성
5. overlay 결과 재추출 검증

OCR 기능은 중요한 기능이지만 제품의 목적지가 아니다.
OCR은 TOC detection, bookmark extraction, Markdown 생성이 GIGO에 빠지지 않도록 만드는 선행 조건이다.

---

## 4. 핵심 판단

현재 TOC / bookmark 복원 접근은 fundamentally different한 두 방법으로 나뉜다.

### 4.1 Approach A: TOC page를 찾지 않고 책 전체 hierarchy를 본다

```text
PDF or OCR PDF
→ whole-book line extraction
→ font size / bbox height tiering
→ page-level tier distribution
→ chapter / section heading candidate extraction
→ hierarchy inference
→ bookmark plan
```

이 접근은 책 전체에서 반복되는 시각적 계층을 이용한다.
예를 들어 본문은 작은 font tier에 몰리고, section heading은 중간 tier, chapter heading은 큰 tier에 몰린다.

최근 실험 결론은 다음이다.

- clean text / geometry가 있으면 computer에게는 이 접근이 더 효과적일 가능성이 높다.
- TOC page를 정확히 찾지 않아도 되므로 TOC page label noise에 덜 취약하다.
- 책마다 `font_size`가 더 좋은 경우와 `bbox height`가 더 좋은 경우가 달라서 둘 다 계산해야 한다.
- scanned OCR PDF에서는 수식 조각, 잘못 쪼개진 line, 깨진 reading order가 hierarchy inference를 망가뜨릴 수 있다.
- 따라서 OCR / parse 품질 확보가 선행되어야 한다.

이 접근을 현재 primary runtime strategy로 둔다.

### 4.2 Approach B: TOC page를 찾고 TOC item을 정밀 parsing한다

```text
PDF or OCR PDF
→ TOC page detection
→ pane-aware TOC line reconstruction
→ TOC item extraction
→ printed page to PDF page alignment
→ bookmark plan
```

이 접근은 human에게 자연스럽다.
사람은 목차 페이지를 보고 title, level, printed page를 읽은 뒤 bookmark를 만든다.

하지만 computer에게는 다음 문제가 있었다.

- bookmark-guided TOC page label은 ground truth가 아니라 noisy pseudo label이다.
- TOC page detection 자체가 실패하면 이후 extraction이 모두 실패한다.
- 2-pane TOC의 reading order가 쉽게 깨진다.
- OCR text가 나쁘면 printed page number와 title을 안정적으로 분리할 수 없다.
- page alignment가 추가로 필요하다.

따라서 Approach B는 버리지 않는다.
다만 현재는 primary strategy가 아니라 fallback, evaluation aid, research track으로 둔다.

---

## 5. 최근 실험 근거

`experiments/experiments.json`의 최근 실험에서 다음 판단을 얻었다.

### 5.1 Document Parse feature와 TOC page 구분

`051_parse_feature_toc_page_separation_zvi`는 Document Parse 기반 category, element 위치, numbering, trailing page feature가 TOC page와 non-TOC page를 구분하는 데 강한 신호가 될 수 있음을 보였다.

중요 feature는 다음이었다.

- `trailing_page_ratio`
- `numbering_any_ratio`
- `category_index_ratio`
- `line_index_ratio`
- `line_paragraph_ratio`

이 결과는 TOC page 기반 접근을 완전히 폐기할 필요가 없음을 보여준다.
다만 이 접근도 parse 품질에 의존한다.

### 5.2 책 전체 font / height hierarchy

`052_whole_book_line_font_height_kde`, `053_bookmark_depth_font_size_kde`, `054_tier_merge_and_scanned_font_check`, `055_page_tier_distribution_clustering`은 책 전체 line의 font size와 bbox height가 heading hierarchy를 추론하는 데 의미 있는 신호임을 확인했다.

핵심 결론은 다음이다.

- native PDF에서는 PDF font size 속성이 bbox height보다 깨끗한 경우가 많다.
- bookmark depth와 font tier는 강하게 상관되지만 1:1 대응하지는 않는다.
- level 1 안에도 chapter heading과 front matter heading이 섞일 수 있다.
- scanned PDF에서는 OCR line fragmentation과 수식 OCR 조각이 tier를 오염시킨다.
- `font_size`와 `height` 중 어느 신호가 우세한지는 책마다 다르다.
- 따라서 runtime은 두 신호를 모두 계산하고, 책별로 더 신뢰할 수 있는 hierarchy candidate를 선택해야 한다.

### 5.3 OCR 품질 병목

`056_paddleocr_easyocr_scanned_ocr_compare`와 `057_document_parse_scanned_ocr_compare`는 scanned PDF에서 기존 OCR text layer 품질이 병목이라는 가설 아래 PaddleOCR, EasyOCR, Upstage Document Parse를 비교하기 위한 raw output을 만들었다.

자동 정확도 판정은 아직 pending이지만, 이 실험군은 다음 방향을 만든다.

- OCR 품질을 별도 단계로 다뤄야 한다.
- 기존 PDF의 embedded OCR text를 무조건 신뢰하지 않는다.
- Upstage Document Parse를 기본 provider 후보로 둔다.
- provider 결과는 반드시 cache하고 재현 가능한 artifact로 남긴다.

### 5.4 Document Parse overlay PDF

`058_document_parse_pdf_overlay`는 Document Parse word 좌표와 text를 이용해 scanned page image 위에 invisible text layer를 overlay한 searchable PDF를 만들 수 있음을 확인했다.

재작업된 `058_document_parse_pdf_overlay`는 더 중요한 구현 원칙을 제공한다.

- word 단위 text와 `content.text`가 일치하는 일반 문단은 word-level overlay를 사용한다.
- 표와 수식처럼 word join 결과가 `content.text`와 불일치하는 element는 row-level 또는 whole-element fallback을 사용한다.
- 표에서는 markdown 구분선처럼 실제 page pixel에 대응하지 않는 문법 요소가 있으므로 검증에서 이를 구분해야 한다.
- 수식은 word 좌표만 따라가면 LaTeX 구조가 깨질 수 있으므로 element 전체 text 보존이 더 중요할 수 있다.

`059_document_parse_output_format_compare`는 output format 선택 기준을 제공한다.

- 사람이 읽기 좋은 text / TOC류 processing에는 `text` 또는 `markdown`이 적합하다.
- table 구조, 특히 colspan 같은 병합 셀을 보존하려면 `html`이 필요하다.
- 같은 Document Parse 호출에서 `text`, `html`, `markdown`을 함께 받을 수 있다.

---

## 6. Scope

### 6.1 포함

다음 기능은 project scope에 포함한다.

- Upstage Document Parse 기반 OCR / text extraction
- Document Parse response cache
- page image 위 invisible text layer overlay
- searchable OCR PDF 생성
- overlay PDF 재추출 검증
- PDF line / word / block / element feature 추출
- 책 전체 font size / bbox height tiering
- page별 tier distribution 생성
- heading candidate extraction
- hierarchy inference
- bookmark plan 생성
- PDF bookmark 삽입
- Markdown directory export
- 기존 bookmark 추출과 reference evaluation
- TOC page detection 연구
- TOC page parsing 연구
- 모든 중간 artifact 저장

### 6.2 제외

다음 기능은 기본 scope에서 제외한다.

- 범용 OCR engine 자체 개발
- OCR 결과를 사람이 직접 수정하는 visual editor
- table / figure / equation을 완전한 semantic document model로 복원하는 기능
- 출판 품질의 EPUB 변환
- 기존 bookmark가 있는 PDF를 runtime에서 기본적으로 다시 bookmark하는 기능

단, overlay PDF 생성 과정에서 표와 수식의 text 손실을 줄이기 위한 보존 전략은 scope에 포함한다.
목적은 document understanding 제품을 만드는 것이 아니라 bookmark / Markdown 생성을 위한 clean text layer를 확보하는 것이다.

---

## 7. Page Number Convention

public interface와 저장 artifact는 모두 1-based PDF page number를 사용한다.

이유는 다음이다.

- 사용자가 PDF viewer에서 보는 page 번호와 맞추기 쉽다.
- bookmark target page를 report에서 해석하기 쉽다.
- printed page number와 PDF page number를 나란히 기록할 때 off-by-one 오류를 줄인다.

예시는 다음과 같다.

```json
{
  "title": "2.3 Markov Chains",
  "level": 2,
  "pdf_page": 105,
  "printed_page": 87
}
```

내부 PDF engine이 0-based index를 요구하더라도 public object와 intermediate artifact에는 1-based 값을 기록한다.

---

## 8. 전체 Pipeline

### 8.1 Supportive OCR Pipeline

scanned PDF 또는 OCR 품질이 낮은 PDF를 처리한다.

```text
input PDF
→ page rendering
→ Upstage Document Parse call
→ response cache 저장
→ text/html/markdown/word coordinates 추출
→ overlay strategy 결정
→ image + invisible text layer PDF 생성
→ 재추출 검증
→ OCR report 저장
```

output은 다음이다.

```text
book_ocr.pdf
document_parse_cache/
ocr_overlay_report.json
ocr_text_quality_report.json
```

이 pipeline은 단독으로 실행할 수 있어야 하고, main processing pipeline 앞에서 자동으로 호출할 수도 있어야 한다.

### 8.2 Primary Runtime Pipeline

clean OCR PDF 또는 native PDF를 대상으로 book-wide hierarchy를 추론한다.

```text
PDF input
→ existing bookmark check
→ OCR quality check
→ optional OCR overlay
→ whole-book line extraction
→ font size / height tiering
→ page tier distribution
→ heading candidate extraction
→ hierarchy inference
→ bookmark plan generation
→ bookmark insertion
→ Markdown export
→ report save
```

이 pipeline의 중심은 TOC page가 아니라 책 전체의 시각적 계층이다.

### 8.3 Secondary TOC Pipeline

TOC page 기반 접근은 fallback과 연구 축으로 유지한다.

```text
PDF input
→ OCR quality check
→ optional OCR overlay
→ TOC page detection
→ pane classification
→ pane-adjusted line reconstruction
→ TOC item extraction
→ printed page to PDF page alignment
→ bookmark plan generation
```

이 pipeline은 다음 상황에서 사용한다.

- book-wide hierarchy inference confidence가 낮을 때
- 목차 page가 매우 깨끗하고 heading style이 불규칙할 때
- evaluation용 reference를 만들 때
- 추후 LLM-driven TOC extraction 연구를 진행할 때

---

## 9. Supportive OCR / Document Parse

### 9.1 기본 provider

기본 provider는 Upstage Document Parse로 둔다.

요청 기본값은 다음을 목표로 한다.

```json
{
  "model": "document-parse",
  "output_formats": ["text", "html", "markdown"],
  "coordinates": true,
  "words": true
}
```

provider-specific SDK는 core dependency에 직접 묶지 않고 optional extra 또는 adapter로 둔다.

### 9.2 Cache 정책

Document Parse 호출은 비용과 latency가 있으므로 반드시 cache한다.

cache key 후보는 다음이다.

- input PDF file hash
- page number
- render DPI
- provider
- provider model
- request params
- adapter version

cache artifact는 원본 response를 가능한 한 보존한다.
후처리된 text만 저장하면 나중에 overlay strategy를 바꿀 수 없다.

### 9.3 Overlay 전략

overlay는 page image 위에 invisible text layer를 얹는 방식으로 만든다.
기존 PDF에 들어 있던 나쁜 OCR layer는 기본적으로 이어받지 않는다.

Element별 전략은 다음이다.

```text
word_join == normalized(content.text):
  word-level overlay

word_join != normalized(content.text) and row reconstruction succeeds:
  row-level overlay

word_join != normalized(content.text) and row reconstruction fails:
  whole-element overlay
```

원칙은 다음이다.

- 일반 문단과 heading은 word 좌표 정밀도를 우선한다.
- 표와 수식은 좌표 정밀도보다 text 보존을 우선할 수 있다.
- 화면에 대응하는 pixel이 없는 markdown 문법 요소는 overlay 대상에서 제외할 수 있다.
- overlay report에는 어떤 element가 어떤 fallback을 탔는지 기록한다.

### 9.4 OCR 품질 검증

OCR / overlay 결과는 다음 기준으로 검증한다.

- overlay PDF open 가능 여부
- page count 유지 여부
- 재추출 word / text count
- element별 `content.text` 보존율
- 빈 page 또는 비정상적으로 짧은 page 비율
- 깨진 문자 / 숫자-only token 비율
- heading candidate 추출 가능 여부

검증 결과가 낮으면 main pipeline은 계속 진행할 수 있지만 report에 warning을 남긴다.

---

## 10. Primary Algorithm: Book-wide Hierarchy Inference

### 10.1 목표

책 전체에서 heading 후보를 찾고 bookmark tree를 만든다.

입력은 다음 중 하나다.

- native PDF
- existing OCR PDF
- `pdfbooktree`가 생성한 OCR overlay PDF

출력은 다음이다.

```json
[
  {
    "title": "Chapter 1 Introduction",
    "level": 1,
    "pdf_page": 17,
    "source": "font_height_hierarchy",
    "confidence": 0.93
  },
  {
    "title": "1.1 Motivation",
    "level": 2,
    "pdf_page": 19,
    "source": "font_height_hierarchy",
    "confidence": 0.88
  }
]
```

### 10.2 Line extraction

line extraction은 PDF engine의 raw line boundary를 그대로 믿지 않는다.
특히 OCR PDF에서는 같은 시각적 줄이 여러 조각으로 쪼개질 수 있다.

기본 원칙은 다음이다.

- page의 content span을 추출한다.
- y 중심 좌표 기반으로 시각적 line을 재군집화한다.
- line 대표 `font_size`와 `height`는 max가 아니라 median을 우선 사용한다.
- 숫자만 있는 span도 chapter number일 수 있으므로 조건부로 포함한다.
- 수식, footer, running header, page number 후보는 별도 feature로 표시한다.

### 10.3 Tiering

책 전체 line에서 font size와 bbox height tier를 각각 만든다.

후보 방법은 다음이다.

- KDE peak / valley cut
- 인접 tier peak gap 기반 merge
- 최소 등장 횟수 기반 sparse tier merge
- page position과 text pattern을 이용한 noise tier 제거

`font_size`와 `height`는 어느 하나만 고정 선택하지 않는다.
책마다 더 좋은 신호가 다르므로 두 signal을 병렬로 계산하고 비교한다.

### 10.4 Heading candidate

heading candidate는 다음 신호를 조합해 만든다.

- font tier 또는 height tier
- page 내 위치
- 주변 body text와의 spacing
- numbering pattern
- text length
- letter ratio
- running header / footer 여부
- repeated title 여부
- page tier distribution cluster

candidate에는 항상 source evidence를 남긴다.

```json
{
  "pdf_page": 42,
  "text": "Chapter 3 Fixed-Income Securities",
  "font_tier": 1,
  "height_tier": 1,
  "y0": 126.4,
  "numbering_depth": 1,
  "evidence": ["large_font_tier", "top_page_position", "chapter_keyword"]
}
```

### 10.5 Hierarchy inference

heading candidate sequence를 bookmark tree로 변환한다.

고려할 신호는 다음이다.

- tier rank
- numbering depth
- text semantic cue
- page order
- repeated section pattern
- appendix / glossary / index 같은 back matter cue
- front matter cue
- confidence

level은 단순 font size rank로만 결정하지 않는다.
실험에서 level 1 bookmark 안에도 chapter heading과 front matter heading이 섞이고, level 2 안에도 appendix heading처럼 더 큰 시각적 지위를 가진 항목이 있음을 확인했기 때문이다.

---

## 11. Secondary Algorithm: TOC Page Parsing

### 11.1 역할

TOC page parsing은 현재 secondary strategy다.
다음 목적으로 유지한다.

- primary hierarchy inference 실패 시 fallback
- 책에 명확한 목차가 있고 body heading style이 불규칙한 경우
- evaluation / debugging reference 생성
- LLM-driven extraction 연구

### 11.2 TOC page detection

TOC page detection에는 다음 feature를 사용할 수 있다.

- line-final number ratio
- trailing page number pattern
- numbering monotonicity
- `contents`, `table of contents`, `목차`, `차례` keyword
- Document Parse category
- `category_index_ratio`
- `line_index_ratio`
- pane balance
- page position prior

주의할 점은 다음이다.

- bookmark-guided TOC range는 ground truth가 아니라 pseudo label이다.
- 수동 검수 없는 TOC label로 성능을 확정하지 않는다.
- page-level random split은 layout leakage를 만들 수 있으므로 금지한다.
- evaluation split은 PDF 단위로 한다.

### 11.3 Pane-aware reconstruction

TOC page가 2-pane이면 일반 y-order reading은 실패할 수 있다.
따라서 TOC extraction 전에는 pane classification과 pane-adjusted reading order가 필요하다.

line feature는 다음을 포함한다.

- `source_pdf_page`
- `pane_id`
- `line_order`
- `raw_text`
- `normalized_text`
- `x0`, `x1`, `y0`, `y1`
- `font_tier`
- `indent_tier`
- `category`
- `numbering_depth`
- `trailing_page`

### 11.4 TOC item extraction

TOC item extraction은 deterministic rule, LLM, ML / DL sequence model을 모두 연구 후보로 둔다.

LLM-driven extraction은 다음 역할을 맡을 수 있다.

- 여러 line에 걸친 item 병합
- 깨진 OCR title 보정
- title과 printed page 분리
- hierarchy level 추론
- appendix, part, chapter, section cue 반영

단, LLM output은 바로 bookmark로 쓰지 않는다.
schema validation, source line coverage, printed page monotonicity, level jump, duplicate item 여부를 검증한다.

---

## 12. Page Alignment

primary hierarchy inference는 PDF page를 직접 target으로 삼으므로 page alignment 부담이 작다.

반면 TOC page parsing 결과는 printed page number를 담기 때문에 PDF page로 align해야 한다.

alignment 신호는 다음이다.

- body footer / header의 printed page number
- TOC item printed page sequence
- heading title fuzzy match
- existing bookmark answer reference
- front matter roman numeral pattern

alignment output 예시는 다음이다.

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

## 13. Bookmark Generation

validated hierarchy item을 사용해 bookmark plan을 만든다.

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

검증 항목은 다음이다.

- output PDF open 가능 여부
- 원본 page count 유지 여부
- bookmark count
- level sequence validity
- target page range
- roundtrip bookmark extraction 결과 일치 여부

---

## 14. Markdown Export

Markdown export는 bookmark hierarchy를 directory tree와 문서 metadata로 변환한다.

예시는 다음이다.

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
source_method: font_height_hierarchy
confidence: 0.88
```

본문 text extraction 품질이 낮으면 Markdown export는 warning을 기록하고 가능한 범위만 저장한다.

---

## 15. Intermediate Artifacts

모든 단계는 재현 가능한 artifact를 저장한다.

예시는 다음이다.

```text
existing_bookmarks.json
ocr_quality_report.json
document_parse_cache/
document_parse_pages.jsonl
ocr_overlay_report.json
overlay_reextract_report.json
whole_book_lines.parquet
font_size_tiers.json
height_tiers.json
page_tier_distribution.parquet
heading_candidates.json
hierarchy_candidates.json
bookmark_plan.json
bookmark_roundtrip_report.json
markdown_export_log.json
book_report.json
```

TOC fallback 또는 연구 pipeline을 실행한 경우 다음 artifact를 추가한다.

```text
toc_page_candidates.json
toc_page_predictions.json
toc_range.json
pane_classification.json
pane_adjusted_lines.parquet
toc_items_raw.json
toc_items_validated.json
page_alignment.json
```

artifact에는 최소한 다음 metadata를 포함한다.

- input PDF path
- input file hash
- page number convention
- OCR provider
- parse model
- render DPI
- feature source
- algorithm version
- prompt version
- created_at
- confidence
- warnings

---

## 16. Existing Bookmark의 역할

기존 bookmark가 있는 PDF는 runtime 처리 대상이라기보다 evaluation reference로 사용한다.

기존 bookmark tree는 다음 항목의 answer reference가 될 수 있다.

- title
- target PDF page
- hierarchy level

단, 기존 bookmark 자체도 오류가 있을 수 있으므로 reference source와 matching confidence를 함께 기록한다.

기존 bookmark에서 역추정한 TOC page range는 ground truth가 아니다.
300study manual audit에서 bookmark-guided TOC label이 크게 틀릴 수 있음이 확인되었다.

따라서 기존 bookmark는 다음 용도로 사용한다.

- hierarchy inference 결과 평가
- heading candidate matching 평가
- page alignment 평가
- generated bookmark와 answer bookmark tree 비교
- TOC page 후보 생성

기존 bookmark를 다음 용도로 사용하지 않는다.

- 수동 검수 없는 TOC page ground truth
- runtime 대상 PDF의 필수 입력 조건
- OCR 품질 판단의 정답

---

## 17. Evaluation

### 17.1 OCR / Overlay Evaluation

지표는 다음이다.

- Document Parse call success rate
- overlay PDF creation success rate
- overlay PDF open success rate
- page count preservation
- re-extracted text preservation ratio
- element-level text match ratio
- fallback strategy count
- cost / latency per page

### 17.2 Book-wide Hierarchy Evaluation

기존 bookmark answer reference 또는 manual label 기준으로 평가한다.

지표는 다음이다.

- heading candidate precision
- heading candidate recall
- title match rate
- level accuracy
- relative depth transition accuracy
- parent match accuracy
- target page exact accuracy
- target page ±1 accuracy
- tree edit distance

### 17.3 TOC Pipeline Evaluation

TOC page detection은 manual audited label 또는 confidence gate를 통과한 pseudo-clean label에서만 평가한다.

지표는 다음이다.

- page precision
- page recall
- page F1
- range IoU
- start page error
- end page error
- TOC item F1
- printed page extraction accuracy
- page alignment accuracy

### 17.4 End-to-end Evaluation

최종 평가는 다음을 포함한다.

- OCR / overlay 필요 여부 판단
- bookmark plan 품질
- PDF bookmark insertion 성공 여부
- Markdown export 성공 여부
- book report 완성 여부
- manual review 필요 비율
- cost / latency

---

## 18. Public Interface

### 18.1 OCR Overlay

사용 흐름은 다음이다.

```python
from pdfbooktree.ocr import OcrOverlayBuilder

builder = OcrOverlayBuilder(
    input_pdf="book.pdf",
    output_pdf="outputs/book_ocr.pdf",
    output_dir="outputs/book_ocr_artifacts",
    provider="upstage_document_parse",
    render_dpi=300,
)

result = builder.run()
```

반환 객체는 다음 정보를 포함한다.

```text
status
input_pdf
output_pdf
page_count
provider
model
cache_dir
overlay_report_path
warnings
```

### 18.2 단일 PDF 처리

사용 흐름은 다음이다.

```python
from pdfbooktree import Processor

processor = Processor(
    input_pdf="book.pdf",
    output_dir="outputs/book",
    ocr_policy="auto",
    strategy="book_hierarchy",
    skip_existing_bookmarks=True,
)

result = processor.run()
```

`ocr_policy` 후보는 다음이다.

```text
never
auto
always
```

`strategy` 후보는 다음이다.

```text
book_hierarchy
toc_pages
auto
```

반환 객체는 다음 정보를 포함한다.

```text
status
input_pdf
ocr_pdf
output_pdf
output_markdown_dir
bookmark_count
strategy_used
confidence_summary
warnings
artifact_paths
```

### 18.3 Batch Processing

사용 흐름은 다음이다.

```python
from pdfbooktree import BatchProcessor

batch = BatchProcessor(
    input_dir="pdfs",
    output_dir="outputs",
    recursive=True,
    ocr_policy="auto",
    strategy="auto",
)

summary = batch.run()
```

summary는 다음 정보를 포함한다.

```text
total_pdf_count
processed_count
ocr_overlay_count
skipped_existing_bookmark_count
failed_count
manual_review_required_count
created_bookmarked_pdf_paths
created_markdown_dirs
```

### 18.4 Evaluator

```python
from pdfbooktree.evaluation import Evaluator

evaluator = Evaluator(
    reference_pdf="book_with_bookmarks.pdf",
    prediction_path="outputs/book/bookmark_plan.json",
)

report = evaluator.run()
```

---

## 19. CLI

OCR overlay:

```powershell
uv run pdfbooktree ocr-overlay .\book.pdf --output .\outputs\book_ocr.pdf
```

단일 PDF 처리:

```powershell
uv run pdfbooktree process .\book.pdf --output .\outputs\book --ocr-policy auto --strategy book-hierarchy
```

TOC fallback 사용:

```powershell
uv run pdfbooktree process .\book.pdf --output .\outputs\book --ocr-policy auto --strategy toc-pages
```

batch 처리:

```powershell
uv run pdfbooktree batch .\pdfs --output .\outputs --ocr-policy auto --strategy auto
```

평가:

```powershell
uv run pdfbooktree evaluate .\book_with_bookmarks.pdf .\outputs\book\bookmark_plan.json
```

---

## 20. Dependency

### 20.1 Core

```text
pymupdf
rapidfuzz
numpy
scikit-learn
joblib
typer
rich
```

### 20.2 PDF / OCR Overlay

```text
pillow
ocrmypdf
fpdf2
```

`ocrmypdf` 내부 renderer를 재사용하는 경우 version과 adapter version을 artifact에 기록한다.

### 20.3 Data / Experiment

```text
pandas
matplotlib
pyarrow
```

### 20.4 Optional ML

```text
lightgbm
catboost
```

### 20.5 Optional Provider / LLM

```text
openai
httpx
```

Upstage Document Parse와 LLM 호출은 반드시 provider, model, request params, input hash, output hash를 artifact에 기록한다.

---

## 21. Experiment Roadmap

### 21.1 OCR / Overlay

우선순위가 가장 높다.

```text
060_document_parse_overlay_multibook
061_overlay_text_quality_metrics
062_document_parse_cache_adapter
063_ocr_policy_auto_decision
064_overlay_searchability_showcase
```

목표는 다음이다.

- 여러 책에서 overlay PDF 생성이 안정적으로 되는지 확인한다.
- word-level, row-level, whole-element fallback이 어떤 element에서 발생하는지 기록한다.
- overlay 재추출 검증 기준을 만든다.
- OCR 품질이 낮은 PDF를 자동 감지하는 policy를 만든다.

### 21.2 Book-wide Hierarchy

primary algorithm 연구 축이다.

```text
065_whole_book_hierarchy_multibook
066_font_size_height_signal_selection
067_heading_candidate_filtering
068_hierarchy_inference_from_tiers
069_bookmark_plan_generation_showcase
```

목표는 다음이다.

- font size와 height signal을 책별로 비교한다.
- 수식 조각, footer, running header noise를 줄인다.
- heading candidate에서 bookmark tree를 만든다.
- 기존 bookmark reference와 비교한다.

### 21.3 TOC Fallback

secondary algorithm 연구 축이다.

```text
070_document_parse_toc_page_detector
071_pane_adjusted_toc_line_reconstruction
072_llm_toc_item_extraction_with_clean_ocr
073_toc_pipeline_as_fallback
```

목표는 다음이다.

- clean OCR 위에서 TOC page approach가 얼마나 회복되는지 확인한다.
- TOC page 기반 결과와 book-wide hierarchy 결과를 비교한다.
- fallback 조건을 정한다.

### 21.4 End-to-end

```text
074_ocr_to_bookmark_end_to_end
075_markdown_export_from_bookmark_plan
076_batch_runtime_report
```

목표는 다음이다.

- OCR overlay부터 bookmark embedding까지 하나의 flow로 연결한다.
- Markdown export를 포함한 runtime output shape를 확정한다.
- public API와 CLI shape를 showcase로 검증한다.

---

## 22. Development Roadmap

### v0.1: Document Parse OCR Overlay

포함한다.

- Upstage Document Parse adapter
- response cache
- page rendering
- word / element coordinate parsing
- overlay PDF builder
- overlay 재추출 검증
- OCR report

### v0.2: Book-wide Hierarchy Inference

포함한다.

- whole-book line extraction
- y-coordinate line regrouping
- font size / height tiering
- heading candidate extraction
- hierarchy inference
- confidence report

### v0.3: Bookmark Output

포함한다.

- bookmark plan schema
- PDF bookmark insertion
- roundtrip validation
- existing bookmark reference evaluation

### v0.4: Markdown Export and Batch Runtime

포함한다.

- Markdown tree export
- batch processor
- runtime report
- skipped existing bookmark report
- OCR policy auto mode

### v0.5: TOC Fallback Research

포함한다.

- TOC page detector
- pane-aware line reconstruction
- TOC item extraction
- page alignment
- fallback strategy selection

---

## 23. Success Criteria

### 23.1 OCR Overlay

```text
overlay PDF 생성 성공률 >= 0.95
page count preservation = 1.0
overlay 재추출 text preservation ratio >= 0.9
평균 처리 시간이 실험적으로 허용 가능한 범위일 것
```

### 23.2 Book-wide Hierarchy

기존 bookmark reference 또는 manual label 기준:

```text
heading candidate recall >= 0.85
bookmark title F1 >= 0.8
target page ±1 accuracy >= 0.9
relative depth transition accuracy >= 0.85
```

### 23.3 Bookmark Output

```text
bookmarked PDF 생성 성공
bookmark roundtrip 검증 성공
원본 page count 유지
bookmark target page가 유효 범위 안에 있음
```

### 23.4 Markdown Export

```text
Markdown tree 생성 성공
toc.json 생성 성공
toc.md 생성 성공
source metadata 보존
품질 warning 기록
```

---

## 24. 최종 요약

`pdfbooktree`는 scanned PDF book에서 clean OCR / parse text를 확보한 뒤, 책 전체의 시각적 hierarchy를 이용해 bookmark tree를 만들고, 이를 PDF bookmark와 Markdown tree로 내보내는 library다.

현재 primary direction은 다음이다.

```text
1. OCR 품질을 먼저 확인한다.
2. 필요하면 Upstage Document Parse로 text / coordinates를 얻는다.
3. Document Parse 결과를 scanned page image 위에 overlay해 searchable OCR PDF를 만든다.
4. 책 전체 line의 font size와 bbox height tier를 계산한다.
5. heading candidate를 추출한다.
6. heading sequence를 hierarchy로 변환한다.
7. bookmark plan을 만든다.
8. PDF bookmark를 삽입한다.
9. Markdown tree를 생성한다.
```

TOC page를 찾아 정밀 parsing하는 접근은 여전히 중요하다.
다만 현재 결론은, clean OCR이 있다는 전제에서는 computer에게 book-wide font / height hierarchy approach가 더 유망하다는 것이다.
TOC page approach는 fallback, evaluation aid, research track으로 유지한다.
