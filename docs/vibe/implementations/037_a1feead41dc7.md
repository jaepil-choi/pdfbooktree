# 구현 노트: feat: merge adjacent same-tier heading lines before candidate extraction

## 메타데이터

- 구현 커밋: `a1feead41dc7`
- 전체 커밋 ID: `a1feead41dc706f8cdeb6f4801ec9b9232e3d1b5`
- 커밋 일시: `2026-07-09T09:25:48+09:00`
- 노트 생성 일시: `2026-07-09 09:25:54 +09:00`

## 변경 배경

- 실험 072(Zvi Bodie Investments, native-pdf-indexed, ground truth bookmark 793개)에서
  069의 stack 기반 hierarchy 알고리즘에 parent_idx 추적을 추가해 실제 nested tree를
  만들고, 절대 level 정수 대신 상대적 부모-자식 관계로 평가하는 `parent_accuracy`를
  도입해 재평가했다. 그 결과 `parent_mismatch_sample`을 까본 과정에서, 실제 책의
  chapter 표제가 `'The Investment'` / `'Environment 1 PART I'`처럼 같은 font
  size(36pt)의 서로 다른 line 두 개로 렌더링된다는 사실을 확인했다.
- line 하나 = heading 후보 하나로 다루는 기존 방식에서는 ground-truth title과의
  fuzzy 매칭이 이 fragment 중 하나에만 꽂히고, 그 fragment의 stack 부모가 front
  matter 잔재라서 하위 섹션 전체의 parent 추론이 연쇄로 어긋났다.
- 사용자 지적: "같은 페이지에서 붙어있고(neighboring line) 같은 font size면 한
  덩어리로 봐야 한다." 이 병합 책임을 어느 모듈이 가져야 하는지 검토한 결과,
  `typography/lines.py`(전체 tiering 통계에도 쓰이는 raw line 계약을 유지해야 함)가
  아니라 `typography/headings.py`(heading 후보를 만들기 직전 단계)가 맞는 자리라고
  판단했다.
- 실험 073에서 no_merge / merge_gap1.5 / merge_nogap 세 변형을 mode_only /
  mode_and_smaller 두 body_mode에 A/B로 적용해, gap 게이트가 있어도 없어도
  `parent_accuracy`가 일관되게 개선됨을 Bodie 전체 책(1041p)에서 확인한 뒤 이
  구현에 반영했다.

## 결정 내용

- `extract_heading_candidates`(공개 인터페이스, 시그니처 불변)의 내부에 새 전처리
  단계로 `_merge_adjacent_same_tier_lines`를 추가했다. 이미 계산돼 함수에
  전달되는 `font_tiers`(TierSet)를 그대로 재사용해 tier를 판단하므로 별도의 통계
  재계산이 없다.
- 병합 대상은 "같은 page + 같은 font tier + 수직 gap이
  `max(두 line height) * heading_merge_gap_ratio` 이하"인 line이다. gap 게이트를
  둔 이유는, 게이트 없이 같은 tier면 무조건 합치면 페이지 안에서 멀리 떨어진
  무관한 텍스트(예: 서로 다른 pull quote)까지 하나로 묶일 위험이 있기 때문이다
  (합성 데이터로 직접 재현: `experiments/073_heading_line_merge_bodie.py`의
  `merge_adjacent_same_tier_lines` 단위 테스트에서 gap 게이트가 없을 때만 무관한
  두 텍스트가 잘못 합쳐지는 것을 확인했다). Bodie 실측에서는 게이트가 있어도
  없어도 결과가 거의 같았지만(오히려 게이트가 없을 때 parent_accuracy가 미세하게
  더 높았다), 일반화 위험을 줄이기 위해 게이트를 유지하는 쪽을 택했다.
- `heading_merge_gap_ratio` 기본값 1.5는 실험 073에서 실제로 검증한 값을 그대로
  사용했다(임의로 고른 값이 아니다).
- 병합은 `_repeated_margin_text`/`_is_repeated_margin_line`으로 러닝 헤더/푸터를
  먼저 걸러낸 뒤에 수행하도록 순서를 바꿨다. 원래는 후보를 만드는 메인 루프 안에서
  margin line을 걸렀는데, 병합을 먼저 하면 margin line이 실제 heading과 같은
  tier·인접 위치에 있을 때 잘못 합쳐질 수 있어 margin 필터링을 병합보다 앞으로
  옮겼다.
- 병합된 `TypographyLine`의 `font_size`/`height`는 두 line의 median으로 잡았다
  (bbox 전체 union height를 쓰면 height_tier 판정이 왜곡될 수 있어서 대표값 성격을
  유지했다). `text`는 공백으로 이어붙인 뒤 `normalize_text`로 정규화한다.

## 작동 방식

1. `Processor.run()` -> `extract_typography_lines`로 raw line 목록을 만들고
   `compute_tier_set`으로 font/height tier를 계산한다(변경 없음).
2. `extract_heading_candidates(lines, font_tiers, height_tiers, config)` 내부에서:
   - `_repeated_margin_text`/`_is_repeated_margin_line`으로 반복되는 여백 텍스트를
     먼저 제거한다.
   - `_merge_adjacent_same_tier_lines(kept_lines, font_tiers, gap_ratio)`가 남은
     line을 순서대로 훑으며, 같은 page + 같은 tier + gap 조건을 만족하는 연속된
     line을 `_combine_lines`로 하나씩 누적 병합한다.
   - 병합된 line 목록 위에서 기존 title-shape 검사, tier evidence, numbering,
     confidence scoring, `_dedupe_page_titles`가 그대로 동작한다(이 부분은
     변경하지 않았다).
3. 병합은 tier가 다르거나 page가 바뀌거나 gap이 게이트를 넘으면 즉시 끊긴다 —
   3개 이상의 line이 연쇄로 병합될 수도 있다(순차적으로 계속 이어붙임).

## 검증

- `uv run pytest` — 전체 58개 테스트 통과. 이번 커밋에서
  `test_extract_heading_candidates_merges_adjacent_same_tier_heading_lines`(인접
  헤딩 line이 합쳐지는 것)와
  `test_extract_heading_candidates_does_not_merge_lines_with_large_gap`(gap이 크면
  합쳐지지 않는 것) 2개를 `tests/test_typography_pipeline.py`에 추가했다.
- `uv run ruff check` / `uv run ruff format --check` — 통과.
- showcase 011(`showcase/011_heading_line_merge_live.py`)로 synthetic이 아닌 실제
  Zvi Bodie Investments PDF에 `Processor(skip_existing_bookmarks=False)`를 실행해
  라이브 검증했다. page 30의 실제 raw line이 `'The Investment'` /
  `'Environment 1 PART I'`로 쪼개져 있었고, 병합 후
  `heading_candidates.json`에는 `'The Investment Environment 1 PART I'` 단일
  candidate로 합쳐졌다. `raw_line_split_confirmed`,
  `merged_candidate_exists`, `no_lone_fragment_candidate` 3개 proof 모두 True.
- 실험 073에서 이 로직(실험 monolithic 버전)을 Bodie 전체 책 6개 조합(2
  body_mode × 3 merge variant)에 돌려 `parent_accuracy`/`recall` 개선을 사전
  확인했다.

## 대안과 제외한 선택지

- **`typography/lines.py`에서 병합**: 기각. `lines.py`가 만드는 line은 heading
  뿐 아니라 `compute_tier_set`의 책 전체 font_size KDE 분포 계산에도 쓰인다.
  여기서 인접 line을 미리 합치면 body 문단(같은 font_size로 줄바꿈된 일반
  텍스트)까지 한 덩어리가 돼 tier 통계 자체가 왜곡된다.
- **gap 게이트 없이 무조건 병합(merge_nogap)**: 실험 073에서는 Bodie 한 권 기준
  결과가 게이트 있는 쪽과 거의 같거나 미세하게 더 나았지만, 합성 케이스로
  재현했듯 무관한 같은 tier 텍스트를 잘못 합칠 위험이 있어 채택하지 않았다.
  단일 책 실측만으로 게이트를 제거하기엔 근거가 부족하다고 판단했다.
- **outline/infer.py의 stack 알고리즘부터 productionize**: 069~073에서 검증한
  stack 기반 level 부여(parent_idx 포함) 알고리즘은 아직 `src/`에 반영하지
  않았다. 현재 `outline/infer.py`는 numbering/tier 기반의 더 단순한 방식을 쓴다.
  이번 커밋은 그 알고리즘 교체와 무관하게, heading 후보 생성 단계의 독립적인
  버그(line 분할)만 먼저 고치는 것으로 범위를 좁혔다.

## 남은 리스크

- `heading_merge_gap_ratio=1.5`는 책 1권(Zvi Bodie Investments)에서만 검증했다.
  다른 레이아웃(예: 2단 컬럼, 매우 촘촘한 행간)에서는 값이 너무 관대하거나
  너무 엄격할 수 있다.
- 병합된 heading의 `y0`/`y1`은 첫 줄의 최솟값과 마지막 줄의 최댓값으로 잡히므로,
  `y_center_ratio` 기반 evidence("top_page_position")가 병합 전보다 더 넓은
  범위를 대표하게 된다 — 극단적으로 긴 병합(여러 줄)에서는 이 evidence가 부정확할
  수 있다.
- `outline/infer.py`가 아직 069~073의 stack/parent_idx 알고리즘을 쓰지 않기
  때문에, 이번 병합의 효과가 실제 `infer_outline` 결과(현재는 numbering/tier
  기반 level 부여)에 072/073만큼 크게 드러나지 않을 수 있다. stack 알고리즘
  productionize는 별도 작업으로 남아 있다.
