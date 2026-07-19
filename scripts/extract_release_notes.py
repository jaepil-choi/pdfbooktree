"""CHANGELOG의 특정 version 항목을 GitHub Release notes로 추출한다."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def release_section(changelog: str, version: str) -> str:
    """Markdown CHANGELOG에서 정확한 version section을 반환한다."""

    pattern = re.compile(
        rf"^## {re.escape(version)}(?:\s+-\s+[^\n]+)?\s*$"
        rf"(?P<body>.*?)(?=^##\s|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(changelog)
    if match is None:
        raise ValueError(f"CHANGELOG에 {version!r} 항목이 없다.")
    body = match.group("body").strip()
    if not body:
        raise ValueError(f"CHANGELOG의 {version!r} 항목이 비어 있다.")
    return f"## {version}\n\n{body}\n"


def parse_args() -> argparse.Namespace:
    """CLI 인자를 해석한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--changelog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """release notes를 UTF-8 Markdown으로 기록한다."""

    args = parse_args()
    changelog = args.changelog.read_text(encoding="utf-8")
    notes = release_section(changelog, args.version)
    args.output.write_text(notes, encoding="utf-8", newline="\n")
    print(args.output)


if __name__ == "__main__":
    main()
