from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import matplotlib
import numpy as np
import shap
from sklearn.inspection import PartialDependenceDisplay, permutation_importance
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupShuffleSplit


matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


warnings.filterwarnings(
    "ignore",
    message="X does not have valid feature names.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message="LightGBM binary classifier with TreeExplainer shap values output has changed.*",
    category=UserWarning,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "006_tree_feature_attribution"
SOURCE_EXPERIMENT_ID = "005_tree_toc_page_classifier"
OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / EXPERIMENT_ID
SOURCE_OUTPUT_DIR = ROOT_DIR / "experiments" / "outputs" / SOURCE_EXPERIMENT_ID
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

FEATURE_SETS = {
    "structural_only": STRUCTURAL_FEATURES,
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


def load_dataset(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise ValueError(f"데이터셋이 비어 있습니다: {path}")
    return rows


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
        "group_leakage": bool(train_groups & test_groups),
    }
    return train_index, test_index, split_summary


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_builtin_importance(
    output_dir: Path,
    run_id: str,
    feature_names: list[str],
    importances: np.ndarray,
    max_display: int,
) -> list[dict[str, Any]]:
    rows = ranked_rows(feature_names, importances)
    csv_path = output_dir / "builtin_importance.csv"
    png_path = output_dir / "builtin_importance.png"
    write_csv(csv_path, ["rank", "feature", "importance"], rows)
    save_bar_plot(
        png_path,
        rows[:max_display],
        value_key="importance",
        title=f"{run_id} built-in feature importance",
        xlabel="importance",
    )
    return rows


def save_permutation_importance(
    output_dir: Path,
    run_id: str,
    pipeline: Any,
    x_test: np.ndarray,
    y_test: np.ndarray,
    feature_names: list[str],
    n_repeats: int,
    random_seed: int,
    max_display: int,
) -> list[dict[str, Any]]:
    baseline_pred = pipeline.predict(x_test)
    baseline_f1 = float(f1_score(y_test, baseline_pred, zero_division=0))
    result = permutation_importance(
        pipeline,
        x_test,
        y_test,
        scoring="f1",
        n_repeats=n_repeats,
        random_state=random_seed,
        n_jobs=-1,
    )
    rows = []
    for feature, mean, std in zip(
        feature_names,
        result.importances_mean.tolist(),
        result.importances_std.tolist(),
        strict=True,
    ):
        rows.append(
            {
                "feature": feature,
                "f1_drop_mean": float(mean),
                "f1_drop_std": float(std),
                "baseline_f1": baseline_f1,
            }
        )
    rows = sorted(rows, key=lambda row: row["f1_drop_mean"], reverse=True)
    ranked = [
        {
            "rank": index,
            **row,
        }
        for index, row in enumerate(rows, start=1)
    ]
    csv_path = output_dir / "permutation_importance.csv"
    png_path = output_dir / "permutation_importance.png"
    write_csv(
        csv_path,
        ["rank", "feature", "f1_drop_mean", "f1_drop_std", "baseline_f1"],
        ranked,
    )
    save_bar_plot(
        png_path,
        ranked[:max_display],
        value_key="f1_drop_mean",
        title=f"{run_id} permutation importance",
        xlabel="F1 drop after shuffle",
    )
    return ranked


def ranked_rows(feature_names: list[str], values: np.ndarray) -> list[dict[str, Any]]:
    pairs = sorted(
        zip(feature_names, values.tolist(), strict=True),
        key=lambda item: item[1],
        reverse=True,
    )
    return [
        {
            "rank": index,
            "feature": feature,
            "importance": float(value),
        }
        for index, (feature, value) in enumerate(pairs, start=1)
    ]


def save_bar_plot(
    path: Path,
    rows: list[dict[str, Any]],
    value_key: str,
    title: str,
    xlabel: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    features = [row["feature"] for row in rows][::-1]
    values = [row[value_key] for row in rows][::-1]
    height = max(4.5, 0.36 * len(rows) + 1.2)
    plt.figure(figsize=(9, height))
    plt.barh(features, values, color="#2f6f9f")
    plt.title(title)
    plt.xlabel(xlabel)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def take_sample(
    x: np.ndarray,
    y: np.ndarray,
    sample_size: int,
    random_seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    if len(x) <= sample_size:
        return x, y
    rng = np.random.default_rng(random_seed)
    positive_index = np.where(y == 1)[0]
    negative_index = np.where(y == 0)[0]
    positive_size = min(len(positive_index), sample_size // 2)
    negative_size = min(len(negative_index), sample_size - positive_size)
    selected = np.concatenate(
        [
            rng.choice(positive_index, size=positive_size, replace=False),
            rng.choice(negative_index, size=negative_size, replace=False),
        ]
    )
    rng.shuffle(selected)
    return x[selected], y[selected]


def positive_class_shap_values(shap_values: Any) -> np.ndarray:
    if isinstance(shap_values, list):
        return np.asarray(shap_values[1])
    values = np.asarray(shap_values)
    if values.ndim == 3:
        return values[:, :, 1]
    return values


def save_shap_plots(
    output_dir: Path,
    run_id: str,
    pipeline: Any,
    x_test: np.ndarray,
    y_test: np.ndarray,
    feature_names: list[str],
    sample_size: int,
    random_seed: int,
    max_display: int,
) -> dict[str, Any]:
    x_sample, _ = take_sample(x_test, y_test, sample_size, random_seed)
    x_imputed = pipeline.named_steps["imputer"].transform(x_sample)
    model = pipeline.named_steps["model"]
    explainer = shap.TreeExplainer(model)
    shap_values = positive_class_shap_values(explainer.shap_values(x_imputed))
    mean_abs = np.abs(shap_values).mean(axis=0)
    rows = ranked_rows(feature_names, mean_abs)
    write_csv(output_dir / "shap_mean_abs.csv", ["rank", "feature", "importance"], rows)

    plt.figure()
    shap.summary_plot(
        shap_values,
        x_imputed,
        feature_names=feature_names,
        plot_type="bar",
        max_display=max_display,
        show=False,
    )
    plt.title(f"{run_id} SHAP mean absolute contribution")
    plt.tight_layout()
    plt.savefig(output_dir / "shap_bar.png", dpi=160, bbox_inches="tight")
    plt.close()

    plt.figure()
    shap.summary_plot(
        shap_values,
        x_imputed,
        feature_names=feature_names,
        max_display=max_display,
        show=False,
    )
    plt.title(f"{run_id} SHAP beeswarm")
    plt.tight_layout()
    plt.savefig(output_dir / "shap_beeswarm.png", dpi=160, bbox_inches="tight")
    plt.close()

    dependence_paths = []
    for row in rows[: min(3, len(rows))]:
        feature = row["feature"]
        path = output_dir / f"shap_dependence_{slugify(feature)}.png"
        plt.figure()
        shap.dependence_plot(
            feature,
            shap_values,
            x_imputed,
            feature_names=feature_names,
            show=False,
        )
        plt.title(f"{run_id} SHAP dependence: {feature}")
        plt.tight_layout()
        plt.savefig(path, dpi=160, bbox_inches="tight")
        plt.close()
        dependence_paths.append(str(path.relative_to(ROOT_DIR)))

    return {
        "sample_row_count": int(len(x_imputed)),
        "mean_abs_rows": rows,
        "bar_plot": str((output_dir / "shap_bar.png").relative_to(ROOT_DIR)),
        "beeswarm_plot": str((output_dir / "shap_beeswarm.png").relative_to(ROOT_DIR)),
        "dependence_plots": dependence_paths,
    }


def save_pdp_ice_plots(
    output_dir: Path,
    run_id: str,
    pipeline: Any,
    x_test: np.ndarray,
    y_test: np.ndarray,
    feature_names: list[str],
    top_features: list[str],
    sample_size: int,
    random_seed: int,
) -> list[str]:
    x_sample, _ = take_sample(x_test, y_test, sample_size, random_seed)
    paths = []
    for feature in top_features:
        feature_index = feature_names.index(feature)
        path = output_dir / f"pdp_ice_{slugify(feature)}.png"
        fig, ax = plt.subplots(figsize=(7, 5))
        PartialDependenceDisplay.from_estimator(
            pipeline,
            x_sample,
            features=[feature_index],
            kind="both",
            subsample=min(sample_size, len(x_sample)),
            random_state=random_seed,
            grid_resolution=20,
            ax=ax,
            line_kw={"color": "#1f77b4", "alpha": 0.22, "linewidth": 0.9},
            pd_line_kw={"color": "#d62728", "linewidth": 2.2},
        )
        ax.set_title(f"{run_id} PDP/ICE: {feature}")
        ax.set_xlabel(feature)
        fig.tight_layout()
        fig.savefig(path, dpi=160, bbox_inches="tight")
        plt.close(fig)
        paths.append(str(path.relative_to(ROOT_DIR)))
    return paths


def analyze_run(
    run: dict[str, Any],
    rows: list[dict[str, str]],
    test_index: np.ndarray,
    args: argparse.Namespace,
) -> dict[str, Any]:
    run_id = run["run_id"]
    output_dir = OUTPUT_DIR / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    feature_names = FEATURE_SETS[run["feature_set"]]
    x, y, _ = make_matrix(rows, feature_names)
    x_test = x[test_index]
    y_test = y[test_index]
    pipeline = joblib.load(ROOT_DIR / run["model_path"])

    builtin_rows = save_builtin_importance(
        output_dir,
        run_id,
        feature_names,
        pipeline.named_steps["model"].feature_importances_,
        args.max_display,
    )
    permutation_rows = save_permutation_importance(
        output_dir,
        run_id,
        pipeline,
        x_test,
        y_test,
        feature_names,
        args.permutation_repeats,
        args.random_seed,
        args.max_display,
    )
    shap_summary = save_shap_plots(
        output_dir,
        run_id,
        pipeline,
        x_test,
        y_test,
        feature_names,
        args.shap_sample_size,
        args.random_seed,
        args.max_display,
    )
    pdp_features = [row["feature"] for row in shap_summary["mean_abs_rows"][:5]]
    pdp_paths = save_pdp_ice_plots(
        output_dir,
        run_id,
        pipeline,
        x_test,
        y_test,
        feature_names,
        pdp_features,
        args.ice_sample_size,
        args.random_seed,
    )

    summary = {
        "run_id": run_id,
        "model": run["model"],
        "feature_set": run["feature_set"],
        "source_metrics": run["metrics"],
        "builtin_top_features": builtin_rows[:8],
        "permutation_top_features": permutation_rows[:8],
        "shap_top_features": shap_summary["mean_abs_rows"][:8],
        "plots": {
            "builtin_importance": str((output_dir / "builtin_importance.png").relative_to(ROOT_DIR)),
            "permutation_importance": str((output_dir / "permutation_importance.png").relative_to(ROOT_DIR)),
            "shap_bar": shap_summary["bar_plot"],
            "shap_beeswarm": shap_summary["beeswarm_plot"],
            "shap_dependence": shap_summary["dependence_plots"],
            "pdp_ice": pdp_paths,
        },
        "tables": {
            "builtin_importance": str((output_dir / "builtin_importance.csv").relative_to(ROOT_DIR)),
            "permutation_importance": str((output_dir / "permutation_importance.csv").relative_to(ROOT_DIR)),
            "shap_mean_abs": str((output_dir / "shap_mean_abs.csv").relative_to(ROOT_DIR)),
        },
        "shap_sample_row_count": shap_summary["sample_row_count"],
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def load_source_summary() -> dict[str, Any]:
    path = SOURCE_OUTPUT_DIR / "summary.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def build_finding(summary: dict[str, Any]) -> str:
    parts = [
        (
            f"{SOURCE_EXPERIMENT_ID}의 학습 모델 {len(summary['runs'])}개를 로드해 "
            "내장 importance, permutation importance, SHAP, PDP/ICE를 생성했다."
        )
    ]
    for run in summary["runs"]:
        builtin = run["builtin_top_features"][0]["feature"]
        permutation = run["permutation_top_features"][0]["feature"]
        shap_top = run["shap_top_features"][0]["feature"]
        parts.append(
            f"{run['run_id']}의 1위 feature는 내장 {builtin}, "
            f"permutation {permutation}, SHAP {shap_top}이다."
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
                "005 실험에서 page 위치 feature를 제외하고 학습한 Random Forest와 "
                "LightGBM 모델의 구조 feature 효과를 내장 importance, permutation "
                "importance, SHAP, PDP/ICE 시각화로 비교한다."
            ),
            "inputs": [
                str(DEFAULT_DATASET_CSV.relative_to(ROOT_DIR)),
                str((SOURCE_OUTPUT_DIR / "summary.json").relative_to(ROOT_DIR)),
            ],
            "outputs": str(OUTPUT_DIR.relative_to(ROOT_DIR)),
            "source_experiment": SOURCE_EXPERIMENT_ID,
            "finding": build_finding(summary),
            "ran_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    registry["experiments"] = experiments
    write_json(EXPERIMENTS_JSON, registry)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="학습된 tree classifier의 feature 기여도를 시각화하는 실험이다.",
    )
    parser.add_argument(
        "--dataset-csv",
        type=Path,
        default=DEFAULT_DATASET_CSV,
        help="005 실험과 같은 split을 복원할 dataset CSV 경로다.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="005 실험과 같은 PDF group holdout test 비율이다.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="split, permutation, sampling에 쓸 random seed다.",
    )
    parser.add_argument(
        "--permutation-repeats",
        type=int,
        default=20,
        help="permutation importance 반복 횟수다.",
    )
    parser.add_argument(
        "--shap-sample-size",
        type=int,
        default=300,
        help="SHAP 계산에 사용할 test row 표본 수다.",
    )
    parser.add_argument(
        "--ice-sample-size",
        type=int,
        default=120,
        help="ICE plot에 사용할 test row 표본 수다.",
    )
    parser.add_argument(
        "--max-display",
        type=int,
        default=15,
        help="bar/beeswarm plot에 표시할 최대 feature 수다.",
    )
    parser.add_argument(
        "--run-id",
        default="all",
        help="특정 run_id만 분석하려면 지정한다. 기본값은 all이다.",
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

    rows = load_dataset(dataset_csv)
    _, test_index, split_summary = split_group_holdout(
        rows,
        test_size=args.test_size,
        random_seed=args.random_seed,
    )
    source_summary = load_source_summary()
    source_runs = [
        run
        for run in source_summary["runs"]
        if args.run_id == "all" or run["run_id"] == args.run_id
    ]
    if not source_runs:
        raise ValueError(f"분석할 run_id가 없습니다: {args.run_id}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_summaries = [
        analyze_run(
            run=run,
            rows=rows,
            test_index=test_index,
            args=args,
        )
        for run in source_runs
    ]
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "source_experiment": SOURCE_EXPERIMENT_ID,
        "dataset_csv": str(dataset_csv.relative_to(ROOT_DIR)),
        "split": split_summary,
        "runs": run_summaries,
    }
    write_json(OUTPUT_DIR / "summary.json", summary)
    update_experiment_registry(summary)
    if not args.quiet:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
