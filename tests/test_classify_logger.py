from __future__ import annotations

from pathlib import Path

from pdfbooktree.classify.logger import ClassifyLogEvent, PlainTextClassifyLogger


class Cp949Stdout:
    encoding = "cp949"

    def __init__(self) -> None:
        self.text = ""

    def write(self, value: str) -> int:
        value.encode(self.encoding)
        self.text += value
        return len(value)

    def flush(self) -> None:
        return None


def test_plain_classify_logger_replaces_unencodable_path_text(monkeypatch) -> None:
    stdout = Cp949Stdout()
    monkeypatch.setattr("sys.stdout", stdout)
    logger = PlainTextClassifyLogger()

    logger.emit(
        ClassifyLogEvent(
            event="classified",
            level="info",
            input_pdf=Path("Decoding the Quant Market ò.pdf"),
            completed_count=1,
            total_count=1,
            target_count=0,
            error_count=0,
            elapsed_sec=0.0,
            message="",
        )
    )

    assert "?" in stdout.text
    assert "Decoding the Quant Market" in stdout.text
