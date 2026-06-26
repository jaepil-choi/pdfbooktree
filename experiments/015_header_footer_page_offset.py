"""header/footer 영역 printed page number로 PDF page offset을 추정하는 실험.

가설:
- 본문 page의 상위/하위 10% 영역(머리말/꼬리말 band)에는 인쇄된 책 page number가 반복해서 나온다.
- 각 word box의 (x, y) 좌표와 page 크기를 보고 band 안의 숫자만 뽑으면,
  `offset = pdf_page(1-based) - book_page_number`가 본문 전체에서 거의 일정하게 나온다.
- chapter 번호, 연도, 문제 번호 같은 noise는 offset이 흩어지므로,
  전체 offset 분포의 최빈값(most frequent value)을 실제 offset으로 잡으면 robust하다.

검증 포인트:
- page 크기(rect)와 textbox x/y 좌표로 band 판정이 제대로 되는지 evidence에 좌표 비율을 남긴다.
- 최빈 offset의 modal share와 page coverage로 신뢰도를 본다.
- runtime 경로(bookmark 없는 PDF)에서도 동작하도록 bookmark target에 의존하지 않는다.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "015_header_footer_page_offset"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DATA_DIR = ROOT_DIR / "data"
LABELS_JSON = ROOT_DIR / "experiments" / "labels" / "answer_toc_ranges_manual.json"

# 상/하위 band 비율: page 높이의 10%
BAND_RATIO = 0.10
# 책 page number로 인정할 숫자 상한(연도/식 번호 noise 컷)
MAX_NUMBER = 3000
# 너무 큰 책은 앞부분만 봐도 offset이 잡히지만, 정확한 최빈값을 위해 전체를 본다.
MAX_SCAN_PAGES: int | None = None

# 같은 줄로 볼 y 허용 오차(글자 높이 대비 비율). OCR이 baseline을 흔들어도 묶는다.
LINE_Y_TOLERANCE_RATIO = 0.6
# 같은 줄에서 이어붙일 x 간격 허용치(글자 높이 대비 배수). "1" "9" -> "19" 복원용.
MERGE_GAP_RATIO = 1.0

DIGITS_RE = re.compile(r"\d{1,4}")


def slugify(stem: str) -> str:
    """파일명에서 짧은 ascii id를 만든다."""

    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", stem).strip("_").lower()
    return cleaned[:48] or "pdf"


def load_label_id_map() -> dict[str, str]:
    """수동 라벨 파일에서 input_pdf 경로 -> 깔끔한 id 매핑을 만든다."""

    if not LABELS_JSON.exists():
        return {}
    loaded = json.loads(LABELS_JSON.read_text(encoding="utf-8"))
    id_map: dict[str, str] = {}
    for label in loaded.get("labels", []):
        rel = label.get("input_pdf")
        label_id = label.get("id")
        if rel and label_id:
            id_map[Path(rel).name] = label_id
    return id_map


def discover_input_pdfs() -> list[dict[str, Any]]:
    """data/ 아래 모든 PDF를 실험 입력으로 모은다."""

    id_map = load_label_id_map()
    pdfs = sorted(DATA_DIR.rglob("*.pdf"))
    return [
        {"id": id_map.get(path.name, slugify(path.stem)), "path": path}
        for path in pdfs
    ]


def longest_consecutive_run(offset: int, evidence_rows: list[dict[str, Any]]) -> int:
    """추정 offset과 일치하는 page가 연속으로 이어지는 최장 길이를 센다.

    page number는 1씩 증가하므로, 같은 offset을 지지하는 연속 page run이 길수록
    실제 page number sequence일 가능성이 높다. modal_share보다 강한 신뢰도 신호다.
    """

    pages_with_offset = {
        row["pdf_page"] for row in evidence_rows if row["offset"] == offset
    }
    if not pages_with_offset:
        return 0
    best = 0
    current = 0
    previous: int | None = None
    for page in sorted(pages_with_offset):
        if previous is not None and page == previous + 1:
            current += 1
        else:
            current = 1
        best = max(best, current)
        previous = page
    return best


def extract_page_numbers(text: str) -> list[int]:
    """병합된 run에서 연결된 숫자 그룹을 모두 page number 후보로 뽑는다.

    글자가 섞여도 거르지 않는다. running header(`Part1...23`)여도 `\\d+` 그룹으로
    `23` 같은 후보가 그대로 나오고, page마다 1씩 증가하는 진짜 page number만
    consecutive run을 만들어 mode/run 선택에서 이긴다. OCR이 쪼갠 "1" "9"는
    병합 단계에서 이미 "19"로 합쳐져 한 그룹으로 잡힌다.
    """

    numbers: list[int] = []
    for group in DIGITS_RE.findall(text):
        number = int(group)
        if 0 < number <= MAX_NUMBER:
            numbers.append(number)
    return numbers


def _group_into_lines(
    words: list[tuple[float, float, float, float, str]], height: float
) -> list[list[tuple[float, float, float, float, str]]]:
    """band 안 word를 y 좌표가 비슷한 것끼리 같은 줄로 묶는다."""

    lines: list[dict[str, Any]] = []
    for word in sorted(words, key=lambda w: ((w[1] + w[3]) / 2.0, w[0])):
        y_center = (word[1] + word[3]) / 2.0
        word_height = max(word[3] - word[1], 1.0)
        tolerance = max(LINE_Y_TOLERANCE_RATIO * word_height, 0.006 * height)
        if lines and abs(y_center - lines[-1]["y_center"]) <= tolerance:
            current = lines[-1]
            count = current["count"]
            current["y_center"] = (current["y_center"] * count + y_center) / (count + 1)
            current["count"] = count + 1
            current["words"].append(word)
        else:
            lines.append({"y_center": y_center, "count": 1, "words": [word]})
    return [line["words"] for line in lines]


def _merge_close_words(
    line_words: list[tuple[float, float, float, float, str]],
) -> list[dict[str, Any]]:
    """한 줄 안에서 x 간격이 가까운 word를 이어붙여 token run을 만든다."""

    runs: list[list[tuple[float, float, float, float, str]]] = []
    for word in sorted(line_words, key=lambda w: w[0]):
        if not runs:
            runs.append([word])
            continue
        previous = runs[-1][-1]
        gap = word[0] - previous[2]
        word_height = max(word[3] - word[1], previous[3] - previous[1], 1.0)
        if gap <= MERGE_GAP_RATIO * word_height:
            runs[-1].append(word)
        else:
            runs.append([word])

    merged: list[dict[str, Any]] = []
    for run in runs:
        text = "".join(word[4] for word in run)
        x0 = min(word[0] for word in run)
        y0 = min(word[1] for word in run)
        x1 = max(word[2] for word in run)
        y1 = max(word[3] for word in run)
        merged.append({"text": text, "bbox": (x0, y0, x1, y1)})
    return merged


def extract_band_numbers(page: fitz.Page) -> tuple[list[dict[str, Any]], tuple[float, float]]:
    """page 상/하위 band에서 같은 줄 textbox를 이어붙여 page number를 추출한다.

    OCR이 "19"를 "1" "9"처럼 쪼개 놓아도, 같은 y를 공유하고 x 거리가 가까운
    textbox를 합쳐 본래 숫자를 복원한다.
    """

    rect = page.rect
    width = float(rect.width)
    height = float(rect.height)
    if width <= 0 or height <= 0:
        return [], (width, height)

    top_threshold = rect.y0 + BAND_RATIO * height
    bottom_threshold = rect.y1 - BAND_RATIO * height

    band_words: dict[str, list[tuple[float, float, float, float, str]]] = {
        "top": [],
        "bottom": [],
    }
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        token = word.strip()
        if not token:
            continue
        y_center = (y0 + y1) / 2.0
        if y_center <= top_threshold:
            band_words["top"].append((x0, y0, x1, y1, token))
        elif y_center >= bottom_threshold:
            band_words["bottom"].append((x0, y0, x1, y1, token))

    candidates: list[dict[str, Any]] = []
    for band, words in band_words.items():
        for line_words in _group_into_lines(words, height):
            for run in _merge_close_words(line_words):
                bx0, by0, bx1, by1 = run["bbox"]
                for number in extract_page_numbers(run["text"]):
                    candidates.append(
                        {
                            "number": number,
                            "text": run["text"],
                            "band": band,
                            "x_ratio": round(((bx0 + bx1) / 2.0 - rect.x0) / width, 3),
                            "y_ratio": round(((by0 + by1) / 2.0) / height, 3),
                        }
                    )
    return candidates, (round(width, 1), round(height, 1))


def summarize_offsets(offsets: list[int]) -> dict[str, Any]:
    """offset 리스트에서 최빈값과 신뢰도 지표를 만든다."""

    if not offsets:
        return {
            "estimated_offset": None,
            "modal_count": 0,
            "total": 0,
            "modal_share": 0.0,
            "top_offsets": [],
        }
    counter = Counter(offsets)
    estimated_offset, modal_count = counter.most_common(1)[0]
    total = len(offsets)
    return {
        "estimated_offset": estimated_offset,
        "modal_count": modal_count,
        "total": total,
        "modal_share": round(modal_count / total, 3),
        "top_offsets": [
            {"offset": offset, "count": count}
            for offset, count in counter.most_common(5)
        ],
    }


def analyze_pdf(pdf_id: str, pdf_path: Path) -> dict[str, Any]:
    """단일 PDF에서 band 숫자를 모아 offset을 추정한다."""

    page_sizes: Counter[tuple[float, float]] = Counter()
    evidence_rows: list[dict[str, Any]] = []
    offsets_all: list[int] = []
    offsets_bottom: list[int] = []
    offsets_top: list[int] = []

    with fitz.open(pdf_path) as document:
        limit = document.page_count
        if MAX_SCAN_PAGES is not None:
            limit = min(limit, MAX_SCAN_PAGES)
        page_count = document.page_count
        for page_index in range(limit):
            page = document.load_page(page_index)
            pdf_page = page_index + 1
            candidates, size = extract_band_numbers(page)
            page_sizes[size] += 1
            for candidate in candidates:
                offset = pdf_page - candidate["number"]
                offsets_all.append(offset)
                if candidate["band"] == "bottom":
                    offsets_bottom.append(offset)
                else:
                    offsets_top.append(offset)
                evidence_rows.append(
                    {
                        "pdf_page": pdf_page,
                        "number": candidate["number"],
                        "text": candidate["text"],
                        "offset": offset,
                        "band": candidate["band"],
                        "x_ratio": candidate["x_ratio"],
                        "y_ratio": candidate["y_ratio"],
                    }
                )

    rows_by_band = {
        "all": evidence_rows,
        "bottom": [row for row in evidence_rows if row["band"] == "bottom"],
        "top": [row for row in evidence_rows if row["band"] == "top"],
    }
    summaries = {
        "all": summarize_offsets(offsets_all),
        "bottom": summarize_offsets(offsets_bottom),
        "top": summarize_offsets(offsets_top),
    }

    # band별로 최빈 offset의 consecutive run을 구하고, run이 가장 긴 band를 고른다.
    # modal_share는 noise 그룹이 분모를 키워 신뢰도를 왜곡하므로 선택 기준에서 뺀다.
    band_runs = {
        band: (
            longest_consecutive_run(summary["estimated_offset"], rows_by_band[band])
            if summary["estimated_offset"] is not None
            else 0
        )
        for band, summary in summaries.items()
    }
    best_band = max(
        summaries,
        key=lambda band: (band_runs[band], summaries[band]["modal_count"]),
    )
    best_summary = summaries[best_band]
    estimated_offset = best_summary["estimated_offset"]
    max_run = band_runs[best_band]

    # 최빈 offset과 일치하는(=실제 page number로 보이는) page 수 = coverage.
    consistent_pages: set[int] = set()
    consistent_evidence: list[dict[str, Any]] = []
    if estimated_offset is not None:
        for row in rows_by_band[best_band]:
            if row["offset"] == estimated_offset:
                consistent_pages.add(row["pdf_page"])
                if len(consistent_evidence) < 15:
                    consistent_evidence.append(row)

    most_common_size = (
        page_sizes.most_common(1)[0][0] if page_sizes else None
    )

    write_jsonl(OUTPUT_DIR / f"{pdf_id}_offset_evidence.jsonl", evidence_rows)

    return {
        "pdf_id": pdf_id,
        "pdf_path": str(pdf_path.relative_to(ROOT_DIR)),
        "page_count": page_count,
        "scanned_pages": limit,
        "most_common_page_size": most_common_size,
        "band_ratio": BAND_RATIO,
        "estimated_offset": estimated_offset,
        "best_band": best_band,
        "best_modal_share": best_summary["modal_share"],
        "max_consecutive_run": max_run,
        "consistent_page_count": len(consistent_pages),
        "consistent_page_coverage": (
            round(len(consistent_pages) / limit, 3) if limit else 0.0
        ),
        "band_runs": band_runs,
        "offset_summary": summaries,
        "printed_page_1_estimated_pdf_page": (
            estimated_offset + 1 if estimated_offset is not None else None
        ),
        "consistent_evidence_sample": consistent_evidence,
    }


def build_finding(results: list[dict[str, Any]]) -> str:
    parts = []
    for result in results:
        parts.append(
            f"{result['pdf_id']}는 best band {result['best_band']}에서 추정 offset "
            f"{result['estimated_offset']}(modal share {result['best_modal_share']}, "
            f"최장 연속 run {result['max_consecutive_run']}), "
            f"일치 page {result['consistent_page_count']}개"
            f"(coverage {result['consistent_page_coverage']}), "
            f"printed page 1 ≈ PDF page {result['printed_page_1_estimated_pdf_page']}이다."
        )
    return " ".join(parts)


def load_experiment_registry() -> dict[str, Any]:
    if not EXPERIMENTS_JSON.exists():
        return {"experiments": []}
    loaded = json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))
    if "experiments" not in loaded:
        loaded["experiments"] = []
    return loaded


def update_experiment_registry(results: list[dict[str, Any]]) -> None:
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
                "본문 page 상/하위 10% band에서 word box 좌표로 인쇄된 책 page number를 뽑고, "
                "offset = pdf_page - book_page의 최빈값을 실제 page offset으로 추정한다. "
                "bookmark target에 의존하지 않아 bookmark 없는 runtime PDF에서도 동작한다."
            ),
            "inputs": [result["pdf_path"] for result in results],
            "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
            "finding": build_finding(results),
            "ran_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    registry["experiments"] = experiments
    write_json(EXPERIMENTS_JSON, registry)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(text + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    inputs = discover_input_pdfs()
    if not inputs:
        raise FileNotFoundError(f"data/ 아래 PDF를 찾지 못했다: {DATA_DIR}")

    results = []
    for item in inputs:
        if not item["path"].exists():
            raise FileNotFoundError(item["path"])
        print(f"[scan] {item['id']} <- {item['path'].name}")
        results.append(analyze_pdf(item["id"], item["path"]))

    write_json(OUTPUT_DIR / "summary.json", results)
    update_experiment_registry(results)

    print("\n=== offset 추정 요약 ===")
    for result in results:
        print(
            f"- {result['pdf_id']}: offset={result['estimated_offset']} "
            f"band={result['best_band']} share={result['best_modal_share']} "
            f"run={result['max_consecutive_run']} "
            f"coverage={result['consistent_page_coverage']} "
            f"(pages={result['scanned_pages']})"
        )


if __name__ == "__main__":
    main()
