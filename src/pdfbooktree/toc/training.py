"""PRD 기준 TOC page detector 학습 흐름을 제공한다."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

import fitz
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeRegressor

from pdfbooktree.metrics.toc_pages import compare_toc_pages
from pdfbooktree.models import PageFeature, TocDetectionResult
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.utils.jsonio import to_jsonable, write_json


ModelType = Literal["decision-tree", "hist-gradient", "random-forest"]

OBJECTIVE_FEATURE_NAMES = [
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


@dataclass(frozen=True)
class TocTrainingLabel:
    """검수된 단일 PDF TOC page range label이다."""

    input_pdf: Path
    toc_start_page: int
    toc_end_page: int
    review_status: str

    @property
    def toc_pages(self) -> list[int]:
        """TOC range를 1-based page 목록으로 반환한다."""

        return list(range(self.toc_start_page, self.toc_end_page + 1))


@dataclass(frozen=True)
class RejectedTocTrainingLabel:
    """학습에서 제외한 label과 이유다."""

    index: int
    input_pdf: str | None
    review_status: str | None
    reason: str


@dataclass(frozen=True)
class TocDetectorFoldResult:
    """GroupKFold 한 fold의 TOC range 평가 결과다."""

    fold: int
    train_pdf_count: int
    test_pdf_count: int
    train_row_count: int
    test_row_count: int
    mean_segment_iou: float | None
    mean_abs_start_page_error: float | None
    mean_abs_end_page_error: float | None
    pdf_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class TocDetectorTrainingResult:
    """TOC detector 학습 결과와 산출물 위치다."""

    trained_model_path: Path
    report_path: Path
    accepted_label_count: int
    rejected_label_count: int
    rejected_labels: list[RejectedTocTrainingLabel]
    fold_results: list[TocDetectorFoldResult]
    mean_segment_iou: float | None
    mean_abs_start_page_error: float | None
    mean_abs_end_page_error: float | None
    feature_importance: list[dict[str, Any]]


@dataclass(frozen=True)
class _TrainingExample:
    pdf_key: str
    pdf_page: int
    feature: PageFeature
    target: float


class TocDetectorTrainer:
    """수동 검수 label만 사용해 TOC page detector를 학습한다."""

    def __init__(
        self,
        labels_path: Path | str,
        output_dir: Path | str,
        model_type: ModelType = "random-forest",
        max_text_pages: int = 80,
        n_splits: int = 5,
        random_seed: int = 42,
    ) -> None:
        self.labels_path = Path(labels_path)
        self.output_dir = Path(output_dir)
        self.model_type = model_type
        self.max_text_pages = max_text_pages
        self.n_splits = n_splits
        self.random_seed = random_seed

    def run(self) -> TocDetectorTrainingResult:
        """label을 읽고 GroupKFold 평가 후 최종 모델을 저장한다."""

        labels, rejected_labels = load_training_labels(self.labels_path)
        labels, validation_rejections = validate_training_labels(
            labels,
            max_text_pages=self.max_text_pages,
        )
        rejected_labels = [*rejected_labels, *validation_rejections]
        if not labels:
            raise ValueError(
                "학습 가능한 manual_reviewed label이 없다. "
                f"총 {len(rejected_labels)}개 label이 제외되었다."
            )
        if len(labels) < 2:
            raise ValueError("GroupKFold 평가에는 최소 2개 PDF label이 필요하다.")

        examples = build_training_examples(labels, self.max_text_pages)
        if not examples:
            raise ValueError("학습 row를 만들지 못했다.")

        x, y, groups, page_numbers = make_training_matrix(examples)
        label_by_key = {str(label.input_pdf.resolve()): label for label in labels}
        fold_results = cross_validate_detector(
            x=x,
            y=y,
            groups=groups,
            page_numbers=page_numbers,
            label_by_key=label_by_key,
            model_type=self.model_type,
            n_splits=min(self.n_splits, len(label_by_key)),
            random_seed=self.random_seed,
        )

        final_model = build_regressor(self.model_type, self.random_seed)
        final_model.fit(x, y)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        model_path = self.output_dir / "toc_detector_model.joblib"
        feature_importance = extract_feature_importance(final_model)
        summary = build_training_summary(
            labels=labels,
            rejected_labels=rejected_labels,
            fold_results=fold_results,
            feature_importance=feature_importance,
            model_type=self.model_type,
            max_text_pages=self.max_text_pages,
        )
        artifact = {
            "model": final_model,
            "feature_names": OBJECTIVE_FEATURE_NAMES,
            "label_policy": "manual_reviewed_only",
            "training_summary": to_jsonable(summary),
            "package_version": package_version(),
        }
        joblib.dump(artifact, model_path)

        report_path = self.output_dir / "training_report.json"
        write_json(report_path, summary)

        return TocDetectorTrainingResult(
            trained_model_path=model_path,
            report_path=report_path,
            accepted_label_count=len(labels),
            rejected_label_count=len(rejected_labels),
            rejected_labels=rejected_labels,
            fold_results=fold_results,
            mean_segment_iou=summary["cross_validation"]["mean_segment_iou"],
            mean_abs_start_page_error=summary["cross_validation"][
                "mean_abs_start_page_error"
            ],
            mean_abs_end_page_error=summary["cross_validation"][
                "mean_abs_end_page_error"
            ],
            feature_importance=feature_importance,
        )


class TocDetectorModel:
    """저장된 TOC detector artifact를 로드해 page feature에 적용한다."""

    def __init__(
        self,
        model: Pipeline,
        feature_names: list[str],
        training_summary: dict[str, Any],
    ) -> None:
        self.model = model
        self.feature_names = feature_names
        self.training_summary = training_summary

    @classmethod
    def load(cls, path: Path | str) -> TocDetectorModel:
        """joblib artifact에서 detector를 로드한다."""

        artifact = joblib.load(path)
        return cls(
            model=artifact["model"],
            feature_names=list(artifact["feature_names"]),
            training_summary=dict(artifact.get("training_summary") or {}),
        )

    def predict(self, features: list[PageFeature]) -> TocDetectionResult:
        """page feature 목록에서 ML 기반 TOC range를 예측한다."""

        if not features:
            return TocDetectionResult(
                pages=[],
                start_page=None,
                end_page=None,
                confidence=0.0,
                method="ml_page_soft_label_regression",
                candidates=[],
            )

        x = np.array([feature_vector(feature) for feature in features], dtype=float)
        scores = np.clip(self.model.predict(x), 0.0, 1.0)
        pages = [feature.pdf_page for feature in features]
        selected_pages = select_pages_from_scores(
            {page: float(score) for page, score in zip(pages, scores, strict=True)}
        )
        candidates = [
            {"pdf_page": page, "score": round(float(score), 6)}
            for page, score in zip(pages, scores, strict=True)
        ]
        confidence = float(max(scores)) if selected_pages else 0.0
        return TocDetectionResult(
            pages=selected_pages,
            start_page=min(selected_pages) if selected_pages else None,
            end_page=max(selected_pages) if selected_pages else None,
            confidence=confidence,
            method="ml_page_soft_label_regression",
            candidates=candidates,
        )


def load_training_labels(
    labels_path: Path,
) -> tuple[list[TocTrainingLabel], list[RejectedTocTrainingLabel]]:
    """JSON label 파일에서 manual_reviewed label만 읽는다."""

    raw = json.loads(labels_path.read_text(encoding="utf-8"))
    rows = raw.get("labels", raw) if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("label JSON은 list이거나 labels 배열을 가진 객체여야 한다.")

    dataset_root = resolve_dataset_root(raw, labels_path)
    labels: list[TocTrainingLabel] = []
    rejected: list[RejectedTocTrainingLabel] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            rejected.append(
                RejectedTocTrainingLabel(
                    index, None, None, "label row가 객체가 아니다."
                )
            )
            continue

        review_status = string_or_none(row.get("review_status"))
        input_pdf_text = string_or_none(row.get("input_pdf")) or string_or_none(
            row.get("root_relative_pdf")
        )
        if review_status != "manual_reviewed":
            rejected.append(
                RejectedTocTrainingLabel(
                    index=index,
                    input_pdf=input_pdf_text,
                    review_status=review_status,
                    reason="review_status가 manual_reviewed가 아니다.",
                )
            )
            continue

        try:
            pdf_path = resolve_pdf_path(row, labels_path, dataset_root)
            start_page = int(row["toc_start_page"])
            end_page = int(row["toc_end_page"])
        except (KeyError, TypeError, ValueError) as error:
            rejected.append(
                RejectedTocTrainingLabel(
                    index=index,
                    input_pdf=input_pdf_text,
                    review_status=review_status,
                    reason=f"필수 label field가 유효하지 않다: {error}",
                )
            )
            continue

        labels.append(
            TocTrainingLabel(
                input_pdf=pdf_path,
                toc_start_page=start_page,
                toc_end_page=end_page,
                review_status=review_status,
            )
        )
    return labels, rejected


def validate_training_labels(
    labels: list[TocTrainingLabel],
    max_text_pages: int,
) -> tuple[list[TocTrainingLabel], list[RejectedTocTrainingLabel]]:
    """PDF 존재 여부와 page range를 검증한다."""

    accepted: list[TocTrainingLabel] = []
    rejected: list[RejectedTocTrainingLabel] = []
    for index, label in enumerate(labels):
        reason: str | None = None
        if label.toc_start_page < 1 or label.toc_end_page < 1:
            reason = "page number는 1 이상이어야 한다."
        elif label.toc_start_page > label.toc_end_page:
            reason = "toc_start_page가 toc_end_page보다 크다."
        elif not label.input_pdf.exists():
            reason = "PDF 파일이 존재하지 않는다."
        else:
            with fitz.open(label.input_pdf) as document:
                total_pages = document.page_count
            if label.toc_end_page > total_pages:
                reason = "TOC label이 PDF page 범위를 벗어났다."
            elif label.toc_end_page > max_text_pages:
                reason = "TOC label이 max_text_pages 탐색 범위를 벗어났다."

        if reason is None:
            accepted.append(label)
        else:
            rejected.append(
                RejectedTocTrainingLabel(
                    index=index,
                    input_pdf=str(label.input_pdf),
                    review_status=label.review_status,
                    reason=reason,
                )
            )
    return accepted, rejected


def soft_label_for_page(pdf_page: int, toc_start_page: int, toc_end_page: int) -> float:
    """PRD의 page-level soft label target을 계산한다."""

    if toc_start_page <= pdf_page <= toc_end_page:
        return 1.0
    distance = min(abs(pdf_page - toc_start_page), abs(pdf_page - toc_end_page))
    if distance == 1:
        return 0.5
    if distance == 2:
        return 0.2
    return 0.0


def segment_iou_target(
    candidate_start_page: int,
    candidate_end_page: int,
    toc_start_page: int,
    toc_end_page: int,
) -> float:
    """candidate segment와 GT TOC segment 사이의 IoU target을 계산한다."""

    candidate = set(range(candidate_start_page, candidate_end_page + 1))
    expected = set(range(toc_start_page, toc_end_page + 1))
    union = candidate | expected
    if not union:
        return 0.0
    return len(candidate & expected) / len(union)


def build_training_examples(
    labels: list[TocTrainingLabel],
    max_text_pages: int,
) -> list[_TrainingExample]:
    """검수 label PDF에서 page feature와 soft target row를 만든다."""

    examples: list[_TrainingExample] = []
    for label in labels:
        with fitz.open(label.input_pdf) as document:
            total_pages = document.page_count
        pages = extract_page_texts(label.input_pdf, max_pages=max_text_pages)
        features = calculate_page_features(pages, total_pages=total_pages)
        pdf_key = str(label.input_pdf.resolve())
        for feature in features:
            examples.append(
                _TrainingExample(
                    pdf_key=pdf_key,
                    pdf_page=feature.pdf_page,
                    feature=feature,
                    target=soft_label_for_page(
                        feature.pdf_page,
                        label.toc_start_page,
                        label.toc_end_page,
                    ),
                )
            )
    return examples


def make_training_matrix(
    examples: list[_TrainingExample],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """학습 row를 sklearn 입력 행렬로 변환한다."""

    x = np.array([feature_vector(example.feature) for example in examples], dtype=float)
    y = np.array([example.target for example in examples], dtype=float)
    groups = np.array([example.pdf_key for example in examples], dtype=object)
    page_numbers = np.array([example.pdf_page for example in examples], dtype=int)
    return x, y, groups, page_numbers


def feature_vector(feature: PageFeature) -> list[float]:
    """PRD objective feature만 숫자 벡터로 변환한다."""

    values = []
    for name in OBJECTIVE_FEATURE_NAMES:
        value = getattr(feature, name)
        if isinstance(value, bool):
            values.append(1.0 if value else 0.0)
        elif value is None:
            values.append(np.nan)
        else:
            values.append(float(value))
    return values


def build_regressor(model_type: ModelType, random_seed: int) -> Pipeline:
    """모델 이름에 맞는 sklearn regressor pipeline을 만든다."""

    if model_type == "decision-tree":
        model = DecisionTreeRegressor(
            max_depth=5,
            min_samples_leaf=2,
            random_state=random_seed,
        )
    elif model_type == "hist-gradient":
        model = HistGradientBoostingRegressor(
            max_iter=100,
            learning_rate=0.05,
            random_state=random_seed,
        )
    elif model_type == "random-forest":
        model = RandomForestRegressor(
            n_estimators=200,
            min_samples_leaf=2,
            random_state=random_seed,
            n_jobs=-1,
        )
    else:
        raise ValueError(f"지원하지 않는 모델이다: {model_type}")

    return Pipeline(
        [
            (
                "imputer",
                SimpleImputer(
                    strategy="constant",
                    fill_value=0.0,
                    keep_empty_features=True,
                ),
            ),
            ("model", model),
        ]
    )


def cross_validate_detector(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    page_numbers: np.ndarray,
    label_by_key: dict[str, TocTrainingLabel],
    model_type: ModelType,
    n_splits: int,
    random_seed: int,
) -> list[TocDetectorFoldResult]:
    """PDF 단위 GroupKFold로 TOC segment 예측 성능을 평가한다."""

    splitter = GroupKFold(n_splits=n_splits)
    fold_results: list[TocDetectorFoldResult] = []
    for fold, (train_index, test_index) in enumerate(
        splitter.split(x, y, groups),
        start=1,
    ):
        model = build_regressor(model_type, random_seed + fold)
        model.fit(x[train_index], y[train_index])
        predictions = np.clip(model.predict(x[test_index]), 0.0, 1.0)
        test_groups = groups[test_index]
        test_pages = page_numbers[test_index]
        pdf_results = evaluate_group_predictions(
            groups=test_groups,
            page_numbers=test_pages,
            predictions=predictions,
            label_by_key=label_by_key,
        )
        fold_results.append(
            TocDetectorFoldResult(
                fold=fold,
                train_pdf_count=len(set(groups[train_index].tolist())),
                test_pdf_count=len(set(test_groups.tolist())),
                train_row_count=int(len(train_index)),
                test_row_count=int(len(test_index)),
                mean_segment_iou=mean_optional(
                    [result["segment_iou"] for result in pdf_results]
                ),
                mean_abs_start_page_error=mean_optional(
                    [
                        abs(result["start_page_error"])
                        for result in pdf_results
                        if result["start_page_error"] is not None
                    ]
                ),
                mean_abs_end_page_error=mean_optional(
                    [
                        abs(result["end_page_error"])
                        for result in pdf_results
                        if result["end_page_error"] is not None
                    ]
                ),
                pdf_results=pdf_results,
            )
        )
    return fold_results


def evaluate_group_predictions(
    groups: np.ndarray,
    page_numbers: np.ndarray,
    predictions: np.ndarray,
    label_by_key: dict[str, TocTrainingLabel],
) -> list[dict[str, Any]]:
    """test fold 안의 PDF별 예측 page를 GT range와 비교한다."""

    scores_by_pdf: dict[str, dict[int, float]] = {}
    for group, page_number, prediction in zip(
        groups.tolist(),
        page_numbers.tolist(),
        predictions.tolist(),
        strict=True,
    ):
        scores_by_pdf.setdefault(str(group), {})[int(page_number)] = float(prediction)

    results: list[dict[str, Any]] = []
    for pdf_key, scores in sorted(scores_by_pdf.items()):
        label = label_by_key[pdf_key]
        predicted_pages = select_pages_from_scores(scores)
        comparison = compare_toc_pages(predicted_pages, label.toc_pages)
        results.append(
            {
                "input_pdf": pdf_key,
                "predicted_pages": predicted_pages,
                "expected_pages": label.toc_pages,
                "segment_iou": comparison.segment_iou,
                "start_page_error": comparison.start_page_error,
                "end_page_error": comparison.end_page_error,
            }
        )
    return results


def select_pages_from_scores(
    scores_by_page: dict[int, float],
    threshold: float = 0.5,
) -> list[int]:
    """score mass가 가장 큰 연속 segment를 선택한다."""

    if not scores_by_page:
        return []

    candidate_pages = sorted(
        page for page, score in scores_by_page.items() if score >= threshold
    )
    if not candidate_pages:
        best_page, best_score = max(scores_by_page.items(), key=lambda item: item[1])
        return [best_page] if best_score > 0 else []

    segments = pages_to_segments(candidate_pages)
    best_segment = max(
        segments,
        key=lambda segment: sum(
            scores_by_page.get(page, 0.0) for page in range(segment[0], segment[1] + 1)
        ),
    )
    return list(range(best_segment[0], best_segment[1] + 1))


def pages_to_segments(pages: list[int]) -> list[tuple[int, int]]:
    """page 목록을 연속 구간 목록으로 바꾼다."""

    if not pages:
        return []
    ordered = sorted(set(pages))
    segments: list[tuple[int, int]] = []
    start = ordered[0]
    previous = ordered[0]
    for page in ordered[1:]:
        if page == previous + 1:
            previous = page
            continue
        segments.append((start, previous))
        start = page
        previous = page
    segments.append((start, previous))
    return segments


def extract_feature_importance(model: Pipeline) -> list[dict[str, Any]]:
    """모델이 제공하는 feature importance를 정렬해 반환한다."""

    estimator = model.named_steps["model"]
    importances = getattr(estimator, "feature_importances_", None)
    if importances is None:
        return []
    rows = [
        {"feature": feature, "importance": float(importance)}
        for feature, importance in zip(
            OBJECTIVE_FEATURE_NAMES,
            importances.tolist(),
            strict=True,
        )
    ]
    return [
        {"rank": index, **row}
        for index, row in enumerate(
            sorted(rows, key=lambda item: item["importance"], reverse=True),
            start=1,
        )
    ]


def build_training_summary(
    labels: list[TocTrainingLabel],
    rejected_labels: list[RejectedTocTrainingLabel],
    fold_results: list[TocDetectorFoldResult],
    feature_importance: list[dict[str, Any]],
    model_type: ModelType,
    max_text_pages: int,
) -> dict[str, Any]:
    """report와 artifact에 저장할 학습 요약을 만든다."""

    return {
        "model_type": model_type,
        "target": "page_level_soft_label_regression",
        "label_policy": "manual_reviewed_only",
        "feature_names": OBJECTIVE_FEATURE_NAMES,
        "max_text_pages": max_text_pages,
        "accepted_label_count": len(labels),
        "rejected_label_count": len(rejected_labels),
        "rejected_labels": rejected_labels,
        "cross_validation": {
            "fold_count": len(fold_results),
            "mean_segment_iou": mean_optional(
                [fold.mean_segment_iou for fold in fold_results]
            ),
            "mean_abs_start_page_error": mean_optional(
                [fold.mean_abs_start_page_error for fold in fold_results]
            ),
            "mean_abs_end_page_error": mean_optional(
                [fold.mean_abs_end_page_error for fold in fold_results]
            ),
            "folds": fold_results,
        },
        "feature_importance": feature_importance,
    }


def mean_optional(values: list[float | None]) -> float | None:
    """None을 제외하고 평균을 계산한다."""

    valid = [float(value) for value in values if value is not None]
    if not valid:
        return None
    return float(sum(valid) / len(valid))


def resolve_dataset_root(raw: Any, labels_path: Path) -> Path | None:
    """label JSON의 root_dir을 기준 경로로 해석한다."""

    if not isinstance(raw, dict):
        return None
    root_dir = raw.get("root_dir")
    if root_dir is None:
        return None
    path = Path(str(root_dir))
    if path.is_absolute():
        return path
    return labels_path.parent / path


def resolve_pdf_path(
    row: dict[str, Any],
    labels_path: Path,
    dataset_root: Path | None,
) -> Path:
    """input_pdf 또는 root_relative_pdf에서 PDF path를 복원한다."""

    input_pdf = string_or_none(row.get("input_pdf"))
    if input_pdf:
        path = Path(input_pdf)
        return path if path.is_absolute() else labels_path.parent / path

    root_relative_pdf = string_or_none(row.get("root_relative_pdf"))
    if not root_relative_pdf:
        raise ValueError("input_pdf 또는 root_relative_pdf가 필요하다.")
    if dataset_root is None:
        raise ValueError("root_relative_pdf를 쓰려면 JSON root_dir이 필요하다.")
    return dataset_root / root_relative_pdf


def string_or_none(value: Any) -> str | None:
    """비어 있지 않은 문자열이면 반환한다."""

    if value is None:
        return None
    text = str(value)
    return text if text else None


def package_version() -> str | None:
    """설치된 package version을 반환한다."""

    try:
        return version("pdfbooktree")
    except PackageNotFoundError:
        return None
