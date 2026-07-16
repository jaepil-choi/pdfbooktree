# 구현 노트: feat: split production pipeline into analyze/infer/apply stages

## 메타데이터

- 구현 커밋: `cfb8eaed0dd3`
- 전체 커밋 ID: `cfb8eaed0dd3b79717bd243e24336f2b4dc61b70`
- 커밋 일시: `2026-07-16T08:25:08+09:00`
- 노트 생성 일시: `2026-07-16 08:25:13 +09:00`

## 변경 배경

- `docs/handoff/agent-friendly-interface-roadmap.md`의 Phase 2 목표는 production bookmark algorithm 조립 코드를 한 곳에만 두고, plan 생성과 최종 파일 생성을 독립적으로 실행 가능하게 만드는 것이었다.
- 기존 `Processor.run()`은 typography extraction부터 margin exclusion, tiering, geometry, BPE outline, position fallback, validation, PDF/Markdown export까지 한 메서드에서 순서대로 조립했다. 이 조립 순서는 `experiments/102_engine_bookmark_fuzzy_eval.py`의 `_predict_plan()`에도 거의 그대로 복제되어 있어, 두 코드가 갈라질 위험(production drift)이 있었다.
- 로드맵 5.2~5.6에 따라 `PdfAnalysis`/`BookmarkInferenceResult`/`ApplyResult` public data model과 `analyze_pdf()`/`infer_bookmarks()`/`apply_plan()` 함수를 먼저 만들고, `Processor`가 이를 호출하는 facade로 전환하는 것이 이번 커밋의 범위다. CLI(`infer`/`apply` 명령), showcase, `experiments/102`의 단순화는 다음 증분으로 미뤘다.

## 결정 내용

- production 조립 코드가 유일하게 존재하는 새 모듈 `src/pdfbooktree/pipeline.py`를 만들었다. `analyze_pdf()`는 `extract_typography_lines()`만 호출하는 비용이 큰 추출 단계이고, `infer_bookmarks()`는 margin exclusion부터 validate까지의 순수 추론 단계이며, `apply_plan()`은 검증된 plan을 받아 PDF/Markdown만 쓰는 단계다.
- `models.py`에 세 dataclass를 추가했다. `PdfAnalysis`는 `total_pages`를 들고 있어 `infer_bookmarks()`가 별도 `total_pages` 인자 없이 `analysis.total_pages`만 사용하게 했다 - 호출자가 analyze 결과와 다른 `total_pages`를 실수로 넘기는 drift를 원천 차단한다. 반대로 `apply_plan()`은 (미래 `apply` CLI가 plan을 파일에서 읽어 `PdfAnalysis` 없이 호출해야 하므로) `total_pages`를 명시적 인자로 받는다 - 기존 `export_markdown_tree`/`export_markdown_split` 시그니처와 동일한 패턴이다.
- 로드맵 초안이 언급한 `BookmarkInferenceResult.warnings` 필드는 채울 데이터가 없어(현재 유일한 pipeline 경고인 `ocr_policy` 미연결 경고는 `ProcessingConfig` 소관이라 `Processor.run()`에 남겼다) 추가하지 않았다. 죽은 필드를 만들지 않는 쪽을 택했다.
- `BpeHeading`/`PositionFallbackCandidate`가 이미 `models`를 import하므로, `models.py`에서 이 타입을 필드 타입으로 쓰면 순환 참조가 생긴다. `TYPE_CHECKING` 전용 import로 우회했다 - `models.py`는 `from __future__ import annotations`를 이미 쓰고 있어 런타임에는 문자열 annotation이므로 실제 import가 필요 없다.
- `PdfAnalysis.extraction_config_hash`는 기존 `stable_json_hash()`(run manifest의 config hash와 같은 유틸리티)로 계산한다. 새 hashing 로직을 만들지 않고 Phase 1에서 이미 검증된 것을 재사용했다.

## 작동 방식

- `Processor.run()`은 existing-outline fast path(`_export_existing_outline`, 무변경)를 먼저 확인한 뒤, `analyze_pdf(input_pdf, config.typography)` -> `infer_bookmarks(analysis, config.typography)` -> (`write_artifacts`) -> `apply_plan(input_pdf, output_dir, inference.plan, analysis.total_pages, config.markdown_split)` 순으로 호출한다.
- `analyze_pdf()`는 `fitz.open()`으로 page 수만 읽고 바로 닫은 뒤 `extract_typography_lines()`를 호출한다. `Processor.run()`도 existing-outline 여부 판단을 위해 최상단에서 한 번 더 `fitz.open()`을 연다 - 이는 새 회귀가 아니라 리팩터링 전에도 `total_pages`용 open과 `extract_typography_lines()` 내부 open이 각각 있었던 기존 동작을 그대로 유지한 것이다.
- `infer_bookmarks()`는 margin exclusion -> font/height tier -> geometry context -> heading candidate(`select_geometry_headings`) -> BPE outline(`infer_bpe_outline` + `normalize_bookmark_plan`) -> position fallback(설정에 따라 조건부) -> normalize -> `validate_bookmark_plan`을 순서대로 실행하고 `BookmarkInferenceResult`를 반환한다. 이 함수는 disk에 아무것도 쓰지 않는다.
- `apply_plan()`은 받은 plan을 `validate_bookmark_plan()`으로 한 번 더 검증한다. 검증에 실패하면 `output_pdf`/`output_markdown_dir`가 모두 `None`인 `ApplyResult`를 돌려주고 아무 파일도 쓰지 않는다. 검증에 성공하면 `export_bookmarked_pdf()`와 (`markdown_split` 유무에 따라) `export_markdown_split()` 또는 `export_markdown_tree()`를 호출한다. typography extraction 관련 함수는 이 함수 안에서 import조차 하지 않는다.
- `Processor._write_artifacts()`는 개별 지역 변수 7개를 받던 시그니처를 `BookmarkInferenceResult` 하나를 받는 시그니처로 바꿨을 뿐, 실제로 쓰는 artifact 7개(`whole_book_lines`, `font_size_tiers`, `height_tiers`, `heading_candidates`, `position_fallback_candidates`, `bookmark_plan`, `bookmark_plan_validation`)와 파일명은 그대로다.

## 검증

- `tests/test_pipeline_parity.py`: 리팩터링 **전** `Processor.run()`을 9페이지·3챕터(28pt/16pt font-tier heading + 10pt 반복 position-fallback marker) fixture로 실제 실행해 얻은 plan(title/page/level/source)을 golden 값으로 박제했다. 리팩터링 후에도 이 assertion을 그대로 통과시켜 "동작 무변경"을 증명했다. existing-outline fast path가 `extract_typography_lines`를 호출하지 않는지도 `monkeypatch`로 확인했다.
- `tests/test_pipeline.py`: `analyze_pdf`/`infer_bookmarks`/`apply_plan` 9개 단위 테스트. `extraction_config_hash`가 관련 config 변화에 반응하는지, `infer_bookmarks`가 margin 아티팩트를 실제로 제거하는지, `position_fallback_enabled` on/off에 따라 `fallback_candidates`가 갈리는지, `infer_bookmarks().validation`이 독립 `validate_bookmark_plan()` 호출과 같은지, `apply_plan`이 무효 plan에서는 아무것도 안 쓰는지, typography extraction을 다시 호출하지 않는지, `markdown_split` 설정이 반영되는지를 검증했다.
- `tests/test_import_contract.py`에 새 public export 6개(`analyze_pdf`, `infer_bookmarks`, `apply_plan`, `PdfAnalysis`, `BookmarkInferenceResult`, `ApplyResult`) assertion을 추가했다.
- `uv run pytest`: 159 passed (기존 148 + 신규 11, 기존 테스트 assertion은 하나도 수정하지 않고 통과).
- `uv run ruff check src tests`: 통과.
- `uv run ruff format --check src tests`: 통과.
- `uv run --no-sync pdfbooktree process --help`: 정상 동작 확인. `import pdfbooktree`로 새 export 6개가 실제로 노출되는지 확인.
- showcase는 이번 커밋에서 실행하지 않았다 - 로드맵 5.8의 showcase는 `infer -> inspect -> apply` public CLI 워크플로를 요구하는데, 이번 증분은 CLI를 추가하지 않았다. showcase는 `infer`/`apply` CLI를 추가하는 다음 증분에서 함께 실행하기로 했다.

## 대안과 제외한 선택지

- `analyze_pdf`/`infer_bookmarks`/`apply_plan`을 기존 `typography/`, `outline/`, `export/` 서브패키지 중 하나에 끼워 넣지 않고 새 최상위 모듈 `pipeline.py`를 만들었다. 기존 서브패키지 중 하나에 넣으면 "조립 코드가 그 서브패키지의 하위 기능"이라는 잘못된 인상을 주고, `processor.py`와 미래 `cli.py`가 순환 없이 import할 수 있는 위치가 필요했기 때문이다.
- `BookmarkInferenceResult`에 로드맵 초안이 제안한 `warnings` 필드를 추가하지 않았다. 지금 채울 데이터가 없는 필드를 만들면 나중에 아무도 채우지 않는 죽은 필드가 될 위험이 있다고 판단했다. 필요해지면 그때 추가한다.
- `infer_bookmarks()`가 `total_pages`를 별도 인자로 받는 대신 `PdfAnalysis.total_pages`를 쓰게 했다. 별도 인자로 받으면 `analyze_pdf()`가 관측한 값과 다른 값을 호출자가 실수로 넘길 수 있는 여지가 생긴다.
- `experiments/102_engine_bookmark_fuzzy_eval.py`의 `_predict_plan()`을 `infer_bookmarks()` 호출로 단순화하는 작업은 이번 커밋에 포함하지 않았다. 실험 파일은 이 저장소 규칙상 구현 노트나 별도 테스트 대상이 아니고, 로드맵도 이 정리를 필수 완료 조건에 넣지 않았다.
- CLI(`infer`/`apply` 명령)는 함수 분리와 동시에 만들지 않았다. 내부 계약(함수 시그니처, data model)을 먼저 고정하고 나서 표면적(CLI)을 넓히는 순서가 더 안전하다고 판단했다.

## 남은 리스크

- `experiments/102_engine_bookmark_fuzzy_eval.py`의 `_predict_plan()`은 아직 `infer_bookmarks()`를 호출하도록 단순화되지 않았다 - production 조립 순서가 바뀌면 이 실험 파일이 조용히 낡은 로직을 계속 쓸 수 있다.
- `infer`/`apply` CLI가 아직 없어 이 세 함수는 Python API로만 호출 가능하다. 로드맵 5.7의 CLI와 5.8의 showcase는 다음 증분 과제로 남아 있다.
- `Processor.run()`은 여전히 `analyze_pdf()`가 내부적으로 다시 여는 것과 별개로 최상단에서 한 번 더 `fitz.open()`을 연다. 리팩터링 전부터 있던 중복이라 이번 범위에서 고치지 않았지만, 성능이 문제가 되면 `total_pages`를 `analyze_pdf()` 결과에서만 얻도록 정리할 여지가 있다.
- `ocr_policy`는 여전히 `pipeline.py`의 어떤 함수와도 연결되지 않았다. `Processor.run()`에 남아 있는 경고 메시지로만 존재를 알린다.
- Phase 0의 나머지 항목(대표 native/OCR PDF의 artifact contract, 기존 `process` CLI/Python 결과의 golden test)은 이번 parity test 범위 밖이라 여전히 미완료다.
