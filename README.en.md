# pdfbooktree

[한국어](README.md) · [Documentation](docs/reference.md) ·
[Changelog](CHANGELOG.en.md)

`pdfbooktree` adds bookmarks to PDF books and exports their chapter structure
as Markdown.

It keeps a useful outline when the PDF already has one. Otherwise, it builds a
draft outline from the size and placement of text on each page. You can review
the draft before writing a new bookmarked PDF and a folder of linked Markdown
files.

## When to use it

- Make a long PDF easier to navigate
- Move a book's chapter structure into Markdown or Obsidian
- Process a directory of PDF books with the same settings

## Install

Python 3.12 or newer is required.

```powershell
python -m pip install pdfbooktree
```

Install the OCR extra only if you need to add a text layer to scanned PDFs:

```powershell
python -m pip install "pdfbooktree[ocr]"
```

## Quick start

```powershell
pdfbooktree process "book.pdf" -o .\runs
```

Each run gets its own output directory:

```text
runs/
└── <book name>-<ID>/
    └── <run ID>/
        ├── bookmark_plan.json
        ├── <book name>_bookmarked.pdf
        └── <book name>_markdown/
            ├── toc.md
            └── nodes/
```

- `bookmark_plan.json` contains the outline and page assignments.
- `*_bookmarked.pdf` is a new PDF with bookmarks.
- `*_markdown/` contains the table of contents and chapter files.

The source PDF is never modified.

## Review before applying

An inferred outline can vary with the design of the book. For important
documents, review it with the `infer → inspect → apply` workflow:

```powershell
$pdf = "book.pdf"

pdfbooktree infer $pdf -o .\runs --format json
pdfbooktree inspect plan "<run_dir returned by infer>" --summary
pdfbooktree apply $pdf `
  --plan "<run_dir>\bookmark_plan.json" `
  -o .\runs --dry-run
pdfbooktree apply $pdf `
  --plan "<run_dir>\bookmark_plan.json" `
  -o .\runs
```

`--dry-run` checks page ranges and outline levels without writing output files.

To process a directory:

```powershell
pdfbooktree batch .\books -o .\runs --recursive
```

## Markdown output

Each chapter or section becomes a Markdown file with links to its parent,
children, previous section, and next section. Open the generated Markdown
directory as an Obsidian vault and start with `toc.md`.

You can split long sections by setting a word limit:

```powershell
pdfbooktree process "book.pdf" -o .\runs `
  --max-words 10000 --max-words-coverage 0.95
```

## Scanned PDFs

A PDF without searchable text needs OCR first. The built-in OCR command uses
Upstage Document Parse.

```powershell
$env:UPSTAGE_API_KEY = "<upstage-api-key>"
pdfbooktree ocr-overlay "scan.pdf" -o ".\scan_ocr.pdf"
pdfbooktree process ".\scan_ocr.pdf" -o .\runs
```

OCR sends an image of each page to Upstage and may incur API charges. Check
your security policy and Upstage's data-processing terms before sending
sensitive documents. Never commit API keys.

## PDFs that already have bookmarks

By default, a useful existing outline is reused. Replacing it with an inferred
outline requires an explicit setting:

```powershell
pdfbooktree batch .\books -o .\runs `
  --set outline_quality.replace_when_low_quality=true
```

Review the original bookmarks and the dry-run result before replacing them.

## Python API

```python
from pdfbooktree import process_pdf

result = process_pdf("book.pdf", "runs")
print(result.run_dir)
print(result.result.bookmarked_pdf_path)
print(result.result.markdown_manifest_path)
```

Use `infer_pdf()`, `preview_apply_plan()`, and `apply_plan_file()` when you need
separate inference, validation, and application steps.

## Limitations

- Bad text extraction or reading order in the source PDF carries over to
  Markdown.
- An inferred outline is a draft and should be reviewed when heading styles are
  inconsistent.
- Tables, equations, and figures are not reconstructed semantically.
- Password-protected PDFs are not supported.
- Public page numbers are 1-based.

See the [documentation index](docs/reference.md) for the complete CLI and Python
API references.

## License

[MIT License](LICENSE)
