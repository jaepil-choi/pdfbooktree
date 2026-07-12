"""experiment 081: 기존 insertable artifact만으로 OCR overlay PDF를 재조립한다.

이미 Upstage Document Parse를 끝낸 책은 raw cache key와 원본 hash를 다시 계산하거나
API를 호출하지 않고, artifact의 ``insertable/*.json``을 직접 읽어 원본 PDF에
invisible OCR layer만 다시 삽입할 수 있는지 확인한다.

실행:
    uv run python experiments/081_rebuild_pdf_from_insertable_artifacts.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import fitz

from pdfbooktree.ocr.cache import insertable_page_from_json
from pdfbooktree.ocr.insertion import write_overlay_pdf

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "081_rebuild_pdf_from_insertable_artifacts"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
RELATIVE_PDF = Path("a_books/normalbook/AB테스트_무작정따라하_-_오서준.pdf")
SOURCE_PDF = ROOT_DIR / "data" / "300STUDY" / RELATIVE_PDF
ARTIFACT_DIR = (
    ROOT_DIR / "data" / "300STUDY" / "artifacts" / RELATIVE_PDF.with_suffix("")
)
PREVIOUS_PDF = ROOT_DIR / "data" / "300STUDY" / "pdfs" / RELATIVE_PDF


def render_hash(pdf_path: Path, pdf_page: int) -> str:
    """지정 page의 visual render가 같은지 비교할 SHA-256을 계산한다."""

    with fitz.open(pdf_path) as document:
        png = document[pdf_page - 1].get_pixmap(dpi=144, alpha=False).tobytes("png")
    return hashlib.sha256(png).hexdigest()


def load_insertable_pages(artifact_dir: Path):
    """cache file명과 무관하게 page 모델 안의 1-based page 번호로 정렬한다."""

    cache_dir = artifact_dir / "document_parse_cache" / "insertable"
    pages = [
        insertable_page_from_json(json.loads(path.read_text(encoding="utf-8")))
        for path in cache_dir.glob("*.json")
    ]
    return sorted(pages, key=lambda page: page.pdf_page)


def record_experiment(summary: dict[str, object]) -> None:
    """실험 결과를 registry에 기록한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "기존 Document Parse insertable artifact만 직접 읽어 원본 PDF에 invisible "
            "OCR layer를 다시 삽입하고, API 재호출 없이 이전 PNG sandwich PDF보다 "
            "작은 PDF를 만들 수 있는지 실제 300STUDY 책으로 검증한다."
        ),
        "inputs": [
            str(SOURCE_PDF.relative_to(ROOT_DIR)),
            str(ARTIFACT_DIR.relative_to(ROOT_DIR)),
            str(PREVIOUS_PDF.relative_to(ROOT_DIR)),
        ],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "insertable cache JSON을 pdf_page로 정렬해 직접 역직렬화하고, "
            "write_overlay_pdf로 source PDF의 기존 text object를 교체한 뒤 invisible "
            "OCR layer를 삽입한다. raw cache key, PDF render, Upstage API 호출은 하지 않는다."
        ),
        "summary": summary,
        "finding": (
            "insertable artifact가 모든 source page를 빠짐없이 포함하면 cache key와 API 호출 없이 "
            "OCR overlay PDF를 재조립할 수 있다. 다만 이 결과는 완전한 cache에 한정된 PoC이며, "
            "누락 artifact의 신뢰성 있는 복구와 제품 public interface 도입을 정당화하지는 않는다."
        ),
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["experiments"] = [
        item for item in data["experiments"] if item.get("id") != EXPERIMENT_ID
    ] + [entry]
    EXPERIMENTS_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_pdf = OUTPUT_DIR / "abtest_artifact_rebuild.pdf"
    insertable_pages = load_insertable_pages(ARTIFACT_DIR)
    with fitz.open(SOURCE_PDF) as document:
        source_page_count = document.page_count

    page_numbers = [page.pdf_page for page in insertable_pages]
    expected_pages = list(range(1, source_page_count + 1))
    if page_numbers != expected_pages:
        raise RuntimeError(
            f"artifact page가 source 전체와 일치하지 않습니다: "
            f"loaded={len(page_numbers)}, source={source_page_count}"
        )

    sample_pages = [1, (source_page_count + 1) // 2, source_page_count]
    before_hashes = {page: render_hash(SOURCE_PDF, page) for page in sample_pages}
    write_overlay_pdf(
        insertable_pages,
        SOURCE_PDF,
        output_pdf,
        OUTPUT_DIR / "_overlay_pages",
    )
    after_hashes = {page: render_hash(output_pdf, page) for page in sample_pages}
    with fitz.open(output_pdf) as document:
        text_lengths = {
            page: len(document[page - 1].get_text()) for page in sample_pages
        }

    summary = {
        "source_page_count": source_page_count,
        "insertable_page_count": len(insertable_pages),
        "insertable_pages_complete": page_numbers == expected_pages,
        "source_bytes": SOURCE_PDF.stat().st_size,
        "previous_sandwich_pdf_bytes": PREVIOUS_PDF.stat().st_size,
        "artifact_rebuild_pdf_bytes": output_pdf.stat().st_size,
        "artifact_rebuild_vs_sandwich_ratio": round(
            output_pdf.stat().st_size / PREVIOUS_PDF.stat().st_size, 6
        ),
        "sample_pages": [
            {
                "pdf_page": page,
                "source_render_sha256": before_hashes[page],
                "rebuild_render_sha256": after_hashes[page],
                "visual_identical": before_hashes[page] == after_hashes[page],
                "rebuild_text_length": text_lengths[page],
            }
            for page in sample_pages
        ],
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_experiment(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
