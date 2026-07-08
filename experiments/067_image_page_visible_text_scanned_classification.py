""""scanned pdf는 본질적으로 모든 page가 image다"라는 정의로 native/scanned를 구분한다.

066에서 시도한 embedded font subset 접두어 판정은 특정 조판/스캔 도구의 이름
관행에 기대는 overfit된 기준이었다. 이번에는 도구별 특징이 아니라 PDF 구조의
본질적 정의로 되돌아간다.

- scanned page: page의 시각적 내용이 사실상 하나의 큰 raster image다.
- native page: page의 시각적 내용이 image가 아니라 실제로 paint된(눈에 보이는)
  글자 draw operator로 이루어져 있다.
- 함정: scanned page 위에도 "문자"가 추출될 수 있다. 다만 그 문자는 검색을 위해
  얹은 invisible text overlay(PDF text rendering mode Tr=3, 화면에는 그려지지
  않음)일 뿐 실제 시각적 내용이 아니다. 그래서 "문자 추출 가능 여부"가 아니라
  "화면에 실제로 그려지는(visible) 문자가 있는가"를 봐야 한다.

이 정의를 그대로 코드로 옮긴다.

- image_coverage_ratio: page에서 가장 큰 단일 image가 차지하는 면적 비율.
- visible_char_count: PyMuPDF `page.get_texttrace()`의 text rendering mode
  (`type`)가 invisible(3)/clip-only(7)이 아닌, 실제로 paint되는 문자 수.
- is_scan_like_page: image_coverage_ratio가 높고(page가 사실상 image고)
  visible_char_count가 거의 없을 때(그 image 위에 실제로 그려진 문자가 없을 때).
- 문서 전체에서 is_scan_like_page 비율이 높으면 scanned로 판정한다.

065(image-coverage 단독)와 결과는 같지만, visible-text 조건을 명시적으로 넣어서
"invisible OCR text가 있으니 native"라는 오판을 원천적으로 막는다.

300STUDY는 건드리지 않고 labeled 샘플 6개만 사용한다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "067_image_page_visible_text_scanned_classification"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DATA_DIR = ROOT_DIR / "data"

# PDF text rendering mode(Tr) 중 실제로 화면에 paint되는 값이다.
# 3=invisible, 7=clip만 추가(그리지 않음)이라 제외한다.
VISIBLE_RENDER_MODES = {0, 1, 2, 4, 5, 6}

IMAGE_COVERAGE_THRESHOLD = 0.85
VISIBLE_CHAR_THRESHOLD = 10
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
    # 핵심 조건: page가 사실상 image이고, 그 위에 실제로 그려진(visible) 문자가
    # 없다면 scan-like page다. invisible OCR text가 있어도 이 판정은 바뀌지 않는다.
    is_scan_like_page = is_image_dominant and not has_visible_text

    return {
        "image_coverage_ratio": image_coverage_ratio,
        "visible_char_count": visible_char_count,
        "invisible_char_count": invisible_char_count,
        "is_image_dominant": is_image_dominant,
        "has_visible_text": has_visible_text,
        "is_scan_like_page": is_scan_like_page,
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
    is_scanned = scanned_page_fraction >= SCANNED_PAGE_FRACTION_THRESHOLD

    total_visible_chars = sum(f["visible_char_count"] for f in page_features)
    total_invisible_chars = sum(f["invisible_char_count"] for f in page_features)

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
    scanned_correct = sum(1 for row in rows if row["eval"]["scanned_correct"])
    all_correct = sum(1 for row in rows if row["eval"]["all_correct"])
    parts = [
        f"labeled 샘플 {total}개에서 'page가 image로 뒤덮여 있고 그 위에 "
        f"visible text가 없으면 scan-like page'라는 정의만으로 is_scanned를 "
        f"판정하니 {scanned_correct}/{total}개가 정확했다. "
        f"has_meaningful_bookmark까지 합친 all_correct는 {all_correct}/{total}개였다. "
        f"066의 font subset 판정과 결과는 동일하지만, 이번엔 도구별 font 이름 "
        f"관행이 아니라 PDF rendering mode(Tr)라는 구조적 정의를 썼다."
    ]
    for row in rows:
        result = row["result"]
        parts.append(
            f"{row['pdf_id']}(폴더={row['folder']}): "
            f"scanned_page_fraction={result['scanned_page_fraction']:.2f}, "
            f"visible_chars(sampled)={result['total_visible_chars_sampled']}, "
            f"invisible_chars(sampled)={result['total_invisible_chars_sampled']}, "
            f"is_scanned={result['is_scanned']}."
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
                "066의 font subset 판정이 도구별 이름 관행에 기댄 overfit 기준이라는 "
                "지적에 따라, 'scanned page는 본질적으로 image고 그 위의 문자는 "
                "invisible overlay일 뿐 실제 시각적 내용이 아니다'라는 일반 정의로 "
                "native/scanned 판정을 다시 만든다. image coverage와 PDF text "
                "rendering mode(Tr, get_texttrace의 type)를 함께 써서 6개 labeled "
                "샘플로 검증한다."
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
            f"is_scanned={result['is_scanned']}(기대 {item['expected_is_scanned']}), "
            f"scanned_page_fraction={result['scanned_page_fraction']:.2f}, "
            f"visible_chars={result['total_visible_chars_sampled']}, "
            f"invisible_chars={result['total_invisible_chars_sampled']}, "
            f"has_meaningful_bookmark={result['has_meaningful_bookmark']}"
            f"(기대 {item['expected_has_bookmark']}), "
            f"all_correct={eval_result['all_correct']}"
        )

    write_json(OUTPUT_DIR / "summary.json", rows)
    update_experiment_registry(rows)


if __name__ == "__main__":
    main()
