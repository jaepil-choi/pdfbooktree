---
name: use-pdfbooktree
description: 이 저장소의 pdfbooktree Python API와 CLI를 사용해 PDF 책을 조사하고, 스캔 여부를 분류하고, OCR text layer를 만들거나 재사용하고, 북마크 계획을 추론·검토·적용하고, 북마크 PDF와 계층형 또는 길이 제한 Markdown을 생성하며, 디렉터리를 batch 처리하고, 설정·실행 manifest·artifact·계획 차이를 점검한다. Codex가 이 저장소에서 PDF 구조화, OCR overlay, 기존 outline 품질, bookmark plan, Markdown export, batch run, CLI 자동화 또는 pdfbooktree Python 통합을 다룰 때 사용한다.
---

# pdfbooktree 사용

## 기본 원칙

- 저장소 루트에서 모든 실행 명령을 `uv run`으로 호출하라. CLI는 `uv run pdfbooktree ...`, Python 파일은 `uv run python ...` 형식을 사용하라.
- pip로 설치한 package를 새 project에서 사용할 때 skill이 없다면 project root에서 `pdfbooktree skill install`을 한 번 실행하라.
- PowerShell 문법으로 예시와 명령을 작성하라.
- 입력 PDF와 결과 artifact를 먼저 조사하고, 사용자 목적에 맞는 가장 작은 workflow를 선택하라.
- 외부에 표시하는 PDF page는 항상 1부터 시작하는 값으로 다루라.
- 정확한 현재 옵션이 필요하면 `uv run pdfbooktree <command> --help`와 `uv run pdfbooktree config explain`을 실행하라. 이 스킬과 코드가 다르면 현재 코드와 테스트를 우선하라.

## Workflow 선택

1. 입력을 빠르게 파악하려면 읽기 전용 `inspect page-count`, `inspect text`, `inspect bookmarks`를 사용하라.
2. 디렉터리의 PDF를 선별하려면 `classify-scan`을 사용하라. 스캔 PDF이면서 의미 있는 bookmark가 없는 항목이 OCR batch target이다.
3. OCR batch에서 일정 길이 이상의 책만 대상으로 삼으려면 `--min-page-count N`을 사용하라. `page_count >= N`인 문서만 target이 되며, 실제 호출 전 확인에는 `--dry-run`을 함께 사용하라.
4. 추출 가능한 text가 없거나 부족하면 북마크 추론 전에 `ocr-overlay` 또는 `ocr-overlay-batch`를 별도 전처리로 실행하라. `ProcessingConfig.ocr_policy`는 현재 `never`만 지원하며 `auto|always`는 config validation에서 거부된다.
5. 빠른 최종 결과가 필요하면 `process` 또는 `Processor.run()`을 사용하라.
6. 계획을 검토·수정·비교해야 하면 `infer` → `inspect plan`/`inspect compare` → `apply` 흐름을 사용하라.
7. 여러 PDF를 구조화하려면 `batch` 또는 `BatchProcessor.run()`을 사용하라.
8. 결과를 기계적으로 소비하려면 `--format json`을 사용하고 exit code와 stderr를 함께 검사하라.

상세 명령과 예시는 [CLI 레퍼런스](references/cli.md)를 읽고, Python 통합이 필요하면 [Python API 레퍼런스](references/python-api.md)를 읽으라. 출력 파일·설정·로그 계약을 다룰 때는 [계약과 artifact](references/contracts.md)를 읽으라.

## 기존 outline 정책

- 기본 `processing.skip_existing_bookmarks=true`에서는 의미 있는 기존 outline을 재사용하고 Markdown만 export한다. 이 경로에서는 기존 PDF outline을 덮어쓴 새 PDF가 생성되지 않을 수 있다.
- 기존 outline이 너무 작거나 숫자 제목뿐이거나 페이지 수에 비해 지나치게 많으면 low quality로 판정될 수 있다.
- low-quality outline도 기본값에서는 재사용한다. typography 결과로 교체하려면 `--set outline_quality.replace_when_low_quality=true` 또는 대응 Python config를 명시하라.
- 기존 outline을 무조건 무시할 목적이면 config field와 해당 명령의 현재 help를 확인한 뒤 명시적으로 설정하라. 기본 동작을 추측하지 마라.

## OCR 안전 규칙

- 현재 내장 OCR engine은 Upstage Document Parse다. 기본 환경 변수 `UPSTAGE_API_KEY`가 필요하며 `.env`도 검색한다.
- `ocr-overlay`는 입력과 별도의 output PDF를 만들도록 구성하라. 기존 output을 덮어쓸 때만 `--force`를 사용하라.
- 기존 bookmark가 있는 PDF의 text layer를 교체할 때는 `--confirm-bookmark-ocr-overwrite`가 필요하다.
- `--cache-policy reuse`는 cache hit를 재사용하고 miss만 live call한다. `refresh`는 다시 호출하며, `only`는 API를 호출하지 않고 cache가 없으면 실패한다.
- `ocr-overlay-batch --min-page-count N`은 전체 PDF page 수가 `N` 이상인 문서만 OCR target으로 남긴다. 기본값은 `1`이며 1 이상의 정수만 사용하라.
- live OCR은 비용과 외부 상태 변경을 수반하므로 사용자의 요청 범위와 인증 상태를 확인하라. 검증만 필요하면 `--dry-run` 또는 `--cache-policy only`를 우선 검토하라.

## 계획 검토와 적용

- `bookmark_plan.json`의 각 항목에서 `title`, `level`, `pdf_page`를 핵심 계약으로 다루라. `pdf_page`는 1-based다.
- `infer` 뒤에는 `bookmark_review_summary.json`을 먼저 읽고 `inspect plan <RUN> --attention-only --limit 20`으로 검토 범위를 줄인 다음 `--item-id`, `--page-range`, `--level`, `--source`로 필요한 item만 열어라.
- `bookmark_review_items.jsonl`의 item은 plan order 기반 `n####` ID, source/confidence/evidence, candidate geometry, 주변 typography line, 제한된 page preview와 원본 artifact 위치를 보존한다. duplicate candidate가 normalize 과정에서 축약되면 canonical 첫 후보와 alternative reference를 함께 확인하라.
- attention signal과 `confidence`는 품질 합격/불합격 판정이나 정확도 확률이 아니다. 빈 plan, page 범위와 level jump 같은 구조 validation과 내용 eye-check를 구분하라.
- `infer`는 bookmarked PDF와 Markdown을 만들지 않는다. 최종 산출물에는 반드시 `apply`를 이어서 사용하라.
- `apply`는 plan을 다시 검증하며 typography 분석이나 추론을 반복하지 않는다.
- 설정 A/B 비교에는 두 infer run의 `bookmark_plan.json`을 `inspect compare` 또는 `inspect_compare_plans()`에 전달하라.
- 사람이 수정한 plan을 적용하기 전에 `inspect plan`이 아니라 plan JSON 자체의 필수 field·level·page 범위를 확인하고, `apply`의 validation 결과를 검사하라.

## 설정 사용

- 반복 실행에는 `config init`으로 versioned TOML을 만들고 `config validate`로 검증하라.
- 단일 실험에는 `--set dotted.key=value`를 여러 번 사용하라.
- 설정 병합 우선순위를 `defaults < TOML < 명시적 CLI option < --set`으로 이해하라.
- 지원 key, 타입, 기본값, 범위는 `config explain [KEY]`에서 읽으라. 문서에 config 전체를 복제하지 마라.
- 기본 Markdown tree는 `processing.markdown_content_mode=direct`인 progressive graph다. 기존처럼 parent에 descendant 본문까지 포함하려면 `inclusive`를 명시하라.
- Markdown 길이 제한 export는 `[markdown]` 설정 또는 `--max-words`로 활성화하라. 제약을 만족하지 못하면 가장 깊은 사용 가능 level로 fallback할 수 있으므로 `markdown_manifest.json`의 `constraint_satisfied`, `fallback_used`, overflow 통계를 확인하라.

## 실행 결과 확인

- 기본 `process`, `infer`, `apply`는 immutable run directory와 `run_manifest.json`, `config.resolved.json`을 만든다. JSON 결과가 반환한 `run_dir`과 `manifest_path`를 기준으로 후속 작업을 이어가라. typography inference run은 manifest의 `artifact_paths.bookmark_review_summary`와 `artifact_paths.bookmark_review_items`도 연결한다.
- tree와 length-limited split 결과는 모두 `toc.md`, `bookmark_plan.json`, `nodes/`, `markdown_manifest.json`을 만든다. split은 `export_mode=split`, `content_mode=bounded`이며 원래 plan order 기반 node ID를 유지한다. run manifest의 `artifact_paths.markdown_manifest` 또는 `inspect plan` 결과에서 manifest를 찾을 수 있다.
- `--flat-output`은 호환 모드다. 재현 가능한 작업에는 기본 run directory를 유지하라.
- JSON 성공 결과는 stdout의 단일 envelope이고, 오류는 stderr envelope다. batch/OCR/classify의 JSON 진행 event는 stderr JSONL이다.
- 성공 `0`, runtime 오류 `1`, 입력·config·plan 오류 `2`, 유효한 결과를 만들지 못한 처리 `3`을 구분하라.
- 완료 보고에는 입력, 선택한 workflow/config, run 또는 artifact 경로, bookmark 수, validation·warning·실패 사유를 포함하라.

## Python과 CLI 선택

- 재현 가능한 사용자 실행, agent orchestration, shell 자동화에는 CLI를 우선하라.
- 기존 Python 코드에 조합하거나 중간 `PdfAnalysis`/`BookmarkInferenceResult`를 직접 다룰 때는 Python API를 사용하라.
- 한 파일의 고수준 처리에는 `Processor`; 단계형 처리에는 `analyze_pdf`, `infer_bookmarks`, `write_inference_artifacts`, `apply_plan`; directory 처리에는 `BatchProcessor`를 사용하라.
- OCR은 `pdfbooktree.ocr`, 분류는 `pdfbooktree.classify`, 낮은 수준 typography geometry 기능은 `pdfbooktree.typography`에서 import하라.
- 공개 import는 각 package의 `__all__`을 기준으로 삼고 private helper에 의존하지 마라.

## 저장소 근거 확인

- 현재 공개 surface는 `src/pdfbooktree/__init__.py`, `src/pdfbooktree/ocr/__init__.py`, `src/pdfbooktree/classify/__init__.py`, `src/pdfbooktree/typography/__init__.py`에서 확인하라.
- 실제 사용 흐름은 `showcase/021_*`, `showcase/023_*`, `showcase/025_*`, `showcase/026_*`를 참고하라.
- CLI 결과와 오류 계약은 `tests/test_cli_result_contract.py`, 실행 manifest는 `tests/test_process_cli.py`, `tests/test_infer_apply_cli.py`, `tests/test_batch_cli.py`를 확인하라.
- 새 public interface가 추가되거나 옵션이 바뀌면 이 스킬의 관련 reference와 `agents/openai.yaml`도 함께 갱신하고 validator를 실행하라.
- package에 번들된 `src/pdfbooktree/_skill_templates/use-pdfbooktree`와 repo-local `.agents/skills/use-pdfbooktree`가 byte-identical한지 테스트로 유지하라.
