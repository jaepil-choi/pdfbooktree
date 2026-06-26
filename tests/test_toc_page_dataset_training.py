from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.toc.dataset_training import (
    TOC_PAGE_DATASET_FEATURE_NAMES,
    TocPageDatasetTrainer,
    load_toc_page_dataset_rows,
)


def make_dataset_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for pdf_index in range(1, 5):
        pdf_path = f"C:/books/book_{pdf_index}.pdf"
        rows.append(make_row(pdf_path, pdf_page=2, label=1, toc_like=True))
        rows.append(make_row(pdf_path, pdf_page=40, label=0, toc_like=False))
    return rows


def make_row(
    input_pdf: str,
    pdf_page: int,
    label: int,
    toc_like: bool,
) -> dict[str, object]:
    line_final_number_count = 6 if toc_like else 0
    row: dict[str, object] = {
        "input_pdf": input_pdf,
        "root_relative_pdf": Path(input_pdf).name,
        "pdf_page": pdf_page,
        "label": label,
        "sample_role": "positive" if label == 1 else "negative",
        "label_source": "bookmark_guided_toc_detection",
        "total_pages": 100,
        "bookmark_count": 10,
        "detection_confidence": 0.8,
        "line_count": 8 if toc_like else 3,
        "word_count": 40 if toc_like else 120,
        "mean_line_length": 18.0 if toc_like else 62.0,
        "line_length_std": 3.0 if toc_like else 20.0,
        "line_final_number_count": line_final_number_count,
        "line_final_numbers": [3, 8, 15, 20, 31, 40] if toc_like else [],
        "line_final_number_monotonicity": 1.0 if toc_like else None,
        "line_final_number_gap_mean": 7.4 if toc_like else None,
        "line_final_number_gap_median": 7.0 if toc_like else None,
        "line_final_number_gap_max": 11 if toc_like else None,
        "line_final_number_negative_gap_count": 0,
        "toc_entry_pattern_count": 5 if toc_like else 0,
        "toc_entry_pattern_ratio": 0.6 if toc_like else 0.0,
        "chapter_or_part_line_count": 2 if toc_like else 0,
        "page_position": pdf_page / 100,
        "toc_keyword_presence": toc_like,
        "prev_page_available": True,
        "prev_line_count": 1,
        "prev_word_count": 2,
        "prev_mean_line_length": 8.0,
        "prev_line_length_std": 0.0,
        "prev_line_final_number_count": 0,
        "prev_line_final_number_monotonicity": None,
        "prev_line_final_number_gap_mean": None,
        "prev_line_final_number_gap_median": None,
        "prev_line_final_number_gap_max": None,
        "prev_line_final_number_negative_gap_count": 0,
        "prev_toc_entry_pattern_count": 0,
        "prev_toc_entry_pattern_ratio": 0.0,
        "prev_chapter_or_part_line_count": 0,
        "prev_toc_keyword_presence": False,
    }
    return row


def test_toc_page_dataset_trainer_writes_model_and_report(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.json"
    output_dir = tmp_path / "model"
    dataset_path.write_text(
        json.dumps(make_dataset_rows(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = TocPageDatasetTrainer(
        dataset_path=dataset_path,
        output_dir=output_dir,
        model_type="decision-tree",
        test_size=0.25,
    ).run()

    assert result.row_count == 8
    assert result.pdf_count == 4
    assert result.train_pdf_count == 3
    assert result.test_pdf_count == 1
    assert result.trained_model_path.exists()
    assert result.report_path.exists()
    assert result.best_model == "decision-tree"

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["split_policy"] == "GroupShuffleSplit by input_pdf"
    assert report["label_sources"] == ["bookmark_guided_toc_detection"]
    assert report["feature_names"] == TOC_PAGE_DATASET_FEATURE_NAMES
    assert "bookmark_count" not in report["feature_names"]
    assert "detection_confidence" not in report["feature_names"]
    assert report["model_reports"][0]["f1"] >= 0.0


def test_load_toc_page_dataset_rows_accepts_detection_result_object(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "detection.json"
    rows = make_dataset_rows()
    dataset_path.write_text(
        json.dumps({"dataset_rows": rows}, ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = load_toc_page_dataset_rows(dataset_path)

    assert len(loaded) == len(rows)
    assert loaded[0]["label_source"] == "bookmark_guided_toc_detection"


def test_load_toc_page_dataset_rows_accepts_csv(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.csv"
    rows = make_dataset_rows()
    with dataset_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    loaded = load_toc_page_dataset_rows(dataset_path)

    assert len(loaded) == len(rows)
    assert loaded[0]["input_pdf"] == "C:/books/book_1.pdf"


def test_train_toc_page_dataset_cli_writes_outputs(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.json"
    output_dir = tmp_path / "cli_model"
    dataset_path.write_text(
        json.dumps(make_dataset_rows(), ensure_ascii=False),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "train-toc-page-dataset",
            str(dataset_path),
            "--output-dir",
            str(output_dir),
            "--model",
            "decision-tree",
            "--test-size",
            "0.25",
        ],
    )

    assert result.exit_code == 0
    assert (output_dir / "toc_page_dataset_model.joblib").exists()
    assert (output_dir / "train_test_report.json").exists()
