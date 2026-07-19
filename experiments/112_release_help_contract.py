"""80열 terminal에서 Rich help 축약과 plain help 후보 계약을 비교한다.

실행:
    uv run python experiments/112_release_help_contract.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rich.text import Text
from typer.testing import CliRunner

from pdfbooktree.cli import app


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "experiments" / "outputs" / "112_release_help_contract" / "result.json"
TERMINAL_WIDTH = 80
REQUIRED_OPTIONS = (
    "--heading-candidate-mode",
    "--body-font-text-coverage",
    "--position-fallback",
    "--position-fallback-tolerance",
    "--position-fallback-min-isolation-ratio",
)


def _plain(value: str) -> str:
    """ANSI style을 제거해 option 이름 자체만 비교한다."""

    return Text.from_ansi(value).plain


def _inspect_help(runner: CliRunner) -> dict[str, object]:
    """현재 app 설정으로 80열 process help를 조사한다."""

    result = runner.invoke(
        app,
        ["process", "--help"],
        terminal_width=TERMINAL_WIDTH,
    )
    plain = _plain(result.stdout)
    missing = [option for option in REQUIRED_OPTIONS if option not in plain]
    return {
        "exit_code": result.exit_code,
        "missing_options": missing,
        "ellipsis_present": "…" in plain,
        "all_required_options_visible": not missing,
    }


def main() -> None:
    """현재 Rich help와 Typer의 공식 plain help 후보를 같은 process에서 비교한다."""

    runner = CliRunner()
    original_markup_mode = app.rich_markup_mode
    try:
        app.rich_markup_mode = "rich"
        baseline = _inspect_help(runner)
        app.rich_markup_mode = None
        plain_candidate = _inspect_help(runner)
    finally:
        app.rich_markup_mode = original_markup_mode

    validation_passed = (
        bool(baseline["missing_options"])
        and bool(baseline["ellipsis_present"])
        and bool(plain_candidate["all_required_options_visible"])
        and not bool(plain_candidate["ellipsis_present"])
    )
    result = {
        "terminal_width": TERMINAL_WIDTH,
        "required_options": list(REQUIRED_OPTIONS),
        "baseline": baseline,
        "plain_candidate": plain_candidate,
        "validation_passed": validation_passed,
        "finding": (
            "Rich help는 80열에서 긴 option 이름을 축약하지만 "
            "Typer의 rich_markup_mode=None plain help는 전체 이름을 보존한다."
        ),
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not validation_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
