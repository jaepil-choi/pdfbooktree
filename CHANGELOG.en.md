# Changelog

[한국어](CHANGELOG.md)

This project follows [Semantic Versioning](https://semver.org/).

## Unreleased

Changes after 0.1.0 are recorded here.

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
- Korean and English docs state the Alpha/review-assisted positioning, limits
  of the 400-book weak-reference evaluation, external OCR page-PNG transfer,
  cost, credential and cache sensitivity, encrypted-PDF limitations, and lack
  of semantic reconstruction.
- The built-in v0.1.0 OCR provider is explicitly Upstage Document Parse only.
