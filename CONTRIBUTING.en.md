# Contributing

[한국어](CONTRIBUTING.md)

## Development environment

Python 3.12 or newer and `uv` are required. CI validates Python 3.12, 3.13, and
3.14 on Windows and Linux.

```powershell
uv sync --locked --dev --python 3.12
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Run Python commands through `uv run`. Code comments and internal repository
documents are written in Korean. Public documentation—README, CLI, Python API,
artifact contracts, contribution, security, and changelog—must keep equivalent
Korean and English coverage.

## Change workflow

1. Validate a new hypothesis first in a monolithic
   `experiments/NNN_description.py` proof of concept and record the result in
   `experiments/experiments.json`.
2. Implement supported interfaces in `src/` and `tests/`.
3. Exercise real data and live public interfaces in
   `showcase/NNN_description.py`, recording the result in
   `showcase/showcase.json`. Synthetic or mocked input alone is not evidence of
   showcase success.
4. When CLI/API contracts change, update the repo-local skill, package-bundled
   skill, and both public documentation languages.
5. Run relevant tests and the full lint/format checks.

Do not undo unrelated user changes. Commits are created only when requested.
After a requested implementation commit that changes `src/` or `tests/`, create
the separate implementation note required by the repository workflow.

## Pull Request checklist

- Are input/output paths safe and is existing data preserved on overwrite
  failure?
- Are all public page numbers 1-based?
- Are JSON stdout, progress stderr, and exit-code contracts preserved?
- Are Windows/Linux filenames, YAML, and wiki relations deterministic?
- Do Python API, CLI, both language references, the bundled skill, and real-data
  showcase evidence agree?
- Do tests, Ruff lint, Ruff format, package checks, and same-wheel smoke pass?
