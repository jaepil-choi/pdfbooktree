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
- `inspect sweep` command plus `inspect_heading_sweep()`, which analyzes a PDF
  exactly once and re-evaluates heading-knob combinations entirely in memory.
  No `process` output artifact is written, so an agent can see the candidate
  count and direction (`increases_candidates`/`decreases_candidates`/`mixed`/
  `no_effect`) for every combination cheaply, without rerunning per setting.
- Book-relative typography knobs `max_headings_per_page` and
  `size_class_depth`. Both default to `0` (off), so current behavior is
  unchanged. The OCR overlay sets each line's font size from its bounding box
  and clamps at a per-book value, so an absolute font size or tier index does
  not carry the same meaning across books and is not an axis an agent can act
  on. Both new knobs are book-relative (per-page sparsity, count of top size
  classes) instead, so they avoid that trap.
- `skill install` now installs two targets. `.agents/skills/` gets the full
  instructions, and `.claude/skills/` gets a single adapter file that mirrors
  how this repository's `CLAUDE.md` defers to `AGENTS.md`. Both targets are
  derived from the same bundled source, so content such as the workflow list
  is never hand-duplicated between them.

### Changed

- A structurally invalid embedded outline is no longer reused, and the reason is
  reported in the processing warnings and the review summary.
- Level jumps in an inferred plan are normalized to contiguous depths.
- Existing heading evidence is used, one candidate per page, only when the
  strict geometry selector produces no candidates.

### Fixed

- An IndexError raised while building typography tiers when the number of
  density peaks and cuts disagreed.
- `max_headings_per_page` had no effect at all in
  `heading_candidate_mode=position`. The cap was applied only to the font
  candidate set, which `position` mode never uses, so changing the value left
  the plan silently unchanged. The cap is now applied to the final selected
  candidates after the mode branch, in every heading candidate mode.

### Removed

- The `typography.min_tier_gap` config key, which had no consumer. Supplying it
  is now rejected with `invalid_config` instead of being silently ignored.
- The `TierSet.gap_merged_tier_count` field, which always equalled
  `raw_tier_count`, and the same entry in the `font_size_tiers.json` and
  `height_tiers.json` artifacts.
- Duplicated height-tier evidence. In an OCR overlay, font size and
  bounding-box height are the same measurement (their top tiers agreed 100%
  across the sample), so treating them as two independent signals was
  removed and only the font tier remains.

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
