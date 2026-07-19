# Contracts and artifacts

[한국어](contracts.md)

## Contents

1. [Pages and plans](#pages-and-plans)
2. [Single-run directory](#single-run-directory)
3. [Inference and review artifacts](#inference-and-review-artifacts)
4. [Final PDF and Markdown](#final-pdf-and-markdown)
5. [Batch and classification](#batch-and-classification)
6. [OCR cache](#ocr-cache)
7. [Configuration](#configuration)
8. [CLI streams and exit codes](#cli-streams-and-exit-codes)

## Pages and plans

All public `pdf_page`, page ranges, bookmark destinations, review pages, and
Markdown page fields are 1-based. Internal zero-based indices are not a public
contract.

`bookmark_plan.json` is an ordered JSON array. Each item requires `title`,
positive `level`, and 1-based `pdf_page`; it also preserves `source`,
`confidence`, and `evidence`. Structural validation rejects empty plans, invalid
pages, nonpositive levels, and illegal level jumps. It does not certify whether
titles are semantically correct.

Every non-dry-run process/infer/apply run owns an immutable canonical
`bookmark_plan.json` snapshot. An external plan supplied to apply is also
recorded as `plan_source` with path and SHA-256.

## Single-run directory

Default commands create an immutable timestamped run under the requested output
root. Use returned paths; do not predict names. Typical files include:

```text
<run>/
├── run_manifest.json
├── config.resolved.json
├── bookmark_plan.json
├── bookmark_plan_validation.json
├── bookmark_review_summary.json
├── bookmark_review_items.jsonl
├── <book>_bookmarked.pdf
└── <book>_markdown/
```

`run_manifest.json` records schema/tool identity, input path/hash/page count,
resolved configuration, status, errors, warnings, and artifact paths. A failed
run must not report nonexistent planned paths as successful artifacts.
`--flat-output` is compatibility mode and should not be used for reproducible
automation.

## Inference and review artifacts

Typography inference can write:

- `whole_book_lines.jsonl`
- `font_size_tiers.json`, `height_tiers.json`
- `heading_candidates.json`
- `position_fallback_candidates.json`
- `bookmark_plan.json`, `bookmark_plan_validation.json`
- `bookmark_review_summary.json`
- `bookmark_review_items.jsonl`

The summary contains counts and distributions plus attention signals and
suggested inspection commands. Each JSONL item preserves plan identity,
source/confidence/evidence, geometry, nearby typography lines, a bounded source
preview, and references to larger artifacts. Attention signals and confidence
are review heuristics, not calibrated probabilities.

Review previews and line artifacts may contain sensitive source text. Protect
them with the same controls as the input PDF.

## Final PDF and Markdown

The bookmarked PDF is a new file; the source PDF is not overwritten. Markdown
tree and split exports contain:

```text
<book>_markdown[_split]/
├── toc.md
├── bookmark_plan.json
├── markdown_manifest.json
└── nodes/*.md
```

Every node starts with parseable YAML front matter. Stable fields include
`schema_version`, node identity/order, title/level, PDF page range,
source/confidence/evidence, and parent/children/previous/next relations.
Navigation links in YAML and Markdown must agree.

The default graph uses `export_mode=tree_graph`, `content_mode=direct`: a page is
assigned to the node that directly owns it, avoiding descendant duplication.
Length-limited output uses `export_mode=split`, `content_mode=bounded`.
`markdown_manifest.json` contains node/path mappings, root count, page coverage,
relation symmetry, dangling-link results, and constraint/fallback statistics.

## Batch and classification

A batch run has a batch manifest and per-item run references. Selection order is
deterministic. Include/exclude globs are relative to the input root, extension
matching accepts `.pdf` case-insensitively, and an output subtree inside the
input is excluded.

Classification output records source path, page/sample counts, scan-like
fractions, visible/invisible text evidence, bookmark counts, target decisions,
and rejection/error reasons. A target classification is evidence for review,
not permission to make a paid OCR call.

## OCR cache

The v0.1.0 engine is Upstage Document Parse only. During a live call each page
is rendered to PNG and sent externally. Cache policy meanings are:

- `reuse`: reuse complete cached pages; call for misses
- `refresh`: call and replace cache
- `only`: use cache only; fail on missing pages

Raw provider responses, insertable OCR JSON, line statistics, previews, and
rendered content can contain sensitive document data. Output directories must
follow the user's retention and access policy.

OCR writes a separate output PDF. Identical input/output paths are always
rejected. Existing output requires `force`, and a PDF with bookmarks requires
explicit overwrite confirmation. A sibling temporary PDF is completed before
atomic replacement, preserving existing output on failure.

Credential lookup reads the configured environment variable
(`UPSTAGE_API_KEY` by default). With the OCR extra installed, `.env` is searched
from the working directory upward and does not override an existing variable.

## Configuration

Resolved configuration is immutable and is saved in every run. Merge order is:

```text
defaults < TOML < explicit CLI options < --set overrides
```

Unknown keys, invalid types, invalid ranges, and unsupported OCR policies are
configuration errors before PDF analysis or external calls.
`processing.ocr_policy` supports only `never`; run OCR overlay explicitly.
Use `config schema`, `config explain`, and `config validate` as the authoritative
machine and human contracts.

## CLI streams and exit codes

Human final output goes to stdout and progress/errors to stderr. With
`--format json`, stdout is exactly one final result envelope. With
`--log-mode json`, stderr is zero or more JSONL progress events.

- `0`: success
- `1`: runtime/provider/filesystem failure
- `2`: invalid input, configuration, or plan
- `3`: processing completed without a structurally valid result

Automation must inspect the exit code and `ok` field, retain stderr separately,
and follow returned manifest/artifact paths.
