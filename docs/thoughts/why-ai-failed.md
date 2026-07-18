# 왜 `pdf-md-harness-clean`은 일반적인 책에서 실패했는가

## 진단 범위

이 문서는 [`references/pdf-md-harness-clean`](../../references/pdf-md-harness-clean/)을 일반적인 PDF 책에 적용하기 어려웠던 이유를 진단한다. 분석 근거는 다음 세 종류다.

- harness의 설명, 구현, 테스트와 포함된 세 권의 결과
- [`experiments/experiments.json`](../../experiments/experiments.json)의 관련 실험, 특히 089~102
- `금리의 경제학`을 Windows에서 처리한 `096_pdf_md_harness_interest_economics`

먼저 기록을 정확히 구분할 필요가 있다. `experiments.json`에서 **이 harness 자체를 이름으로 직접 실행한 기록은 096 한 건**이다. 그러나 OCR text layer, heading 후보, hierarchy, position/font 신호, Markdown graph를 같은 목표로 검증한 실험은 여러 건이다. 따라서 “harness를 여러 번 실행했다”기보다 **동일한 PDF 구조 복원 문제를 여러 접근으로 반복 검증했고, harness도 그중 하나로 실패했다**고 표현하는 편이 정확하다.

또한 제목의 “AI 실패”는 엄밀한 명칭이 아니다. 이 harness에서 AI 모델은 주로 OCR 문자 인식을 담당한다. 장·절 탐지와 Markdown 변환은 정규식, 점수 규칙, 책별 map으로 수행된다. 실패의 핵심은 AI의 추론 능력보다는 **OCR 모델, 손실이 큰 중간 표현, 책별 heuristic, 불충분한 평가를 하나의 일반 변환기로 간주한 시스템 설계**에 있다.

## 핵심 결론

`pdf-md-harness-clean`은 일반 PDF-to-Markdown 엔진이 아니라 다음 조건에서 유용한 **책별 반자동 ETL harness**다.

```text
지원되는 로컬 OCR이 안정적으로 실행되고
+ OCR이 읽기 순서를 충분히 보존하고
+ 책이 미리 정의한 장·절 표기 관례와 비슷하고
+ 사람이 boundary/subsection map을 준비하거나 결과를 교정할 수 있을 때
→ 챕터별 Markdown을 재생성한다
```

반대로 새 책에 map 없이 넣어 구조가 자동 복원되는 성질은 검증되지 않았다. 포함된 성공 산출물은 오히려 그 반대를 보여준다.

- 세 권의 `detection-report.json`에 있는 **42개 장 경계가 모두 `source: "boundary-map"`**이다.
- `computer-science-human`의 92개 소절은 `toc` 29개와 기존 리포트를 Vision OCR 텍스트에 다시 맞춘 `vision-title` 63개다.
- `mathematical-statistics`의 47개 소절 중 43개가 `vision-title`이며, 별도의 `subsection-map`도 제공된다.
- 각 `subsection-report.json`의 `source_subsection_report`는 clean bundle 밖의 이전 `outputs/book-md/...` 결과를 가리킨다.

즉, 결과물이 좋아 보이는 것은 “새 책에서 구조를 발견했다”는 증거가 아니다. **이미 알고 있던 구조를 OCR 결과에 투영하여 결과물을 조립했다**는 증거에 가깝다.

## 실패를 네 단계로 분리해야 한다

096은 첫 페이지 OCR에서 중단되었으므로 관측된 직접 실패는 실행 환경 문제다. 그러나 그 오류를 고쳤다고 일반화 문제가 해결되는 것은 아니다. 실패는 최소 네 단계로 나뉜다.

| 단계 | 096에서 관측된 문제 | 오류를 고친 뒤 남는 문제 |
| --- | --- | --- |
| 실행 환경 | 인증서, 한글 사용자 경로, Paddle/oneDNN 호환성 | OS·버전별 재현성과 장시간 작업 복구 |
| OCR | 첫 페이지 추론 실패 | 문자 정확도, bbox, 읽기 순서, 표·수식 |
| 구조 추론 | 실행 전에 도달하지 못함 | 장·절 표기와 layout 다양성 |
| 평가 | 완성 산출물이 없어 실패 판정 | 자동 생성 구조가 맞는지 판단할 gold와 metric 부재 |

이 구분이 중요한 이유는 다음 두 명제가 모두 거짓이기 때문이다.

```text
PaddleOCR이 실행되면 일반적인 책도 변환된다.
Markdown 파일이 생성되면 변환이 성공했다.
```

첫 번째는 구조 정확도를 보장하지 않고, 두 번째는 내용·순서·계층 정확도를 전혀 보장하지 않는다.

## 1. 096은 이식 가능한 pipeline이 아니었음을 드러냈다

[`scripts/test-flight-pdf-md-tool.ps1`](../../scripts/test-flight-pdf-md-tool.ps1)은 Poppler 경로, Paddle model source, cache, `TEMP`와 `TMP`, 전용 venv를 모두 환경별로 고정한다. 실행 중 실제로 다음 문제를 순차적으로 만났다.

1. 사설 인증서 체인 때문에 모델 다운로드 TLS 검증이 실패했다.
2. Paddle C++ 계층이 한글 사용자 홈 경로를 처리하지 못했다.
3. 모델 초기화 뒤 Windows oneDNN/PIR 조합에서 지원되지 않는 attribute 오류가 발생했다.
4. `enable_mkldnn=False`까지 적용했지만 반복되는 호환성 문제 때문에 실험을 중단했다.

이것은 단순 설치 문서 누락이 아니다. harness가 다음 요소를 하나의 안정된 실행 계약으로 묶지 못했다는 뜻이다.

- OS와 CPU backend
- Python, PaddleOCR, PaddlePaddle, PaddleX의 호환 버전
- 모델 download source와 인증서 정책
- non-ASCII 경로
- OCR model cache와 임시 디렉터리

[`ocr_pdf_to_markdown.py`](../../references/pdf-md-harness-clean/ocr_pdf_to_markdown.py)는 PaddleOCR이 없으면 최신 package를 자동 설치한다. 버전 lock과 검증된 조합이 없으므로 같은 코드가 설치 시점에 따라 다른 runtime을 구성할 수 있다. README의 “Windows 10/11, Python 3.10~3.12” 범위는 실제 호환성 보증으로 보기 어렵다.

장시간 작업의 failure isolation도 약하다.

- 전체 대상 페이지를 먼저 임시 PNG로 렌더링한다.
- `paddle_ocr_runner.py`에 모든 이미지 경로를 한 번에 넘긴다.
- 최종 Markdown은 모든 OCR이 끝난 뒤에만 쓴다.
- 페이지별 durable cache, resume manifest, 실패 페이지 재시도 정책이 없다.
- 임시 디렉터리 안의 중간 결과는 오류가 나면 재사용하기 어렵다.

따라서 600페이지 책의 599페이지까지 성공해도 마지막 페이지 오류가 전체 작업 실패와 재실행 비용으로 이어질 수 있다. 이 구조는 “한 페이지 데모”와 “책 전체 production run” 사이의 운영 차이를 흡수하지 못한다.

## 2. OCR 결과를 너무 일찍 평문으로 축소한다

Paddle runner는 OCR 결과에서 `rec_texts`와 `rec_scores`를 읽지만, 실제 다음 단계로 전달하는 것은 **줄바꿈으로 연결한 문자열**뿐이다. JSON에도 line 수와 평균 confidence만 남긴다.

이 과정에서 구조 복원에 필요한 정보가 사라진다.

- 각 line의 bbox와 polygon
- column과 block 소속
- line별 confidence
- font 또는 glyph 크기의 proxy
- 표 cell과 그림 caption 관계
- OCR engine이 반환한 원래 reading order의 근거

그 뒤 [`pdf_to_markdown.py`](../../references/pdf-md-harness-clean/pdf_to_markdown.py)의 `join_wrapped_lines()`가 평문을 다시 문단과 heading으로 추정한다. 그러나 한 번 잃은 geometry는 문자열 규칙으로 복원할 수 없다.

예를 들어 다음 두 페이지는 평문 line sequence가 비슷해질 수 있다.

```text
왼쪽 column 본문 + 오른쪽 column 본문
한 column의 연속된 두 문단
```

반대로 시각적으로 같은 heading도 OCR line wrapping 차이 때문에 다른 문자열이 된다. 따라서 이 pipeline은 **OCR 오류를 구조 추론으로 전달할 뿐 아니라, OCR이 가진 구조 신호까지 의도적으로 폐기**한다.

이는 `experiments.json`의 089 결과와도 일치한다. 실제 heading인 `1.3 확률변수와 확률분포`가 body tier와 같은 font size로 관측되어 heading 후보가 되지 못했다. 즉, 제목과 본문은 단일 관측 신호에서 식별 불가능할 수 있다. 더 적은 정보인 평문만 남기면 이 비식별성은 더 심해진다.

## 3. Markdown 변환 규칙은 layout 변환기가 아니라 문자열 정리기다

`looks_like_heading()`은 대략 다음 항목만 heading으로 인정한다.

- `Chapter`, `Part`, `Appendix`
- `1.2`, `2-1`, `I)` 같은 번호형 문자열
- ASCII 문자의 75% 이상이 대문자이고 10단어 이하인 문자열

이 규칙에는 일반적인 한국어 책의 비번호형 소제목, 장식형 제목, 질문형 제목, 세로쓰기, 두 줄 제목, 제목과 kicker가 분리된 layout이 포함되지 않는다. 반대로 짧은 대문자 표기, running header, 표 label은 heading으로 오인될 수 있다.

문단 복원도 다음과 같은 취약한 가정을 쓴다.

- 빈 줄이면 문단 경계다.
- line 안에 3칸 이상의 공백이 있으면 독립 block이다.
- 나머지 연속 line은 공백 하나로 합친다.
- 숫자만 있는 line은 페이지 번호이므로 버린다.

일반적인 책에서는 이 가정이 서로 충돌한다.

- `pdftotext -layout`의 다중 column 간격은 3칸 이상일 수 있다.
- 들여쓰기, 코드, 표, 각주도 여러 공백을 쓴다.
- OCR은 문단 사이 빈 줄을 안정적으로 보존하지 않는다.
- 수식 번호나 목록 번호만 있는 line은 내용일 수 있다.
- hyphenation, 각주, caption, sidenote를 합칠 규칙이 없다.

따라서 생성된 `.md`가 UTF-8 평문으로 열리는 것과 책의 논리적 reading order가 보존되는 것은 별개다.

## 4. 장 탐지는 매우 좁은 출판 관례를 모델링한다

[`pdf_to_chapters.py`](../../references/pdf-md-harness-clean/pdf_to_chapters.py)의 자동 장 탐지는 다음 가정에 의존한다.

- 장은 `제N장`, `N장`, `Chapter N`, `Chap. N` 형태다.
- 후보는 페이지의 앞쪽 **최대 24개 non-empty line** 안에 있다.
- 한 페이지에서 서로 다른 장 번호가 3개 이상 나오면 TOC-like page다.
- 도입부 표현, 페이지 상단 위치, standalone marker를 정수 점수로 합산한다.
- 장 번호마다 후보 하나를 고른다.
- 강한 후보 사이에 빠진 번호가 있으면 페이지 순서 interval 안에서 약한 후보를 보충한다.
- 같은 페이지에 두 경계가 있으면 하나만 남긴다.

이는 특정 교재에는 합리적인 heuristic이지만 일반적인 책의 불변식은 아니다.

- 장 번호가 없는 에세이·인문서는 탐지할 수 없다.
- `제1부`, `첫째 마당`, 날짜, 인물명, 로마 숫자만 있는 장을 포괄하지 않는다.
- 제목이 이미지이거나 OCR에서 번호만 유실되면 후보가 없다.
- 장 시작 전에 epigraph, illustration, 긴 여백이 있으면 24-line 위치 가정이 달라진다.
- TOC가 페이지당 두 장만 표시되면 `distinct_numbers >= 3` gate가 작동하지 않는다.
- 본문 page에 세 개 이상의 장 번호를 인용하면 TOC로 오인할 수 있다.
- appendix, index, bibliography를 연속 정수 chapter로 강제하면 의미 계층이 변형된다.

특히 `choose_boundaries()`의 “빠진 장 번호를 이웃 장 사이에서 채운다”는 규칙은 정답을 발견하는 것이 아니다. **책이 1, 2, 3… 순서의 정수 장 구조를 가진다는 사전 가정으로 약한 후보를 승격**하는 것이다. 이 가정 밖의 책에서는 조용히 그럴듯한 오답을 만든다.

## 5. 절 탐지는 더 강한 책별 가정을 요구한다

[`split_pdf_subsections.py`](../../references/pdf-md-harness-clean/split_pdf_subsections.py)는 `2.1`, `2-2` 같은 번호형 절을 우선 탐지한다. 이 방식에는 다음 문제가 있다.

- 절 번호와 예제·정리·수식·연습문제 번호의 표면형이 겹친다.
- title에 숫자가 있거나 문장부호로 끝나면 제거하는 규칙은 정상 제목도 버린다.
- 장 안에서 `연습문제`를 한 번 만나면 `exercise_started=True`가 되어 이후 모든 후보를 무시한다. 절마다 연습문제가 반복되는 교재에서는 첫 연습문제 이후의 정상 절을 잃을 수 있다.
- 중복 번호를 억제하려면 사람이 예상 번호를 적은 `subsection-map`이 사실상 필요하다.

번호가 없는 절을 찾는 [`pdf_toc.py`](../../references/pdf-md-harness-clean/pdf_toc.py)도 특정 TOC typography를 전제한다.

- bullet block
- `|`, `｜`, OCR의 `I`, `[` 같은 separator
- line 끝의 page token
- footer의 숫자 line을 이용한 printed-to-physical page mapping
- 깨진 page token을 앞뒤 순서로 보간

이 규칙은 소수의 관측된 TOC 형식을 코드에 옮긴 것이다. dot leader, 다중 column TOC, 제목이 여러 줄인 TOC, page number가 왼쪽에 있는 형식, 로마 숫자 front matter, section별 page numbering, footer가 없는 스캔본에는 안정적인 공통 규칙이 아니다.

## 6. 성공 사례에는 정답 정보가 입력으로 들어갔다

성공 사례의 가장 큰 문제는 **검증 대상과 입력 정답이 분리되지 않았다는 것**이다.

세 권 모두 [`examples/boundary-maps`](../../references/pdf-md-harness-clean/examples/boundary-maps/)에 장 시작 page와 정제된 title 전체가 들어 있다. 수리통계학에는 [`subsection-map`](../../references/pdf-md-harness-clean/examples/subsection-maps/mathematical-statistics.json)까지 있다. 생성된 detection report는 이 map을 그대로 `source: "boundary-map"`으로 기록한다.

따라서 이 결과가 검증한 것은 다음이다.

```text
알고 있는 page range를 따라 OCR text를 파일로 나눌 수 있는가?  → 대체로 그렇다.
새 책의 장·절 경계를 자동으로 찾을 수 있는가?                → 검증하지 않았다.
```

더구나 포함된 최종 결과는 README가 밝히듯 **macOS Vision OCR**로 재생성되었다. 반면 새 책의 기본 실행 경로와 096은 **PaddleOCR on Windows**다. 성공 artifact와 신규 적용이 다음 축에서 동시에 달라졌다.

- OCR engine
- operating system
- 책의 장르와 typography
- 사전 boundary/subsection map의 존재
- 이미 생성된 report의 재사용 여부

이 정도의 distribution shift가 있으면 세 권의 결과를 Paddle 기반 신규 책 처리의 근거로 사용할 수 없다.

## 7. OCR benchmark는 구조 일반화를 평가하지 않았다

[`benchmark_ocr.py`](../../references/pdf-md-harness-clean/benchmark_ocr.py)는 세 권에서 각각 세 페이지, 총 **9페이지**를 고정 표본으로 쓴다. 각 페이지에 사람이 적은 4~5개 anchor 문자열이 OCR 결과에 포함되는지를 세어 `anchor_score`를 만들고 평균이 가장 높은 engine을 winner로 선택한다.

이 평가는 작은 smoke benchmark로는 쓸 수 있지만 “책 전체 Markdown에 가장 적합한 OCR”을 고르기에는 부족하다.

- 표본이 성공 결과를 만든 동일한 세 권에서만 나온다.
- 무작위 표본이나 held-out book이 아니다.
- anchor selection 자체가 사람이 읽기 쉬운 본문 문자열에 편향될 수 있다.
- substring recall만 있고 잘못 삽입된 문자의 precision penalty가 없다.
- CER/WER, reading order, bbox, heading 보존, 표·수식, 장 경계 metric이 없다.
- 9페이지 평균을 300~600페이지 전체 책의 안정성으로 외삽한다.

PaddleOCR이 이 benchmark에서 이기더라도 의미하는 것은 “선택된 9페이지에서 선택된 문자열을 더 많이 포함했다”뿐이다. 장·절 구조를 더 정확히 보존하거나 Windows에서 완주한다는 뜻이 아니다.

## 8. 테스트가 실제 성공 조건을 보장하지 않는다

`tests/test_structure_and_notion.py`의 구조 테스트는 다음 수준이다.

- `"제2장 검색엔진"`과 `"Chapter IV Networks"`가 parser에 맞는지
- 5개의 짧은 synthetic page 문자열에서 두 TOC 항목이 4, 5페이지로 매핑되는지

Paddle 관련 테스트도 주로 설치 command와 dependency 상태를 검사한다. 실제 PDF를 OCR하고, 장·절을 탐지하고, Markdown reading order와 content fidelity를 검증하는 end-to-end corpus test가 아니다.

이 차이는 중요하다.

```text
parser가 의도한 예제에 맞는다 ≠ 일반 책에서 parser가 맞는다
dependency import가 된다      ≠ 수백 페이지 OCR이 완주한다
파일 개수가 맞는다            ≠ 경계와 내용이 정확하다
```

현재 report는 후보 점수와 source를 남기지만, 자동 결과가 실제 목차와 일치하는지 판정하는 acceptance criterion은 없다. 결국 사람이 전체 결과를 읽어야만 성공 여부를 알 수 있다.

## 9. 관련 실험은 이 문제가 단일 heuristic으로 풀리지 않음을 보여준다

`experiments.json`의 후속 실험은 harness보다 더 풍부한 font와 geometry 신호를 사용했지만 일반화 한계를 반복해서 드러냈다.

- **089**: 알려진 heading 5개 중 2개만 깨끗하게 매칭되었고, 실제 heading 하나는 body tier와 구분되지 않았다.
- **093**: joint position/font style의 최선 설정도 bookmark recall 0.6667, matched level accuracy 0.3947이었다.
- **094**: `금리의 경제학`에는 label이 없어 208~731개 후보 중 어떤 설정이 맞는지 자동 선택할 수 없었다.
- **097**: 한 책 안에서 chapter 28개를 완벽히 맞힌 threshold가 나왔지만, 같은 책에서 고른 탐색적 최적값이므로 일반화 근거가 아니라고 기록했다.
- **099**: 반복 위치의 isolation은 실제 bookmark일 가능성을 높여도 coarse chapter level임을 보장하지 못했다.
- **100**: native PDF 두 권에서 body-font position fallback의 supplementary precision이 모두 0이었다.
- **101**: scanned PDF 세 권의 fallback 후보는 자동 gold 없이 manual eye check에 머물렀다.
- **102**: page 100쪽 초과이며 embedded bookmark가 있는 400권에서 더 완성된 production pipeline의 전체 mean F1은 0.4089, clean gold 312권에서도 0.4662였다.

102는 이 harness 자체의 평가가 아니므로 수치를 직접 귀속하면 안 된다. 다만 더 많은 geometry와 font 정보를 보존한 pipeline도 corpus 수준에서 낮은 precision을 보였다는 점은 **문제 자체의 비식별성과 문서 간 이질성**을 보여주는 외부 근거다. 평문과 정규식에 더 크게 의존하는 harness가 별도 증거 없이 더 잘 일반화한다고 기대할 이유는 없다.

## 10. 구조 복원은 관측만으로 유일하게 결정되지 않는다

일반적인 책에 대해 다음 관계를 생각할 수 있다.

```text
원본의 의미 구조 S
  → 출판 layout L
  → PDF/scan D
  → OCR engine E가 만든 관측 O
  → heuristic H(O; θ, book-map)
  → 예측 구조 Ŝ
```

일반화를 위해서는 서로 다른 책에서도 $H(O)$가 $S$를 복원해야 한다. 그러나 현재 harness는 다음 두 종류의 충돌을 해결할 정보가 없다.

### 같은 관측, 다른 의미

- `2.1 확률분포`는 절 제목일 수도 있고 문제 번호가 붙은 문장일 수도 있다.
- 큰 글씨 한 줄은 장 제목, 인용문, 표 제목, 광고 문구 중 하나일 수 있다.
- 반복되는 상단 text는 장 marker일 수도 있고 running header일 수도 있다.

### 다른 관측, 같은 의미

- 장 제목이 텍스트, 이미지, 두 줄 OCR, 세로쓰기, 번호 없는 문구로 나타날 수 있다.
- 같은 TOC가 dot leader, 표, 두 column, bullet, page number 선행형으로 조판될 수 있다.
- 같은 heading level이 장마다 다른 font size나 위치를 사용할 수 있다.

즉, text pattern이나 geometry 하나만으로는 구조가 식별되지 않는다. 책 내부의 반복성, TOC와 본문의 상호 검증, semantic role, 인접 block, page sequence를 함께 보존해도 불확실성이 남는다. 이때 올바른 시스템 동작은 억지로 경계를 확정하는 것이 아니라 **근거와 불확실성을 가진 plan을 만들고 검토 대상으로 보내는 것**이다.

## 11. “일반화 가능한 규칙”과 “책별 설정”의 경계가 흐리다

README는 “고정된 정규식 하나”나 title hardcoding을 쓰지 않는다고 설명한다. 부분적으로는 맞다. 여러 정규식과 fallback을 조합하고 title-map을 분리했기 때문이다. 그러나 일반화 관점에서 더 중요한 질문은 코드 위치가 아니라 **새 책마다 사람이 제공해야 하는 정보량**이다.

boundary map에 모든 장의 번호, 시작 page, title을 넣으면 사실상 top-level bookmark plan을 수동으로 작성한 것이다. subsection map과 이전 report까지 필요하면 구조 discovery의 상당 부분이 이미 끝난 상태다. 이 경우 harness가 재사용하는 것은 구조 추론이 아니라 다음 기능이다.

- PDF/OCR text 추출
- page marker 보존
- 알려진 range별 파일 분할
- Markdown 파일과 report 생성
- 선택적 Notion 업로드

이 기능은 유용하지만 “일반적인 책에서 자동으로 먹힌다”는 주장과는 다른 제품 범주다.

## 12. 실패 원인의 우선순위

관측 증거를 기준으로 원인을 정렬하면 다음과 같다.

1. **성공 증거의 누수**: 성공한 세 권 모두 수동 boundary map을 사용해 자동 structure discovery를 검증하지 않았다.
2. **표현 손실**: OCR bbox와 line-level evidence를 버리고 평문만 후속 구조 추론에 전달했다.
3. **좁은 구조 가정**: 장 번호, TOC separator, footer page number, 절 번호 같은 특정 출판 관례에 의존했다.
4. **평가 부재**: held-out book, manual gold, end-to-end metric 없이 file 생성과 소수 anchor hit를 성공으로 간주했다.
5. **runtime 비재현성**: 자동 최신 설치와 OS별 native backend 차이 때문에 책 전체 OCR 시작조차 보장하지 못했다.
6. **복구 불가능한 실행 단위**: 페이지별 cache/resume 없이 전체 책을 하나의 임시 작업으로 처리했다.

096에서 가장 먼저 드러난 것은 5번이지만, 5번만 고치면 1~4번 때문에 **완주하는 오답 생성기**가 될 가능성이 높다.

## 보존할 가치가 있는 부분

전체 접근을 폐기할 필요는 없다. 다음 설계는 재사용 가치가 있다.

- 원본 PDF page 번호를 Markdown comment로 보존한다.
- OCR, 구조 분할, Notion 업로드를 분리한다.
- `boundary-map`, `title-map`, `subsection-map`을 코드 밖 데이터로 둔다.
- detection/subsection report에 source를 남긴다.
- `--dry-run`으로 쓰기 전에 경계를 검토한다.
- 자동 감지가 불확실하면 수동 map을 허용한다.

다만 이 기능들은 **자동 일반화의 증거**가 아니라 **사람이 교정할 수 있는 반자동 workflow의 구성 요소**로 설명해야 한다.

## 권고

### 1. 제품 범주를 다시 정의한다

현재 harness는 다음처럼 명명하는 것이 사실에 가깝다.

> 알려진 또는 검토된 경계 계획을 이용해 PDF/OCR 텍스트를 page-aware Markdown으로 재조립하는 반자동 harness

“새 PDF를 넣으면 챕터·소챕터 Markdown이 자동 생성된다”는 기대는 제거해야 한다. map 없이 자동 탐지한 결과와 map을 사용한 결과를 같은 성공 사례로 제시해서도 안 된다.

### 2. OCR과 구조 추론 사이에 lossless artifact를 둔다

페이지별로 최소한 다음 정보를 영속화해야 한다.

```text
page number
raw OCR response reference
line/block text
bbox 또는 polygon
reading order
line confidence
engine/model/version
render DPI와 page dimensions
cache key와 status
```

Markdown은 이 artifact의 한 projection이어야 한다. 최초 OCR 단계에서 평문만 남기면 이후 알고리즘을 개선해도 원본을 다시 OCR해야 한다.

### 3. 전체 책 실행을 resumable stage로 나눈다

```text
inspect
→ render/cache per page
→ OCR per page
→ normalize layout
→ infer structure plan
→ validate/review
→ apply/export
```

각 단계는 immutable manifest, 성공/실패 page, 설정과 model version을 남겨야 한다. 한 페이지 실패가 전체 성공분을 지우지 않아야 하며, retry와 cache-only 실행이 가능해야 한다.

### 4. 자동 산출물이 아니라 검토 가능한 plan을 우선한다

장·절 후보마다 다음을 보존해야 한다.

- title, level, PDF page
- source와 confidence가 아닌 **구체적 evidence**
- 후보 bbox와 page crop
- TOC/body/기존 outline 간 일치 여부
- 중복, level jump, page order 같은 attention signal

confidence를 정답 확률처럼 쓰면 안 된다. label이 없는 094처럼 설정 선택이 불가능한 경우에는 자동 확정하지 말고 review queue를 생성해야 한다.

### 5. 평가를 책 단위 held-out protocol로 바꾼다

최소한 다음 평가를 분리해야 한다.

- OCR: CER/WER, line/block recall, reading-order error
- 구조: title/page match precision·recall·F1, level accuracy
- Markdown: 누락·중복 page, paragraph order, 표·수식 보존
- 운영: 완주율, page당 시간, resume 성공률, cache hit

train/tuning과 test는 반드시 PDF 단위로 분리해야 한다. boundary map을 사용한 책은 자동 탐지 test에서 제외하거나 “oracle boundary” 조건으로 별도 보고해야 한다.

### 6. corpus를 구조 유형별로 층화한다

“일반적인 책”은 하나의 분포가 아니다. 최소한 다음 strata를 나눠 성능을 보고해야 한다.

- native text / scanned / OCR overlay
- 한국어 / 영어 / 혼합
- 단일 column / 다중 column
- 번호형 / 비번호형 heading
- prose / textbook / technical / equation-heavy
- TOC 있음 / 없음 / image TOC
- 기존 outline clean / noisy / 없음

전체 평균 하나는 특정 strata의 실패를 가린다. 지원하지 않는 유형은 명시적으로 `needs_review` 또는 `unsupported`로 분류하는 편이 잘못된 자동 결과보다 낫다.

## 최종 판단

`pdf-md-harness-clean`이 일반적인 책에서 잘 먹히지 않은 가장 큰 이유는 OCR engine 선택이 틀려서가 아니다. **세 권의 책에 맞춘 반자동 성공 workflow를 일반 구조 discovery pipeline으로 오해했기 때문**이다.

성공 결과는 수동 boundary map, subsection map, 이전 report와 macOS Vision OCR에 의존했다. 신규 책 경로는 다른 OS와 OCR engine에서 시작했고, geometry를 잃은 평문 위에 좁은 장·절 정규식을 적용했다. 평가는 9페이지 anchor hit와 synthetic parser test에 머물렀다. 이 조건에서는 새 책의 layout과 출판 관례가 달라지는 순간 실패하는 것이 예외가 아니라 예상 동작이다.

따라서 다음 방향이 타당하다.

```text
범용 자동 변환기라는 주장
→ 폐기

책별 반자동 변환 harness
+ lossless OCR/layout artifact
+ resumable execution
+ evidence-rich structure plan
+ book-level held-out evaluation
→ 유지·발전
```

핵심 성공 기준도 “Markdown 파일이 생성되었는가”에서 다음으로 바뀌어야 한다.

> **처음 보는 책에서 사전 boundary map 없이 어느 구조 유형까지 정확히 복원했고, 무엇을 복원하지 못했는지를 근거와 함께 측정할 수 있는가.**
