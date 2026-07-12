"""experiment 082: raw Document Parse cache로 누락된 insertable page를 복원한다.

이미 API 응답 raw cache는 남았지만 표준 insertable cache가 일부 빠진 실제 책에서,
``cache_policy=only``로 page render와 adapter 변환만 수행할 때, API 호출 없이
누락 insertable model이 실제로 보완되는지 확인한다.

실행:
    uv run python experiments/082_recover_insertable_from_raw_cache.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pdfbooktree.ocr import OcrOverlayBuilder, OcrOverlayConfig

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
EXPERIMENT_ID = "082_recover_insertable_from_raw_cache"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
RELATIVE_PDF = Path("a_books/normalbook/금리의_경제학_-_홍완표.pdf")
INPUT_PDF = ROOT_DIR / "data" / "300STUDY" / RELATIVE_PDF
ARTIFACT_DIR = (
    ROOT_DIR / "data" / "300STUDY" / "artifacts" / RELATIVE_PDF.with_suffix("")
)


def cache_file_count(name: str) -> int:
    """지정 cache 하위 directory의 JSON 파일 수를 센다."""

    return len(list((ARTIFACT_DIR / "document_parse_cache" / name).glob("*.json")))


def record_experiment(summary: dict[str, object]) -> None:
    """실험 결과를 registry에 기록한다."""

    data = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": EXPERIMENT_ID,
        "purpose": (
            "insertable cache가 누락됐지만 raw Document Parse response cache는 완전한 "
            "실제 300STUDY PDF에서, OCR API를 다시 호출하지 않고 raw cache와 adapter로 "
            "누락 insertable page를 복원한 뒤 OCR overlay PDF를 재조립할 수 있는지 검증한다."
        ),
        "inputs": [
            str(INPUT_PDF.relative_to(ROOT_DIR)),
            str(ARTIFACT_DIR.relative_to(ROOT_DIR)),
        ],
        "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
        "method": (
            "기존 OCR 설정과 동일한 input hash, engine, 요청 옵션, DPI로 "
            "OcrOverlayBuilder(cache_policy=only)를 실행한다. raw cache hit이면 page를 "
            "로컬 render한 뒤 adapter로 insertable model을 만들어 저장하고, raw cache가 "
            "없으면 즉시 실패하므로 Upstage API 호출은 발생하지 않는다."
        ),
        "summary": summary,
        "finding": (
            "실패: raw cache는 264개 전부 hit하고 API 호출도 없었지만 insertable 파일 수는 "
            "263개에서 늘지 않았다. 기존 insertable cache key가 raw response와 adapter version만 "
            "포함해 OCR 내용이 같은 서로 다른 page가 하나의 model을 공유하는 collision이 원인이다. "
            "따라서 artifact만으로 누락 page를 신뢰성 있게 재조립하는 기능은 제품에 넣지 않는다."
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
    original_config = json.loads(
        (ARTIFACT_DIR / "ocr_overlay_config.json").read_text(encoding="utf-8")
    )
    insertable_before = cache_file_count("insertable")
    raw_before = cache_file_count("raw")
    result = OcrOverlayBuilder(
        OcrOverlayConfig(
            input_pdf=INPUT_PDF,
            output_pdf=OUTPUT_DIR / "interest_economics_raw_cache_rebuild.pdf",
            output_dir=ARTIFACT_DIR,
            engine=original_config["engine"],
            engine_options=original_config["engine_options"],
            render_dpi=original_config["render_dpi"],
            force=True,
            confirm_bookmark_ocr_overwrite=True,
            cache_policy="only",
        )
    ).run()
    summary = {
        "page_count": result.page_count,
        "raw_cache_file_count": raw_before,
        "insertable_before": insertable_before,
        "insertable_after": cache_file_count("insertable"),
        "cache_hit_count": result.cache_hit_count,
        "cache_miss_count": result.cache_miss_count,
        "output_pdf": str(result.output_pdf.relative_to(ROOT_DIR)),
        "output_pdf_bytes": result.output_pdf.stat().st_size,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    record_experiment(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
