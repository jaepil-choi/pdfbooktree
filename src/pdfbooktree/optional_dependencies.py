"""선택 기능의 dependency 설치 여부를 안정된 오류로 보고한다."""

from __future__ import annotations

from importlib.util import find_spec
from typing import Mapping


OCR_DEPENDENCIES: Mapping[str, str] = {
    "httpx": "httpx",
    "pikepdf": "pikepdf",
    "python-dotenv": "dotenv",
}


class OptionalDependencyError(ImportError):
    """선택 기능에 필요한 extra가 설치되지 않았을 때 발생한다."""

    def __init__(self, extra: str, missing_packages: tuple[str, ...]) -> None:
        self.extra = extra
        self.missing_packages = missing_packages
        self.install_command = f'python -m pip install "pdfbooktree[{extra}]"'
        packages = ", ".join(missing_packages)
        super().__init__(
            f"{extra} 기능에 필요한 optional dependency가 설치되지 않았다: "
            f"{packages}. 설치 명령: {self.install_command}"
        )


def require_optional_dependencies(
    extra: str,
    dependencies: Mapping[str, str],
) -> None:
    """extra에 속한 import module이 모두 존재하는지 확인한다."""

    missing = tuple(
        distribution
        for distribution, module in dependencies.items()
        if find_spec(module) is None
    )
    if missing:
        raise OptionalDependencyError(extra, missing)


def require_ocr_dependencies() -> None:
    """실제 OCR overlay에 필요한 dependency를 확인한다."""

    require_optional_dependencies("ocr", OCR_DEPENDENCIES)
