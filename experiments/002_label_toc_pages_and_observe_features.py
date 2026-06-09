from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
from rapidfuzz import fuzz


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "002_label_toc_pages_and_observe_features"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
MAX_TEXT_PAGES = 30
WINDOW_MAX_LINES = 3
MATCH_SCORE_THRESHOLD = 88.0
MIN_UNIQUE_MATCHES_FOR_TOC_LABEL = 3
MIN_BOOKMARK_ORDER_DENSITY_FOR_TOC_LABEL = 0.25

INPUT_PDFS = [
    {
        "id": "john_hull",
        "path": ROOT_DIR
        / "data"
        / "native-pdf-indexed"
        / "John Hull - Options, Futures, and Other Derivatives, Global Edition-Pearson (2021).pdf",
    },
    {
        "id": "shreve_binomial",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "(Springer Finance) Steven E. Shreve - Stochastic Calculus for Finance I The Binomial Asset Pricing Model-Springer (2005)-indexed.pdf",
    },
    {
        "id": "luenberger_investment_science",
        "path": ROOT_DIR
        / "data"
        / "scanned-pdf-indexed"
        / "David G. Luenberger, Investment Science 2nd - adobeOCR - indexed.pdf",
    },
]

REVIEWED_TOC_PAGE_RANGES = {
    "john_hull": {
        "accepted_pages": list(range(5, 16)),
        "core_pages": list(range(6, 16)),
        "note": "page 5는 contents in brief라서 optional이고, 실질 TOC는 page 6-15다.",
    },
    "shreve_binomial": {
        "accepted_pages": list(range(3, 12)),
        "core_pages": list(range(3, 12)),
        "note": "page 3-11이 TOC다.",
    },
    "luenberger_investment_science": {
        "accepted_pages": list(range(7, 21)),
        "core_pages": list(range(9, 21)),
        "note": "page 7-8은 brief contents라서 optional이고, 실질 TOC는 page 9-20이다.",
    },
}

TOC_KEYWORDS = (
    "contents",
    "table of contents",
    "목차",
    "차례",
)

GENERIC_BOOKMARK_TITLES = {
    "summary",
    "further reading",
    "practice questions",
    "problems",
    "exercises",
    "references",
    "bibliography",
    "appendix",
    "index",
}


def normalize_text(text: str) -> str:
    text = text.replace("\x08", " ")
    text = text.replace("\u0001", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_match(text: str) -> str:
    replacements = {
        "ﬁ": "fi",
        "ﬂ": "fl",
        "–": "-",
        "—": "-",
        "’": "'",
        "“": '"',
        "”": '"',
    }
    for source, target in replacements.items():
        text = text.replace(source, target)

    text = normalize_text(text).lower()
    text = re.sub(r"\.{2,}", " ", text)
    text = re.sub(r"[\s.·•_=-]{4,}", " ", text)
    text = re.sub(r"\b\d{1,4}\s*$", " ", text)
    text = re.sub(r"[^0-9a-z가-힣]+", " ", text)
    return normalize_text(text)


def extract_lines(text: str) -> list[str]:
    return [normalize_text(line) for line in text.splitlines() if normalize_text(line)]


def extract_line_final_number(line: str) -> int | None:
    match = re.search(r"(?<![\w.])(\d{1,4})[\s.)\]]*$", line.strip())
    if not match:
        return None
    return int(match.group(1))


def monotonicity(numbers: list[int]) -> float | None:
    if len(numbers) < 2:
        return None
    non_decreasing_count = sum(
        1 for left, right in zip(numbers, numbers[1:], strict=False) if right >= left
    )
    return non_decreasing_count / (len(numbers) - 1)


def gap_stats(numbers: list[int]) -> dict[str, float | int | None]:
    if len(numbers) < 2:
        return {
            "mean_gap": None,
            "median_gap": None,
            "max_gap": None,
            "negative_gap_count": 0,
        }

    gaps = [right - left for left, right in zip(numbers, numbers[1:], strict=False)]
    return {
        "mean_gap": statistics.mean(gaps),
        "median_gap": statistics.median(gaps),
        "max_gap": max(gaps),
        "negative_gap_count": sum(1 for gap in gaps if gap < 0),
    }


def has_toc_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in TOC_KEYWORDS)


def calculate_page_features(page_number: int, total_pages: int, text: str) -> dict[str, Any]:
    lines = extract_lines(text)
    line_lengths = [len(line) for line in lines]
    final_numbers = [
        final_number
        for line in lines
        if (final_number := extract_line_final_number(line)) is not None
    ]
    gaps = gap_stats(final_numbers)

    return {
        "pdf_page": page_number,
        "line_count": len(lines),
        "word_count": len(text.split()),
        "mean_line_length": statistics.mean(line_lengths) if line_lengths else 0,
        "line_final_number_count": len(final_numbers),
        "line_final_numbers": final_numbers,
        "line_final_number_monotonicity": monotonicity(final_numbers),
        "line_final_number_gap_mean": gaps["mean_gap"],
        "line_final_number_gap_median": gaps["median_gap"],
        "line_final_number_gap_max": gaps["max_gap"],
        "line_final_number_negative_gap_count": gaps["negative_gap_count"],
        "page_position": page_number / total_pages,
        "toc_keyword_presence": has_toc_keyword(text),
    }


def extract_bookmarks_for_labeling(document: fitz.Document) -> list[dict[str, Any]]:
    bookmarks = []
    for order, item in enumerate(document.get_toc(simple=False), start=1):
        level, title, target_pdf_page = item[:3]
        normalized_title = normalize_for_match(title)
        if not is_usable_bookmark_title(normalized_title):
            continue
        bookmarks.append(
            {
                "order": order,
                "level": level,
                "title": normalize_text(title),
                "normalized_title": normalized_title,
                "target_pdf_page": target_pdf_page if target_pdf_page > 0 else None,
            }
        )
    return bookmarks


def is_usable_bookmark_title(normalized_title: str) -> bool:
    if len(normalized_title) < 6:
        return False
    if normalized_title in GENERIC_BOOKMARK_TITLES:
        return False
    if len(normalized_title.split()) == 1 and not re.search(r"\d", normalized_title):
        return False
    return True


def build_page_windows(page_number: int, lines: list[str]) -> list[dict[str, Any]]:
    windows = []
    for start_index in range(len(lines)):
        for size in range(1, WINDOW_MAX_LINES + 1):
            end_index = start_index + size
            if end_index > len(lines):
                continue
            raw_text = " ".join(lines[start_index:end_index])
            normalized_text = normalize_for_match(raw_text)
            if len(normalized_text) < 6:
                continue
            windows.append(
                {
                    "pdf_page": page_number,
                    "start_line": start_index + 1,
                    "end_line": end_index,
                    "raw_text": raw_text,
                    "normalized_text": normalized_text,
                }
            )
    return windows


def score_window_against_title(window_text: str, title: str) -> float:
    if not has_enough_title_token_coverage(window_text, title):
        return 0.0

    ratio_score = fuzz.ratio(window_text, title)
    token_sort_score = fuzz.token_sort_ratio(window_text, title)
    partial_score = fuzz.partial_ratio(window_text, title)
    return max(ratio_score, token_sort_score, partial_score)


def has_enough_title_token_coverage(window_text: str, title: str) -> bool:
    window_tokens = set(window_text.split())
    title_tokens = set(title.split())
    if not title_tokens or not window_tokens:
        return False

    overlap_ratio = len(window_tokens & title_tokens) / len(title_tokens)
    if len(title_tokens) <= 3:
        return overlap_ratio >= 0.85
    if len(title_tokens) <= 6:
        return overlap_ratio >= 0.70
    return overlap_ratio >= 0.60


def match_bookmarks_to_pages(
    bookmarks: list[dict[str, Any]],
    windows_by_page: dict[int, list[dict[str, Any]]],
) -> dict[int, dict[str, Any]]:
    evidence_by_page = {}

    for page_number, windows in windows_by_page.items():
        best_match_by_bookmark: dict[int, dict[str, Any]] = {}
        for window in windows:
            window_text = window["normalized_text"]
            for bookmark in bookmarks:
                score = score_window_against_title(
                    window_text,
                    bookmark["normalized_title"],
                )
                if score < MATCH_SCORE_THRESHOLD:
                    continue
                previous = best_match_by_bookmark.get(bookmark["order"])
                if previous is not None and previous["score"] >= score:
                    continue
                best_match_by_bookmark[bookmark["order"]] = {
                    "bookmark_order": bookmark["order"],
                    "bookmark_level": bookmark["level"],
                    "bookmark_title": bookmark["title"],
                    "bookmark_target_pdf_page": bookmark["target_pdf_page"],
                    "score": score,
                    "window": {
                        "start_line": window["start_line"],
                        "end_line": window["end_line"],
                        "raw_text": window["raw_text"],
                    },
                }

        matches = sorted(
            best_match_by_bookmark.values(),
            key=lambda match: (-match["score"], match["bookmark_order"]),
        )
        unique_orders = sorted(match["bookmark_order"] for match in matches)
        scores = [match["score"] for match in matches]
        level_counts = Counter(str(match["bookmark_level"]) for match in matches)
        bookmark_order_density = calculate_bookmark_order_density(unique_orders)
        evidence_by_page[page_number] = {
            "pdf_page": page_number,
            "is_toc_label": (
                len(matches) >= MIN_UNIQUE_MATCHES_FOR_TOC_LABEL
                and bookmark_order_density >= MIN_BOOKMARK_ORDER_DENSITY_FOR_TOC_LABEL
            ),
            "unique_matched_bookmark_count": len(matches),
            "matched_bookmark_order_density": bookmark_order_density,
            "matched_level_counts": dict(
                sorted(level_counts.items(), key=lambda item: int(item[0]))
            ),
            "median_match_score": statistics.median(scores) if scores else None,
            "max_match_score": max(scores) if scores else None,
            "matched_bookmark_order_min": min(unique_orders) if unique_orders else None,
            "matched_bookmark_order_max": max(unique_orders) if unique_orders else None,
            "matched_examples": matches[:10],
        }

    return evidence_by_page


def calculate_bookmark_order_density(orders: list[int]) -> float:
    if not orders:
        return 0.0
    order_span = max(orders) - min(orders) + 1
    return len(orders) / order_span


def compare_features(labeled_pages: list[dict[str, Any]]) -> dict[str, Any]:
    feature_names = [
        "line_count",
        "word_count",
        "mean_line_length",
        "line_final_number_count",
        "line_final_number_monotonicity",
        "line_final_number_gap_mean",
        "line_final_number_gap_median",
        "line_final_number_gap_max",
        "line_final_number_negative_gap_count",
        "page_position",
        "toc_keyword_presence",
    ]
    toc_rows = [row for row in labeled_pages if row["is_toc_label"]]
    non_toc_rows = [row for row in labeled_pages if not row["is_toc_label"]]

    return {
        "toc_page_count": len(toc_rows),
        "non_toc_page_count": len(non_toc_rows),
        "toc_pages": [row["pdf_page"] for row in toc_rows],
        "features": {
            feature_name: {
                "toc": summarize_feature(toc_rows, feature_name),
                "non_toc": summarize_feature(non_toc_rows, feature_name),
            }
            for feature_name in feature_names
        },
    }


def summarize_feature(rows: list[dict[str, Any]], feature_name: str) -> dict[str, Any]:
    values = []
    for row in rows:
        value = row["features"][feature_name]
        if value is None:
            continue
        values.append(float(value) if isinstance(value, bool) else value)

    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}

    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def analyze_pdf(pdf_id: str, pdf_path: Path) -> dict[str, Any]:
    output_dir = OUTPUT_DIR / pdf_id
    output_dir.mkdir(parents=True, exist_ok=True)

    with fitz.open(pdf_path) as document:
        bookmarks = extract_bookmarks_for_labeling(document)
        pages = []
        windows_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)

        for page_index in range(min(MAX_TEXT_PAGES, document.page_count)):
            page_number = page_index + 1
            text = document.load_page(page_index).get_text("text")
            lines = extract_lines(text)
            features = calculate_page_features(page_number, document.page_count, text)
            windows = build_page_windows(page_number, lines)
            windows_by_page[page_number] = windows
            pages.append(
                {
                    "pdf_page": page_number,
                    "features": features,
                    "text_preview": normalize_text(text)[:500],
                }
            )

    evidence_by_page = match_bookmarks_to_pages(bookmarks, windows_by_page)
    labeled_pages = []
    for page in pages:
        page_number = page["pdf_page"]
        evidence = evidence_by_page[page_number]
        labeled_pages.append(
            {
                "pdf_page": page_number,
                "is_toc_label": evidence["is_toc_label"],
                "features": page["features"],
                "label_evidence": {
                    "unique_matched_bookmark_count": evidence[
                        "unique_matched_bookmark_count"
                    ],
                    "matched_bookmark_order_density": evidence[
                        "matched_bookmark_order_density"
                    ],
                    "median_match_score": evidence["median_match_score"],
                    "max_match_score": evidence["max_match_score"],
                    "matched_bookmark_order_min": evidence[
                        "matched_bookmark_order_min"
                    ],
                    "matched_bookmark_order_max": evidence[
                        "matched_bookmark_order_max"
                    ],
                },
                "text_preview": page["text_preview"],
            }
        )

    flattened_windows = [
        window
        for page_number in sorted(windows_by_page)
        for window in windows_by_page[page_number]
    ]
    label_evidence = {
        "label_generation_note": (
            "bookmark title은 TOC 정답 page label 생성에만 사용했다. "
            "page-level features는 bookmark를 사용하지 않고 page text에서만 계산했다."
        ),
        "match_score_threshold": MATCH_SCORE_THRESHOLD,
        "min_unique_matches_for_toc_label": MIN_UNIQUE_MATCHES_FOR_TOC_LABEL,
        "min_bookmark_order_density_for_toc_label": (
            MIN_BOOKMARK_ORDER_DENSITY_FOR_TOC_LABEL
        ),
        "toc_pages": [
            page_number
            for page_number, evidence in evidence_by_page.items()
            if evidence["is_toc_label"]
        ],
        "pages": [evidence_by_page[page_number] for page_number in sorted(evidence_by_page)],
    }
    feature_comparison = compare_features(labeled_pages)
    reviewed_comparison = compare_with_reviewed_range(
        predicted_pages=label_evidence["toc_pages"],
        reviewed_range=REVIEWED_TOC_PAGE_RANGES[pdf_id],
    )

    write_json(output_dir / "bookmarks_for_labeling.json", bookmarks)
    write_jsonl(output_dir / "page_windows_first_30.jsonl", flattened_windows)
    write_json(output_dir / "toc_page_label_evidence.json", label_evidence)
    write_jsonl(output_dir / "page_features_labeled_first_30.jsonl", labeled_pages)
    write_json(output_dir / "feature_comparison.json", feature_comparison)
    write_json(output_dir / "reviewed_toc_page_comparison.json", reviewed_comparison)
    (output_dir / "report.md").write_text(
        build_report(
            pdf_id,
            pdf_path,
            bookmarks,
            label_evidence,
            feature_comparison,
            reviewed_comparison,
        ),
        encoding="utf-8",
    )

    return {
        "pdf_id": pdf_id,
        "input_pdf": str(pdf_path.relative_to(ROOT_DIR)),
        "usable_bookmark_count": len(bookmarks),
        "toc_pages": label_evidence["toc_pages"],
        "toc_page_count": feature_comparison["toc_page_count"],
        "non_toc_page_count": feature_comparison["non_toc_page_count"],
        "reviewed_toc_page_comparison": reviewed_comparison,
        "feature_comparison": feature_comparison,
    }


def compare_with_reviewed_range(
    predicted_pages: list[int],
    reviewed_range: dict[str, Any],
) -> dict[str, Any]:
    predicted = set(predicted_pages)
    accepted = set(reviewed_range["accepted_pages"])
    core = set(reviewed_range["core_pages"])

    return {
        "note": reviewed_range["note"],
        "predicted_pages": sorted(predicted),
        "accepted_pages": sorted(accepted),
        "core_pages": sorted(core),
        "accepted_comparison": compare_page_sets(predicted, accepted),
        "core_comparison": compare_page_sets(predicted, core),
    }


def compare_page_sets(predicted: set[int], expected: set[int]) -> dict[str, Any]:
    true_positive = predicted & expected
    missing = expected - predicted
    extra = predicted - expected

    precision = len(true_positive) / len(predicted) if predicted else None
    recall = len(true_positive) / len(expected) if expected else None

    return {
        "true_positive_pages": sorted(true_positive),
        "missing_pages": sorted(missing),
        "extra_pages": sorted(extra),
        "precision": precision,
        "recall": recall,
    }


def build_report(
    pdf_id: str,
    pdf_path: Path,
    bookmarks: list[dict[str, Any]],
    label_evidence: dict[str, Any],
    feature_comparison: dict[str, Any],
    reviewed_comparison: dict[str, Any],
) -> str:
    toc_pages = label_evidence["toc_pages"]
    page_lines = "\n".join(
        (
            f"- PDF page {page['pdf_page']}: "
            f"toc={page['is_toc_label']}, "
            f"matches={page['unique_matched_bookmark_count']}, "
            f"median_score={page['median_match_score']}"
        )
        for page in label_evidence["pages"]
    )
    feature_lines = "\n".join(
        (
            f"- {feature_name}: "
            f"TOC mean={stats['toc']['mean']}, "
            f"non-TOC mean={stats['non_toc']['mean']}"
        )
        for feature_name, stats in feature_comparison["features"].items()
    )
    accepted_comparison = reviewed_comparison["accepted_comparison"]
    core_comparison = reviewed_comparison["core_comparison"]

    return f"""# {pdf_id} TOC label and feature observation

## 입력

- PDF: `{pdf_path.relative_to(ROOT_DIR)}`
- 사용 가능한 bookmark title 수: {len(bookmarks)}
- 텍스트 관찰 범위: 첫 {MAX_TEXT_PAGES}페이지

## 라벨 생성 원칙

- bookmark title은 TOC 정답 page label 생성에만 사용했다.
- page-level feature는 bookmark를 사용하지 않고 page text에서만 계산했다.
- match threshold: {MATCH_SCORE_THRESHOLD}
- TOC label 최소 unique bookmark match 수: {MIN_UNIQUE_MATCHES_FOR_TOC_LABEL}
- TOC label 최소 bookmark order density: {MIN_BOOKMARK_ORDER_DENSITY_FOR_TOC_LABEL}

## TOC 정답 page label

- TOC pages: {toc_pages}
- TOC page 수: {feature_comparison["toc_page_count"]}
- non-TOC page 수: {feature_comparison["non_toc_page_count"]}

## 사용자 검수 range 비교

- 검수 메모: {reviewed_comparison["note"]}
- accepted pages: {reviewed_comparison["accepted_pages"]}
- core pages: {reviewed_comparison["core_pages"]}
- accepted missing: {accepted_comparison["missing_pages"]}
- accepted extra: {accepted_comparison["extra_pages"]}
- accepted recall: {accepted_comparison["recall"]}
- core missing: {core_comparison["missing_pages"]}
- core extra: {core_comparison["extra_pages"]}
- core recall: {core_comparison["recall"]}

## Page별 label evidence

{page_lines}

## Feature 비교

{feature_lines}
"""


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


def build_finding(results: list[dict[str, Any]]) -> str:
    parts = []
    for result in results:
        comparison = result["feature_comparison"]["features"]
        final_number_toc = comparison["line_final_number_count"]["toc"]["mean"]
        final_number_non_toc = comparison["line_final_number_count"]["non_toc"]["mean"]
        monotonicity_toc = comparison["line_final_number_monotonicity"]["toc"]["mean"]
        monotonicity_non_toc = comparison["line_final_number_monotonicity"]["non_toc"][
            "mean"
        ]
        parts.append(
            f"{result['pdf_id']}는 bookmark title 기반 label 생성으로 TOC page "
            f"{result['toc_pages']}를 얻었다. TOC page 평균 line-final number count는 "
            f"{final_number_toc}, non-TOC 평균은 {final_number_non_toc}이고, "
            f"monotonicity 평균은 TOC {monotonicity_toc}, non-TOC "
            f"{monotonicity_non_toc}이다."
        )
    return " ".join(parts)


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
                "3개 silver label PDF의 bookmark 정보를 정답 label 생성에만 사용해 "
                "첫 30페이지 안의 TOC page를 자동 라벨링하고, bookmark 없이 추출한 "
                "objective page feature가 TOC page에서 어떤 특성을 보이는지 관찰한다."
            ),
            "inputs": [str(item["path"].relative_to(ROOT_DIR)) for item in INPUT_PDFS],
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
    results = []
    for item in INPUT_PDFS:
        if not item["path"].exists():
            raise FileNotFoundError(item["path"])
        results.append(analyze_pdf(item["id"], item["path"]))

    write_json(OUTPUT_DIR / "summary.json", results)
    update_experiment_registry(results)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
