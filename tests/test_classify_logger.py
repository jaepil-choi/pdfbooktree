from __future__ import annotations

import json
from pathlib import Path

from pdfbooktree.classify.logger import (
    ClassifyLogEvent,
    JsonStderrClassifyLogger,
    PlainTextClassifyLogger,
)


class Cp949Stderr:
    encoding = "cp949"

    def __init__(self) -> None:
        self.text = ""

    def write(self, value: str) -> int:
        value.encode(self.encoding)
        self.text += value
        return len(value)

    def flush(self) -> None:
        return None


def _event(*, error_count: int = 0) -> ClassifyLogEvent:
    return ClassifyLogEvent(
        event="classified",
        level="info",
        input_pdf=Path("Decoding the Quant Market ò.pdf"),
        completed_count=1,
        total_count=1,
        target_count=0,
        error_count=error_count,
        elapsed_sec=0.0,
        message="분류 완료",
    )


def test_plain_classify_logger_replaces_unencodable_path_text(monkeypatch) -> None:
    stderr = Cp949Stderr()
    monkeypatch.setattr("sys.stderr", stderr)
    logger = PlainTextClassifyLogger()

    logger.emit(_event())

    assert "?" in stderr.text
    assert "Decoding the Quant Market" in stderr.text


def test_json_classify_logger_writes_versioned_event_to_stderr(capsys) -> None:
    logger = JsonStderrClassifyLogger()

    logger.emit(_event())

    captured = capsys.readouterr()
    assert captured.out == ""
    envelope = json.loads(captured.err)
    assert envelope["schema_version"] == 1
    assert envelope["command"] == "classify-scan"
    assert envelope["event"] == "classified"
    assert envelope["level"] == "info"
    assert envelope["message"] == "분류 완료"
    assert envelope["data"]["input_pdf"].endswith("Quant Market ò.pdf")
    assert envelope["data"]["completed_count"] == 1
