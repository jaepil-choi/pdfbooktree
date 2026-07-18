"""process CLI의 config precedence와 immutable run integration을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
from typer.testing import CliRunner

from pdfbooktree.cli import app
from pdfbooktree.config import CONFIG_SCHEMA_VERSION
from pdfbooktree.models import ProcessingResult


def make_pdf(path: Path) -> None:
    """run identity를 만들 수 있는 단일 page PDF를 생성한다."""

    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "Chapter 1")
        document.save(path)
    finally:
        document.close()


def install_fake_processor(monkeypatch, captured: dict[str, object]) -> None:
    """config/run 연결만 검증하도록 실제 typography 계산을 대체한다."""

    class FakeProcessor:
        def __init__(self, pdf, output_dir, config, log=None):
            captured["pdf"] = Path(pdf)
            captured["output_dir"] = Path(output_dir)
            captured["config"] = config

        def run(self):
            output_dir = captured["output_dir"]
            output_dir.mkdir(parents=True, exist_ok=True)
            artifact = output_dir / "bookmark_plan.json"
            artifact.write_text("[]", encoding="utf-8")
            report = output_dir / "book_report.json"
            report.write_text("{}", encoding="utf-8")
            output_pdf = output_dir / "book_bookmarked.pdf"
            output_pdf.write_bytes(b"%PDF-1.7\n")
            return ProcessingResult(
                status="processed",
                input_pdf=captured["pdf"],
                output_pdf=output_pdf,
                bookmark_count=0,
                artifact_paths={"bookmark_plan": artifact},
                report_path=report,
            )

    monkeypatch.setattr("pdfbooktree.cli.Processor", FakeProcessor)
    monkeypatch.setattr("pdfbooktree.workflows.Processor", FakeProcessor)


def test_process는_기본적으로_run_directory와_manifest를_만든다(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    install_fake_processor(monkeypatch, captured)
    pdf = tmp_path / "book.pdf"
    output_root = tmp_path / "runs"
    make_pdf(pdf)

    result = CliRunner().invoke(
        app,
        ["process", str(pdf), "--output-dir", str(output_root)],
    )

    assert result.exit_code == 0
    run_dir = captured["output_dir"]
    assert run_dir != output_root
    assert run_dir.parent.parent == output_root
    assert captured["config"].typography.heading_candidate_mode == "font"
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    resolved = json.loads(
        (run_dir / "config.resolved.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "succeeded"
    assert manifest["processing_status"] == "processed"
    assert manifest["config_hash"]
    assert resolved["typography"]["position_min_repeated_pages"] == 5
    assert "manifest_path" in result.stdout


def test_process_config_precedence는_set이_가장_높다(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    install_fake_processor(monkeypatch, captured)
    pdf = tmp_path / "book.pdf"
    config_path = tmp_path / "book.toml"
    make_pdf(pdf)
    config_path.write_text(
        "\n".join(
            [
                f"schema_version = {CONFIG_SCHEMA_VERSION}",
                "",
                "[typography]",
                "position_min_repeated_pages = 3",
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "process",
            str(pdf),
            "--output-dir",
            str(tmp_path / "runs"),
            "--config",
            str(config_path),
            "--position-min-repeated-pages",
            "5",
            "--set",
            "typography.position_min_repeated_pages=8",
        ],
    )

    assert result.exit_code == 0
    assert captured["config"].typography.position_min_repeated_pages == 8
    run_dir = captured["output_dir"]
    resolved = json.loads(
        (run_dir / "config.resolved.json").read_text(encoding="utf-8")
    )
    assert resolved["typography"]["position_min_repeated_pages"] == 8


def test_process_flat_output은_기존_output_dir를_그대로_사용한다(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    install_fake_processor(monkeypatch, captured)
    pdf = tmp_path / "book.pdf"
    output_dir = tmp_path / "flat"
    make_pdf(pdf)

    result = CliRunner().invoke(
        app,
        [
            "process",
            str(pdf),
            "--output-dir",
            str(output_dir),
            "--flat-output",
        ],
    )

    assert result.exit_code == 0
    assert captured["output_dir"] == output_dir
    assert not (output_dir / "run_manifest.json").exists()


def test_process_exception은_run_manifest를_failed로_남긴다(
    monkeypatch, tmp_path: Path
) -> None:
    class FailingProcessor:
        def __init__(self, pdf, output_dir, config, log=None):
            self.output_dir = Path(output_dir)

        def run(self):
            raise RuntimeError("pipeline failed")

    monkeypatch.setattr("pdfbooktree.workflows.Processor", FailingProcessor)
    pdf = tmp_path / "book.pdf"
    output_root = tmp_path / "runs"
    make_pdf(pdf)

    result = CliRunner().invoke(
        app,
        ["process", str(pdf), "--output-dir", str(output_root)],
    )

    assert result.exit_code == 1
    manifests = list(output_root.rglob("run_manifest.json"))
    assert len(manifests) == 1
    payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["error"] == {
        "type": "RuntimeError",
        "message": "pipeline failed",
    }
