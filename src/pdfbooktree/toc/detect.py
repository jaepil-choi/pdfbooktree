"""학습된 classifier로 TOC page range를 찾는 runtime 탐지기다.

역할:
- PDF 앞부분에서 추출한 page feature를 학습된 ML 모델에 넣어 TOC page range를 고른다.
- 기존 PDF bookmark, 평가용 정답, 사람이 검수한 label은 참조하지 않는다.
- `Processor`가 호출하는 기본 TOC page detection 진입점으로 유지한다.
- 모델 artifact가 없거나 현재 runtime feature와 맞지 않으면 실패한다.

책임 밖:
- 기존 bookmark title을 기준으로 TOC page를 복원하는 흐름은
  `toc.detect_from_bookmarks`가 담당한다.
- 탐지 결과의 IoU, start/end error, precision/recall 같은 metric 계산은
  `metrics.toc_pages`가 담당한다.
- TOC line에서 chapter/section item을 파싱하는 일은 `toc.parse`가 담당한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np

from pdfbooktree.config import TocMlDetectionConfig
from pdfbooktree.models import PageFeature, TocDetectionResult
from pdfbooktree.toc.dataset_training import (
    TOC_PAGE_DATASET_FEATURE_NAMES,
    numeric_feature_value,
)


def detect_toc_pages(
    features: list[PageFeature],
    config: TocMlDetectionConfig | None = None,
) -> TocDetectionResult:
    """학습된 page classifier 확률로 TOC page range를 고른다.

    휴리스틱 fallback은 없다. 모델 파일이 없거나 feature schema가 다르면 예외를
    발생시켜, runtime 이전에 반드시 train을 거치도록 강제한다.
    """

    detector = TrainedTocPageDetector(config or TocMlDetectionConfig())
    return detector.detect(features)


class TrainedTocPageDetector:
    """joblib artifact에 저장된 TOC page classifier를 runtime에 적용한다."""

    def __init__(self, config: TocMlDetectionConfig) -> None:
        self.config = config

    def detect(self, features: list[PageFeature]) -> TocDetectionResult:
        """page feature 목록을 모델 확률로 변환하고 최선 segment를 고른다."""

        if not features:
            return TocDetectionResult(
                pages=[],
                start_page=None,
                end_page=None,
                confidence=0.0,
                method="ml_toc_page_classifier",
                candidates=[],
            )

        artifact = load_model_artifact(self.config.model_path)
        model = artifact["model"]
        feature_names = validate_feature_names(artifact)
        rows = build_runtime_feature_rows(features)
        matrix = make_runtime_matrix(rows, feature_names)
        probabilities = model.predict_proba(matrix)[:, 1]
        candidates = build_candidates(features, probabilities, self.config)
        segment = select_ml_segment(candidates, self.config)
        method = build_method_name(artifact)
        if segment is None:
            return TocDetectionResult(
                pages=[],
                start_page=None,
                end_page=None,
                confidence=float(max(probabilities, default=0.0)),
                method=method,
                candidates=candidates,
            )

        pages = list(range(segment["start_page"], segment["end_page"] + 1))
        confidence = float(segment["mean_probability"])
        return TocDetectionResult(
            pages=pages,
            start_page=segment["start_page"],
            end_page=segment["end_page"],
            confidence=confidence,
            method=method,
            candidates=candidates,
        )


def load_model_artifact(model_path: Path) -> dict[str, Any]:
    """학습된 joblib artifact를 읽는다. 없으면 runtime을 중단한다."""

    if not model_path.exists():
        raise FileNotFoundError(
            f"TOC page classifier 모델이 없다: {model_path}. "
            "먼저 `uv run pdfbooktree train-toc-page-dataset ... --model hist-gradient`로 "
            "모델을 학습해야 한다."
        )
    artifact = joblib.load(model_path)
    if not isinstance(artifact, dict) or "model" not in artifact:
        raise ValueError(f"TOC page classifier artifact 형식이 올바르지 않다: {model_path}")
    return artifact


def validate_feature_names(artifact: dict[str, Any]) -> list[str]:
    """artifact feature schema가 현재 runtime feature와 같은지 확인한다."""

    feature_names = list(artifact.get("feature_names") or [])
    expected = list(TOC_PAGE_DATASET_FEATURE_NAMES)
    if feature_names != expected:
        raise ValueError(
            "TOC page classifier feature schema가 현재 코드와 다르다. "
            "dataset을 현재 코드로 다시 만들고 모델을 재학습해야 한다."
        )
    return feature_names


def build_runtime_feature_rows(features: list[PageFeature]) -> list[dict[str, Any]]:
    """PageFeature 목록에서 학습 dataset과 같은 feature row를 만든다."""

    rows: list[dict[str, Any]] = []
    total_pages = infer_total_pages(features)
    previous: PageFeature | None = None
    for feature in features:
        row = current_feature_row(feature, total_pages)
        row.update(previous_feature_row(previous))
        rows.append(row)
        previous = feature
    return rows


def infer_total_pages(features: list[PageFeature]) -> int:
    """page_position에서 전체 page 수를 복원한다."""

    estimates = [
        round(feature.pdf_page / feature.page_position)
        for feature in features
        if feature.page_position > 0
    ]
    if estimates:
        return max(estimates)
    return max((feature.pdf_page for feature in features), default=0)


def current_feature_row(feature: PageFeature, total_pages: int) -> dict[str, Any]:
    """현재 page feature를 dataset row 필드명으로 변환한다."""

    return {
        "line_count": feature.line_count,
        "word_count": feature.word_count,
        "mean_line_length": feature.mean_line_length,
        "line_length_std": feature.line_length_std,
        "line_final_number_count": feature.line_final_number_count,
        "line_final_number_monotonicity": feature.line_final_number_monotonicity,
        "line_final_number_gap_mean": feature.line_final_number_gap_mean,
        "line_final_number_gap_median": feature.line_final_number_gap_median,
        "line_final_number_gap_max": feature.line_final_number_gap_max,
        "line_final_number_negative_gap_count": (
            feature.line_final_number_negative_gap_count
        ),
        "toc_entry_pattern_count": feature.toc_entry_pattern_count,
        "toc_entry_pattern_ratio": feature.toc_entry_pattern_ratio,
        "chapter_or_part_line_count": feature.chapter_or_part_line_count,
        "page_position": feature.page_position,
        "toc_keyword_presence": feature.toc_keyword_presence,
        "total_pages": total_pages,
    }


def previous_feature_row(previous: PageFeature | None) -> dict[str, Any]:
    """직전 page feature를 dataset row의 prev_* 필드로 변환한다."""

    if previous is None:
        return {
            "prev_page_available": False,
            "prev_line_count": None,
            "prev_word_count": None,
            "prev_mean_line_length": None,
            "prev_line_length_std": None,
            "prev_line_final_number_count": None,
            "prev_line_final_number_monotonicity": None,
            "prev_line_final_number_gap_mean": None,
            "prev_line_final_number_gap_median": None,
            "prev_line_final_number_gap_max": None,
            "prev_line_final_number_negative_gap_count": None,
            "prev_toc_entry_pattern_count": None,
            "prev_toc_entry_pattern_ratio": None,
            "prev_chapter_or_part_line_count": None,
            "prev_toc_keyword_presence": None,
        }
    return {
        "prev_page_available": True,
        "prev_line_count": previous.line_count,
        "prev_word_count": previous.word_count,
        "prev_mean_line_length": previous.mean_line_length,
        "prev_line_length_std": previous.line_length_std,
        "prev_line_final_number_count": previous.line_final_number_count,
        "prev_line_final_number_monotonicity": previous.line_final_number_monotonicity,
        "prev_line_final_number_gap_mean": previous.line_final_number_gap_mean,
        "prev_line_final_number_gap_median": previous.line_final_number_gap_median,
        "prev_line_final_number_gap_max": previous.line_final_number_gap_max,
        "prev_line_final_number_negative_gap_count": (
            previous.line_final_number_negative_gap_count
        ),
        "prev_toc_entry_pattern_count": previous.toc_entry_pattern_count,
        "prev_toc_entry_pattern_ratio": previous.toc_entry_pattern_ratio,
        "prev_chapter_or_part_line_count": previous.chapter_or_part_line_count,
        "prev_toc_keyword_presence": previous.toc_keyword_presence,
    }


def make_runtime_matrix(
    rows: list[dict[str, Any]],
    feature_names: list[str],
) -> np.ndarray:
    """runtime row를 artifact feature 순서에 맞춘 numpy matrix로 바꾼다."""

    return np.array(
        [
            [numeric_feature_value(row.get(name)) for name in feature_names]
            for row in rows
        ],
        dtype=float,
    )


def build_candidates(
    features: list[PageFeature],
    probabilities: np.ndarray,
    config: TocMlDetectionConfig,
) -> list[dict[str, Any]]:
    """report/intermediate에 남길 page별 ML 후보 정보를 만든다."""

    candidates = [
        {
            "pdf_page": feature.pdf_page,
            "toc_probability": float(probability),
            "predicted_label": bool(probability >= config.probability_threshold),
            "line_final_number_count": feature.line_final_number_count,
            "toc_entry_pattern_count": feature.toc_entry_pattern_count,
            "toc_keyword_presence": feature.toc_keyword_presence,
        }
        for feature, probability in zip(features, probabilities, strict=True)
    ]
    return candidates


def select_ml_segment(
    candidates: list[dict[str, Any]],
    config: TocMlDetectionConfig,
) -> dict[str, Any] | None:
    """threshold를 넘은 page들에서 가장 확률 mass가 큰 연속 구간을 고른다."""

    positive_pages = [
        candidate["pdf_page"]
        for candidate in candidates
        if candidate["toc_probability"] >= config.probability_threshold
    ]
    if not positive_pages:
        return None
    segments = merge_pages_to_segments(positive_pages, config.max_segment_gap)
    probability_by_page = {
        candidate["pdf_page"]: candidate["toc_probability"] for candidate in candidates
    }

    best: dict[str, Any] | None = None
    for start_page, end_page in segments:
        pages = list(range(start_page, end_page + 1))
        if len(pages) > config.max_segment_length:
            pages = choose_best_subwindow(pages, probability_by_page, config)
            start_page, end_page = pages[0], pages[-1]
        probabilities = [probability_by_page.get(page, 0.0) for page in pages]
        probability_sum = float(sum(probabilities))
        mean_probability = probability_sum / len(pages)
        score = probability_sum - len(pages) * 0.02
        segment = {
            "start_page": start_page,
            "end_page": end_page,
            "probability_sum": probability_sum,
            "mean_probability": mean_probability,
            "score": score,
        }
        if best is None or segment["score"] > best["score"]:
            best = segment
    return best


def merge_pages_to_segments(
    pages: list[int],
    max_gap: int,
) -> list[tuple[int, int]]:
    """positive page를 gap 허용 연속 구간으로 묶는다."""

    ordered = sorted(set(pages))
    if not ordered:
        return []
    segments: list[tuple[int, int]] = []
    start = ordered[0]
    previous = ordered[0]
    for page in ordered[1:]:
        if page - previous <= max_gap + 1:
            previous = page
            continue
        segments.append((start, previous))
        start = page
        previous = page
    segments.append((start, previous))
    return segments


def choose_best_subwindow(
    pages: list[int],
    probability_by_page: dict[int, float],
    config: TocMlDetectionConfig,
) -> list[int]:
    """너무 긴 segment에서 확률 합이 가장 큰 window만 남긴다."""

    best_pages = pages[: config.max_segment_length]
    best_score = -1.0
    for index in range(0, len(pages) - config.max_segment_length + 1):
        window = pages[index : index + config.max_segment_length]
        score = sum(probability_by_page.get(page, 0.0) for page in window)
        if score > best_score:
            best_score = score
            best_pages = window
    return best_pages


def build_method_name(artifact: dict[str, Any]) -> str:
    """학습 report의 best model 이름을 method에 반영한다."""

    summary = artifact.get("training_summary") or {}
    best_model = str(summary.get("best_model") or "unknown").replace("-", "_")
    return f"ml_{best_model}_toc_page_classifier"
