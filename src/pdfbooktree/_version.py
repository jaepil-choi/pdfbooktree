"""설치된 pdfbooktree 배포판 version을 한 곳에서 읽는다."""

from __future__ import annotations

from importlib import metadata


def package_version() -> str:
    """설치 metadata의 version을 반환하고 source-only 환경은 fallback한다."""

    try:
        return metadata.version("pdfbooktree")
    except metadata.PackageNotFoundError:
        return "0+unknown"


__version__ = package_version()
