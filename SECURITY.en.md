# Security policy

[한국어](SECURITY.md)

## Supported versions

Security fixes target the latest public release. Before the first public
release, reports are investigated against the latest release candidate on
`master`.

## Private reporting

Do not publish exploit details for vulnerabilities, arbitrary file overwrite,
credential exposure, or malicious-PDF handling in a public issue.

1. Open **Security → Report a vulnerability** in the GitHub repository.
2. If private security advisories are unavailable, email
   `chljeffreyz@gmail.com` with reproduction conditions, impact, affected
   versions, and the smallest practical proof of concept.

Do not disclose vulnerability details or real user documents before the report
is acknowledged. Share OCR provider keys and source PDFs only when strictly
necessary.

Live OCR sends page PNGs to the external Upstage API. `.env`, raw OCR caches,
and review previews can contain credentials or sensitive source content. Never
attach them to public issues or reproduction archives.
