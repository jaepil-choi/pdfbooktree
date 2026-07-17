"""디렉터리 기반 command가 공유하는 PDF 탐색 계약이다."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path


@dataclass(frozen=True)
class PdfDiscoveryResult:
    """결정적으로 선택한 PDF와 자동 제외한 output subtree다."""

    paths: tuple[Path, ...]
    excluded_output_subtree: Path | None
    include_globs: tuple[str, ...]
    exclude_globs: tuple[str, ...]


def discover_pdfs(
    input_dir: Path | str,
    output_dir: Path | str,
    *,
    recursive: bool = False,
    include_globs: tuple[str, ...] = (),
    exclude_globs: tuple[str, ...] = (),
) -> PdfDiscoveryResult:
    """PDF를 대소문자와 OS에 무관한 상대 경로 규칙으로 찾는다.

    output directory가 input의 하위이면 이전 실행 결과를 다시 입력으로 읽지
    않도록 subtree 전체를 제외한다. 두 directory가 같으면 report/output을
    입력과 안전하게 분리할 수 없으므로 거부한다.
    """

    input_path = Path(input_dir).resolve()
    output_path = Path(output_dir).resolve()
    if not input_path.is_dir():
        raise NotADirectoryError(f"입력 디렉터리가 없다: {input_path}")
    if input_path == output_path:
        raise ValueError(
            f"입력과 출력 디렉터리는 달라야 한다: input={input_path}, output={output_path}"
        )

    normalized_includes = _normalize_globs(include_globs, name="include_globs")
    normalized_excludes = _normalize_globs(exclude_globs, name="exclude_globs")
    output_subtree = output_path if output_path.is_relative_to(input_path) else None
    iterator = input_path.rglob("*") if recursive else input_path.iterdir()
    selected: list[tuple[str, Path]] = []
    for path in iterator:
        if not path.is_file() or path.suffix.casefold() != ".pdf":
            continue
        resolved = path.resolve()
        if output_subtree is not None and resolved.is_relative_to(output_subtree):
            continue
        relative = path.relative_to(input_path).as_posix()
        folded = relative.casefold()
        included = not normalized_includes or any(
            fnmatch(folded, pattern.casefold()) for pattern in normalized_includes
        )
        excluded = any(
            fnmatch(folded, pattern.casefold()) for pattern in normalized_excludes
        )
        if included and not excluded:
            selected.append((relative, path))
    selected.sort(key=lambda item: (item[0].casefold(), item[0]))
    return PdfDiscoveryResult(
        paths=tuple(path for _, path in selected),
        excluded_output_subtree=output_subtree,
        include_globs=normalized_includes,
        exclude_globs=normalized_excludes,
    )


def _normalize_globs(values: tuple[str, ...], *, name: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name}에는 비어 있지 않은 문자열만 사용할 수 있다.")
        normalized.append(value.strip().replace("\\", "/"))
    return tuple(normalized)
