# pdfbooktree CLI reference

[한국어](cli.md)

## Contents

1. [Common rules](#common-rules)
2. [Project skill](#project-skill)
3. [Quick workflows](#quick-workflows)
4. [Structure commands](#structure-commands)
5. [OCR and classification](#ocr-and-classification)
6. [Inspection](#inspection)
7. [Configuration](#configuration)
8. [Automation contract](#automation-contract)

## Common rules

- Public PDF page numbers are 1-based.
- Use `--format human|json` for final output. Structure/classification progress
  supports `--log-mode auto|rich|plain|json|none`; OCR uses
  `auto|tqdm|plain|json|none`.
- JSON final output is one envelope on stdout. JSON progress is JSONL on
  stderr. Do not merge the streams.
- Exit codes are `0` success, `1` runtime failure, `2` invalid
  input/config/plan, and `3` structurally invalid processing output.
- In a source checkout run `uv run pdfbooktree ...`. After installation run
  `pdfbooktree ...`.
- Run `pdfbooktree <command> --help` for the exact current option set. Help is
  plain Click output so long option names remain visible at 80 columns.

## Project skill

```powershell
pdfbooktree skill install
pdfbooktree skill install --project-dir C:\work\project
pdfbooktree skill install --force --format json
```

The command installs the package-bundled `use-pdfbooktree` skill under
`.agents/skills` in the project. Existing content is protected unless
`--force` replaces the complete tree. Check `status`, `project_dir`,
`skill_dir`, `file_count`, and `files` in JSON output.

## Quick workflows

Review before writing:

```powershell
pdfbooktree infer "book.pdf" -o .\runs --format json
pdfbooktree inspect plan "<run_dir>" --summary --format json
pdfbooktree inspect plan "<run_dir>" `
  --attention-only --limit 20 --format json
pdfbooktree apply "book.pdf" `
  --plan "<run_dir>\bookmark_plan.json" `
  -o .\runs --dry-run --format json
pdfbooktree apply "book.pdf" `
  --plan "<run_dir>\bookmark_plan.json" `
  -o .\runs --format json
```

One-step processing:

```powershell
pdfbooktree process "book.pdf" -o .\runs --format json
```

Directory processing:

```powershell
pdfbooktree batch .\books -o .\runs --recursive `
  --include-glob "*.pdf" --exclude-glob "archive/*" `
  --format json --log-mode json
```

Scanned input:

```powershell
python -m pip install "pdfbooktree[ocr]"
pdfbooktree ocr-overlay "scan.pdf" -o "scan_ocr.pdf"
pdfbooktree infer "scan_ocr.pdf" -o .\runs
```

## Structure commands

### `process`

Runs analysis, inference, validation, PDF application, and Markdown export.
Use `--flat-output` only for compatibility; immutable run directories are the
default. Important option groups include:

- `--config`, repeated `--set KEY=VALUE`
- `--skip-existing-bookmarks/--no-skip-existing-bookmarks`
- heading and position fallback options such as
  `--heading-candidate-mode`, `--body-font-text-coverage`,
  `--position-fallback`, `--position-fallback-tolerance`, and
  `--position-fallback-min-isolation-ratio`
- Markdown limits: `--max-words`, `--max-words-coverage`
- final `--format` and progress `--log-mode`

With a meaningful existing outline, the default policy reuses that outline for
Markdown and may produce no rewritten PDF.

### `infer`

Analyzes typography and writes a plan plus review artifacts without creating a
bookmarked PDF or Markdown graph. Use the returned `run_dir` and
`bookmark_plan_path` for review and later `apply`.

### `apply`

Validates and applies an existing plan without repeating typography inference.
`--dry-run` performs validation and returns predicted paths without creating
them. The source plan is copied into the non-dry-run run as an immutable
`bookmark_plan.json` snapshot and recorded by path and SHA-256.

### `batch`

Processes matching PDFs in deterministic order. `--recursive`,
`--include-glob`, and `--exclude-glob` control selection. The output subtree is
excluded automatically. A batch run manifest links item runs and failures.
Analysis cache, resume, and parallel jobs are not available in v0.1.0.

## OCR and classification

### `classify-scan`

Classifies PDF files by scan-like page coverage and meaningful existing
bookmarks. Inspect its JSON/report results before large OCR work. Sampling
options and thresholds are shown by command help.

### `ocr-overlay`

Creates a separate PDF with invisible OCR text. The built-in engine is
exclusively `upstage` in v0.1.0. A custom provider cannot be registered.

```powershell
$env:UPSTAGE_API_KEY = "<key>"
pdfbooktree ocr-overlay "scan.pdf" -o "scan_ocr.pdf" `
  --engine upstage --render-dpi 300 --cache-policy reuse
```

Each page is rendered as PNG and sent to Upstage during a live call. Charges may
apply. The process searches `.env` from the current working directory upward
without overriding an existing environment variable. Raw cache and preview
artifacts can contain sensitive text and geometry.

Input and output cannot resolve to the same path, even with `--force`. Existing
output requires `--force`; replacing the text layer of a PDF with bookmarks
requires `--confirm-bookmark-ocr-overwrite`. Cache policies are:

- `reuse`: reuse hits and call the provider for misses
- `refresh`: call again
- `only`: never call externally and fail on a miss

### `ocr-overlay-batch`

Classifies and processes a directory. `--min-page-count N` is inclusive:
`page_count >= N`. Use `--recursive`, confirm options, and `--dry-run` before
live calls. Core-only installs support help and batch dry-run; live OCR requires
`pdfbooktree[ocr]` and otherwise raises `OptionalDependencyError`.

## Inspection

Read-only commands:

```powershell
pdfbooktree inspect page-count "book.pdf" --format json
pdfbooktree inspect text "book.pdf" --pages 10-12 --format json
pdfbooktree inspect bookmarks "book.pdf" --format json
pdfbooktree inspect ocr ".\ocr-artifacts" --format json
pdfbooktree inspect compare "plan-a.json" "plan-b.json" --format json
```

`inspect plan` accepts a plan, run directory, or Markdown graph directory. Use
`--summary`, `--attention-only`, `--limit`, `--item-id`, `--page-range`,
`--level`, and `--source` to progressively disclose only needed evidence.
Confidence and attention signals prioritize review; they do not certify
quality.

## Configuration

```powershell
pdfbooktree config defaults --format json
pdfbooktree config schema --format json
pdfbooktree config init .\pdfbooktree.toml
pdfbooktree config explain
pdfbooktree config explain typography.position_fallback_enabled
pdfbooktree config validate .\pdfbooktree.toml
```

Precedence is `defaults < TOML < explicit command options < repeated --set`.
Unknown keys, invalid types/ranges, and `processing.ocr_policy=auto|always` are
rejected before processing. Use `config explain` and command help rather than
copying all defaults into automation.

## Automation contract

`--version` prints `pdfbooktree <installed-metadata-version>`. Successful JSON
uses `schema_version`, `command`, `ok=true`, and `result`. Errors use
`ok=false` and a stable error object. Human-readable progress and JSON progress
belong to stderr; parse only stdout for the final JSON envelope.

Every non-dry-run `process`, `infer`, and `apply` keeps resolved configuration,
input identity, a manifest, and a canonical plan snapshot. Follow paths returned
by the result instead of predicting timestamped run names.
