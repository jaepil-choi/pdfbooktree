README 기준으로 보면, 기존 도구들은 크게 **4계열**로 나뉜다.

1. **TOC page를 사람이 지정 → TOC parsing → bookmark 삽입**
2. **본문 heading style/font를 탐지 → synthetic outline 생성**
3. **OCR/LLM으로 사용자가 준 TOC 이미지/텍스트를 JSON화**
4. **수동 bookmark helper**

`pdfbooktree` PRD처럼 **TOC page 자동 탐지 + TOC item parsing + offset 자동 추정 + body heading fuzzy verification + ML detector/evaluation workflow**를 모두 포함한 것은 README 기준으로는 찾기 어렵다. PRD의 범위는 이 기존 도구들보다 더 “pipeline/package” 지향이다. 

---

## 요약 비교

| 프로젝트                     | README상 핵심 알고리즘                                                 | TOC page 자동 detection | TOC item parsing |              page alignment | LLM/OCR | 판단                              |
| ------------------------ | --------------------------------------------------------------- | --------------------: | ---------------: | --------------------------: | ------: | ------------------------------- |
| `kszenes/tocPDF`         | 사용자가 TOC start/end와 offset 입력 → parser로 TOC 추출 → outline 생성     |                     X |                O | 수동 offset + missing page 보정 |       X | 가장 가까운 TOC 기반 도구                |
| `PDF-Bookmark-Automator` | TOC 이미지 OCR → LLM으로 structured JSON refine → offset 적용          |  X, 사용자가 TOC image 제공 |          LLM/OCR |                   수동 offset |       O | LLM/OCR GUI workflow            |
| `pdf-to-chapters`        | bookmark 추출 우선, 없으면 TOC fallback, LLM으로 main chapter 식별         |                   불명확 |       chapter 중심 |                smart offset |       O | chapter splitter에 가까움           |
| `pdf.tocgen`             | 본문 heading의 font/position metadata로 outline 생성                  |           TOC page 아님 |    본문 heading 기반 |             heading page 자체 |       X | generated PDF용 heading detector |
| `pdf_scout`              | header text가 body보다 크고 left-aligned인 generated PDF에서 heading 탐지 |           TOC page 아님 |    본문 heading 기반 |             heading page 자체 |       X | 구조가 규칙적인 PDF용                   |
| `Tocify`                 | AI로 scanned directory image/raw text를 structured outline으로 파싱   |             X, 입력 제공형 |        AI parser |              사용자가 보정 가능성 높음 |       O | 웹앱/interactive                  |
| `ifnoelse/pdf-bookmark`  | 사용자가 목차 텍스트/URL과 page offset 입력                                 |                     X |           수동/URL |                   수동 offset |       X | GUI bookmark helper             |
| `aminya/tocPDF`          | TOC page 추출, Tabula/OCR, 사람이 text 정리, k2pdfopt로 삽입              |                     X |            수동 정리 |                   수동 offset |  외부 OCR | manual recipe                   |

---

## 1. `kszenes/tocPDF`

README 기준으로는 **가장 가까운 TOC 기반 자동 bookmark 도구**다. 다만 핵심 입력인 `start_toc`, `end_toc`, `offset`은 사용자가 제공해야 한다. README는 지원 parser로 `pdfplumber`, `pypdf`, `tika`를 나열하고, TOC 첫/마지막 PDF page와 PDF-book page offset이 필수 입력이라고 설명한다. `--missing_pages` 옵션은 책 중간 누락 페이지가 있을 때 expected PDF page와 book page number를 확인해 offset을 동적으로 재계산하는 방식이다. ([GitHub][1])

알고리즘 구조는 대략 다음으로 보인다.

```text
user-specified TOC page range
→ chosen text parser로 TOC text extraction
→ TOC line parsing
→ user-specified global offset 적용
→ optional missing_pages로 offset 동적 보정
→ PDF outline 생성
```

중요한 한계도 README에 명시되어 있다. scanned PDF는 OCR을 하지 않기 때문에 지원하지 않고, multi-column TOC도 지원하지 않는다. ([GitHub][1])

**pdfbooktree와의 차이:**
`tocPDF`는 **TOC page detection**과 **offset estimation**을 자동화하지 않는다. `pdfbooktree`의 ML-based TOC segment detector와 body heading fuzzy verification이 들어가면 `tocPDF`보다 훨씬 자동화 수준이 높다.

---

## 2. `AhmedMoustafaa/PDF-Bookmark-Automator`

README 기준 알고리즘은 **TOC 이미지 OCR + LLM JSON refinement + offset 적용**이다. Tesseract로 TOC image에서 text를 추출하고, OpenAI GPT로 OCR output을 structured JSON으로 refine하며, 사용자는 PDF Operations 탭에서 PDF와 page offset을 지정하고 bookmark를 적용한다. scanned PDF용 OCR option도 있다. ([GitHub][2])

구조는 다음에 가깝다.

```text
user selects TOC images
→ Tesseract OCR
→ user reviews OCR output
→ LLM refines OCR output into structured JSON
→ user selects target PDF
→ user sets page offset
→ apply bookmarks
```

README의 offset 설명은 수동이다.

```text
offset = PDF viewer page number - book page number
PDF_page = JSON_page + offset
```

([GitHub][2])

**pdfbooktree와의 차이:**
이 도구는 LLM/OCR가 중심축이고, TOC page를 PDF 안에서 자동 탐지하는 구조가 아니다. `pdfbooktree`의 철학인 **OCR text layer 기반 deterministic/ML pipeline + low-confidence LLM fallback**과는 반대에 가깝다.

---

## 3. `ahnafnafee/pdf-to-chapters`

README상 목적은 bookmark 생성 자체보다는 **textbook을 chapter별 PDF로 split**하는 것이다. 먼저 PDF bookmarks를 읽고, bookmark가 없으면 TOC fallback을 사용하며, LLM으로 primary chapters와 subsections/front matter/appendix를 구분한다고 설명한다. 또한 TOC 기반 extraction에서는 page offset calculation을 수행한다고 되어 있다. ([GitHub][3])

README의 “How It Works”는 다음 흐름이다.

```text
1. bookmark extraction
2. TOC fallback
3. LLM analysis로 main chapters 식별
4. page offset calculation
5. chapter splitting
```

([GitHub][3])

**pdfbooktree와의 차이:**
README만 보면 TOC page를 어떻게 찾는지, TOC item을 어떤 규칙으로 파싱하는지는 구체적으로 설명되어 있지 않다. 또한 chapter 중심이라 section-level hierarchy 전체 복원보다는 **main chapter extraction**에 초점이 있다.

---

## 4. `Krasjet/pdf.tocgen`

이건 TOC page를 읽는 도구가 아니라, **본문 heading metadata로 outline을 생성하는 도구**다. README는 embedded font attributes와 heading position을 이용해 PDF outline을 추론한다고 설명한다. workflow는 `pdfxmeta → pdftocgen → pdftocio`의 3단계다. ([GitHub][4])

README의 핵심은 다음이다.

```text
pdfxmeta:
  heading metadata / font attributes / positions 추출
  recipe.toml 생성

pdftocgen:
  recipe에 맞는 heading들을 본문에서 찾아 TOC 생성

pdftocio:
  생성된 TOC를 PDF outline으로 import
```

예시 recipe는 heading level별 font name과 font size를 지정한다.

```toml
[[heading]]
level = 1
font.name = "Times-Bold"
font.size = 19.9253

[[heading]]
level = 2
font.name = "Times-Bold"
font.size = 11.9552
```

([GitHub][4])

또한 `pdftocgen -v`는 heading의 vertical position까지 출력할 수 있고, `pdftocio`가 이를 이용해 page top이 아니라 실제 heading 위치로 link할 수 있다고 설명한다. ([GitHub][4])

**pdfbooktree와의 차이:**
`pdf.tocgen`은 **body-first heading detection**이다. OCR scanned textbook이나 text overlay 품질이 낮은 경우보다는 TeX/Word/InDesign 등 generated PDF에 맞다. README도 scanned PDF에는 기대하지 말라고 한다. ([GitHub][4])

---

## 5. `hueyy/pdf_scout`

`pdf_scout`도 TOC page parser가 아니라 **본문 heading detector**다. README는 computer-generated PDF용으로, 조건이 꽤 강하다. single column, heading font size가 body보다 큼, heading이 left-aligned/justified, heading paragraph spacing이 body보다 큼, consistent left margin 같은 조건을 요구한다. ([GitHub][5])

알고리즘은 README 수준에서는 구체적 코드까지 설명되지 않지만, 요구 조건으로 보아 다음 계열이다.

```text
body text layout 분석
→ heading-like text 탐지
  - larger font
  - left alignment
  - larger spacing
  - consistent margins
→ detected headings로 bookmarks 생성
```

**pdfbooktree와의 차이:**
`pdf_scout`은 TOC page를 찾지 않는다. **본문 heading style이 명확한 generated PDF**를 대상으로 한다. scanned OCR textbook의 TOC-first pipeline과는 목적이 다르다.

---

## 6. `Tocify`

README 기준으로는 웹앱이며, **scanned directory image 또는 raw text를 AI로 structured outline으로 파싱**한다고 설명한다. 그리고 clickable bookmarks와 printable TOC pages를 만든다고 되어 있다. ([GitHub][6])

흐름은 대략 다음으로 추정된다.

```text
user provides scanned directory image or raw text
→ AI parses it into structured outline
→ user edits/formats
→ clickable bookmarks / printable TOC 생성
```

**pdfbooktree와의 차이:**
Tocify는 interactive web app에 가깝고, PDF 전체에서 TOC page를 자동 탐지하거나 offset을 본문 heading으로 검증하는 pipeline은 README에 드러나지 않는다. LLM/AI는 parser 중심으로 쓰이는 것으로 보인다.

---

## 7. `ifnoelse/pdf-bookmark`

이건 자동 detection보다는 **manual-assisted bookmark GUI**에 가깝다. README는 사용자가 PDF를 선택하고, page offset을 채우고, directory contents를 직접 입력하거나 china-pub URL에서 가져오는 방식이라고 설명한다. page offset은 PDF reader의 실제 page와 책의 printed page를 비교해 수동 계산한다. ([GitHub][7])

알고리즘이라기보다 workflow는 이렇다.

```text
user selects PDF
→ user calculates page offset
→ user inputs/copies directory contents or provides supported bookstore URL
→ tool applies bookmarks
```

**pdfbooktree와의 차이:**
TOC page detection도, TOC item parsing도, heading alignment도 없다. 사용자가 이미 정리한 목차와 offset을 넣는 bookmark insertion helper다.

---

## 8. `aminya/tocPDF`

이 프로젝트는 이름은 자동화처럼 보이지만 README 기준으로는 **manual recipe**다. 사용자가 Chrome 등으로 TOC page를 추출하고, Tabula 또는 OCR.space로 TOC text를 뽑은 뒤, 사람이 spreadsheet/text editor로 목차를 정리한다. 이후 `k2pdfopt -toclist`로 bookmark를 넣는다. ([GitHub][8])

README상 절차는 다음이다.

```text
1. TOC pages를 PDF에서 수동 추출
2. Tabula 또는 OCR.space로 TOC text 추출
3. 사람이 page number와 hierarchy marker를 정리
4. page offset을 사람이 더함
5. k2pdfopt -toclist로 bookmark 삽입
```

수동 text format 예시는 `+`, `++`로 hierarchy를 표현한다.

```text
1 Cover
2 Table of Contents
5 Chapter 1
+6 Subchapter1
++7 Sub-Subchapter1
25 Chapter 2
```

([GitHub][8])

**pdfbooktree와의 차이:**
`pdfbooktree`가 자동화하려는 과정을 사람이 수행하는 workflow 문서에 가깝다. 다만 사용자 관점에서 “무엇을 자동화해야 하는지”를 잘 보여주는 reference다.

---

# 핵심 결론

README 기준으로 기존 프로젝트들의 detection 방식은 거의 세 부류다.

## A. TOC-driven but manual-range

대표: `kszenes/tocPDF`, `aminya/tocPDF`, `ifnoelse/pdf-bookmark`

```text
TOC page는 사람이 지정하거나 추출한다.
offset도 사람이 준다.
도구는 TOC text parsing과 bookmark insertion을 돕는다.
```

이 계열은 `pdfbooktree`와 문제의식은 가장 가깝지만, 자동화 수준은 낮다.

---

## B. Body-heading style detection

대표: `pdf.tocgen`, `pdf_scout`

```text
PDF 내부 TOC page를 보지 않는다.
본문 heading의 font size, font name, position, spacing, margin 등으로 outline을 만든다.
```

이 계열은 generated PDF에는 강하지만, OCR scanned textbook에는 취약하다.

---

## C. AI/OCR-assisted manual or semi-automatic parsing

대표: `PDF-Bookmark-Automator`, `Tocify`, `pdf-to-chapters`

```text
OCR 또는 raw text를 LLM/AI로 structured outline으로 바꾼다.
사용자 입력/검토가 들어간다.
LLM이 parser 또는 chapter classifier 역할을 한다.
```

이 계열은 messy TOC에 유연하지만, deterministic evaluation과 batch reproducibility는 약하다.

---

## `pdfbooktree`와 직접 비교하면

현재 PRD의 차별점은 이거다.

```text
기존 도구:
  TOC range 수동 지정 or body heading style 탐지 or LLM parser 중심

pdfbooktree:
  OCR text layer가 있는 scanned textbook에서
  TOC page 자동 탐지
  → TOC item parsing
  → printed page offset 자동 추정
  → body heading fuzzy verification
  → bookmark PDF + Markdown tree
  → silver-label evaluation
```

특히 README 기준으로는 다음 요소를 동시에 가진 프로젝트를 못 찾았다.

* TOC page range를 자동으로 탐지
* fixed weighted sum이 아니라 ML-based TOC segment scorer로 확장
* printed page → PDF page offset을 자동 추정
* offset 주변에서 body heading fuzzy verification
* low-confidence case만 LLM fallback
* `_bookmarked.pdf`뿐 아니라 Markdown tree와 evaluation artifact까지 생성

따라서 `pdfbooktree`는 기존 툴을 단순 재구현하는 것보다는, **TOC-driven bookmark generation을 scanned/OCR textbook용 robust pipeline으로 확장하는 프로젝트**라고 보는 게 맞다.

[1]: https://github.com/kszenes/tocPDF "GitHub - kszenes/tocPDF: Automatic CLI tool for generating outline of PDFs based on parsing the table of contents. · GitHub"
[2]: https://github.com/AhmedMoustafaa/PDF-Bookmark-Automator "GitHub - AhmedMoustafaa/PDF-Bookmark-Automator: Generate Automatic PDF bookmarks using OCR and AI refining. · GitHub"
[3]: https://github.com/ahnafnafee/pdf-to-chapters "GitHub - ahnafnafee/pdf-to-chapters: Split PDF textbooks into organized chapter files using AI-powered bookmark and TOC analysis. Supports OpenAI-compatible APIs. · GitHub"
[4]: https://github.com/Krasjet/pdf.tocgen "GitHub - Krasjet/pdf.tocgen: A CLI toolset to generate table of contents for PDF files automatically. · GitHub"
[5]: https://github.com/hueyy/pdf_scout "GitHub - hueyy/pdf_scout: a CLI tool for automatically generating bookmarks for PDF documents (i.e. scouting the PDF document for you) · GitHub"
[6]: https://github.com/anig1scur/tocify "GitHub - anig1scur/tocify: Add or edit PDF bookmarks / Table of Contents online - 快速给 PDF 添加目录 / 书签 · GitHub"
[7]: https://github.com/ifnoelse/pdf-bookmark/blob/master/README-EN.md "pdf-bookmark/README-EN.md at master · ifnoelse/pdf-bookmark · GitHub"
[8]: https://github.com/aminya/tocPDF "GitHub - aminya/tocPDF: Generates bookmarks from the table of contents already available at the beginning of pdf files. · GitHub"
