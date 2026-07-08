"""scanned pdf 판정을 엄격한 두 조건으로 좁히고, 불충족 사유를 값과 함께 남긴다.

067까지는 "sample page 중 scan-like page 비율이 60% 이상"이라는 다수결
threshold를 썼다. 이번에는 기준을 엄격하게 좁힌다.

- scanned pdf 조건: scanned_page_fraction == 1.0 AND total_visible_chars_sampled == 0
- 두 조건 중 하나라도 어긋나면 not-scanned로 분류하고, 어떤 조건이 왜 실패했는지
  reason 문자열과 실제 수치를 함께 기록한다. page 단위로도 왜 그 page가
  scan-like가 아닌지(image_coverage_ratio 부족 vs visible_char_count 존재) 남긴다.

이 실험은 300STUDY에 배치로 돌리기 전에, src에 올릴 CSV/JSONL 스키마를 6개
labeled 샘플로 먼저 검증하는 것이 목적이다. 300STUDY는 건드리지 않는다.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "068_strict_scanned_criteria_reason_log"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DATA_DIR = ROOT_DIR / "data"

VISIBLE_RENDER_MODES = {0, 1, 2, 4, 5, 6}
IMAGE_COVERAGE_THRESHOLD = 0.85
VISIBLE_CHAR_THRESHOLD = 10
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
    if page_count <= max_pages:
        return list(range(page_count))
    step = page_count / max_pages
    return sorted({int(i * step) for i in range(max_pages)})


def clipped_area(bbox: fitz.Rect, page_rect: fitz.Rect) -> float:
    clipped = bbox & page_rect
    return 0.0 if clipped.is_empty else clipped.width * clipped.height


def analyze_page(page: fitz.Page) -> dict[str, Any]:
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height

    image_coverage_ratio = 0.0
    for info in page.get_image_info():
        ratio = clipped_area(fitz.Rect(info["bbox"]), page_rect) / page_area if page_area else 0.0
        image_coverage_ratio = max(image_coverage_ratio, ratio)

    trace = page.get_texttrace()
    visible_char_count = sum(
        len(span["chars"]) for span in trace if span["type"] in VISIBLE_RENDER_MODES
    )
    invisible_char_count = sum(
        len(span["chars"]) for span in trace if span["type"] not in VISIBLE_RENDER_MODES
    )

    is_image_dominant = image_coverage_ratio >= IMAGE_COVERAGE_THRESHOLD
    has_visible_text = visible_char_count >= VISIBLE_CHAR_THRESHOLD
    is_scan_like_page = is_image_dominant and not has_visible_text

    page_reject_reasons: list[str] = []
    if not is_image_dominant:
        page_reject_reasons.append(
            f"image_coverage_ratio={image_coverage_ratio:.4f} < {IMAGE_COVERAGE_THRESHOLD}"
        )
    if has_visible_text:
        page_reject_reasons.append(
            f"visible_char_count={visible_char_count} >= {VISIBLE_CHAR_THRESHOLD}"
        )

    return {
        "image_coverage_ratio": image_coverage_ratio,
        "visible_char_count": visible_char_count,
        "invisible_char_count": invisible_char_count,
        "is_scan_like_page": is_scan_like_page,
        "page_reject_reasons": page_reject_reasons,
    }


def classify_pdf(path: Path) -> dict[str, Any]:
    with fitz.open(path) as document:
        page_count = document.page_count
        toc = document.get_toc(simple=True)
        has_bookmark = len(toc) > 0
        toc_level_count = len({item[0] for item in toc})
        has_meaningful_bookmark = has_bookmark and toc_level_count >= 2

        indices = sample_page_indices(page_count, MAX_SAMPLE_PAGES)
        page_features = []
        for index in indices:
            feature = analyze_page(document.load_page(index))
            feature["pdf_page"] = index + 1
            page_features.append(feature)

    scan_like_count = sum(1 for f in page_features if f["is_scan_like_page"])
    scanned_page_fraction = scan_like_count / len(page_features) if page_features else 0.0
    total_visible_chars = sum(f["visible_char_count"] for f in page_features)
    total_invisible_chars = sum(f["invisible_char_count"] for f in page_features)

    # 엄격한 두 조건: 전부 scan-like page여야 하고, visible text가 전혀 없어야 한다.
    fraction_ok = scanned_page_fraction == 1.0
    visible_chars_ok = total_visible_chars == 0
    is_scanned = fraction_ok and visible_chars_ok

    reject_reasons: list[str] = []
    if not fraction_ok:
        non_scan_pages = [
            {"pdf_page": f["pdf_page"], "reasons": f["page_reject_reasons"]}
            for f in page_features
            if not f["is_scan_like_page"]
        ]
        reject_reasons.append(
            f"scanned_page_fraction={scanned_page_fraction:.4f} != 1.0 "
            f"(non_scan_like_page_count={len(non_scan_pages)}/{len(page_features)})"
        )
    else:
        non_scan_pages = []
    if not visible_chars_ok:
        pages_with_visible_text = [
            {"pdf_page": f["pdf_page"], "visible_char_count": f["visible_char_count"]}
            for f in page_features
            if f["visible_char_count"] > 0
        ]
        reject_reasons.append(
            f"total_visible_chars_sampled={total_visible_chars} != 0 "
            f"(pages_with_visible_text_count={len(pages_with_visible_text)})"
        )
    else:
        pages_with_visible_text = []

    return {
        "page_count": page_count,
        "sampled_page_count": len(page_features),
        "bookmark_count": len(toc),
        "toc_level_count": toc_level_count,
        "has_bookmark": has_bookmark,
        "has_meaningful_bookmark": has_meaningful_bookmark,
        "scanned_page_fraction": scanned_page_fraction,
        "total_visible_chars_sampled": total_visible_chars,
        "total_invisible_chars_sampled": total_invisible_chars,
        "is_scanned": is_scanned,
        "reject_reasons": reject_reasons,
        "non_scan_like_pages": non_scan_pages,
        "pages_with_visible_text": pages_with_visible_text,
        "page_features": page_features,
    }


def evaluate(item: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    meaningful_bookmark_correct = (
        result["has_meaningful_bookmark"] == item["expected_has_bookmark"]
    )
    scanned_correct = result["is_scanned"] == item["expected_is_scanned"]
    return {
        "meaningful_bookmark_correct": meaningful_bookmark_correct,
        "scanned_correct": scanned_correct,
        "all_correct": meaningful_bookmark_correct and scanned_correct,
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


CSV_FIELDS = [
    "pdf_id",
    "folder",
    "path",
    "page_count",
    "sampled_page_count",
    "scanned_page_fraction",
    "total_visible_chars_sampled",
    "total_invisible_chars_sampled",
    "is_scanned",
    "reject_reasons",
    "bookmark_count",
    "toc_level_count",
    "has_meaningful_bookmark",
    "is_ocr_overwrite_target",
    "target_reject_reason",
]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def to_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    result = row["result"]
    is_scanned = result["is_scanned"]
    has_meaningful_bookmark = result["has_meaningful_bookmark"]
    is_target = is_scanned and not has_meaningful_bookmark
    if is_target:
        target_reject_reason = ""
    elif not is_scanned:
        target_reject_reason = "not_scanned: " + " | ".join(result["reject_reasons"])
    else:
        target_reject_reason = "has_meaningful_bookmark"
    return {
        "pdf_id": row["pdf_id"],
        "folder": row["folder"],
        "path": row["path"],
        "page_count": result["page_count"],
        "sampled_page_count": result["sampled_page_count"],
        "scanned_page_fraction": f"{result['scanned_page_fraction']:.4f}",
        "total_visible_chars_sampled": result["total_visible_chars_sampled"],
        "total_invisible_chars_sampled": result["total_invisible_chars_sampled"],
        "is_scanned": is_scanned,
        "reject_reasons": " | ".join(result["reject_reasons"]),
        "bookmark_count": result["bookmark_count"],
        "toc_level_count": result["toc_level_count"],
        "has_meaningful_bookmark": has_meaningful_bookmark,
        "is_ocr_overwrite_target": is_target,
        "target_reject_reason": target_reject_reason,
    }


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
    all_correct = sum(1 for row in rows if row["eval"]["all_correct"])
    parts = [
        f"엄격 기준(scanned_page_fraction==1.0 AND total_visible_chars_sampled==0)으로 "
        f"labeled 샘플 {total}개 중 {all_correct}개가 is_scanned/"
        f"has_meaningful_bookmark 모두 기대값과 일치했다. "
        f"CSV summary({', '.join(CSV_FIELDS)})와 사유 문자열(reject_reasons, "
        f"target_reject_reason)을 함께 저장해 300STUDY 배치 실행 시 어떤 파일이 "
        f"왜 대상/비대상인지 바로 확인할 수 있게 했다."
    ]
    for row in rows:
        result = row["result"]
        reason_text = "; ".join(result["reject_reasons"]) if result["reject_reasons"] else "없음"
        parts.append(
            f"{row['pdf_id']}(폴더={row['folder']}): is_scanned={result['is_scanned']}, "
            f"reject_reasons=[{reason_text}]."
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
                "scanned pdf 판정 기준을 scanned_page_fraction==1.0 AND "
                "total_visible_chars_sampled==0으로 엄격화하고, 불충족 시 어떤 "
                "조건이 왜 실패했는지 reason과 수치를 함께 남기는 CSV/JSON 스키마를 "
                "6개 labeled 샘플로 검증한다. src 배치 classify 기능에 올릴 "
                "필드 구성을 이 실험에서 먼저 정한다."
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
        reason_text = (
            "; ".join(result["reject_reasons"]) if result["reject_reasons"] else "없음"
        )
        print(
            f"[{item['folder']}] {pdf_id}: is_scanned={result['is_scanned']}"
            f"(기대 {item['expected_is_scanned']}), reject_reasons=[{reason_text}], "
            f"all_correct={eval_result['all_correct']}"
        )

    write_json(OUTPUT_DIR / "summary.json", rows)
    write_csv(OUTPUT_DIR / "classification_report.csv", [to_csv_row(row) for row in rows])
    update_experiment_registry(rows)


if __name__ == "__main__":
    main()
