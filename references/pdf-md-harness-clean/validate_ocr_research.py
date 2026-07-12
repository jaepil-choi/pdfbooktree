#!/usr/bin/env python3
"""Validate the OCR research artifact and its measured winner."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / ".omx/specs/autoresearch-ocr/result.json"
BENCHMARK = ROOT / "outputs/book-md-vision/ocr-benchmark/benchmark.json"


def main() -> int:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    scores = {
        engine: values["mean_anchor_score"]
        for engine, values in benchmark["summary"].items()
    }
    winner = max(scores, key=scores.get)
    checks = {
        "result_passed": result.get("passed") is True,
        "benchmark_completed": benchmark.get("status") == "completed",
        "winner_matches": benchmark.get("winner") == winner and result.get("winner") == winner,
        "implementation_present": all(
            (ROOT / path).exists() for path in result.get("implementation_artifacts", [])
        ),
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "checks": checks, "scores": scores, "winner": winner}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
