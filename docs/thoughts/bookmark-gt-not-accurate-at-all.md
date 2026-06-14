# Bookmark 기반 TOC ground truth가 매우 부정확하다는 판단

## 배경

초기 실험의 전제는 다음과 같았다.

```text
기존 bookmark가 있는 PDF는 구조가 이미 사람이 볼 수 있을 만큼 정리되어 있다.
따라서 기존 bookmark title과 target page를 이용하면 PDF 내부 TOC page range도 복원할 수 있다.
복원된 TOC page range는 detector 학습용 silver label로 사용할 수 있다.
```

이 전제에 따라 다음 흐름으로 실험이 진행되었다.

* `001_extract_pdf_signals`에서 기존 bookmark를 추출하고, bookmark가 충분히 정리되어 있는 PDF를 silver label 후보로 보았다.
* `002_label_toc_pages_and_observe_features`에서 bookmark title 기반으로 TOC page label을 만들고 page feature를 관찰했다.
* `003_ensemble_toc_page_labelers`에서 bookmark anchor, printed page number sequence, TOC entry pattern, contiguous window mass, target-page offset consistency를 결합했다.
* `005_tree_toc_page_classifier`와 `006_tree_feature_attribution`에서는 `showcase/outputs/300study_toc_dataset.csv`의 bookmark-guided label을 사실상 ground truth처럼 사용해 tree classifier와 feature attribution을 만들었다.

초기 3개 PDF에서는 사용자 검수 range와 잘 맞았기 때문에 이 방식이 확장 가능하다고 판단했다.
그러나 300study dataset으로 확장한 뒤 랜덤 검수를 해보니 이 판단은 일반화되지 않았다.

## 수동 검수에서 확인된 문제

랜덤으로 뽑은 PDF 단위 label 중 사용자가 직접 확인한 주요 사례는 다음과 같다.

| PDF | bookmark-guided label | 실제 TOC page |
| --- | --- | --- |
| Gilbert Strang - Introduction to Linear Algebra | 2-80 | 3-4 |
| Advances in Active Portfolio Management | 2 | 8-10 |
| Software Architecture with Python | 6-18 | 11-18 |
| 당뇨병 완치 설명서 | 4 | 7-10 |
| 오픈소스 혁명의 목소리 | 27-34 | 30-34 |
| 주식투자 무작정 따라하기 | 7-13 | 15-26 |

이 결과는 단순히 boundary가 1-2 page 어긋난 수준이 아니다.

* `Gilbert Strang - Introduction to Linear Algebra`는 기존 label이 2-80으로 매우 넓게 잡혔지만 실제 TOC는 3-4뿐이다.
* `Advances in Active Portfolio Management`는 기존 label이 2 한 page였지만 실제 TOC는 8-10이다.
* `주식투자 무작정 따라하기`는 기존 label 7-13과 실제 TOC 15-26이 거의 겹치지 않는다.
* 일부 사례는 end page는 맞지만 start page가 크게 앞쪽으로 당겨졌다.
* 일부 사례는 실제 TOC 이전의 front matter나 다른 숫자 패턴이 TOC로 오인된 것으로 보인다.

즉, bookmark-guided label은 `ground truth`가 아니라 noisy weak label이다.
현재 상태에서는 이 label을 학습용 정답으로 쓰면 모델은 실제 TOC page를 배우는 것이 아니라 잘못된 heuristic의 산출물을 모방하게 된다.

## 왜 기존 bookmark로 TOC page를 안정적으로 복원하기 어려운가

기존 bookmark는 본문 chapter / section의 target page를 알려준다.
하지만 PDF 내부에서 TOC가 어느 page에 있는지는 직접 알려주지 않는다.

bookmark-guided TOC page 복원은 다음 간접 가정에 의존한다.

```text
TOC page 안에는 bookmark title과 비슷한 text가 많이 나온다.
TOC line 안의 숫자와 bookmark target page 사이에는 일관된 offset이 있다.
TOC page는 앞부분의 연속된 range로 나타난다.
```

이 가정은 textbook 일부에서는 잘 맞는다.
하지만 실제 PDF corpus에서는 다음 이유로 쉽게 깨진다.

* TOC title과 bookmark title의 표기가 다르다.
* OCR text layer에서 TOC line이 깨져 title과 page number가 분리된다.
* front matter, list of figures, formula sheet, index, bibliography에도 숫자 sequence가 많이 나온다.
* 기존 bookmark가 chapter 시작 page를 가리키지 않고 cover, section, appendix, exercise page 등 다양한 기준을 섞을 수 있다.
* TOC가 여러 종류로 나뉘거나 앞부분이 아닌 곳에 있을 수 있다.
* 한국어 PDF나 스캔 PDF에서는 공백, dot leader, 줄바꿈이 일관되지 않다.
* page text만 보면 좌표 정보가 사라져 TOC layout과 본문 layout을 구분하기 어렵다.

따라서 기존 bookmark는 generated bookmark의 item/page 평가 reference로는 쓸 수 있지만, TOC page detector의 ground truth로는 직접 사용할 수 없다.

## 기존 실험 결과의 재해석

`005_tree_toc_page_classifier`의 결과는 다음처럼 기록되어 있다.

```text
best run은 lightgbm_structural_with_prev_page이며 F1 0.822,
precision 0.904, recall 0.753, ROC-AUC 0.918이다.
```

이 숫자는 더 이상 실제 TOC page detector 성능으로 해석하면 안 된다.
학습 label 자체가 틀렸기 때문이다.

올바른 해석은 다음에 가깝다.

```text
tree classifier는 bookmark-guided weak label heuristic을 어느 정도 모방했다.
하지만 그 weak label이 실제 TOC page와 맞는지는 보장되지 않는다.
```

`006_tree_feature_attribution`도 마찬가지다.
feature importance는 실제 TOC page를 설명하는 feature라기보다, noisy label을 만들어낸 heuristic과 상관된 feature를 보여줄 수 있다.
특히 `toc_keyword_presence`, `mean_line_length`, `prev_mean_line_length` 같은 feature가 중요하게 나온 것은 흥미롭지만, ground truth 검수 없이는 detector 설계의 근거로 삼기 어렵다.

## 앞으로의 label 정책

TOC page detector 학습과 평가는 다음 기준을 따라야 한다.

* `manual_reviewed` 상태의 TOC start/end page만 ground truth로 사용한다.
* bookmark-guided label은 `weak_candidate` 또는 `needs_manual_review`로만 저장한다.
* label 파일에는 최소한 `label_source`, `review_status`, `reviewer`, `reviewed_at`, `notes`를 남긴다.
* ML train/test split에는 검수되지 않은 weak label을 넣지 않는다.
* 기존 `300study_toc_dataset.csv`는 학습용 GT dataset이 아니라 error discovery와 manual labeling queue 생성용으로 재분류한다.

## 접근 방향 전환

기존 로드맵은 TOC-first에 강하게 의존했다.

```text
TOC page detection
→ TOC item parsing
→ printed page offset estimation
→ body heading fuzzy verification
→ bookmark generation
```

이 흐름은 TOC page가 정확히 탐지될 때 강하다.
하지만 지금 확인된 문제는 바로 TOC page ground truth 자체가 부정확하다는 점이다.

따라서 다음 접근을 별도 실험 축으로 추가해야 한다.

```text
TOC page를 먼저 찾지 않는다.
본문 전체에서 chapter 시작 page와 heading title을 직접 찾는다.
word / block box 좌표를 사용해 반복되는 top-level heading layout을 찾는다.
그 결과로 top-level bookmark 후보를 만든다.
```

## Word box 좌표 기반 chapter heading discovery

PyMuPDF에서는 page text를 plain text로만 뽑는 대신 word / block 단위 bbox를 얻을 수 있다.
이 좌표 정보는 TOC page detection보다 chapter 시작 page 탐지에 더 직접적인 신호가 될 수 있다.

chapter 시작 page에서 기대할 수 있는 신호는 다음과 같다.

* 제목 block이 page 상단 또는 일정한 y 좌표 근처에 반복된다.
* 제목 text가 본문보다 짧고, 주변 vertical whitespace가 크다.
* chapter number와 title이 비슷한 bbox 패턴으로 반복된다.
* 본문 paragraph가 시작되기 전 heading 후보의 x/y 위치가 책 안에서 안정적이다.
* running header보다 크거나 본문 block과 다른 위치에 있다.
* 여러 chapter 시작 page에서 비슷한 line height, bbox height, x position, y position이 반복된다.

초기 PoC는 section-level까지 욕심내지 말고 top-level chapter만 목표로 한다.

### 후보 feature

page별 heading candidate에 대해 다음 feature를 만들 수 있다.

```text
pdf_page
text
normalized_text
x0, y0, x1, y1
width, height
page_width, page_height
relative_x0, relative_y0
relative_width, relative_height
line_count
word_count
char_count
font_size proxy
top_margin
bottom_gap_to_next_block
text_numbering_pattern
is_all_caps
starts_with_chapter_keyword
starts_with_numeric_heading
```

PDF 전체에서는 다음 aggregate를 볼 수 있다.

```text
비슷한 y 좌표에 반복되는 heading 후보 cluster
비슷한 text pattern을 가진 후보 cluster
chapter number가 증가하는 후보 sequence
후보 page 간 간격 분포
기존 bookmark top-level page와의 거리
```

### 예상 출력

실험 출력은 사람이 검수하기 쉬워야 한다.

```text
pdf
candidate_rank
pdf_page
heading_text
bbox
cluster_id
score
evidence
nearest_existing_bookmark
page_image_crop_path
```

가능하면 page crop 이미지를 함께 저장해 수동 검수 속도를 높인다.

## 다음 실험 제안

다음 실험은 `experiments/008_word_box_heading_discovery.py` 또는 `009_word_box_heading_discovery.py` 형태가 적합하다.

목표:

```text
수동 검수에서 bookmark-guided TOC label이 틀린 PDF들을 대상으로,
word / block bbox 기반 heading 후보가 실제 chapter 시작 page를 잡을 수 있는지 확인한다.
```

우선 입력 PDF는 이번에 틀린 사례를 포함한다.

* Gilbert Strang - Introduction to Linear Algebra
* Advances in Active Portfolio Management
* Software Architecture with Python
* 당뇨병 완치 설명서
* 오픈소스 혁명의 목소리
* 주식투자 무작정 따라하기

성공 기준은 다음처럼 잡는다.

* top-level chapter 시작 page 후보가 기존 bookmark top-level target과 대체로 가까운가?
* 후보 text가 chapter title로 읽을 수 있는가?
* running header나 본문 소제목을 과하게 뽑지 않는가?
* PDF마다 다른 layout에서도 동일한 feature schema로 후보를 만들 수 있는가?

## 결론

현재 가장 중요한 결론은 다음이다.

```text
bookmark가 있는 PDF에서 복원한 TOC page label은 ground truth가 아니다.
300study dataset에서는 실제로 매우 부정확한 사례가 다수 확인되었다.
이 label로 ML feature와 classifier를 학습하는 것은 실제 문제 해결에 큰 의미가 없다.
```

따라서 기존 bookmark-guided label은 검수 전 후보로 격하한다.
TOC page detector 학습에는 수동 검수된 label만 사용한다.
그리고 TOC page 자체를 찾는 데 실패할 수 있다는 현실을 인정하고, word box 좌표 기반으로 본문 chapter heading을 직접 찾는 unsupervised bookmark generation 접근을 실험해야 한다.
