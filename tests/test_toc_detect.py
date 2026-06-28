from __future__ import annotations

import joblib
import numpy as np

from pdfbooktree.config import TocMlDetectionConfig
from pdfbooktree.models import PageFeature
from pdfbooktree.toc.dataset_training import TOC_PAGE_DATASET_FEATURE_NAMES
from pdfbooktree.toc.detect import detect_toc_pages


class FinalNumberProbabilityModel:
    """line-final number가 있으면 TOC 확률을 높게 주는 테스트용 모델이다."""

    def predict_proba(self, rows):
        final_number_index = TOC_PAGE_DATASET_FEATURE_NAMES.index(
            "line_final_number_count"
        )
        probabilities = []
        for row in rows:
            positive = 0.9 if row[final_number_index] > 0 else 0.1
            probabilities.append([1.0 - positive, positive])
        return np.asarray(probabilities)


def make_feature(
    pdf_page: int,
    final_count: int = 0,
    monotonicity: float | None = None,
    toc_entry_count: int = 0,
) -> PageFeature:
    return PageFeature(
        pdf_page=pdf_page,
        line_count=20,
        word_count=100,
        mean_line_length=30.0,
        line_length_std=4.0,
        line_final_number_count=final_count,
        line_final_numbers=list(range(1, final_count + 1)),
        line_final_number_monotonicity=monotonicity,
        line_final_number_gap_mean=None,
        line_final_number_gap_median=None,
        line_final_number_gap_max=None,
        line_final_number_negative_gap_count=0,
        toc_entry_pattern_count=toc_entry_count,
        toc_entry_pattern_ratio=toc_entry_count / 20,
        chapter_or_part_line_count=0,
        page_position=pdf_page / 100,
        toc_keyword_presence=False,
    )


def write_model(path) -> None:
    joblib.dump(
        {
            "model": FinalNumberProbabilityModel(),
            "feature_names": TOC_PAGE_DATASET_FEATURE_NAMES,
            "training_summary": {"best_model": "hist-gradient"},
        },
        path,
    )


def test_detect_toc_pages_returns_segment_and_candidates(tmp_path) -> None:
    model_path = tmp_path / "toc_model.joblib"
    write_model(model_path)
    features = [
        make_feature(1),
        make_feature(2, final_count=9, monotonicity=1.0, toc_entry_count=3),
        make_feature(3, final_count=10, monotonicity=1.0, toc_entry_count=3),
        make_feature(4, final_count=9, monotonicity=1.0, toc_entry_count=3),
        make_feature(5),
    ]

    result = detect_toc_pages(features, TocMlDetectionConfig(model_path=model_path))

    assert result.pages == [2, 3, 4]
    assert result.start_page == 2
    assert result.end_page == 4
    assert result.confidence > 0
    assert result.method == "ml_hist_gradient_toc_page_classifier"
    assert result.candidates[1]["predicted_label"] is True


def test_detect_toc_pages_returns_empty_when_no_page_has_evidence(tmp_path) -> None:
    model_path = tmp_path / "toc_model.joblib"
    write_model(model_path)

    result = detect_toc_pages(
        [make_feature(1), make_feature(2), make_feature(3)],
        TocMlDetectionConfig(model_path=model_path),
    )

    assert result.pages == []
    assert result.confidence == 0.1


def test_detect_toc_pages_requires_trained_model(tmp_path) -> None:
    missing_model = tmp_path / "missing.joblib"

    try:
        detect_toc_pages([make_feature(1)], TocMlDetectionConfig(model_path=missing_model))
    except FileNotFoundError as exc:
        assert "모델이 없다" in str(exc)
    else:
        raise AssertionError("학습 모델이 없으면 실패해야 한다.")
