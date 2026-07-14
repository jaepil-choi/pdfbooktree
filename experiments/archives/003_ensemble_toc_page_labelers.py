from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
from rapidfuzz import fuzz


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "003_ensemble_toc_page_labelers"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
MAX_TEXT_PAGES = 30
WINDOW_MAX_LINES = 3
MATCH_SCORE_THRESHOLD = 88.0

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
            trailing_number = extract_line_final_number(raw_text)
            windows.append(
                {
                    "pdf_page": page_number,
                    "start_line": start_index + 1,
                    "end_line": end_index,
                    "raw_text": raw_text,
                    "normalized_text": normalized_text,
                    "trailing_number": trailing_number,
                }
            )
    return windows


def calculate_page_features(
    page_number: int,
    total_pages: int,
    text: str,
    lines: list[str],
) -> dict[str, Any]:
    line_lengths = [len(line) for line in lines]
    final_numbers = [
        final_number
        for line in lines
        if (final_number := extract_line_final_number(line)) is not None
    ]
    gaps = gap_stats(final_numbers)
    toc_entry_lines = [line for line in lines if is_toc_entry_like(line)]

    return {
        "pdf_page": page_number,
        "line_count": len(lines),
        "word_count": len(text.split()),
        "mean_line_length": statistics.mean(line_lengths) if line_lengths else 0,
        "line_length_std": statistics.pstdev(line_lengths) if len(line_lengths) > 1 else 0,
        "line_final_number_count": len(final_numbers),
        "line_final_numbers": final_numbers,
        "line_final_number_monotonicity": monotonicity(final_numbers),
        "line_final_number_gap_mean": gaps["mean_gap"],
        "line_final_number_gap_median": gaps["median_gap"],
        "line_final_number_gap_max": gaps["max_gap"],
        "line_final_number_negative_gap_count": gaps["negative_gap_count"],
        "toc_entry_pattern_count": len(toc_entry_lines),
        "toc_entry_pattern_ratio": len(toc_entry_lines) / len(lines) if lines else 0,
        "chapter_or_part_line_count": sum(
            1 for line in lines if re.search(r"\b(chapter|part|appendix)\b", line, re.I)
        ),
        "page_position": page_number / total_pages,
        "toc_keyword_presence": has_toc_keyword(text),
    }


def is_toc_entry_like(line: str) -> bool:
    normalized = normalize_text(line)
    if len(normalized) < 8:
        return False
    if extract_line_final_number(normalized) is None:
        return False
    patterns = [
        r"^\d+(\.\d+)*\s+\S+",
        r"^chapter\s+\d+",
        r"^part\s+[ivx0-9]+",
        r"^appendix\s+[a-z0-9]+",
        r"^[a-z]\.\d+\s+\S+",
    ]
    lowered = normalized.lower()
    return any(re.search(pattern, lowered) for pattern in patterns)


def has_toc_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in TOC_KEYWORDS)


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
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    evidence_by_page = {}
    all_matches = []

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

                match = {
                    "pdf_page": page_number,
                    "bookmark_order": bookmark["order"],
                    "bookmark_level": bookmark["level"],
                    "bookmark_title": bookmark["title"],
                    "bookmark_target_pdf_page": bookmark["target_pdf_page"],
                    "score": score,
                    "trailing_number": window["trailing_number"],
                    "window": {
                        "start_line": window["start_line"],
                        "end_line": window["end_line"],
                        "raw_text": window["raw_text"],
                    },
                }
                previous = best_match_by_bookmark.get(bookmark["order"])
                if previous is not None and previous["score"] >= score:
                    continue
                best_match_by_bookmark[bookmark["order"]] = match

        matches = sorted(
            best_match_by_bookmark.values(),
            key=lambda match: (-match["score"], match["bookmark_order"]),
        )
        all_matches.extend(matches)
        unique_orders = sorted(match["bookmark_order"] for match in matches)
        scores = [match["score"] for match in matches]
        level_counts = Counter(str(match["bookmark_level"]) for match in matches)
        density = calculate_bookmark_order_density(unique_orders)
        evidence_by_page[page_number] = {
            "pdf_page": page_number,
            "unique_matched_bookmark_count": len(matches),
            "matched_bookmark_order_density": density,
            "matched_level_counts": dict(
                sorted(level_counts.items(), key=lambda item: int(item[0]))
            ),
            "median_match_score": statistics.median(scores) if scores else None,
            "max_match_score": max(scores) if scores else None,
            "matched_bookmark_order_min": min(unique_orders) if unique_orders else None,
            "matched_bookmark_order_max": max(unique_orders) if unique_orders else None,
            "matched_examples": matches[:10],
        }

    return evidence_by_page, all_matches


def calculate_bookmark_order_density(orders: list[int]) -> float:
    if not orders:
        return 0.0
    return len(orders) / (max(orders) - min(orders) + 1)


def labeler_bookmark_anchor_density(
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    page_scores = {}
    for page in pages:
        evidence = page["anchor_evidence"]
        count = evidence["unique_matched_bookmark_count"]
        density = evidence["matched_bookmark_order_density"]
        median_score = evidence["median_match_score"] or 0
        page_scores[page["pdf_page"]] = min(count, 20) * density * (median_score / 100)

    selected_pages = [
        page
        for page, score in page_scores.items()
        if score >= 1.5
        or (
            pages_by_number(pages)[page]["anchor_evidence"][
                "unique_matched_bookmark_count"
            ]
            >= 10
            and pages_by_number(pages)[page]["anchor_evidence"][
                "matched_bookmark_order_density"
            ]
            >= 0.08
        )
    ]
    return build_labeler_result("bookmark_anchor_density", selected_pages, page_scores)


def labeler_printed_page_sequence(pages: list[dict[str, Any]]) -> dict[str, Any]:
    page_scores = {}
    for page in pages:
        features = page["features"]
        count = features["line_final_number_count"]
        monotone = features["line_final_number_monotonicity"] or 0
        negative = features["line_final_number_negative_gap_count"]
        page_scores[page["pdf_page"]] = max(0, count * monotone - negative * 2)

    selected_pages = [
        page
        for page, score in page_scores.items()
        if score >= 8
    ]
    return build_labeler_result("printed_page_sequence", selected_pages, page_scores)


def labeler_toc_entry_pattern_density(pages: list[dict[str, Any]]) -> dict[str, Any]:
    page_scores = {}
    for page in pages:
        features = page["features"]
        score = (
            features["toc_entry_pattern_count"] * 1.5
            + features["chapter_or_part_line_count"] * 0.5
            + (3 if features["toc_keyword_presence"] else 0)
        )
        page_scores[page["pdf_page"]] = score

    selected_pages = [page for page, score in page_scores.items() if score >= 4]
    return build_labeler_result("toc_entry_pattern_density", selected_pages, page_scores)


def labeler_window_mass_contrast(pages: list[dict[str, Any]]) -> dict[str, Any]:
    page_scores = {}
    for page in pages:
        features = page["features"]
        anchor_count = page["anchor_evidence"]["unique_matched_bookmark_count"]
        score = (
            min(anchor_count, 20) * 0.35
            + min(features["line_final_number_count"], 40) * 0.15
            + min(features["toc_entry_pattern_count"], 20) * 0.25
            + (features["line_final_number_monotonicity"] or 0) * 2
            + (1 if features["toc_keyword_presence"] else 0)
        )
        page_scores[page["pdf_page"]] = score

    best = find_best_window(page_scores, min_length=2, max_length=20)
    selected_pages = list(range(best["start"], best["end"] + 1)) if best else []
    result = build_labeler_result("window_mass_contrast", selected_pages, page_scores)
    result["best_window"] = best
    return result


def labeler_offset_consistency(
    pages: list[dict[str, Any]],
    all_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    offsets_by_page: dict[int, list[int]] = defaultdict(list)
    for match in all_matches:
        trailing_number = match.get("trailing_number")
        target_pdf_page = match.get("bookmark_target_pdf_page")
        if trailing_number is None or target_pdf_page is None:
            continue
        if trailing_number <= 0 or trailing_number > 2000:
            continue
        offsets_by_page[match["pdf_page"]].append(target_pdf_page - trailing_number)

    page_scores = {}
    for page in pages:
        page_number = page["pdf_page"]
        offsets = offsets_by_page.get(page_number, [])
        if len(offsets) < 2:
            page_scores[page_number] = 0.0
            continue
        offset_counts = Counter(offsets)
        modal_count = offset_counts.most_common(1)[0][1]
        modal_share = modal_count / len(offsets)
        page_scores[page_number] = modal_count * modal_share

    selected_pages = [page for page, score in page_scores.items() if score >= 2]
    result = build_labeler_result("offset_consistency", selected_pages, page_scores)
    result["offsets_by_page"] = {
        str(page): offsets for page, offsets in sorted(offsets_by_page.items())
    }
    return result


def find_best_window(
    page_scores: dict[int, float],
    min_length: int,
    max_length: int,
) -> dict[str, Any] | None:
    page_numbers = sorted(page_scores)
    best: dict[str, Any] | None = None

    for start in page_numbers:
        for end in page_numbers:
            if end < start:
                continue
            length = end - start + 1
            if length < min_length or length > max_length:
                continue

            inside_pages = list(range(start, end + 1))
            inside_scores = [page_scores.get(page, 0.0) for page in inside_pages]
            inside_sum = sum(inside_scores)
            inside_mean = inside_sum / length
            left_score = page_scores.get(start - 1, 0.0)
            right_score = page_scores.get(end + 1, 0.0)
            boundary_contrast = max(0.0, inside_mean - (left_score + right_score) / 2)
            weak_page_penalty = sum(1 for score in inside_scores if score < 1.5) * 0.7
            length_penalty = math.log1p(length) * 0.8
            total_score = inside_sum + boundary_contrast * 2 - weak_page_penalty - length_penalty

            if best is None or total_score > best["score"]:
                best = {
                    "start": start,
                    "end": end,
                    "length": length,
                    "score": total_score,
                    "inside_sum": inside_sum,
                    "inside_mean": inside_mean,
                    "boundary_contrast": boundary_contrast,
                    "weak_page_penalty": weak_page_penalty,
                    "length_penalty": length_penalty,
                }

    return best


def build_labeler_result(
    name: str,
    selected_pages: list[int],
    page_scores: dict[int, float],
) -> dict[str, Any]:
    selected = sorted(set(selected_pages))
    return {
        "name": name,
        "selected_pages": selected,
        "segments": pages_to_segments(selected),
        "page_scores": {str(page): score for page, score in sorted(page_scores.items())},
    }


def pages_to_segments(pages: list[int]) -> list[dict[str, int]]:
    if not pages:
        return []

    segments = []
    start = pages[0]
    previous = pages[0]
    for page in pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        segments.append({"start": start, "end": previous})
        start = page
        previous = page
    segments.append({"start": start, "end": previous})
    return segments


def ensemble_labeler_results(
    labeler_results: list[dict[str, Any]],
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    page_numbers = [page["pdf_page"] for page in pages]
    page_by_number = pages_by_number(pages)
    votes_by_page = {}
    for page in page_numbers:
        voters = [
            result["name"]
            for result in labeler_results
            if page in set(result["selected_pages"])
        ]
        votes_by_page[page] = voters

    vote_counts = {page: len(voters) for page, voters in votes_by_page.items()}
    strong_pages = [page for page, count in vote_counts.items() if count >= 2]
    strong_segments = pages_to_segments(strong_pages)
    best_segment = choose_best_strong_segment(strong_segments, vote_counts)
    accepted_pages = expand_segment_edges(
        best_segment,
        vote_counts,
        votes_by_page,
        page_by_number,
    )
    core_pages = (
        list(range(best_segment["start"], best_segment["end"] + 1))
        if best_segment
        else []
    )

    return {
        "vote_counts": {str(page): count for page, count in sorted(vote_counts.items())},
        "votes_by_page": {
            str(page): voters for page, voters in sorted(votes_by_page.items())
        },
        "strong_pages": strong_pages,
        "strong_segments": strong_segments,
        "accepted_pages": accepted_pages,
        "core_pages": core_pages,
        "best_strong_segment": best_segment,
    }


def choose_best_strong_segment(
    strong_segments: list[dict[str, int]],
    vote_counts: dict[int, int],
) -> dict[str, Any] | None:
    best = None
    for segment in strong_segments:
        pages = list(range(segment["start"], segment["end"] + 1))
        vote_sum = sum(vote_counts.get(page, 0) for page in pages)
        length = len(pages)
        score = vote_sum + length * 0.5
        candidate = segment | {
            "length": length,
            "vote_sum": vote_sum,
            "score": score,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def expand_segment_edges(
    segment: dict[str, Any] | None,
    vote_counts: dict[int, int],
    votes_by_page: dict[int, list[str]],
    page_by_number: dict[int, dict[str, Any]],
) -> list[int]:
    if segment is None:
        return []

    start = segment["start"]
    end = segment["end"]

    while is_soft_edge_toc_page(start - 1, vote_counts, votes_by_page, page_by_number):
        start -= 1
    while is_soft_edge_toc_page(end + 1, vote_counts, votes_by_page, page_by_number):
        end += 1

    return list(range(start, end + 1))


def is_soft_edge_toc_page(
    page_number: int,
    vote_counts: dict[int, int],
    votes_by_page: dict[int, list[str]],
    page_by_number: dict[int, dict[str, Any]],
) -> bool:
    if page_number not in page_by_number:
        return False
    if vote_counts.get(page_number, 0) != 1:
        return False
    if "window_mass_contrast" not in votes_by_page.get(page_number, []):
        return False

    features = page_by_number[page_number]["features"]
    return (
        features["line_final_number_count"] >= 5
        and features["word_count"] <= 220
        and features["line_final_number_negative_gap_count"] <= 1
    )


def pages_by_number(pages: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {page["pdf_page"]: page for page in pages}


def analyze_pdf(pdf_id: str, pdf_path: Path) -> dict[str, Any]:
    output_dir = OUTPUT_DIR / pdf_id
    output_dir.mkdir(parents=True, exist_ok=True)

    with fitz.open(pdf_path) as document:
        bookmarks = extract_bookmarks_for_labeling(document)
        pages = []
        windows_by_page: dict[int, list[dict[str, Any]]] = {}

        for page_index in range(min(MAX_TEXT_PAGES, document.page_count)):
            page_number = page_index + 1
            text = document.load_page(page_index).get_text("text")
            lines = extract_lines(text)
            windows = build_page_windows(page_number, lines)
            windows_by_page[page_number] = windows
            pages.append(
                {
                    "pdf_page": page_number,
                    "features": calculate_page_features(
                        page_number,
                        document.page_count,
                        text,
                        lines,
                    ),
                    "text_preview": normalize_text(text)[:500],
                }
            )

    anchor_evidence_by_page, all_matches = match_bookmarks_to_pages(
        bookmarks,
        windows_by_page,
    )
    for page in pages:
        page["anchor_evidence"] = anchor_evidence_by_page[page["pdf_page"]]

    labeler_results = [
        labeler_bookmark_anchor_density(pages),
        labeler_printed_page_sequence(pages),
        labeler_toc_entry_pattern_density(pages),
        labeler_window_mass_contrast(pages),
        labeler_offset_consistency(pages, all_matches),
    ]
    ensemble = ensemble_labeler_results(
        labeler_results,
        pages,
    )
    reviewed_comparison = compare_with_reviewed_range(
        predicted_pages=ensemble["accepted_pages"],
        reviewed_range=REVIEWED_TOC_PAGE_RANGES[pdf_id],
    )

    write_json(output_dir / "bookmarks_for_labeling.json", bookmarks)
    write_jsonl(output_dir / "page_features_first_30.jsonl", pages)
    write_jsonl(output_dir / "bookmark_title_matches.jsonl", all_matches)
    write_json(output_dir / "weak_labeler_results.json", labeler_results)
    write_json(output_dir / "ensemble_result.json", ensemble)
    write_json(output_dir / "reviewed_toc_page_comparison.json", reviewed_comparison)
    (output_dir / "report.md").write_text(
        build_report(pdf_id, pdf_path, labeler_results, ensemble, reviewed_comparison),
        encoding="utf-8",
    )

    return {
        "pdf_id": pdf_id,
        "input_pdf": str(pdf_path.relative_to(ROOT_DIR)),
        "usable_bookmark_count": len(bookmarks),
        "weak_labeler_pages": {
            result["name"]: result["selected_pages"] for result in labeler_results
        },
        "ensemble": ensemble,
        "reviewed_toc_page_comparison": reviewed_comparison,
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
    labeler_results: list[dict[str, Any]],
    ensemble: dict[str, Any],
    reviewed_comparison: dict[str, Any],
) -> str:
    labeler_lines = "\n".join(
        f"- {result['name']}: {result['selected_pages']}"
        for result in labeler_results
    )
    accepted = reviewed_comparison["accepted_comparison"]
    core = reviewed_comparison["core_comparison"]

    return f"""# {pdf_id} ensemble TOC labeler

## 입력

- PDF: `{pdf_path.relative_to(ROOT_DIR)}`
- 관찰 범위: 첫 {MAX_TEXT_PAGES}페이지

## Weak labelers

{labeler_lines}

## Ensemble

- accepted pages: {ensemble["accepted_pages"]}
- core pages: {ensemble["core_pages"]}
- best strong segment: {ensemble["best_strong_segment"]}

## 사용자 검수 range 비교

- 검수 메모: {reviewed_comparison["note"]}
- accepted expected: {reviewed_comparison["accepted_pages"]}
- accepted missing: {accepted["missing_pages"]}
- accepted extra: {accepted["extra_pages"]}
- accepted precision: {accepted["precision"]}
- accepted recall: {accepted["recall"]}
- core expected: {reviewed_comparison["core_pages"]}
- core missing: {core["missing_pages"]}
- core extra: {core["extra_pages"]}
- core precision: {core["precision"]}
- core recall: {core["recall"]}
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
        comparison = result["reviewed_toc_page_comparison"]["accepted_comparison"]
        parts.append(
            f"{result['pdf_id']} ensemble accepted pages는 "
            f"{result['ensemble']['accepted_pages']}이고, 사용자 검수 accepted range 대비 "
            f"precision {comparison['precision']}, recall {comparison['recall']}, "
            f"missing {comparison['missing_pages']}, extra {comparison['extra_pages']}이다."
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
                "bookmark가 있는 silver label PDF에서 TOC 정답 page range를 deterministic하게 "
                "복원하기 위해 bookmark anchor, printed page number sequence, TOC entry pattern, "
                "contiguous window mass, target-page offset consistency라는 5개 orthogonal weak "
                "labeler를 ensemble한다."
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
