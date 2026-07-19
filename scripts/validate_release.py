"""릴리스 tag, source metadata, wheel metadata와 master 위치를 검증한다."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def project_version(pyproject_path: Path) -> str:
    """pyproject의 project version을 반환한다."""

    with pyproject_path.open("rb") as file:
        value = tomllib.load(file)["project"]["version"]
    if not isinstance(value, str):
        raise ValueError("project.version이 문자열이 아니다.")
    return value


def wheel_version(wheel_path: Path) -> str:
    """wheel 내부 METADATA의 Version을 반환한다."""

    with zipfile.ZipFile(wheel_path) as archive:
        metadata_names = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValueError(
                f"wheel METADATA가 정확히 하나가 아니다: {metadata_names!r}"
            )
        metadata = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
    version = metadata["Version"]
    if version is None:
        raise ValueError("wheel METADATA에 Version이 없다.")
    return version


def git_revision(reference: str) -> str:
    """git reference의 commit ID를 반환한다."""

    completed = subprocess.run(
        ["git", "rev-parse", reference],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout.strip()


def validate_tag(tag: str, channel: str) -> str:
    """channel에 맞는 tag 형식을 확인하고 package version을 반환한다."""

    pattern = (
        r"v(?P<version>\d+\.\d+\.\d+rc[1-9]\d*)"
        if channel == "testpypi"
        else r"v(?P<version>\d+\.\d+\.\d+)"
    )
    match = re.fullmatch(pattern, tag)
    if match is None:
        raise ValueError(f"{channel} tag 형식이 아니다: {tag!r}")
    return match.group("version")


def parse_args() -> argparse.Namespace:
    """CLI 인자를 해석한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument(
        "--channel",
        choices=("testpypi", "pypi"),
        required=True,
    )
    parser.add_argument("--master-ref", default="origin/master")
    parser.add_argument("--wheel", type=Path)
    return parser.parse_args()


def main() -> None:
    """릴리스 불변 조건을 검증하고 JSON 결과를 출력한다."""

    args = parse_args()
    tag_version = validate_tag(args.tag, args.channel)
    source_version = project_version(ROOT / "pyproject.toml")
    if tag_version != source_version:
        raise ValueError(
            f"tag version과 project version이 다르다: "
            f"{tag_version!r} != {source_version!r}"
        )

    head = git_revision("HEAD")
    master = git_revision(args.master_ref)
    if head != master:
        raise ValueError(
            f"tag commit이 {args.master_ref} HEAD가 아니다: {head} != {master}"
        )

    distribution_version = None
    if args.wheel is not None:
        distribution_version = wheel_version(args.wheel.resolve(strict=True))
        if distribution_version != tag_version:
            raise ValueError(
                f"wheel version과 tag version이 다르다: "
                f"{distribution_version!r} != {tag_version!r}"
            )

    print(
        json.dumps(
            {
                "ok": True,
                "channel": args.channel,
                "tag": args.tag,
                "version": tag_version,
                "wheel_version": distribution_version,
                "commit": head,
                "master_ref": args.master_ref,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
