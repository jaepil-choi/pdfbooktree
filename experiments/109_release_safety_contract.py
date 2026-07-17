"""0.1.0 릴리스 안전성 계약을 독립 PoC로 검증한다."""

from __future__ import annotations

import json
import os
import tempfile
from fnmatch import fnmatch
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "experiments" / "outputs" / "109_release_safety_contract"


def _make_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "release safety contract")
    document.save(path)
    document.close()


def _same_file_deletion_risk(work_dir: Path) -> bool:
    """기존 unlink-first 흐름이 같은 input/output을 삭제하는지 재현한다."""

    source = work_dir / "same.pdf"
    _make_pdf(source)
    output = source
    if output.exists():
        output.unlink()
    try:
        fitz.open(source)
    except Exception:  # noqa: BLE001 - 삭제 위험 재현 여부만 기록한다.
        return not source.exists()
    return False


def _atomic_replace_preserves_old_output(work_dir: Path) -> bool:
    output = work_dir / "atomic.pdf"
    output.write_bytes(b"old-output")
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".pdf", dir=output.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(b"new-output")
        os.replace(temporary, output)
        return output.read_bytes() == b"new-output" and not temporary.exists()
    finally:
        temporary.unlink(missing_ok=True)


def _discover_pdfs(
    input_dir: Path,
    output_dir: Path,
    *,
    recursive: bool,
    include_globs: tuple[str, ...] = (),
    exclude_globs: tuple[str, ...] = (),
) -> list[str]:
    input_resolved = input_dir.resolve()
    output_resolved = output_dir.resolve()
    if input_resolved == output_resolved:
        raise ValueError("입력과 출력 디렉터리가 같다.")
    output_subtree = (
        output_resolved
        if output_resolved.is_relative_to(input_resolved)
        else None
    )
    iterator = input_dir.rglob("*") if recursive else input_dir.iterdir()
    found: list[str] = []
    for path in iterator:
        if not path.is_file() or path.suffix.casefold() != ".pdf":
            continue
        resolved = path.resolve()
        if output_subtree is not None and resolved.is_relative_to(output_subtree):
            continue
        relative = path.relative_to(input_dir).as_posix()
        folded = relative.casefold()
        included = not include_globs or any(
            fnmatch(folded, pattern.casefold()) for pattern in include_globs
        )
        excluded = any(
            fnmatch(folded, pattern.casefold()) for pattern in exclude_globs
        )
        if included and not excluded:
            found.append(relative)
    return sorted(found, key=lambda value: (value.casefold(), value))


def _discovery_contract(work_dir: Path) -> dict[str, object]:
    input_dir = work_dir / "books"
    output_dir = input_dir / "runs"
    (input_dir / "nested").mkdir(parents=True)
    output_dir.mkdir()
    for relative in ("ROOT.PDF", "nested/keep.pdf", "nested/skip.PdF"):
        target = input_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _make_pdf(target)
    _make_pdf(output_dir / "generated.pdf")
    discovered = _discover_pdfs(
        input_dir,
        output_dir,
        recursive=True,
        include_globs=("*.pdf", "nested/*.pdf"),
        exclude_globs=("nested/skip.pdf",),
    )
    return {
        "discovered": discovered,
        "uppercase_found": "ROOT.PDF" in discovered,
        "excluded_output_subtree": "runs/generated.pdf" not in discovered,
        "exclude_wins": "nested/skip.PdF" not in discovered,
        "deterministic_order": discovered == sorted(
            discovered, key=lambda value: (value.casefold(), value)
        ),
    }


def _dry_run_contract(work_dir: Path) -> dict[str, object]:
    input_pdf = work_dir / "plan.pdf"
    _make_pdf(input_pdf)
    plan = [{"title": "Chapter 1", "level": 1, "pdf_page": 1}]
    before = sorted(path.relative_to(work_dir).as_posix() for path in work_dir.rglob("*"))
    with fitz.open(input_pdf) as document:
        page_count = document.page_count
    valid = bool(plan) and all(
        item["level"] >= 1 and 1 <= item["pdf_page"] <= page_count for item in plan
    )
    after = sorted(path.relative_to(work_dir).as_posix() for path in work_dir.rglob("*"))
    return {
        "valid": valid,
        "page_count": page_count,
        "bookmark_count": len(plan),
        "filesystem_unchanged": before == after,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pdfbooktree-release-safety-") as temp:
        work_dir = Path(temp)
        deletion_risk = _same_file_deletion_risk(work_dir)
        atomic_replace = _atomic_replace_preserves_old_output(work_dir)
        discovery = _discovery_contract(work_dir)
        dry_run = _dry_run_contract(work_dir)

    result = {
        "same_input_output_deletion_risk_reproduced": deletion_risk,
        "atomic_replace_success": atomic_replace,
        "discovery": discovery,
        "dry_run": dry_run,
        "validation_passed": bool(
            deletion_risk
            and atomic_replace
            and discovery["uppercase_found"]
            and discovery["excluded_output_subtree"]
            and discovery["exclude_wins"]
            and discovery["deterministic_order"]
            and dry_run["valid"]
            and dry_run["filesystem_unchanged"]
        ),
    }
    (OUTPUT_DIR / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
