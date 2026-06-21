from __future__ import annotations

import json
from pathlib import Path

import fitz
from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.pdf.text import extract_page_texts
from pdfbooktree.toc.features import calculate_page_features
from pdfbooktree.toc.training import (
    TocDetectorModel,
    TocDetectorTrainer,
    load_training_labels,
    segment_iou_target,
    soft_label_for_page,
)


def write_pdf(path: Path, page_texts: list[str]) -> None:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def write_training_labels(path: Path, pdf_paths: list[Path]) -> None:
    rows = [
        {
            "input_pdf": str(pdf_paths[0]),
            "toc_start_page": 2,
            "toc_end_page": 3,
            "review_status": "manual_reviewed",
        },
        {
            "input_pdf": str(pdf_paths[1]),
            "toc_start_page": 2,
            "toc_end_page": 2,
            "review_status": "manual_reviewed",
        },
        {
            "input_pdf": str(pdf_paths[0]),
            "toc_start_page": 2,
            "toc_end_page": 3,
            "review_status": "unreviewed",
        },
    ]
    path.write_text(
        json.dumps({"labels": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def make_pdf_pair(tmp_path: Path) -> list[Path]:
    first_pdf = tmp_path / "first.pdf"
    second_pdf = tmp_path / "second.pdf"
    write_pdf(
        first_pdf,
        [
            "Preface",
            "Contents\nChapter 1 Introduction ........ 3\n1.1 Motivation ........ 7",
            "1.2 Background ........ 12\nChapter 2 Probability ........ 25",
            "Chapter 1 Introduction\nBody",
            "1.1 Motivation\nBody",
        ],
    )
    write_pdf(
        second_pdf,
        [
            "Cover",
            "Table of Contents\nChapter 1 Start ........ 5\nChapter 2 End ........ 20",
            "Chapter 1 Start\nBody",
            "Chapter 2 End\nBody",
            "Appendix",
        ],
    )
    return [first_pdf, second_pdf]


def test_load_training_labels_accepts_only_manual_reviewed(tmp_path: Path) -> None:
    pdf_paths = make_pdf_pair(tmp_path)
    labels_path = tmp_path / "labels.json"
    write_training_labels(labels_path, pdf_paths)

    labels, rejected = load_training_labels(labels_path)

    assert len(labels) == 2
    assert len(rejected) == 1
    assert rejected[0].review_status == "unreviewed"
    assert rejected[0].reason == "review_status가 manual_reviewed가 아니다."


def test_soft_label_and_segment_iou_targets_follow_prd() -> None:
    assert [soft_label_for_page(page, 5, 7) for page in range(3, 10)] == [
        0.2,
        0.5,
        1.0,
        1.0,
        1.0,
        0.5,
        0.2,
    ]
    assert segment_iou_target(5, 6, 5, 7) == 2 / 3


def test_toc_detector_trainer_writes_artifact_and_report(tmp_path: Path) -> None:
    pdf_paths = make_pdf_pair(tmp_path)
    labels_path = tmp_path / "labels.json"
    output_dir = tmp_path / "model"
    write_training_labels(labels_path, pdf_paths)

    result = TocDetectorTrainer(
        labels_path=labels_path,
        output_dir=output_dir,
        model_type="decision-tree",
        max_text_pages=5,
        n_splits=2,
    ).run()

    assert result.accepted_label_count == 2
    assert result.rejected_label_count == 1
    assert result.trained_model_path.exists()
    assert result.report_path.exists()
    assert len(result.fold_results) == 2
    assert all(fold.train_pdf_count == 1 for fold in result.fold_results)
    assert all(fold.test_pdf_count == 1 for fold in result.fold_results)
    assert result.mean_segment_iou is not None

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["label_policy"] == "manual_reviewed_only"
    assert report["target"] == "page_level_soft_label_regression"
    assert report["feature_names"] == [
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

    detector = TocDetectorModel.load(result.trained_model_path)
    pages = extract_page_texts(pdf_paths[0], max_pages=5)
    features = calculate_page_features(pages, total_pages=5)
    prediction = detector.predict(features)
    assert prediction.method == "ml_page_soft_label_regression"
    assert prediction.candidates


def test_toc_detector_trainer_rejects_pseudo_labels(tmp_path: Path) -> None:
    pdf_path = make_pdf_pair(tmp_path)[0]
    labels_path = tmp_path / "pseudo_labels.json"
    labels_path.write_text(
        json.dumps(
            {
                "labels": [
                    {
                        "input_pdf": str(pdf_path),
                        "toc_start_page": 2,
                        "toc_end_page": 3,
                        "label_source": "bookmark_guided_toc_start_pseudo_label",
                        "review_status": "unreviewed",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    try:
        TocDetectorTrainer(
            labels_path=labels_path,
            output_dir=tmp_path / "model",
            model_type="decision-tree",
            max_text_pages=5,
            n_splits=2,
        ).run()
    except ValueError as error:
        assert "manual_reviewed label이 없다" in str(error)
        assert "총 1개 label이 제외" in str(error)
    else:
        raise AssertionError("unreviewed pseudo label은 학습에 쓰면 안 된다.")


def test_train_toc_detector_cli_writes_outputs(tmp_path: Path) -> None:
    pdf_paths = make_pdf_pair(tmp_path)
    labels_path = tmp_path / "labels.json"
    output_dir = tmp_path / "cli_model"
    write_training_labels(labels_path, pdf_paths)

    result = CliRunner().invoke(
        app,
        [
            "train-toc-detector",
            str(labels_path),
            "--output-dir",
            str(output_dir),
            "--model",
            "decision-tree",
            "--max-text-pages",
            "5",
            "--n-splits",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert (output_dir / "toc_detector_model.joblib").exists()
    assert (output_dir / "training_report.json").exists()
