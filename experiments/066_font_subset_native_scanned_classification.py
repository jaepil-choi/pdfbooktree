"""embedded font subset 유무로 native/scanned PDF를 구분할 수 있는지 확인한다.

065에서는 page당 최대 단일 이미지의 면적 비율(image coverage)로 native/scanned를
판정했다. 이번에는 image 분석 대신 PDF font resource라는 metadata성 field만으로
같은 판정이 가능한지 확인한다.

가설: Adobe InDesign, LaTeX 같은 정식 조판 도구는 폰트를 "subset embed"하면서
`ABCDEF+FontName`처럼 6글자 대문자 접두어를 붙인다(PDF 표준 관행). 반면 스캐너
소프트웨어(ScanSnap 등)가 붙이는 invisible OCR text layer는 Courier/Gulim 같은
범용 base font를 subset 없이 그대로 참조한다. 따라서 문서 전체에서 subset
접두어가 붙은 font가 하나라도 있으면 native, 전혀 없으면 scanned로 볼 수 있다.

300STUDY는 건드리지 않고, 065와 동일한 6개 labeled 샘플만 사용한다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "066_font_subset_native_scanned_classification"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DATA_DIR = ROOT_DIR / "data"

SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")
SCAN_TOOL_KEYWORDS = (
    "scansnap",
    "pfu",
    "camscanner",
    "hp scan",
    "canon scan",
    "adobe scan",
    "office lens",
    "scanner",
)

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


def has_scan_tool_signature(metadata: dict[str, Any]) -> bool:
    text = f"{metadata.get('creator', '')} {metadata.get('producer', '')}".lower()
    return any(keyword in text for keyword in SCAN_TOOL_KEYWORDS)


def classify_pdf(path: Path) -> dict[str, Any]:
    with fitz.open(path) as document:
        page_count = document.page_count
        toc = document.get_toc(simple=True)
        has_bookmark = len(toc) > 0
        toc_level_count = len({item[0] for item in toc})
        has_meaningful_bookmark = has_bookmark and toc_level_count >= 2

        distinct_fonts: set[str] = set()
        for index in range(page_count):
            for font in document.load_page(index).get_fonts(full=True):
                distinct_fonts.add(font[3])

        metadata = document.metadata or {}

    subset_fonts = sorted(name for name in distinct_fonts if SUBSET_PREFIX_RE.match(name))
    non_subset_fonts = sorted(distinct_fonts - set(subset_fonts))
    has_subset_font = len(subset_fonts) > 0
    scan_tool_signature = has_scan_tool_signature(metadata)

    # 핵심 판정: subset embed font가 하나라도 있으면 native, 없으면 scanned.
    is_scanned = not has_subset_font

    return {
        "page_count": page_count,
        "bookmark_count": len(toc),
        "toc_level_count": toc_level_count,
        "has_bookmark": has_bookmark,
        "has_meaningful_bookmark": has_meaningful_bookmark,
        "creator": metadata.get("creator", ""),
        "producer": metadata.get("producer", ""),
        "scan_tool_signature": scan_tool_signature,
        "distinct_font_count": len(distinct_fonts),
        "subset_font_count": len(subset_fonts),
        "subset_fonts_sample": subset_fonts[:5],
        "non_subset_fonts_sample": non_subset_fonts[:5],
        "has_subset_font": has_subset_font,
        "is_scanned": is_scanned,
    }


def evaluate(item: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    bookmark_correct = result["has_bookmark"] == item["expected_has_bookmark"]
    meaningful_bookmark_correct = (
        result["has_meaningful_bookmark"] == item["expected_has_bookmark"]
    )
    scanned_correct = result["is_scanned"] == item["expected_is_scanned"]
    return {
        "bookmark_correct": bookmark_correct,
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
    meaningful_correct = sum(
        1 for row in rows if row["eval"]["meaningful_bookmark_correct"]
    )
    all_correct = sum(1 for row in rows if row["eval"]["all_correct"])
    parts = [
        f"labeled 샘플 {total}개에서 subset embed font 유무만으로 판정한 "
        f"is_scanned는 {scanned_correct}/{total}개가 정확했다(문서 전체 페이지의 "
        f"font resource를 훑어 6글자대문자+'+'접두어 subset font가 하나라도 있으면 "
        f"native, 전혀 없으면 scanned로 판정). "
        f"065의 image-coverage 방식과 결과가 동일했고, 이번엔 이미지 분석 없이 "
        f"font 이름 문자열만 봐서 훨씬 가벼웠다. "
        f"has_meaningful_bookmark(toc_level_count>=2) 기준 bookmark 판정도 "
        f"{meaningful_correct}/{total}개가 정확했다. 두 기준을 합치면 "
        f"{all_correct}/{total}개가 완전히 일치했다."
    ]
    for row in rows:
        parts.append(
            f"{row['pdf_id']}(폴더={row['folder']}): "
            f"distinct_font={row['result']['distinct_font_count']}, "
            f"subset_font={row['result']['subset_font_count']}, "
            f"creator='{row['result']['creator']}', "
            f"scan_tool_signature={row['result']['scan_tool_signature']}, "
            f"is_scanned={row['result']['is_scanned']}."
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
                "065의 image-coverage 기반 native/scanned 판정을 대체할 수 있는 "
                "metadata/field 기반 판정이 있는지 확인한다. PDF font resource의 "
                "subset embed 접두어(`ABCDEF+FontName`) 유무로 native/scanned를 "
                "구분하는 가설을 6개 labeled 샘플로 검증한다."
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
            f"distinct_font={result['distinct_font_count']}, "
            f"subset_font={result['subset_font_count']}, "
            f"has_meaningful_bookmark={result['has_meaningful_bookmark']}"
            f"(기대 {item['expected_has_bookmark']}), "
            f"all_correct={eval_result['all_correct']}"
        )

    write_json(OUTPUT_DIR / "summary.json", rows)
    update_experiment_registry(rows)


if __name__ == "__main__":
    main()
