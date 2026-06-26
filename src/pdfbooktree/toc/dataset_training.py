"""생성된 TOC page dataset으로 classifier를 학습하고 평가한다."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier

from pdfbooktree.utils.jsonio import write_json


TocPageDatasetModelType = Literal[
    "decision-tree",
    "hist-gradient",
    "random-forest",
    "all",
]

TOC_PAGE_DATASET_FEATURE_NAMES = [
    "line_count",
    "word_count",
    "mean_line_length",
    "line_length_std",
    "line_final_number_count",
    "line_final_number_monotonicity",
    "line_final_number_gap_mean",
    "line_final_number_gap_median",
    "line_final_number_gap_max",
    "line_final_number_negative_gap_count",
    "toc_entry_pattern_count",
    "toc_entry_pattern_ratio",
    "chapter_or_part_line_count",
    "page_position",
    "toc_keyword_presence",
    "prev_page_available",
    "prev_line_count",
    "prev_word_count",
    "prev_mean_line_length",
    "prev_line_length_std",
    "prev_line_final_number_count",
    "prev_line_final_number_monotonicity",
    "prev_line_final_number_gap_mean",
    "prev_line_final_number_gap_median",
    "prev_line_final_number_gap_max",
    "prev_line_final_number_negative_gap_count",
    "prev_toc_entry_pattern_count",
    "prev_toc_entry_pattern_ratio",
    "prev_chapter_or_part_line_count",
    "prev_toc_keyword_presence",
    "total_pages",
]


@dataclass(frozen=True)
class TocPageDatasetModelReport:
    """단일 모델의 test split 평가 결과다."""

    model: str
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float | None
    average_precision: float | None
    confusion_matrix: dict[str, int | list[int]]
    classification_report: dict[str, Any]


@dataclass(frozen=True)
class TocPageDatasetTrainingResult:
    """dataset 기반 TOC page classifier 학습 결과다."""

    trained_model_path: Path
    report_path: Path
    dataset_path: Path
    row_count: int
    pdf_count: int
    train_row_count: int
    train_pdf_count: int
    test_row_count: int
    test_pdf_count: int
    positive_count: int
    negative_count: int
    best_model: str
    model_reports: list[TocPageDatasetModelReport]
    feature_importance: list[dict[str, Any]] = field(default_factory=list)


class TocPageDatasetTrainer:
    """생성된 dataset row를 train/test split으로 학습하고 평가한다."""

    def __init__(
        self,
        dataset_path: Path | str,
        output_dir: Path | str,
        model_type: TocPageDatasetModelType = "random-forest",
        test_size: float = 0.2,
        random_seed: int = 42,
    ) -> None:
        self.dataset_path = Path(dataset_path)
        self.output_dir = Path(output_dir)
        self.model_type = model_type
        self.test_size = test_size
        self.random_seed = random_seed

    def run(self) -> TocPageDatasetTrainingResult:
        """모델을 학습하고 best model artifact와 평가 report를 저장한다."""

        rows = load_toc_page_dataset_rows(self.dataset_path)
        validate_dataset_rows(rows)
        x, y, groups = make_dataset_matrix(rows)

        unique_groups = sorted(set(groups.tolist()))
        if len(unique_groups) < 2:
            raise ValueError("train/test 분할에는 최소 2개 PDF group이 필요하다.")

        splitter = GroupShuffleSplit(
            n_splits=1,
            test_size=self.test_size,
            random_state=self.random_seed,
        )
        train_index, test_index = next(splitter.split(x, y, groups))
        x_train, x_test = x[train_index], x[test_index]
        y_train, y_test = y[train_index], y[test_index]

        model_names = resolve_model_names(self.model_type)
        fitted_models: dict[str, Pipeline] = {}
        reports: list[TocPageDatasetModelReport] = []
        for model_name in model_names:
            model = build_classifier(model_name, self.random_seed)
            model.fit(x_train, y_train)
            fitted_models[model_name] = model
            reports.append(evaluate_classifier(model_name, model, x_test, y_test))

        best_report = max(
            reports,
            key=lambda report: (
                report.f1,
                report.roc_auc if report.roc_auc is not None else -1.0,
            ),
        )
        best_model = fitted_models[best_report.model]

        self.output_dir.mkdir(parents=True, exist_ok=True)
        model_path = self.output_dir / "toc_page_dataset_model.joblib"
        report_path = self.output_dir / "train_test_report.json"
        feature_importance = extract_feature_importance(best_model)
        result = TocPageDatasetTrainingResult(
            trained_model_path=model_path,
            report_path=report_path,
            dataset_path=self.dataset_path,
            row_count=len(rows),
            pdf_count=len(unique_groups),
            train_row_count=int(len(train_index)),
            train_pdf_count=len(set(groups[train_index].tolist())),
            test_row_count=int(len(test_index)),
            test_pdf_count=len(set(groups[test_index].tolist())),
            positive_count=int(y.sum()),
            negative_count=int(len(y) - y.sum()),
            best_model=best_report.model,
            model_reports=reports,
            feature_importance=feature_importance,
        )
        write_json(report_path, build_report_dict(rows, result))
        joblib.dump(
            {
                "model": best_model,
                "feature_names": TOC_PAGE_DATASET_FEATURE_NAMES,
                "training_summary": build_report_dict(rows, result),
            },
            model_path,
        )
        return result


def load_toc_page_dataset_rows(dataset_path: Path) -> list[dict[str, Any]]:
    """JSON 또는 CSV dataset row를 dict 목록으로 읽는다."""

    if dataset_path.suffix.lower() == ".csv":
        with dataset_path.open(encoding="utf-8", newline="") as file:
            return [dict(row) for row in csv.DictReader(file)]

    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    rows = (
        raw.get("dataset_rows", raw.get("rows", raw)) if isinstance(raw, dict) else raw
    )
    if not isinstance(rows, list):
        raise ValueError(
            "dataset은 row list이거나 dataset_rows 배열을 가진 객체여야 한다."
        )
    return [dict(row) for row in rows if isinstance(row, dict)]


def validate_dataset_rows(rows: list[dict[str, Any]]) -> None:
    """학습에 필요한 최소 field와 label 값을 검증한다."""

    if not rows:
        raise ValueError("학습할 dataset row가 없다.")
    missing = [
        name
        for name in ["input_pdf", "label", *TOC_PAGE_DATASET_FEATURE_NAMES]
        if any(name not in row for row in rows)
    ]
    if missing:
        raise ValueError(f"dataset row에 필요한 field가 없다: {sorted(set(missing))}")
    labels = {int(row["label"]) for row in rows}
    if labels != {0, 1}:
        raise ValueError("dataset label은 0과 1을 모두 포함해야 한다.")


def make_dataset_matrix(
    rows: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """dataset row를 sklearn 입력 행렬로 변환한다."""

    x = np.array(
        [
            [
                numeric_feature_value(row.get(name))
                for name in TOC_PAGE_DATASET_FEATURE_NAMES
            ]
            for row in rows
        ],
        dtype=float,
    )
    y = np.array([int(row["label"]) for row in rows], dtype=int)
    groups = np.array([str(row["input_pdf"]) for row in rows], dtype=object)
    return x, y, groups


def numeric_feature_value(value: Any) -> float:
    """JSON/CSV scalar 값을 숫자 feature 값으로 바꾼다."""

    if value is None or value == "":
        return np.nan
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return 1.0
        if normalized == "false":
            return 0.0
    return float(value)


def resolve_model_names(model_type: TocPageDatasetModelType) -> list[str]:
    """학습할 모델 이름 목록을 반환한다."""

    if model_type == "all":
        return ["decision-tree", "hist-gradient", "random-forest"]
    return [model_type]


def build_classifier(model_type: str, random_seed: int) -> Pipeline:
    """모델 이름에 맞는 classifier pipeline을 만든다."""

    if model_type == "decision-tree":
        model = DecisionTreeClassifier(
            max_depth=8,
            min_samples_leaf=3,
            class_weight="balanced",
            random_state=random_seed,
        )
    elif model_type == "hist-gradient":
        model = HistGradientBoostingClassifier(
            max_iter=200,
            learning_rate=0.05,
            random_state=random_seed,
        )
    elif model_type == "random-forest":
        model = RandomForestClassifier(
            n_estimators=500,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=random_seed,
            n_jobs=-1,
        )
    else:
        raise ValueError(f"지원하지 않는 model이다: {model_type}")

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


def evaluate_classifier(
    model_name: str,
    model: Pipeline,
    x_test: np.ndarray,
    y_test: np.ndarray,
) -> TocPageDatasetModelReport:
    """test split에서 classifier 성능을 계산한다."""

    probabilities = model.predict_proba(x_test)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)
    matrix = confusion_matrix(y_test, predictions, labels=[0, 1])
    tn, fp, fn, tp = matrix.ravel()
    return TocPageDatasetModelReport(
        model=model_name,
        accuracy=float(accuracy_score(y_test, predictions)),
        precision=float(precision_score(y_test, predictions, zero_division=0)),
        recall=float(recall_score(y_test, predictions, zero_division=0)),
        f1=float(f1_score(y_test, predictions, zero_division=0)),
        roc_auc=safe_roc_auc(y_test, probabilities),
        average_precision=safe_average_precision(y_test, probabilities),
        confusion_matrix={
            "labels": [0, 1],
            "tn": int(tn),
            "fp": int(fp),
            "fn": int(fn),
            "tp": int(tp),
        },
        classification_report=cast(
            dict[str, Any],
            classification_report(
                y_test,
                predictions,
                labels=[0, 1],
                output_dict=True,
                zero_division=0,
            ),
        ),
    )


def safe_roc_auc(y_true: np.ndarray, probabilities: np.ndarray) -> float | None:
    """test label이 한 class뿐이면 ROC AUC를 생략한다."""

    if len(set(y_true.tolist())) < 2:
        return None
    return float(roc_auc_score(y_true, probabilities))


def safe_average_precision(
    y_true: np.ndarray,
    probabilities: np.ndarray,
) -> float | None:
    """positive label이 없으면 average precision을 생략한다."""

    if int(y_true.sum()) == 0:
        return None
    return float(average_precision_score(y_true, probabilities))


def extract_feature_importance(model: Pipeline) -> list[dict[str, Any]]:
    """best model이 제공하는 feature importance를 반환한다."""

    estimator = model.named_steps["model"]
    importances = getattr(estimator, "feature_importances_", None)
    if importances is None:
        return []
    ordered = sorted(
        zip(TOC_PAGE_DATASET_FEATURE_NAMES, importances.tolist(), strict=True),
        key=lambda item: item[1],
        reverse=True,
    )
    return [
        {"rank": rank, "feature": feature, "importance": float(importance)}
        for rank, (feature, importance) in enumerate(ordered, start=1)
    ]


def build_report_dict(
    rows: list[dict[str, Any]],
    result: TocPageDatasetTrainingResult,
) -> dict[str, Any]:
    """저장용 train/test report를 만든다."""

    return {
        "dataset_path": result.dataset_path,
        "label_sources": sorted({str(row.get("label_source")) for row in rows}),
        "interpretation_warning": (
            "이 평가는 dataset의 pseudo label 재현 성능이다. "
            "bookmark_guided_toc_detection label은 독립 수동 검수 ground truth가 아니다. "
            "학습 feature에는 runtime에서 bookmark 없이 계산 가능한 값만 포함한다."
        ),
        "split_policy": "GroupShuffleSplit by input_pdf",
        "row_count": result.row_count,
        "pdf_count": result.pdf_count,
        "positive_count": result.positive_count,
        "negative_count": result.negative_count,
        "train": {
            "row_count": result.train_row_count,
            "pdf_count": result.train_pdf_count,
        },
        "test": {
            "row_count": result.test_row_count,
            "pdf_count": result.test_pdf_count,
        },
        "best_model": result.best_model,
        "model_reports": result.model_reports,
        "feature_names": TOC_PAGE_DATASET_FEATURE_NAMES,
        "feature_importance": result.feature_importance,
        "trained_model_path": result.trained_model_path,
        "report_path": result.report_path,
    }
