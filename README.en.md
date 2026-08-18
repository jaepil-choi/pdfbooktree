# pdfbooktree

[한국어](https://github.com/jaepil-choi/pdfbooktree/blob/master/README.md) ·
[Docs](https://github.com/jaepil-choi/pdfbooktree/blob/master/docs/reference.md) ·
[Changelog](https://github.com/jaepil-choi/pdfbooktree/blob/master/CHANGELOG.en.md)

`pdfbooktree` is a Python tool that reads a PDF book and infers a hierarchical
bookmark tree. Instead of locating and parsing a table-of-contents page, it
recovers the chapter and section structure from the typography and page
geometry of the whole book. The result is saved as a navigable bookmarked PDF
and as a Markdown directory tree an LLM can read section by section.

## Core capabilities

- Bookmark structure inferred from typography and geometry, with no TOC page required
- Bookmarked PDF output
- Markdown directory tree export, split per section
- OCR text layer overlay for scanned PDFs
- Batch processing across many books
- Read-only inspection commands for intermediate results

## Built for AI agents

This package is designed for AI agents as much as for people. Rather than
reading a whole book, an agent runs a cheap deterministic extraction, checks
with the inspection commands whether the resulting structure makes sense, and
then adjusts parameters per book and runs again.

## Install

```powershell
uv add pdfbooktree
```

Add the `[ocr]` extra if you need live OCR overlay for scanned PDFs.

```powershell
uv add "pdfbooktree[ocr]"
```

## Getting started

Run this once in your project. It registers the same skill for both
agents-style tools and Claude.

```powershell
pdfbooktree skill install
```

From there the installed skill and its reference documents cover the commands,
options and output structure. Remove it with `pdfbooktree skill uninstall`.

## Good to know

- The inferred result is a **draft outline**, not a finished answer. It assumes
  a person or an agent will review and adjust it. Use the flow that builds a
  plan first (`infer`), checks it, and then applies it (`apply`) so you can
  correct the structure before it is written.
- OCR overlay calls an external document parsing service, so it needs
  **API keys**. Without them you can still process PDFs that already carry a
  text layer.
- **Password-protected PDFs** are not supported. Use a copy with the password
  already removed.
- The original PDF is not overwritten by default.

## License

[MIT License](https://github.com/jaepil-choi/pdfbooktree/blob/master/LICENSE)
