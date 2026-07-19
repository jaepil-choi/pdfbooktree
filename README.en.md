# pdfbooktree

[한국어](README.md) · [Documentation index](docs/reference.md) ·
[Changelog](CHANGELOG.en.md) · [Security policy](SECURITY.en.md)

`pdfbooktree` is a Python library and CLI that analyzes typography in
text-searchable PDF books and produces a reviewable bookmark plan, a bookmarked
PDF, and a hierarchical Markdown graph.

This project is a **review-assisted Alpha tool**. It creates structural
candidates and evidence to make review faster; it is not an automatic
ground-truth generator. The recommended workflow is `infer → review → apply`.
Confidence values and attention signals are heuristics for prioritizing review,
not accuracy probabilities or pass/fail decisions.

## Why it exists

Splitting a book into fixed-size chunks breaks chapter boundaries and context.
Instead of parsing only contents pages, `pdfbooktree` examines recurring font
size, text-region height, position, margin, and isolation patterns across the
whole book. It reuses a meaningful existing outline rather than inferring a new
one.

## Quality evidence and its limits

On 2026-07-15, commit `06f214f` on `develop` was evaluated against 400 PDFs from
`300STUDY` that were longer than 100 pages and had embedded outlines. Across all
400 books, mean precision was 0.3393, recall 0.6932, and F1 0.4089. The 312 books
classified as having cleaner references had mean F1 0.4662. Some books exceeded
F1 0.9, while books with OCR-heavy equations or poor reference outlines scored
very low.

These numbers are not an accuracy guarantee. Embedded outlines vary in detail
and quality and are only **weak references**. Books without outlines were not
covered, and the implementation has changed since the evaluation. The result
demonstrates substantial book-to-book variation and the need for review and
book-specific configuration. See the
[package interface evaluation](docs/review/pkg-evaluation-20260715.md) for the
method and context.

Existing real-PDF release evidence includes showcase 031, run on 2026-07-17,
which installed a source-built wheel into a separate Python 3.12 environment and
processed a two-page PDF, and showcase 033, run on 2026-07-18, which exercised
`infer_pdf → preview_apply_plan → apply_plan_file`. These are execution checks on
a limited sample, not claims about content quality across books.

## Supported scope

- Python 3.12, 3.13, and 3.14
- Windows and Linux
- PDFs with an extractable text layer
- Reuse of an existing outline or typography-based outline inference
- Markdown graphs with standard YAML front matter and wiki navigation
- Optional Upstage Document Parse OCR overlay

The following are not currently supported:

- encrypted PDFs that require a password
- automatic handling of scanned PDFs without a text layer; create an OCR
  overlay first
- semantic reconstruction of complex tables, equations, or figures
- automatic ground-truth decisions about outline quality
- `processing.ocr_policy=auto|always`; only `never` is valid

Markdown preserves extractable page text. A broken text layer or reading order
will therefore remain visible in the export.

## Installation

```powershell
python -m pip install pdfbooktree
pdfbooktree --help
pdfbooktree --version
```

Install the OCR extra only when live OCR overlay is required:

```powershell
python -m pip install "pdfbooktree[ocr]"
```

The wheel contains a project-scoped Codex skill with the complete CLI and Python
API references:

```powershell
pdfbooktree skill install
```

It is installed under `.agents/skills/use-pdfbooktree` in the current project.
Existing skill files are protected unless `--force` is explicitly supplied.

## Quick start: infer → review → apply

```powershell
$pdf = "book.pdf"

pdfbooktree infer $pdf -o .\runs --format json
pdfbooktree inspect plan "<run_dir returned by infer>" --summary --format json
pdfbooktree inspect plan "<run_dir returned by infer>" `
  --attention-only --limit 20 --format json
pdfbooktree inspect plan "<run_dir returned by infer>" `
  --item-id n0042 --format json
pdfbooktree apply $pdf `
  --plan "<run_dir>\bookmark_plan.json" `
  -o .\runs --dry-run --format json
pdfbooktree apply $pdf `
  --plan "<run_dir>\bookmark_plan.json" `
  -o .\runs --format json
```

`infer` creates `bookmark_plan.json`, `bookmark_review_summary.json`, and
`bookmark_review_items.jsonl`. Start with level/source distributions and
attention signals in the summary, then inspect only the relevant items. Item
details preserve candidate geometry, nearby typography lines, a bounded page
preview, and evidence locations.

`apply --dry-run` validates page ranges and level structure without creating
files. The final `apply` writes the same plan snapshot into a bookmarked PDF and
Markdown graph.

Convenience and directory workflows are also available:

```powershell
pdfbooktree process "book.pdf" -o .\runs --format json
pdfbooktree batch .\books -o .\runs --recursive `
  --include-glob "*.pdf" --exclude-glob "archive/*" `
  --log-mode json --format json
```

## Markdown graph

Both the default tree and length-limited split use this layout:

```text
<input-stem>_markdown[_split]/
├── toc.md
├── bookmark_plan.json
├── markdown_manifest.json
└── nodes/
    ├── 0001_L1_p0010_Chapter-1.md
    └── 0002_L2_p0015_First-section.md
```

Every node begins with standard YAML front matter and has `parent`, `children`,
`previous`, and `next` wiki links. The default `content_mode=direct` assigns a
page to the node that directly owns it instead of duplicating descendant text.
Length-limited output uses `export_mode=split` and `content_mode=bounded` while
preserving the original node ID, source, confidence, and evidence reference.

Open `<input-stem>_markdown` as an Obsidian vault and start at `toc.md`.
`markdown_manifest.json` records node paths, relations, page coverage, dangling
links, and validation results, so graph integrity can be checked without a GUI.

```powershell
pdfbooktree process "book.pdf" -o .\runs `
  --max-words 10000 --max-words-coverage 0.95 --format json
```

## OCR, credentials, privacy, and cost

**The built-in OCR provider in v0.1.0 is exclusively Upstage Document Parse.**
There is no custom provider registration API. Live OCR renders every PDF page
as a PNG and sends that image to Upstage. Before processing personal data,
contracts, trade secrets, or material restricted from external transmission,
check your organizational policy and Upstage's processing terms. External API
charges may apply.

```powershell
$env:UPSTAGE_API_KEY = "<upstage-api-key>"
pdfbooktree ocr-overlay "scan.pdf" -o ".\scan_ocr.pdf"
```

Credentials are read from the current process environment first. With the
`[ocr]` extra installed, the process also searches for `.env` from the current
working directory upward and does not override an existing environment
variable. Never commit `.env`.

The raw OCR cache may contain provider responses, extracted text, and geometry.
Review previews may contain excerpts from the source document. Treat output
directories as sensitive data and define sharing, retention, and deletion
rules. `--cache-policy reuse` reuses hits, `refresh` calls the provider again,
and `only` forbids external calls and requires existing cache.

When `--output-dir` is omitted, cache and statistics are stored next to the
output PDF in `<output-stem>_artifacts`. Input and output PDFs cannot be the same
path; `--force` does not bypass this guard.

```powershell
pdfbooktree ocr-overlay-batch .\books `
  -o .\runs\ocr --recursive --min-page-count 101 --dry-run
```

Use `--dry-run` to inspect targets and page counts before live OCR. Replacing the
text layer of a PDF that already has an outline requires a separate explicit
confirmation option.

## Existing-outline policy

With the default `processing.skip_existing_bookmarks=true`, a meaningful
existing outline is reused for Markdown and the PDF outline is not overwritten.
Even an outline classified as low quality is reused by default.

Request typography replacement explicitly:

```powershell
pdfbooktree batch .\books -o .\runs `
  --set outline_quality.replace_when_low_quality=true
```

Because replacement can discard the original outline, inspect bookmarks and the
dry-run result first.

## Python API

Use the high-level workflow functions when immutable runs and manifests are
required. `preview_apply_plan()` creates no output.

```python
from pathlib import Path

from pdfbooktree import (
    __version__,
    apply_plan_file,
    infer_pdf,
    preview_apply_plan,
)

pdf = Path("book.pdf")
inferred = infer_pdf(pdf, Path("runs"))
plan = inferred.result.bookmark_plan_path
assert plan is not None

preview = preview_apply_plan(pdf, plan, Path("runs"))
assert preview.validation.valid
applied = apply_plan_file(pdf, plan, Path("runs"))
print(__version__, applied.run_dir, applied.result.markdown_manifest_path)
```

Use `to_jsonable()` or `to_json()` to serialize public results. Dataclasses
become objects, `Path` values become strings, tuples become arrays, and
unsupported objects are rejected.

```python
from pdfbooktree import process_pdf, to_json

result = process_pdf("book.pdf", "runs")
payload = to_json(result, ensure_ascii=False, indent=2)
```

See the [Python API reference](.agents/skills/use-pdfbooktree/references/python-api.en.md),
[CLI reference](.agents/skills/use-pdfbooktree/references/cli.en.md), and
[artifact contracts](.agents/skills/use-pdfbooktree/references/contracts.en.md).
The [documentation index](docs/reference.md) links both languages.

## Output and automation contracts

- Public PDF page numbers are 1-based.
- `--format json` writes one final envelope to stdout.
- `--log-mode json` writes progress events as JSONL to stderr.
- Exit codes are `0` for success, `1` for runtime errors, `2` for invalid
  input/config/plan, and `3` when no structurally valid result can be produced.
- Non-dry-run `process`, `infer`, and `apply` runs preserve resolved
  configuration, input identity, artifact paths, and an immutable
  `bookmark_plan.json` snapshot.

## Contributing and security

See [CONTRIBUTING.en.md](CONTRIBUTING.en.md) for development and Pull Request
rules, [SECURITY.en.md](SECURITY.en.md) for private vulnerability reporting,
and [RELEASING.md](RELEASING.md) for the release procedure.

## License

Distributed under the MIT License. Commercial use, modification, and
redistribution are permitted as long as the copyright and license notices are
retained. See [LICENSE](LICENSE).
