# 구현 노트: fix: preserve same-page headings in markdown split

## 메타데이터

- 구현 커밋: `ecae9af97ece`
- 전체 커밋 ID: `ecae9af97ece5da2a691eed1b29f5bf79104ebc4`
- 커밋 일시: `2026-07-17T15:47:07+09:00`
- 노트 생성 일시: `2026-07-17 15:47:22 +09:00`

## 변경 배경

- length-limited Markdown은 선택한 bookmark level의 boundary 사이를 하나의
  segment로 만들고, 다음 boundary가 시작하는 page 직전까지만 현재 segment의
  본문으로 소유한다. 이 정책은 같은 PDF page 본문을 여러 node에 복제하지 않기
  위해 필요하다.
- 기존 구현은 소유한 page를 순회할 때만 segment 내부 bookmark heading을
  렌더링했다. 따라서 `L2 Section (p.2)` 다음에 선택된 `L1 Chapter (p.2)`가
  이어지면 Section은 앞 segment의 plan 범위에 속하지만 p.2 본문은 다음
  Chapter가 소유해 어느 node Markdown에도 heading으로 기록되지 않았다.
  `bookmark_plan.json`에는 남아 있어 graph snapshot과 실제 사람이 읽는
  Markdown 내용이 불일치했다.
- 임시 PDF와 기존 embedded outline을 사용하는 `Processor` 전체 경로에서 이
  누락을 재현했다. 수정 전 회귀 테스트는 `## Section Before Next Chapter`의
  출현 횟수가 0이라 실패했다.

## 결정 내용

- **heading 소유권과 page text 소유권을 분리했다.** 현재 segment의 plan 범위에
  속한 bookmark heading은 모두 현재 segment에 남기되, PDF page text는 기존의
  단일-owner 정책을 그대로 유지한다.
- ancestor heading은 content page 범위가 비어 있어도 먼저 렌더링한다. 그 뒤
  기존 page 범위 안의 heading과 본문을 기록하고, 아직 `emitted`에 포함되지 않은
  plan item을 heading-only로 추가한다.
- heading-only 항목도 실제 Markdown payload이므로 max-word level 선택에 쓰는
  `word_count`에 포함한다.
- public API, config, manifest schema와 `max_words_coverage`/deepest fallback
  정책은 변경하지 않았다.

## 작동 방식

- `_render_split_documents()`는 선택한 level마다 `start_index:end_index` plan
  범위와 `content_start_page:content_end_page` 본문 범위를 계산한다.
- 먼저 `_ancestor_indices()` 결과를 원래 Markdown level의 heading으로 쓰고
  `emitted` set에 기록한다. content page가 있으면 각 page에서 아직 쓰지 않은
  heading과 page marker, 추출 text를 기존 순서대로 렌더링한다.
- page loop 뒤에도 `emitted`에 없는 plan item은 다음 boundary와 같은 page에
  있으면서 현재 segment에 속하는 heading이다. 이를 plan 순서대로 heading만
  기록한다. 다음 segment만 해당 page text를 소유하므로 duplicated page는
  발생하지 않는다.
- 기존 outline fast path와 typography/OCR 추론 후 `apply_plan()` 경로가 모두
  같은 `export_markdown_split()`을 사용하므로 두 workflow에 동일하게 적용된다.
  PDF page와 bookmark page 번호는 기존 계약대로 1-based다.

## 검증

- 수정 전 `uv run --no-sync pytest -q tests/test_processor.py -k same_page`:
  신규 회귀 테스트 1개가 heading 출현 횟수 `0 != 1`로 실패해 결함을 고정했다.
- 수정 후 같은 명령: 1개 통과.
- `uv run --no-sync pytest -q tests/test_processor.py
  tests/test_bpe_markdown_split.py tests/test_markdown_graph_export.py
  tests/test_existing_outline_policy.py tests/test_process_cli.py
  tests/test_infer_apply_cli.py`: 관련 테스트 38개 통과.
- `uv run --no-sync pytest -q`: 전체 294개 테스트 통과.
- `uv run --no-sync ruff check src/pdfbooktree/export/markdown.py
  tests/test_processor.py`: 통과.
- `uv run --no-sync ruff format --check src/pdfbooktree/export/markdown.py
  tests/test_processor.py`: 통과.
- 회귀 테스트는 heading이 정확히 한 번 존재하고 `<!-- pdf_page 2 -->` marker도
  정확히 한 번 존재하는지 함께 검사해 heading 보존과 본문 비중복을 고정한다.

## 대안과 제외한 선택지

- 앞 segment가 다음 boundary와 같은 page text까지 소유하게 하는 방식은 page
  text 중복 또는 현재 graph의 last-boundary owner 계약을 깨므로 제외했다.
- 누락 heading을 다음 segment로 옮기는 방식은 원래 plan에서 이전 Chapter의
  하위 item인 heading을 다음 Chapter 내용으로 잘못 귀속하므로 제외했다.
- 실제 node에는 heading을 쓰지 않고 `contained_plan_node_ids`와
  `bookmark_plan.json`에만 남기는 방식은 사람이 읽는 Markdown에서 구조가
  사라진다는 원래 결함을 해결하지 못하므로 제외했다.

## 남은 리스크

- bookmark plan은 page 내부 좌표를 갖지 않으므로 같은 page에서 Section과 다음
  Chapter 사이의 본문을 정확히 나눌 수 없다. 이번 수정은 heading을 보존하지만
  page text는 결정적인 단일-owner 정책을 계속 사용한다.
- `max_words`는 기본적으로 `max_words_coverage=0.95` 목표이며 hard cap이 아니다.
  어떤 bookmark level도 조건을 만족하지 못하면 가장 깊은 level로 fallback하고
  overflow가 남을 수 있다. strict hard-cap은 page/text chunk fallback을 포함한
  별도 정책 변경이 필요하다.
