"""출력 파일과 디렉터리 경로를 만든다."""

from __future__ import annotations

import re
from pathlib import Path


def safe_filename(value: str, max_length: int = 80) -> str:
    """파일명으로 안전한 ASCII 중심 문자열을 만든다."""

    normalized = re.sub(r"[^\w가-힣.-]+", "_", value.strip(), flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized).strip("_.")
    if not normalized:
        normalized = "untitled"
    return normalized[:max_length]


# Windows에서 디렉터리/파일 이름에 쓸 수 없는 문자와 제어 문자.
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_title_for_path(title: str, max_length: int = 80) -> str:
    """bookmark 제목을 Windows 안전한 디렉터리/파일 이름으로 바꾼다.

    ``safe_filename``과 달리 공백과 Unicode(한글 등)를 그대로 두어 사람이 읽기 쉬운
    제목을 보존한다. Windows 금지 문자만 제거하고, 연속 공백은 하나로 줄이며, 끝의
    점/공백은 떼어낸다(Windows가 싫어한다). 결과가 비면 ``untitled``로 둔다.
    """

    name = _ILLEGAL_FILENAME_CHARS.sub("", title).strip()
    name = re.sub(r"\s+", " ", name)
    name = name.rstrip(". ")
    if not name:
        name = "untitled"
    if len(name) > max_length:
        name = name[:max_length].rstrip()
    return name


def build_bookmarked_pdf_path(input_pdf: Path, output_dir: Path) -> Path:
    """`_bookmarked.pdf` 출력 경로를 만든다."""

    return output_dir / f"{input_pdf.stem}_bookmarked.pdf"


def build_markdown_dir_path(input_pdf: Path, output_dir: Path) -> Path:
    """Markdown tree 출력 디렉터리 경로를 만든다."""

    return output_dir / f"{input_pdf.stem}_markdown"


def build_report_path(input_pdf: Path, output_dir: Path) -> Path:
    """처리 report JSON 경로를 만든다."""

    return output_dir / f"{input_pdf.stem}_report.json"
