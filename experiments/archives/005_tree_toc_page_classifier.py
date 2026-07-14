from __future__ import annotations

import argparse
import csv
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline


warnings.filterwarnings(
    "ignore",
    message="X does not have valid feature names.*",
    category=UserWarning,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "005_tree_toc_page_classifier"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
EXPERIMENTS_JSON = ROOT_DIR / "experiments" / "experiments.json"
DEFAULT_DATASET_CSV = ROOT_DIR / "showcase" / "outputs" / "300study_toc_dataset.csv"

STRUCTURAL_FEATURES = [
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
    "toc_keyword_presence",
]

PREVIOUS_PAGE_FEATURES = [
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
]

FEATURE_SETS = {
    "structural_only": STRUCTURAL_FEATURES,
    "structural_with_prev_page": STRUCTURAL_FEATURES + PREVIOUS_PAGE_FEATURES,
}


def parse_bool(value: str) -> float:
    if value.lower() == "true":
        return 1.0
    if value.lower() == "false":
        return 0.0
    return np.nan


def parse_float(value: str) -> float:
    if value == "":
        return np.nan
    try:
        return float(value)
    except ValueError:
        return parse_bool(value)


def load_dataset(path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    if not rows:
        raise ValueError(f"데이터셋이 비어 있습니다: {path}")

    pdfs = sorted({row["root_relative_pdf"] for row in rows})
    positives = sum(int(row["label"]) for row in rows)
    summary = {
        "dataset_csv": str(path.relative_to(ROOT_DIR)),
        "row_count": len(rows),
        "pdf_count": len(pdfs),
        "positive_count": positives,
        "negative_count": len(rows) - positives,
    }
    return rows, summary


def validate_feature_columns(
    rows: list[dict[str, str]],
    feature_sets: dict[str, list[str]],
) -> None:
    """실험에 필요한 feature column이 dataset에 모두 있는지 확인한다."""

    available_columns = set(rows[0])
    missing_by_feature_set = {
        feature_set: [
            feature for feature in feature_names if feature not in available_columns
        ]
        for feature_set, feature_names in feature_sets.items()
    }
    missing_by_feature_set = {
        feature_set: missing_features
        for feature_set, missing_features in missing_by_feature_set.items()
        if missing_features
    }
    if not missing_by_feature_set:
        return

    details = "; ".join(
        f"{feature_set}: {', '.join(missing_features)}"
        for feature_set, missing_features in missing_by_feature_set.items()
    )
    raise ValueError(
        "dataset CSV에 실험 feature column이 없습니다. "
        "t-1 feature 추가 이후 생성된 dataset이 필요합니다. "
        "먼저 `uv run pdfbooktree detect-bookmark-toc ... --dataset-csv "
        "showcase/outputs/300study_toc_dataset.csv`를 다시 실행하세요. "
        f"missing columns: {details}"
    )


def make_matrix(
    rows: list[dict[str, str]],
    feature_names: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.array(
        [[parse_float(row.get(feature_name, "")) for feature_name in feature_names] for row in rows],
        dtype=float,
    )
    y = np.array([int(row["label"]) for row in rows], dtype=int)
    groups = np.array([row["root_relative_pdf"] for row in rows], dtype=object)
    return x, y, groups


def split_group_holdout(
    rows: list[dict[str, str]],
    test_size: float,
    random_seed: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    _, y, groups = make_matrix(rows, STRUCTURAL_FEATURES)
    splitter = GroupShuffleSplit(
        n_splits=1,
        test_size=test_size,
        random_state=random_seed,
    )
    train_index, test_index = next(splitter.split(np.zeros(len(rows)), y, groups))

    train_groups = set(groups[train_index])
    test_groups = set(groups[test_index])
    if train_groups & test_groups:
        raise AssertionError("PDF group이 train/test에 동시에 들어갔습니다.")

    split_summary = {
        "test_size": test_size,
        "random_seed": random_seed,
        "train_row_count": int(len(train_index)),
        "test_row_count": int(len(test_index)),
        "train_pdf_count": len(train_groups),
        "test_pdf_count": len(test_groups),
        "train_positive_count": int(y[train_index].sum()),
        "test_positive_count": int(y[test_index].sum()),
        "train_negative_count": int(len(train_index) - y[train_index].sum()),
        "test_negative_count": int(len(test_index) - y[test_index].sum()),
    }
    return train_index, test_index, split_summary


def build_models(random_seed: int) -> dict[str, Pipeline]:
    return {
        "random_forest": Pipeline(
            [
                (
                    "imputer",
                    SimpleImputer(
                        strategy="constant",
                        fill_value=0.0,
                        keep_empty_features=True,
                    ),
                ),
                (
                    "model",
                    RandomForestClassifier(
                        n_estimators=500,
                        min_samples_leaf=3,
                        class_weight="balanced",
                        random_state=random_seed,
                        n_jobs=-1,
                    ),
                ),
            ],
        ),
        "lightgbm": Pipeline(
            [
                (
                    "imputer",
                    SimpleImputer(
                        strategy="constant",
                        fill_value=0.0,
                        keep_empty_features=True,
                    ),
                ),
                (
                    "model",
                    LGBMClassifier(
                        objective="binary",
                        n_estimators=300,
                        learning_rate=0.05,
                        num_leaves=15,
                        min_child_samples=20,
                        subsample=0.9,
                        colsample_bytree=0.9,
                        random_state=random_seed,
                        n_jobs=-1,
                        verbosity=-1,
                    ),
                ),
            ],
        ),
    }


def evaluate_predictions(y_true: np.ndarray, y_prob: np.ndarray) -> dict[str, Any]:
    y_pred = (y_prob >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "average_precision": float(average_precision_score(y_true, y_prob)),
        "confusion_matrix": {
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "true_positive": int(tp),
        },
    }
    if len(set(y_true.tolist())) == 2:
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_prob))
    else:
        metrics["roc_auc"] = None
    return metrics


def write_predictions(
    path: Path,
    rows: list[dict[str, str]],
    test_index: np.ndarray,
    y_prob: np.ndarray,
) -> None:
    fieldnames = [
        "root_relative_pdf",
        "pdf_page",
        "label",
        "predicted_probability",
        "predicted_label",
        "sample_role",
    ]
    output_rows = []
    for source_index, probability in zip(test_index.tolist(), y_prob.tolist(), strict=True):
        row = rows[source_index]
        output_rows.append(
            {
                "root_relative_pdf": row["root_relative_pdf"],
                "pdf_page": row["pdf_page"],
                "label": row["label"],
                "predicted_probability": f"{probability:.8f}",
                "predicted_label": int(probability >= 0.5),
                "sample_role": row["sample_role"],
            }
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)


def write_feature_importance(
    path: Path,
    feature_names: list[str],
    importances: np.ndarray,
) -> list[dict[str, Any]]:
    rows = [
        {
            "rank": rank,
            "feature": feature,
            "importance": float(importance),
        }
        for rank, (feature, importance) in enumerate(
            sorted(
                zip(feature_names, importances.tolist(), strict=True),
                key=lambda item: item[1],
                reverse=True,
            ),
            start=1,
        )
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["rank", "feature", "importance"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def train_and_evaluate(
    rows: list[dict[str, str]],
    train_index: np.ndarray,
    test_index: np.ndarray,
    random_seed: int,
) -> list[dict[str, Any]]:
    results = []
    for feature_set_name, feature_names in FEATURE_SETS.items():
        x, y, _ = make_matrix(rows, feature_names)
        for model_name, pipeline in build_models(random_seed).items():
            run_id = f"{model_name}_{feature_set_name}"
            pipeline.fit(x[train_index], y[train_index])
            y_prob = pipeline.predict_proba(x[test_index])[:, 1]
            metrics = evaluate_predictions(y[test_index], y_prob)

            model_path = OUTPUT_DIR / "models" / f"{run_id}.joblib"
            predictions_path = OUTPUT_DIR / "predictions" / f"{run_id}.csv"
            importance_path = OUTPUT_DIR / "feature_importance" / f"{run_id}.csv"

            model_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(pipeline, model_path)
            write_predictions(predictions_path, rows, test_index, y_prob)
            importance_rows = write_feature_importance(
                importance_path,
                feature_names,
                pipeline.named_steps["model"].feature_importances_,
            )

            results.append(
                {
                    "run_id": run_id,
                    "model": model_name,
                    "feature_set": feature_set_name,
                    "feature_names": feature_names,
                    "metrics": metrics,
                    "top_features": importance_rows[:8],
                    "model_path": str(model_path.relative_to(ROOT_DIR)),
                    "predictions_path": str(predictions_path.relative_to(ROOT_DIR)),
                    "feature_importance_path": str(importance_path.relative_to(ROOT_DIR)),
                }
            )
    return results


def build_finding(summary: dict[str, Any]) -> str:
    runs = sorted(
        summary["runs"],
        key=lambda run: run["metrics"]["f1"],
        reverse=True,
    )
    best = runs[0]
    parts = [
        (
            f"{summary['dataset']['row_count']}개 page row와 "
            f"{summary['dataset']['pdf_count']}개 PDF를 "
            "PDF 단위 group holdout으로 train/test split했다."
        ),
        (
            f"best run은 {best['run_id']}이며 "
            f"F1 {best['metrics']['f1']:.3f}, "
            f"precision {best['metrics']['precision']:.3f}, "
            f"recall {best['metrics']['recall']:.3f}, "
            f"ROC-AUC {best['metrics']['roc_auc']:.3f}이다."
        ),
    ]
    for run in runs:
        top_features = ", ".join(item["feature"] for item in run["top_features"][:3])
        parts.append(
            f"{run['run_id']}는 F1 {run['metrics']['f1']:.3f}이고 "
            f"상위 feature는 {top_features}이다."
        )
    return " ".join(parts)


def load_experiment_registry() -> dict[str, Any]:
    if not EXPERIMENTS_JSON.exists():
        return {"experiments": []}
    return json.loads(EXPERIMENTS_JSON.read_text(encoding="utf-8"))


def update_experiment_registry(summary: dict[str, Any]) -> None:
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
                "bookmark-guided TOC dataset을 PDF 단위 train/test split으로 나누고, "
                "page 위치 feature를 제외한 현재 page 구조 feature와 직전 page "
                "구조 feature로 Random Forest와 LightGBM tree classifier가 "
                "page-level TOC 여부를 얼마나 잘 분류하는지 비교한다."
            ),
            "inputs": [summary["dataset"]["dataset_csv"]],
            "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
            "models": sorted({run["model"] for run in summary["runs"]}),
            "finding": build_finding(summary),
            "ran_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    registry["experiments"] = experiments
    write_json(EXPERIMENTS_JSON, registry)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="TOC page dataset으로 RF/LGBM tree classifier를 비교하는 실험이다.",
    )
    parser.add_argument(
        "--dataset-csv",
        type=Path,
        default=DEFAULT_DATASET_CSV,
        help="학습에 사용할 TOC page dataset CSV 경로다.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="PDF group holdout test 비율이다.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="split과 model 학습에 쓸 random seed다.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="결과 파일만 쓰고 콘솔 JSON 출력은 생략한다.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    dataset_csv = args.dataset_csv
    if not dataset_csv.is_absolute():
        dataset_csv = ROOT_DIR / dataset_csv

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, dataset_summary = load_dataset(dataset_csv)
    validate_feature_columns(rows, FEATURE_SETS)
    train_index, test_index, split_summary = split_group_holdout(
        rows=rows,
        test_size=args.test_size,
        random_seed=args.random_seed,
    )
    runs = train_and_evaluate(
        rows=rows,
        train_index=train_index,
        test_index=test_index,
        random_seed=args.random_seed,
    )
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "dataset": dataset_summary,
        "split": split_summary,
        "runs": runs,
    }

    write_json(OUTPUT_DIR / "summary.json", summary)
    update_experiment_registry(summary)
    if not args.quiet:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
