"""실험 022: 복사본 PDF에서 bookmark를 지우고 다시 삽입한다.

목적
- 원본 Hull PDF는 절대 수정하지 않고, output 디렉터리에 duplicate PDF를 만든다.
- duplicate에서 기존 bookmark를 추출한다.
- 별도 duplicate stage에서 PDF bookmark를 모두 제거한다.
- 추출한 bookmark를 다시 embed해 level/title/page가 동일하게 복원되는지 확인한다.

주의
- PyMuPDF의 detailed TOC에는 원본 PDF 내부 xref가 들어 있어, 다른 저장본에 그대로
  재삽입하면 target page가 깨질 수 있다. 따라서 이 실험은 공개 구현 후보로 안전한
  simple TOC(level, title, page) round-trip을 검증한다.
- 원본 파일 무결성은 SHA-256 전후 해시가 같은지로 확인한다.

출력
- experiments/outputs/022_roundtrip_pdf_bookmarks/john_hull_duplicate_original.pdf
- experiments/outputs/022_roundtrip_pdf_bookmarks/john_hull_duplicate_without_bookmarks.pdf
- experiments/outputs/022_roundtrip_pdf_bookmarks/john_hull_duplicate_reembedded_bookmarks.pdf
- experiments/outputs/022_roundtrip_pdf_bookmarks/bookmarks_extracted.json
- experiments/outputs/022_roundtrip_pdf_bookmarks/summary.json
- experiments/outputs/022_roundtrip_pdf_bookmarks/report.md

실행
    uv run python experiments/022_roundtrip_pdf_bookmarks.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "022_roundtrip_pdf_bookmarks"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"

DEFAULT_PDF = (
    ROOT_DIR
    / "data"
    / "native-pdf-indexed"
    / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf"
)

DUPLICATE_ORIGINAL = OUTPUT_DIR / "john_hull_duplicate_original.pdf"
WITHOUT_BOOKMARKS = OUTPUT_DIR / "john_hull_duplicate_without_bookmarks.pdf"
REEMBEDDED_BOOKMARKS = OUTPUT_DIR / "john_hull_duplicate_reembedded_bookmarks.pdf"


def sha256(path: Path) -> str:
    """파일 SHA-256 해시를 계산한다."""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_simple_toc(pdf_path: Path) -> list[list[Any]]:
    """PyMuPDF simple TOC(level, title, page)를 추출한다."""

    with fitz.open(pdf_path) as document:
        return document.get_toc(simple=True)


def toc_to_records(toc: list[list[Any]]) -> list[dict[str, Any]]:
    """JSON 기록용 bookmark dict 목록으로 변환한다."""

    records: list[dict[str, Any]] = []
    for order, item in enumerate(toc, start=1):
        level, title, pdf_page = item[:3]
        records.append(
            {
                "order": order,
                "level": int(level),
                "title": str(title),
                "pdf_page": int(pdf_page) if int(pdf_page) > 0 else None,
            }
        )
    return records


def summarize_toc(toc: list[list[Any]]) -> dict[str, Any]:
    """bookmark 개수, 레벨 분포, page target 품질을 요약한다."""

    pages = [int(item[2]) for item in toc if int(item[2]) > 0]
    return {
        "bookmark_count": len(toc),
        "level_counts": {
            str(level): count for level, count in sorted(Counter(item[0] for item in toc).items())
        },
        "min_target_page": min(pages) if pages else None,
        "max_target_page": max(pages) if pages else None,
        "missing_target_count": len(toc) - len(pages),
        "preview": toc_to_records(toc[:12]),
    }


def rewrite_pdf_toc(source_pdf: Path, target_pdf: Path, toc: list[list[Any]]) -> int:
    """source_pdf를 열어 toc를 설정하고 target_pdf로 저장한다."""

    if target_pdf.exists():
        target_pdf.unlink()
    with fitz.open(source_pdf) as document:
        changed_count = document.set_toc(toc)
        document.save(target_pdf, garbage=4, deflate=True)
    return int(changed_count)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_report(summary: dict[str, Any]) -> None:
    """사람이 빠르게 확인할 수 있는 markdown 리포트를 작성한다."""

    extracted = summary["extracted"]
    without = summary["without_bookmarks"]
    reembedded = summary["reembedded"]
    report = f"""# Experiment 022: PDF Bookmark Round-trip

## 입력

- 원본 PDF: `{summary["source_pdf"]}`
- duplicate PDF: `{summary["duplicate_pdf"]}`

## 안전성 확인

- 원본 SHA-256 before: `{summary["source_sha256_before"]}`
- 원본 SHA-256 after: `{summary["source_sha256_after"]}`
- 원본 무결성 유지: `{summary["source_unchanged"]}`

## 단계별 결과

1. duplicate 생성: `{summary["duplicate_pdf"]}`
2. bookmark 추출: {extracted["bookmark_count"]}개
3. bookmark 삭제 stage: {without["bookmark_count"]}개
4. bookmark 재삽입 stage: {reembedded["bookmark_count"]}개
5. round-trip 동일성(level/title/page): `{summary["roundtrip_equal"]}`

## 판단

{summary["finding"]}

## 비고

PyMuPDF detailed TOC는 내부 xref를 포함하므로 별도 저장본에 그대로 옮기면 page target이
깨질 수 있다. 이 실험은 구현 후보로 simple TOC(level/title/page)를 사용한다.
"""
    (OUTPUT_DIR / "report.md").write_text(report, encoding="utf-8")


def record_experiment(summary: dict[str, Any]) -> None:
    """experiments.json에 이번 실험 결과를 append/갱신한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "원본 Hull PDF를 건드리지 않고 duplicate을 만든 뒤 bookmark를 추출하고, "
            "복사본 stage에서 bookmark를 모두 제거한 다음, 추출한 bookmark를 다시 embed해 "
            "level/title/page round-trip이 가능한지 검증한다."
        ),
        "inputs": [summary["source_pdf"]],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "finding": summary["finding"],
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    experiments = data.get("experiments", data) if isinstance(data, dict) else data
    experiments = [item for item in experiments if item.get("id") != EXPERIMENT_ID]
    experiments.append(entry)
    if isinstance(data, dict):
        data["experiments"] = experiments
    else:
        data = experiments
    write_json(EXPERIMENTS_JSON, data)


def run(pdf_path: Path, record: bool) -> dict[str, Any]:
    """실험 전체를 실행한다."""

    source_pdf = pdf_path.resolve()
    if not source_pdf.exists():
        raise SystemExit(f"PDF가 없다: {source_pdf}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    source_hash_before = sha256(source_pdf)
    shutil.copy2(source_pdf, DUPLICATE_ORIGINAL)

    extracted_toc = extract_simple_toc(DUPLICATE_ORIGINAL)
    if not extracted_toc:
        raise SystemExit(f"bookmark가 없다(이 실험 대상 아님): {DUPLICATE_ORIGINAL}")

    removed_count = rewrite_pdf_toc(DUPLICATE_ORIGINAL, WITHOUT_BOOKMARKS, [])
    without_toc = extract_simple_toc(WITHOUT_BOOKMARKS)

    inserted_count = rewrite_pdf_toc(
        WITHOUT_BOOKMARKS, REEMBEDDED_BOOKMARKS, extracted_toc
    )
    reembedded_toc = extract_simple_toc(REEMBEDDED_BOOKMARKS)

    source_hash_after = sha256(source_pdf)
    roundtrip_equal = extracted_toc == reembedded_toc
    source_unchanged = source_hash_before == source_hash_after

    finding = (
        f"원본 Hull PDF는 SHA-256 전후가 같아 수정되지 않았다"
        f"(source_unchanged={source_unchanged}). duplicate에서 bookmark "
        f"{len(extracted_toc)}개를 추출했고, 삭제 stage에서는 bookmark가 "
        f"{len(without_toc)}개로 비었다. simple TOC(level/title/page)를 다시 embed한 "
        f"결과 bookmark {len(reembedded_toc)}개가 복원되었고 round-trip 동일성은 "
        f"{roundtrip_equal}이다. set_toc([])가 보고한 제거 수는 {removed_count}, "
        f"set_toc(extracted_toc)가 보고한 삽입 수는 {inserted_count}이다."
    )

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "source_pdf": str(source_pdf.relative_to(ROOT_DIR)),
        "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "source_unchanged": source_unchanged,
        "duplicate_pdf": str(DUPLICATE_ORIGINAL.relative_to(ROOT_DIR)),
        "without_bookmarks_pdf": str(WITHOUT_BOOKMARKS.relative_to(ROOT_DIR)),
        "reembedded_bookmarks_pdf": str(REEMBEDDED_BOOKMARKS.relative_to(ROOT_DIR)),
        "removed_count_returned_by_pymupdf": removed_count,
        "inserted_count_returned_by_pymupdf": inserted_count,
        "roundtrip_equal": roundtrip_equal,
        "extracted": summarize_toc(extracted_toc),
        "without_bookmarks": summarize_toc(without_toc),
        "reembedded": summarize_toc(reembedded_toc),
        "finding": finding,
    }

    write_json(OUTPUT_DIR / "bookmarks_extracted.json", toc_to_records(extracted_toc))
    write_json(OUTPUT_DIR / "summary.json", summary)
    write_report(summary)

    if record:
        record_experiment(summary)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument(
        "--no-record", action="store_true", help="experiments.json 기록을 건너뛴다"
    )
    args = parser.parse_args()

    summary = run(args.pdf, record=not args.no_record)
    print(summary["finding"])
    print(f"summary: {OUTPUT_DIR / 'summary.json'}")
    print(f"reembedded pdf: {REEMBEDDED_BOOKMARKS}")


if __name__ == "__main__":
    main()
