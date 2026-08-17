# Changelog

[한국어](CHANGELOG.md)

This project follows [Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- `inspect markdown` command plus `inspect_markdown_tree()` and
  `inspect_compare_markdown()` for diagnosing a produced Markdown tree. Each
  result carries a verdict, the cause, and runnable retry candidates.
- `inspect compare` now distinguishes a bookmark plan JSON from a Markdown
  manifest automatically.

### Changed

- A structurally invalid embedded outline is no longer reused, and the reason is
  reported in the processing warnings and the review summary.
- Level jumps in an inferred plan are normalized to contiguous depths.
- Existing heading evidence is used, one candidate per page, only when the
  strict geometry selector produces no candidates.

### Fixed

- An IndexError raised while building typography tiers when the number of
  density peaks and cuts disagreed.

### Removed

- The `typography.min_tier_gap` config key, which had no consumer. Supplying it
  is now rejected with `invalid_config` instead of being silently ignored.
- The `TierSet.gap_merged_tier_count` field, which always equalled
  `raw_tier_count`, and the same entry in the `font_size_tiers.json` and
  `height_tiers.json` artifacts.

## 0.1.1 - 2026-07-19

### Documentation

- Rewrote the project description and README as a shorter, task-oriented guide.
- Removed internal evaluation data, commit identifiers, and showcase records
  from the public documentation.
- Kept internal review documents on `develop` and excluded them from the public
  `master` release.

## 0.1.0 - 2026-07-19

### Added

- Typography-based bookmark inference, existing-outline reuse, and the staged
  `infer → inspect → apply` workflow.
- Bookmarked PDFs and hierarchical Markdown graphs with YAML front matter and
  wiki navigation.
- Non-destructive Upstage Document Parse OCR overlay and scan/OCR batch
  classification.
- Immutable run/batch manifests, JSON CLI envelopes, and review summary/item
  evidence.
- `apply --dry-run`, process/infer progress events, and batch include/exclude
  globs.
- `__version__`, `package_version()`, PEP 561 `py.typed`, and typed artifact
  paths.
- High-level immutable Python workflows: `process_pdf()`, `infer_pdf()`,
  `preview_apply_plan()`, and `apply_plan_file()`.
- A canonical `bookmark_plan.json` snapshot in every process/infer/apply run.
- Public result serialization through `to_jsonable()`, `to_json()`, and
  `JsonValue`.
- Supported `__all__` surfaces and complete Korean/English Python API, CLI, and
  artifact references in the installable project skill.

### Distribution

- Windows/Linux tests and same-wheel clean-install smoke on Python
  3.12/3.13/3.14.
- Plain Click help that preserves long option names and `--version` at 80
  columns.
- One sdist/wheel build, `twine check`, SHA-256 checksums, and provenance
  attestations.
- TestPyPI/PyPI OIDC Trusted Publishing through protected GitHub environments.

### Dependencies

- `httpx`, `pikepdf`, and `python-dotenv` moved to the `pdfbooktree[ocr]` extra.
- `tqdm` remains a core dependency because regular processing uses it.
- Core-only installs retain OCR help and batch dry-run; live overlay fails with
  a stable `OptionalDependencyError` and installation guidance.

### Safety and documentation

- OCR rejects identical input/output paths and atomically replaces output from a
  sibling temporary PDF.
- Recursive batch safely excludes its output subtree and accepts uppercase
  `.PDF`.
- Failed results do not expose nonexistent planned output paths as artifacts.
- Source text containing `[[...]]` is not mistaken for generated wiki links.
- Korean and English docs cover outline review, external OCR transfer and cost,
  encrypted-PDF limitations, and complex document structures.
- The built-in v0.1.0 OCR provider is explicitly Upstage Document Parse only.
