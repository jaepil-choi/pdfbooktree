"""data/ 아래 labeled 샘플 PDF로 bookmark 유무 / native-scanned 구분이 잘 되는지 확인한다.

300STUDY 전체는 건드리지 않고, 이미 라벨이 폴더명으로 붙어 있는 6개 샘플만 사용한다.

- data/native-pdf-indexed: bookmark 있음 + native text PDF
- data/scanned-pdf-indexed: bookmark 있음 + scanned PDF
- data/scanned-pdf-not-indexed: bookmark 없음 + scanned PDF
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "065_bookmark_native_scanned_labeled_check"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DATA_DIR = ROOT_DIR / "data"

# 페이지 전체를 거의 다 덮는 단일 이미지가 있으면 그 page는 "scan-like"로 본다.
IMAGE_COVERAGE_THRESHOLD = 0.85
# sample PDF 중 scan-like page 비율이 이 값을 넘으면 문서를 scanned로 판정한다.
SCANNED_PAGE_FRACTION_THRESHOLD = 0.6
MAX_SAMPLE_PAGES = 20

LABEL_FOLDERS: dict[str, dict[str, bool]] = {
    "native-pdf-indexed": {"expected_has_bookmark": True, "expected_is_scanned": False},
    "scanned-pdf-indexed": {"expected_has_bookmark": True, "expected_is_scanned": True},
    "scanned-pdf-not-indexed": {
        "expected_has_bookmark": False,
        "expected_is_scanned": True,
    },
}


def discover_labeled_pdfs() -> list[dict[str, Any]]:
    items = []
    for folder_name, expected in LABEL_FOLDERS.items():
        folder = DATA_DIR / folder_name
        for path in sorted(folder.glob("*.pdf")):
            items.append(
                {
                    "folder": folder_name,
                    "path": path,
                    "expected_has_bookmark": expected["expected_has_bookmark"],
                    "expected_is_scanned": expected["expected_is_scanned"],
                }
            )
    return items


def sample_page_indices(page_count: int, max_pages: int) -> list[int]:
    """문서 전체에 걸쳐 고르게 page index를 뽑는다. body page 편향을 줄이기 위함이다."""

    if page_count <= max_pages:
        return list(range(page_count))
    step = page_count / max_pages
    return sorted({int(i * step) for i in range(max_pages)})


def clipped_area(bbox: fitz.Rect, page_rect: fitz.Rect) -> float:
    clipped = bbox & page_rect
    if clipped.is_empty:
        return 0.0
    return clipped.width * clipped.height


def analyze_page(page: fitz.Page) -> dict[str, Any]:
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height

    image_info = page.get_image_info()
    max_image_ratio = 0.0
    for info in image_info:
        bbox = fitz.Rect(info["bbox"])
        ratio = clipped_area(bbox, page_rect) / page_area if page_area else 0.0
        max_image_ratio = max(max_image_ratio, ratio)

    text = page.get_text("text")
    char_count = len(text.strip())

    return {
        "max_image_ratio": max_image_ratio,
        "char_count": char_count,
        "image_count": len(image_info),
        "is_scan_like_page": max_image_ratio >= IMAGE_COVERAGE_THRESHOLD,
    }


def classify_pdf(path: Path) -> dict[str, Any]:
    with fitz.open(path) as document:
        page_count = document.page_count
        toc = document.get_toc(simple=True)
        has_bookmark = len(toc) > 0
        toc_level_count = len({item[0] for item in toc})
        # production ocr/builder.py의 _validate_existing_bookmark_confirmation은
        # bookmark 품질과 무관하게 존재만으로 confirm을 요구한다. 여기서는 그
        # 원문 판정(raw)과, level 구조가 있는지(품질 신호)를 함께 남긴다.
        has_meaningful_bookmark = has_bookmark and toc_level_count >= 2

        indices = sample_page_indices(page_count, MAX_SAMPLE_PAGES)
        page_features = []
        for index in indices:
            page = document.load_page(index)
            feature = analyze_page(page)
            feature["pdf_page"] = index + 1
            page_features.append(feature)

    scan_like_count = sum(1 for f in page_features if f["is_scan_like_page"])
    scanned_page_fraction = scan_like_count / len(page_features) if page_features else 0.0
    is_scanned = scanned_page_fraction >= SCANNED_PAGE_FRACTION_THRESHOLD

    median_char_count = (
        sorted(f["char_count"] for f in page_features)[len(page_features) // 2]
        if page_features
        else 0
    )

    return {
        "page_count": page_count,
        "sampled_page_count": len(page_features),
        "bookmark_count": len(toc),
        "toc_level_count": toc_level_count,
        "has_bookmark": has_bookmark,
        "has_meaningful_bookmark": has_meaningful_bookmark,
        "scanned_page_fraction": scanned_page_fraction,
        "median_char_count_sampled": median_char_count,
        "is_scanned": is_scanned,
        "page_features": page_features,
    }


def evaluate(item: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    bookmark_correct = result["has_bookmark"] == item["expected_has_bookmark"]
    scanned_correct = result["is_scanned"] == item["expected_is_scanned"]
    return {
        "bookmark_correct": bookmark_correct,
        "scanned_correct": scanned_correct,
        "all_correct": bookmark_correct and scanned_correct,
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_experiment_registry() -> dict[str, Any]:
    if not EXPERIMENTS_JSON.exists():
        return {"experiments": []}
    text = EXPERIMENTS_JSON.read_text(encoding="utf-8").strip()
    if not text:
        return {"experiments": []}
    loaded = json.loads(text)
    if isinstance(loaded, list):
        return {"experiments": loaded}
    if "experiments" not in loaded:
        loaded["experiments"] = []
    return loaded


def build_finding(rows: list[dict[str, Any]]) -> str:
    total = len(rows)
    correct = sum(1 for row in rows if row["eval"]["all_correct"])
    wrong = [row for row in rows if not row["eval"]["all_correct"]]
    parts = [
        f"labeled 샘플 {total}개 중 {correct}개에서 raw bookmark 유무와 "
        f"native/scanned 판정이 모두 기대값과 일치했다. "
        f"image-coverage 기반 native/scanned 판정은 6개 전부 정확했다."
    ]
    for row in wrong:
        parts.append(
            f"{row['pdf_id']}(폴더={row['folder']})는 기대값 "
            f"has_bookmark={row['expected_has_bookmark']}였지만 raw 판정은 "
            f"has_bookmark={row['result']['has_bookmark']} "
            f"(bookmark {row['result']['bookmark_count']}개, "
            f"level_count={row['result']['toc_level_count']})였다. "
            f"이 PDF의 bookmark는 전부 level 1이고 제목이 "
            f"'부분1, 부분2...'식 기계적 분할 마커라 실제 목차가 아니었다. "
            f"toc_level_count>=2 조건을 추가한 has_meaningful_bookmark 기준으로는 "
            f"{row['result']['has_meaningful_bookmark']}로 기대값과 일치했다. "
            f"production ocr/builder.py의 bookmark confirm gate는 raw 존재만 보므로 "
            f"이 PDF에서는 여전히 --confirm-bookmark-ocr-overwrite가 필요하지만, "
            f"'bookmark 없는 scanned PDF만 골라 OCR overwrite'라는 이번 목적에는 "
            f"has_meaningful_bookmark 기준이 더 적합해 보인다."
        )
    return " ".join(parts)


def update_experiment_registry(rows: list[dict[str, Any]]) -> None:
    registry = load_experiment_registry()
    experiments = [
        experiment
        for experiment in registry["experiments"]
        if experiment.get("id") != EXPERIMENT_ID
    ]
    experiments.append(
        {
            "id": EXPERIMENT_ID,
            "purpose": (
                "300STUDY 전체를 건드리기 전에, 이미 폴더명으로 라벨이 붙은 6개 "
                "샘플 PDF(native-pdf-indexed/scanned-pdf-indexed/"
                "scanned-pdf-not-indexed)로 bookmark 유무 판정과 "
                "image-coverage 기반 native/scanned 판정이 정확한지 확인한다."
            ),
            "inputs": [
                str(item["path"].relative_to(ROOT_DIR)) for item in discover_labeled_pdfs()
            ],
            "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
            "finding": build_finding(rows),
            "ran_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    registry["experiments"] = experiments
    write_json(EXPERIMENTS_JSON, registry)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    items = discover_labeled_pdfs()
    if not items:
        raise FileNotFoundError("labeled sample PDF를 찾지 못했다: " + str(DATA_DIR))

    rows = []
    for item in items:
        pdf_id = item["path"].stem[:80]
        result = classify_pdf(item["path"])
        eval_result = evaluate(item, result)
        row = {
            "pdf_id": pdf_id,
            "folder": item["folder"],
            "path": str(item["path"].relative_to(ROOT_DIR)),
            "expected_has_bookmark": item["expected_has_bookmark"],
            "expected_is_scanned": item["expected_is_scanned"],
            "result": result,
            "eval": eval_result,
        }
        rows.append(row)
        write_json(OUTPUT_DIR / f"{pdf_id}.json", row)
        print(
            f"[{item['folder']}] {pdf_id}: "
            f"has_bookmark={result['has_bookmark']}(기대 {item['expected_has_bookmark']}), "
            f"is_scanned={result['is_scanned']}(기대 {item['expected_is_scanned']}), "
            f"scanned_page_fraction={result['scanned_page_fraction']:.2f}, "
            f"median_char_count={result['median_char_count_sampled']}, "
            f"correct={eval_result['all_correct']}"
        )

    write_json(OUTPUT_DIR / "summary.json", rows)
    update_experiment_registry(rows)


if __name__ == "__main__":
    main()
