"""showcase 034: 300STUDY OCR PDF를 추론부터 chosen-level in-place 적용까지 처리한다.

실행:
    uv run python showcase/034_in_place_markdown_level_sync.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz

from pdfbooktree import process_pdf, resolve_processing_config
from pdfbooktree.utils.hashing import file_sha256

ROOT_DIR = Path(__file__).resolve().parents[1]
SHOWCASE_ID = "034_in_place_markdown_level_sync"
INPUT_PDF = (
    ROOT_DIR
    / "data"
    / "300STUDY_ocr_overlay"
    / "pdfs"
    / "NOW_READING"
    / "books"
    / (
        "Patrick G. Riley - The One-Page Proposal_  How to Get Your Business "
        "Pitch onto One Persuasive Page[office book].pdf"
    )
)
OUTPUT_ROOT = ROOT_DIR / "showcase" / "outputs" / SHOWCASE_ID
RESULT_PATH = OUTPUT_ROOT / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SAMPLE_PAGES = (1, 55, 111)


def main() -> None:
    before = inspect_pdf(INPUT_PDF)
    resolved = resolve_processing_config(
        set_overrides=[
            "markdown.enabled=true",
            "markdown.max_words=10000",
            "markdown.max_words_coverage=0.95",
            "processing.skip_existing_bookmarks=false",
        ]
    )
    run = process_pdf(
        INPUT_PDF,
        OUTPUT_ROOT,
        resolved,
        in_place=True,
    )
    after = inspect_pdf(INPUT_PDF)
    markdown_manifest_path = run.result.markdown_manifest_path
    if markdown_manifest_path is None:
        raise RuntimeError("Markdown manifest가 생성되지 않았다.")
    markdown_manifest = read_json(markdown_manifest_path)
    effective_plan_path = run.result.bookmark_plan_path
    if effective_plan_path is None:
        raise RuntimeError("effective bookmark plan이 생성되지 않았다.")
    effective_plan = read_json(effective_plan_path)
    full_plan = read_json(run.run_dir / "bookmark_plan_full.json")
    overwrite = read_json(run.run_dir / "pdf_overwrite.json")
    chosen_level = int(markdown_manifest["chosen_level"])
    embedded_max_level = max(
        (int(item["level"]) for item in effective_plan),
        default=0,
    )
    separate_bookmarked_pdfs = [
        str(path.relative_to(ROOT_DIR))
        for path in OUTPUT_ROOT.rglob("*_bookmarked.pdf")
    ]
    proof = {
        "same_input_path_overwritten": run.result.output_pdf.resolve()
        == INPUT_PDF.resolve(),
        "pdf_sha256_changed": before["sha256"] != after["sha256"],
        "page_count_preserved": before["page_count"] == after["page_count"],
        "sample_text_preserved": before["sample_text_sha256"]
        == after["sample_text_sha256"],
        "markdown_chosen_level_matches_pdf_max_level": chosen_level
        == embedded_max_level,
        "pdf_bookmark_count_matches_effective_plan": after["bookmark_count"]
        == len(effective_plan),
        "full_plan_preserved": len(full_plan) >= len(effective_plan),
        "overwrite_hashes_match": overwrite["original_sha256"] == before["sha256"]
        and overwrite["final_sha256"] == after["sha256"],
        "markdown_manifest_hash_matches_final_pdf": markdown_manifest["input"]["sha256"]
        == after["sha256"],
        "no_separate_bookmarked_pdf": not separate_bookmarked_pdfs,
    }
    result = {
        "status": "proved" if all(proof.values()) else "failed",
        "input_pdf": rel(INPUT_PDF),
        "run_dir": rel(run.run_dir),
        "manifest_path": rel(run.manifest_path),
        "effective_plan_path": rel(effective_plan_path),
        "full_plan_path": rel(run.run_dir / "bookmark_plan_full.json"),
        "markdown_manifest_path": rel(markdown_manifest_path),
        "pdf_overwrite_path": rel(run.run_dir / "pdf_overwrite.json"),
        "before": before,
        "after": after,
        "full_plan_count": len(full_plan),
        "effective_plan_count": len(effective_plan),
        "markdown_chosen_level": chosen_level,
        "embedded_max_level": embedded_max_level,
        "constraint_satisfied": markdown_manifest["constraint_satisfied"],
        "fallback_used": markdown_manifest["fallback_used"],
        "separate_bookmarked_pdfs": separate_bookmarked_pdfs,
        "proof": proof,
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_showcase(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "proved":
        raise RuntimeError(f"showcase proof 실패: {proof}")


def inspect_pdf(path: Path) -> dict[str, Any]:
    with fitz.open(path) as document:
        toc = document.get_toc()
        sample_text_sha256 = {
            str(pdf_page): hashlib.sha256(
                document.load_page(pdf_page - 1).get_text("text").encode("utf-8")
            ).hexdigest()
            for pdf_page in SAMPLE_PAGES
        }
        return {
            "path": rel(path),
            "sha256": file_sha256(path),
            "size_bytes": path.stat().st_size,
            "page_count": document.page_count,
            "bookmark_count": len(toc),
            "bookmark_max_level": max((int(item[0]) for item in toc), default=0),
            "sample_text_sha256": sample_text_sha256,
        }


def record_showcase(result: dict[str, Any]) -> None:
    catalog = read_json(SHOWCASE_JSON)
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "data/300STUDY_ocr_overlay의 실제 OCR PDF를 typography로 재추론하고, "
            "기본 10K Markdown chosen level과 PDF bookmark 최대 level을 "
            "동기화하며, 별도 bookmarked PDF 없이 검증된 sibling temporary "
            "PDF로 원본을 atomic replace한다."
        ),
        "inputs": [result["input_pdf"]],
        "outputs": rel(RESULT_PATH),
        "finding": (
            f"full_plan={result['full_plan_count']}, "
            f"effective_plan={result['effective_plan_count']}, "
            f"chosen_level={result['markdown_chosen_level']}, "
            f"embedded_max_level={result['embedded_max_level']}, "
            f"proof={result['proof']}"
        ),
        "command": "uv run python showcase/034_in_place_markdown_level_sync.py",
        "ran_at": result["ran_at"],
    }
    catalog["showcases"] = [
        item for item in catalog.get("showcases", []) if item.get("id") != SHOWCASE_ID
    ]
    catalog["showcases"].append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT_DIR))


if __name__ == "__main__":
    main()
