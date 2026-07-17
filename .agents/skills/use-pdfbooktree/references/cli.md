# pdfbooktree CLI 레퍼런스

## 목차

- [공통 실행 규칙](#공통-실행-규칙)
- [Project skill 설치](#project-skill-설치)
- [빠른 workflow](#빠른-workflow)
- [구조화 명령](#구조화-명령)
- [OCR과 분류 명령](#ocr과-분류-명령)
- [Inspect 명령](#inspect-명령)
- [Config 명령](#config-명령)
- [자동화 계약](#자동화-계약)

## 공통 실행 규칙

저장소 루트에서 `uv run pdfbooktree`를 사용하라. 모든 명령에 `--debug`가 있으며, 예상하지 못한 오류를 traceback으로 조사할 때만 켜라. agent나 script가 결과를 소비하면 `--format json`을 사용하라.

현재 명령 목록과 option을 확인하려면 다음을 실행하라.

```powershell
uv run pdfbooktree --help
uv run pdfbooktree process --help
uv run pdfbooktree inspect --help
uv run pdfbooktree config --help
```

## Project skill 설치

pip로 `pdfbooktree`를 설치한 project root에서 package에 번들된 `use-pdfbooktree` skill을 설치하라.

```powershell
pdfbooktree skill install
```

기본 target은 현재 directory의 `.agents/skills/use-pdfbooktree`다. 다른 project를 지정하거나 기존 skill 전체를 package 버전으로 교체할 때만 option을 사용하라.

```powershell
pdfbooktree skill install --project-dir C:\work\my-project --format json
pdfbooktree skill install --force
```

- 기존 target은 기본적으로 exit `2`의 `skill_install_error`로 보호한다.
- `--force`는 기존 skill directory 전체를 교체하므로 local 수정이 필요하면 먼저 보존하라.
- 성공 JSON result의 `status`, `project_dir`, `skill_dir`, `file_count`, `files`를 확인하라.
- 이 저장소를 source checkout으로 실행할 때는 동일하게 `uv run pdfbooktree skill install`을 사용하라.

## 빠른 workflow

입력을 먼저 조사하라.

```powershell
$pdf = "C:\books\book.pdf"
uv run pdfbooktree inspect page-count $pdf --format json
uv run pdfbooktree inspect text $pdf --pages 1-3,42 --format json
uv run pdfbooktree inspect bookmarks $pdf --format json
```

검토 없이 한 번에 처리하라.

```powershell
uv run pdfbooktree process $pdf -o .\runs --format json
```

계획을 분리해 검토하고 적용하라. `infer` JSON의 `run_dir` 아래 `bookmark_plan.json`을 사용하라.

```powershell
uv run pdfbooktree infer $pdf -o .\runs --format json
uv run pdfbooktree inspect plan "<infer-run-dir>" --format json
uv run pdfbooktree apply $pdf --plan "<infer-run-dir>\bookmark_plan.json" -o .\runs --format json
```

low-quality 기존 outline을 typography 결과로 교체하라.

```powershell
uv run pdfbooktree process $pdf -o .\runs `
  --set outline_quality.replace_when_low_quality=true `
  --format json
```

길이 제한 Markdown split을 활성화하라.

```powershell
uv run pdfbooktree process $pdf -o .\runs `
  --set markdown.max_words=10000 `
  --set markdown.max_words_coverage=0.95 `
  --format json
```

## 구조화 명령

### `process`

단일 PDF의 기존 outline 정책, typography 분석·추론, bookmark 적용, Markdown export, report 작성을 한 번에 수행하라.

```powershell
uv run pdfbooktree process <PDF> [-o <OUTPUT_ROOT>] `
  [--config <CONFIG.toml>] [--set <KEY=VALUE>] [--flat-output] `
  [--format human|json]
```

주요 직접 option은 다음과 같다.

- 기존 outline: `--skip-existing-bookmarks`; 반대 값은 `--set processing.skip_existing_bookmarks=false`로 명시하라.
- 후보 선택: `--heading-candidate-mode position|font|position_and_font`, `--body-font-text-coverage`, `--body-font-max-words`, `--position-min-repeated-pages`.
- position fallback: `--position-fallback`, `--position-fallback-tolerance`, `--position-fallback-min-isolation-ratio`.
- tier/BPE: `--min-tier-count`, `--max-heading-tier`, `--bpe-max-node-words`, `--bpe-level-pollution-ratio`.
- margin: `--margin-band-ratio`, `--margin-min-consecutive-pages`.
- Markdown tree: 기본은 `--set processing.markdown_content_mode=direct`이고 기존 subtree 본문 포함은 `inclusive`로 명시한다.
- Markdown split: `--max-words`, `--max-words-coverage`.

더 많은 설정은 `--set`으로 전달하고 `config explain`에서 key를 확인하라.
기본 tree와 length-limited split은 모두 `toc.md`, `bookmark_plan.json`, `nodes/`, `markdown_manifest.json` graph를 만든다. split node는 선택된 level의 boundary만 export하되 원래 plan order 기반 `n####` identity와 source/confidence/evidence reference를 유지한다. run manifest의 `artifact_paths.markdown_manifest` 또는 `inspect plan` 결과를 먼저 읽으면 node 파일을 모두 열지 않고도 graph와 page coverage를 조사할 수 있다.

### `infer`

bookmark plan과 근거 artifact만 만들고 PDF/Markdown 생성은 건너뛰어라.

```powershell
uv run pdfbooktree infer <PDF> -o <OUTPUT_ROOT> `
  [--config <CONFIG.toml>] [--set <KEY=VALUE>] [--flat-output] `
  [--format human|json]
```

기존 outline이 있고 policy가 재사용을 선택하면 typography 추론을 건너뛸 수 있다. 반환된 run의 plan과 `existing_outline_quality.json`을 확인하라.

### `apply`

검증된 plan을 입력 PDF에 적용해 bookmarked PDF와 Markdown만 만들어라. 분석·추론은 다시 실행하지 않는다.

```powershell
uv run pdfbooktree apply <PDF> --plan <BOOKMARK_PLAN.json> `
  -o <OUTPUT_ROOT> [--config <CONFIG.toml>] [--set <KEY=VALUE>] `
  [--flat-output] [--format human|json]
```

run manifest는 plan 경로와 SHA-256을 `plan_source`로 기록하고 생성된 graph manifest를 `artifact_paths.markdown_manifest`로 연결한다.

### `batch`

디렉터리의 PDF를 각각 immutable item run으로 처리하고 batch manifest에서 연결하라.

```powershell
uv run pdfbooktree batch <INPUT_DIR> -o <OUTPUT_ROOT> `
  [--recursive] [--config <CONFIG.toml>] [--set <KEY=VALUE>] `
  [--log-mode auto|rich|plain|json|none] [--format human|json]
```

batch JSON 결과의 `batch_run_id`, `batch_manifest_path`, 각 item의 `run_id`, `manifest_path`, output path를 사용하라.

## OCR과 분류 명령

### `classify-scan`

PDF를 native/scanned로 분류하고 bookmark 유무를 합쳐 OCR overwrite target을 찾아라. 이 명령은 PDF를 수정하지 않는다.

```powershell
uv run pdfbooktree classify-scan <INPUT_DIR> -o <OUTPUT_DIR> `
  [--recursive] [--dry-run] [--write-report] `
  [--max-sample-pages 50] `
  [--log-mode auto|rich|plain|json|none] [--format human|json]
```

기본 report는 `classification_report.csv`, `classification_detail.jsonl`, `classification_summary.json`이다. `is_ocr_overwrite_target`과 `target_reject_reason`을 기준으로 분기하라.

### `ocr-overlay`

PDF page를 이미지로 렌더링하고 OCR한 뒤 원본 위에 invisible text layer를 입힌 별도 PDF를 만들어라.

```powershell
uv run pdfbooktree ocr-overlay <PDF> `
  --output <OCR_PDF> --output-dir <ARTIFACT_DIR> `
  [--engine upstage] [--render-dpi 300] [--pages 1-3,42] `
  [--cache-policy reuse|refresh|only] [--force] `
  [--confirm-bookmark-ocr-overwrite] [--stats-word-level] `
  [--engine-option <KEY=VALUE>] `
  [--log-mode auto|tqdm|plain|json|none] [--no-log-file] `
  [--format human|json]
```

기본 engine은 `UPSTAGE_API_KEY`를 읽는다. 지원 engine option에는 `model`, `output_formats`, `coordinates`, `words`, `base_url`, `api_key_env`, `timeout`, `max_retries`, `retry_initial_wait_sec`가 있다. option 값은 `--engine-option key=value`로 여러 번 전달하라.

### `ocr-overlay-batch`

디렉터리를 먼저 분류하고 scanned + no meaningful bookmark + 최소 page 수 조건을 만족하는 PDF만 OCR하라.

```powershell
uv run pdfbooktree ocr-overlay-batch <INPUT_DIR> -o <OUTPUT_DIR> `
  [--recursive] [--dry-run] [--force] `
  [--confirm-bookmark-ocr-overwrite] [--engine upstage] `
  [--render-dpi 300] [--min-page-count 1] [--max-sample-pages 50] `
  [--stats-word-level] [--engine-option <KEY=VALUE>] `
  [--log-mode auto|tqdm|plain|json|none] [--no-log-file] `
  [--format human|json]
```

101쪽 이상의 PDF만 recursive하게 분류하고 실제 OCR 호출 없이 target을 확인하려면 다음처럼 실행하라.

```powershell
uv run pdfbooktree ocr-overlay-batch .\data\300STUDY `
  -o .\runs\300study-ocr `
  --recursive `
  --min-page-count 101 `
  --dry-run
```

`--min-page-count N`은 inclusive 조건이다. 전체 `page_count >= N`인 문서만 OCR target이 될 수 있고, 그보다 짧은 문서는 `below_min_page_count: page_count=... < min_page_count=...` 사유로 skip한다. 기본값은 `1`이며 1 이상의 정수만 허용한다.

`tqdm` mode는 OCR 전에 PDF 탐색 시작·발견 개수, PDF별 분류 progress, target 권수·page 합계·기존 output·분류 실패·MuPDF 복구 경고 요약을 먼저 표시한다. 이어지는 OCR page bar는 실제 처리 대상만 세며 분류에서 제외된 PDF 수를 `skipped`로 섞지 않는다. `plain`은 단계별 요약을, `json`은 `discovery_started`, `discovery_completed`, `classification_started`, `classification_progress`, `classification_completed`, 선택적 `mupdf_warnings_collected` event를 stderr JSONL로 출력한다.

output root 아래 `pdfs/`, `artifacts/`, `ocr_overlay_batch_report.csv`, `ocr_overlay_batch_detail.jsonl`, `ocr_overlay_batch_summary.json`을 확인하라. API를 호출하지 않고 target만 확인하려면 `--dry-run`을 사용하고, report의 `is_ocr_overwrite_target`, `target_reject_reason`, `page_count`를 검토하라.

## Inspect 명령

모든 inspect 명령은 읽기 전용이다. `--json`은 `--format json`의 호환 alias다.

| 명령 | 목적 | 인수와 주요 option |
| --- | --- | --- |
| `inspect page-count` | PDF 총 page 수 확인 | `<PDF>` |
| `inspect text` | 선택 page의 추출 text 확인 | `<PDF> --pages 1-3,42` |
| `inspect bookmarks` | 기존 bookmark와 target page 확인 | `<PDF>` |
| `inspect ocr` | OCR progress, cache, stats, 마지막 log 확인 | `<ARTIFACT_DIR>` |
| `inspect plan` | plan validation, report, Markdown manifest validation·coverage 요약 | `<RUN_OR_OUTPUT_DIR>` |
| `inspect compare` | 두 plan의 added/removed/moved/level/source 차이 | `<PLAN_A> <PLAN_B> [--page-tolerance 0] [--title-similarity-threshold 0.7]` |

```powershell
uv run pdfbooktree inspect ocr .\ocr-artifacts --format json
uv run pdfbooktree inspect plan .\runs\<run-dir> --format json
uv run pdfbooktree inspect compare .\plan-a.json .\plan-b.json `
  --page-tolerance 1 --title-similarity-threshold 0.8 --format json
```

## Config 명령

| 명령 | 목적 |
| --- | --- |
| `config defaults` | 현재 resolved 기본값을 TOML 또는 JSON으로 출력 |
| `config schema` | public config JSON Schema 출력 |
| `config init <PATH>` | 주석이 있는 versioned TOML 생성; 기존 파일은 `--force` 없이 보호 |
| `config explain [KEY]` | 전체 또는 단일 dotted key의 타입·기본값·범위·설명 출력 |
| `config validate <PATH>` | TOML과 추가 `--set`을 합쳐 검증하고 config hash 출력 |

```powershell
uv run pdfbooktree config init .\pdfbooktree.toml
uv run pdfbooktree config explain typography.position_fallback_enabled --format json
uv run pdfbooktree config validate .\pdfbooktree.toml `
  --set outline_quality.replace_when_low_quality=true --format json
```

## 자동화 계약

- `--format json` 성공: stdout의 단일 `{"schema_version":1,"command":"...","ok":true,"result":...}` envelope를 parse하라.
- `--format json` 오류: stdout은 비고 stderr의 단일 `ok:false` error envelope를 parse하라.
- `--log-mode json`: 진행 event를 stderr JSONL로 parse하라. 최종 결과는 stdout과 분리하라.
- exit `0`: 성공, `1`: runtime 오류, `2`: 입력/config/plan 오류, `3`: pipeline validation 실패로 처리하라.
- `--debug`가 없으면 예상하지 못한 traceback을 사용자에게 노출하지 않는 계약을 유지하라.
