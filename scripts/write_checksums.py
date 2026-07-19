"""배포 파일의 재현 가능한 SHA-256 checksum 목록을 만든다."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    """파일의 SHA-256 hex digest를 계산한다."""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    """CLI 인자를 해석한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    """sdist와 wheel checksum을 정렬된 GNU 형식으로 기록한다."""

    args = parse_args()
    dist_dir = args.dist_dir.resolve(strict=True)
    output_path = (
        args.output.resolve() if args.output is not None else dist_dir / "SHA256SUMS"
    )
    distributions = sorted(
        [
            *dist_dir.glob("*.whl"),
            *dist_dir.glob("*.tar.gz"),
        ],
        key=lambda path: path.name,
    )
    if len(distributions) != 2:
        raise ValueError(f"sdist와 wheel이 정확히 하나씩 필요하다: {distributions!r}")
    lines = [f"{sha256(path)}  {path.name}" for path in distributions]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(output_path)


if __name__ == "__main__":
    main()
