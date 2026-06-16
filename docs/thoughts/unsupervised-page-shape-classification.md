# Unsupervised page shape classification 기반 bookmark 생성 아이디어

## 배경

기존 접근은 PDF 내부 TOC page를 먼저 찾고, TOC item을 parsing한 뒤, 본문 heading과 연결해 bookmark를 생성하는 흐름이었다.
하지만 `bookmark-gt-not-accurate-at-all.md`에서 확인했듯이 bookmark-guided TOC page label은 실제 ground truth로 쓰기 어려울 정도로 부정확했다.

따라서 다음 실험 축이 필요하다.

```text
TOC page를 먼저 찾지 않는다.
text 내용이나 chapter keyword에 강하게 의존하지 않는다.
PDF page의 box 공간 패턴과 box 크기 분포를 유형화해 chapter start page를 찾는다.
```

이 접근의 목표는 완성된 bookmark tree를 한 번에 만드는 것이 아니다.
먼저 수동 검수 가능한 `bookmark item - page` 후보를 robust하게 생성하는 것이다.

## 핵심 관점

PDF를 text sequence가 아니라 page shape sequence로 본다.

각 page는 다음과 같은 box geometry의 집합이다.

```text
text block bbox
line bbox
word bbox
box size
box 위치
box 간 여백
box 밀도
page 내 점유 영역
```

chapter start page는 특정 단어나 번호 패턴으로 정의하지 않는다.
대신 다음과 같은 page shape 특성으로 탐지한다.

* 일반 본문 page와 다른 box 밀도와 여백을 가진다.
* page 안에 상대적으로 두드러진 box 또는 box group이 있다.
* 이전 page와 layout이 크게 바뀐다.
* 이후 page들은 다시 일반 본문 layout으로 수렴한다.
* 책 전체에서 비슷한 transition motif가 반복된다.

즉, chapter start는 단일 page classification 문제가 아니라 `page shape sequence` 안에서 반복되는 boundary motif를 찾는 문제다.

## 일부러 약하게 쓰거나 배제할 신호

초기 실험에서는 다음 신호를 hard rule로 쓰지 않는다.

* `Chapter`, `제1장`, `Part`, `Section` 같은 keyword
* `1`, `1.1`, `I`, `제1부` 같은 numbering pattern
* 제목은 항상 page 상단에 있다는 가정
* chapter 간 page 간격은 일정하다는 가정
* 기존 bookmark target page와 가까워야 한다는 가정

이 신호들은 나중에 evidence나 tie-breaker로 쓸 수는 있다.
하지만 page shape classification의 핵심 판단 근거로 두면 corpus가 바뀔 때 쉽게 깨질 수 있다.

## Page shape feature

각 page는 text 의미를 거의 제거한 geometry feature vector로 표현한다.
좌표와 크기는 page width/height로 normalize한다.

후보 feature는 다음과 같다.

```text
page_width
page_height
box_count
line_count
word_count
content_bbox_x0
content_bbox_y0
content_bbox_x1
content_bbox_y1
content_bbox_width
content_bbox_height
content_area_ratio
top_whitespace_ratio
bottom_whitespace_ratio
left_whitespace_ratio
right_whitespace_ratio
box_area_sum_ratio
box_area_mean
box_area_median
box_area_p90
box_height_mean
box_height_median
box_height_p90
box_width_mean
box_width_median
box_width_p90
vertical_gap_mean
vertical_gap_median
vertical_gap_p90
horizontal_alignment_entropy
vertical_position_entropy
occupancy_grid_4x4
occupancy_grid_6x6
large_box_count
sparse_region_count
```

`occupancy_grid`는 page를 고정 격자로 나눈 뒤 각 cell에 box area가 얼마나 들어가는지 기록한다.
이 feature는 언어, OCR text 품질, font name에 덜 민감하다.

## Page furniture 제거

running header, footer, page number는 text 내용과 무관하게 반복되는 page furniture다.
chapter start 후보를 찾기 전에 최대한 제거해야 한다.

초기 실험에서는 다음 방식으로 제거한다.

```text
각 page의 box를 normalized bbox로 변환한다.
비슷한 위치와 크기의 box가 여러 page에서 반복되면 furniture 후보로 본다.
상단/하단 영역에 반복되는 작은 box에는 더 강한 furniture score를 준다.
furniture score가 높은 box는 page shape feature 계산에서 제외하거나 별도 feature로 분리한다.
```

중요한 점은 text equality를 필수 조건으로 쓰지 않는 것이다.
OCR이나 running header text가 page마다 달라도, 위치와 크기가 반복되면 furniture로 볼 수 있어야 한다.

## Page shape clustering

PDF마다 page shape feature를 만들고, 같은 PDF 안에서 page들을 cluster한다.
전역 모델을 먼저 만들기보다 PDF 내부의 상대적 layout 차이를 우선 사용한다.

초기 cluster는 다음 방법이 적합하다.

```text
feature robust scaling
PCA 또는 UMAP 없이 먼저 직접 clustering
HDBSCAN이 있으면 HDBSCAN
의존성을 늘리지 않으려면 scikit-learn의 DBSCAN, AgglomerativeClustering, KMeans 비교
```

현재 dependency에는 scikit-learn이 있으므로 첫 실험은 `KMeans`와 `AgglomerativeClustering`만으로 충분하다.
cluster 수는 고정값 하나로 단정하지 않고 PDF page 수에 따라 작은 후보군을 비교한다.

예시는 다음과 같다.

```text
n_clusters = min(8, max(3, sqrt(page_count)))
```

cluster에는 사람이 이해할 수 있도록 사후 label을 붙인다.

```text
dense_body_like
sparse_opener_like
list_like
image_or_table_like
blank_like
unknown
```

이 label은 알고리즘의 ground truth가 아니라 검수 편의를 위한 설명이다.

## Chapter start scoring

page `i`가 chapter start인지 판단할 때 page 하나만 보지 않는다.
주변 window를 함께 본다.

```text
i-2, i-1, i, i+1, i+2, i+3
```

초기 score는 다음 요소를 조합한다.

```text
layout_outlier_score
transition_from_previous_score
following_body_convergence_score
opener_shape_score
recurring_motif_score
salient_box_score
```

### layout_outlier_score

page `i`의 feature vector가 PDF의 일반 body-like page 중심에서 얼마나 떨어져 있는지 본다.
body-like cluster는 가장 page 수가 많고 text density가 높은 cluster로 추정한다.

### transition_from_previous_score

`i-1`과 `i`의 feature distance, cluster change 여부, content bbox 변화량을 본다.
chapter start는 보통 이전 page와 shape가 달라지는 boundary다.

### following_body_convergence_score

`i+1`, `i+2`, `i+3` 중 일부가 body-like cluster로 돌아오면 점수를 준다.
chapter opener 다음에 본문이 이어지는 구조를 잡기 위한 신호다.

### opener_shape_score

page `i`가 일반 body보다 더 sparse하거나, 큰 vertical whitespace를 가지거나, salient box가 두드러지면 점수를 준다.
단, page 상단 고정 위치 같은 hard rule은 두지 않는다.

### recurring_motif_score

`cluster(i-1), cluster(i), cluster(i+1)` 또는 feature transition pattern이 PDF 안에서 여러 번 반복되면 점수를 준다.
chapter start는 책 안에서 한 번만 나타나는 이상치보다 반복되는 boundary motif일 가능성이 높다.

### salient_box_score

page `i`에서 furniture를 제거한 뒤 가장 두드러지는 box group이 있는지 본다.
두드러짐은 text 의미가 아니라 box 크기, 주변 여백, 해당 page shape에 대한 기여도로 계산한다.

## Bookmark item 생성

chapter start page 후보를 고른 뒤, 해당 page 안에서 bookmark title 후보 box를 선택한다.
이 단계에서도 text pattern을 먼저 보지 않는다.

title box 후보는 다음 기준으로 고른다.

```text
furniture가 아니다.
page shape feature에 큰 영향을 준 box 또는 box group이다.
주변 vertical whitespace가 크다.
body-like line들과 크기나 위치가 다르다.
같은 opener motif page들에서 비슷한 위치와 크기로 반복된다.
```

최종 title text는 선택된 box group의 text를 읽어서 만든다.
OCR 품질이 낮으면 title이 깨질 수 있으므로, 이 실험에서는 title text 품질보다 `page 후보가 맞는지`와 `crop 검수가 가능한지`를 우선한다.

## 실험 출력

실험은 사람이 검수하기 쉬운 산출물을 만든다.

```text
experiments/outputs/009_unsupervised_page_shape_classification/
  summary.json
  page_shapes.csv
  page_shape_clusters.csv
  chapter_start_candidates.csv
  title_box_candidates.csv
  existing_bookmarks_reference.csv
  crops/
```

`chapter_start_candidates.csv`는 다음 column을 가진다.

```text
pdf
page_number
rank
score
layout_cluster_id
prev_cluster_id
next_cluster_id
layout_outlier_score
transition_from_previous_score
following_body_convergence_score
opener_shape_score
recurring_motif_score
salient_box_score
selected_title_text
selected_title_bbox
crop_path
evidence
```

`title_box_candidates.csv`는 page별 title 후보를 여러 개 남긴다.

```text
pdf
page_number
candidate_rank
text
bbox
salience_score
whitespace_score
furniture_score
cluster_consistency_score
crop_path
```

기존 bookmark가 있는 PDF에서는 `existing_bookmarks_reference.csv`를 별도로 저장한다.
다만 이 정보는 생성 알고리즘에는 넣지 않고, 나중에 수동 비교와 참고 분석에만 사용한다.

## 구현 계획

첫 구현은 단일 monolithic experiment script로 만든다.
패키지화하지 않고 `experiments/009_unsupervised_page_shape_classification.py`에 둔다.

구현 순서는 다음과 같다.

1. `data/` 아래 PDF 목록을 수집한다.
2. PyMuPDF로 page별 block/line/word bbox를 추출한다.
3. normalized bbox와 page geometry feature를 만든다.
4. geometry 기반 page furniture 후보를 찾는다.
5. furniture 제거 전후의 page shape feature를 모두 저장한다.
6. PDF별 page shape clustering을 수행한다.
7. cluster별 summary를 계산해 body-like cluster를 추정한다.
8. page window 기반 chapter start score를 계산한다.
9. score 상위 page에서 salient title box 후보를 고른다.
10. page crop과 title box crop 이미지를 저장한다.
11. CSV와 summary JSON을 저장한다.
12. `experiments/experiments.json`에 실험 목적, 입력, 출력, finding을 기록한다.

## 검증 관점

이 실험의 검증은 자동 metric보다 manual review 중심이다.
사용자는 다음 질문에 답하면 된다.

* top-ranked page들이 실제 chapter start page인가?
* page는 맞지만 title box가 틀렸는가?
* title box는 맞지만 text extraction이 깨졌는가?
* running header/footer가 후보로 많이 섞이는가?
* TOC, list of figures, bibliography, index 같은 list page가 chapter start로 오인되는가?
* indexed PDF와 not-indexed PDF에서 실패 양상이 다른가?

이 검수 결과를 다음 실험에서 score weight와 feature를 조정하는 근거로 사용한다.

## 기대 효과

이 방식은 다음 가정에 덜 의존한다.

```text
TOC page가 존재한다.
TOC page를 정확히 찾을 수 있다.
chapter 제목에 특정 keyword가 있다.
번호 패턴이 안정적이다.
영어/한국어 제목 표기가 일정하다.
기존 bookmark가 chapter start를 정확히 가리킨다.
```

대신 PDF 내부의 더 원초적인 신호를 사용한다.

```text
box가 어디에 놓였는가
box가 얼마나 큰가
box 사이 여백이 어떤가
page shape가 언제 바뀌는가
그 변화가 책 안에서 반복되는가
```

따라서 이 실험은 corpus가 다양해질수록 TOC-first 방식보다 더 robust한 bookmark generation 기반이 될 가능성이 있다.
