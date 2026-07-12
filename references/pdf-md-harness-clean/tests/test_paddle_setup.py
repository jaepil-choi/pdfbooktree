import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ocr_pdf_to_markdown.py"
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("ocr_pdf_to_markdown", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PaddleSetupTests(unittest.TestCase):
    def args(self, venv: Path, *, no_auto_install: bool = False, python: Path | None = None):
        return SimpleNamespace(
            paddle_python=python,
            paddle_venv=venv,
            no_auto_install_paddle=no_auto_install,
        )

    def test_default_engine_is_paddle(self):
        with patch.object(sys, "argv", [str(SCRIPT), "book.pdf", "out.md"]):
            args = MODULE.parse_args()
        self.assertEqual(args.engine, "paddle")
        self.assertFalse(args.no_auto_install_paddle)

    def test_missing_paddle_creates_venv_and_installs_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            venv = Path(temp) / ".venv-paddle"
            expected_python = MODULE.paddle_python_for_venv(venv)
            run_result = SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch.object(MODULE, "paddle_available", side_effect=[False, False, True]),
                patch.object(MODULE, "install_paddle") as install,
                patch.object(MODULE, "bootstrap_python_command", return_value=["python3.11"]),
                patch.object(MODULE.subprocess, "run", return_value=run_result) as run,
            ):
                result = MODULE.ensure_paddle_python(self.args(venv))

            self.assertEqual(result, expected_python)
            install.assert_called_once_with(expected_python)
            command = run.call_args.args[0]
            self.assertEqual(command, ["python3.11", "-m", "venv", str(venv)])

    def test_explicit_python_installs_into_that_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            python = Path(temp) / "python"
            python.touch()
            with (
                patch.object(MODULE, "paddle_available", side_effect=[False, True]),
                patch.object(MODULE, "install_paddle") as install,
            ):
                result = MODULE.ensure_paddle_python(self.args(Path(temp) / "unused", python=python))

            self.assertEqual(result, python)
            install.assert_called_once_with(python)

    def test_no_auto_install_fails_with_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(MODULE, "paddle_available", return_value=False):
                with self.assertRaisesRegex(SystemExit, "no-auto-install-paddle"):
                    MODULE.ensure_paddle_python(
                        self.args(Path(temp) / ".venv-paddle", no_auto_install=True)
                    )

    def test_install_command_contains_both_required_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            python = Path(temp) / "python"
            with patch.object(MODULE.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
                MODULE.install_paddle(python)

            command = run.call_args.args[0]
            self.assertEqual(
                command,
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "paddleocr",
                    "paddlepaddle",
                ],
            )


if __name__ == "__main__":
    unittest.main()
