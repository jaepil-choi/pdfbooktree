"""experiment 083: 실제 부분 OCR artifact의 inspection 계약을 확인한다.

실행 중 중단된 OCR artifact에서 raw/insertable cache 수, 완료 page 번호, progress와
누락 page를 함께 읽어 agent가 다음 행동을 결정할 수 있는 요약을 만들 수 있는지
검증한다.

실행:
    uv run python experiments/083_inspect_partial_ocr_artifact.py
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import fitz


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "083_inspect_partial_ocr_artifact"
INPUT_PDF = (
    ROOT_DIR
    / "data"
    / "scanned-pdf-not-indexed"
    / "수리통계학(개정판)-김우철_upocr_merged.pdf"
)
ARTIFACT_DIR = (
    ROOT_DIR / "showcase" / "outputs" / "014_ocr_overlay_math_statistics" / "artifacts"
)
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID


def load_json(path: Path) -> dict[str, object]:
    """UTF-8 JSON object를 읽는다."""

    return json.loads(path.read_text(encoding="utf-8"))


def record_experiment(summary: dict[str, object]) -> None:
    """실험 결과를 registry에 기록한다."""

    data = load_json(EXPERIMENTS_JSON)
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "실제 부분 OCR artifact에서 raw/insertable cache, progress, page 번호를 "
            "함께 읽어 agent가 OCR 재개 또는 검증을 결정할 수 있는 inspection 요약을 "
            "만들 수 있는지 확인한다."
        ),
        "inputs": [
            str(INPUT_PDF.relative_to(ROOT_DIR)),
            str(ARTIFACT_DIR.relative_to(ROOT_DIR)),
        ],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "원본 PDF page count와 ocr_progress.json의 완료 page 수를 읽고, "
            "insertable JSON 내부의 1-based pdf_page를 세어 raw cache count, "
            "중복 page, 완료 범위 누락, 문서 전체 미처리 page를 비교한다."
        ),
        "summary": summary,
        "finding": (
            "partial OCR artifact는 progress의 completed_pages와 insertable JSON의 "
            "pdf_page 연속성을 함께 보여줘야 한다. raw cache 파일 수만으로는 어떤 "
            "page가 빠졌는지 판단할 수 없으며, insertable page 번호 검증이 필요하다."
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
    """실제 partial artifact의 inspection 요약을 생성한다."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    progress = load_json(ARTIFACT_DIR / "ocr_progress.json")
    raw_paths = list((ARTIFACT_DIR / "document_parse_cache" / "raw").glob("*.json"))
    insertable_pages = [
        int(load_json(path)["pdf_page"])
        for path in (ARTIFACT_DIR / "document_parse_cache" / "insertable").glob(
            "*.json"
        )
    ]
    counts = Counter(insertable_pages)
    completed_pages = int(progress["completed_pages"])
    with fitz.open(INPUT_PDF) as document:
        total_pages = document.page_count

    expected_completed = set(range(1, completed_pages + 1))
    actual_pages = set(insertable_pages)
    summary = {
        "total_pages": total_pages,
        "progress_completed_pages": completed_pages,
        "progress_current_page": progress.get("current_page"),
        "raw_cache_count": len(raw_paths),
        "insertable_cache_count": len(insertable_pages),
        "unique_insertable_page_count": len(actual_pages),
        "duplicate_insertable_pages": sorted(
            page for page, count in counts.items() if count > 1
        ),
        "missing_completed_pages": sorted(expected_completed - actual_pages),
        "unprocessed_page_count": total_pages - len(actual_pages),
        "first_unprocessed_page": min(set(range(1, total_pages + 1)) - actual_pages),
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_experiment(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
