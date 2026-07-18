"""OCR extra의 metadata, import, lazy failure 계약을 검증한다."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from unittest.mock import patch

from pdfbooktree import OptionalDependencyError
from pdfbooktree.optional_dependencies import require_ocr_dependencies


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "experiments" / "outputs" / "110_optional_ocr_dependency_contract"
OUTPUT_PATH = OUTPUT_DIR / "result.json"


pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
project = pyproject["project"]
core_dependencies = tuple(project["dependencies"])
ocr_dependencies = tuple(project["optional-dependencies"]["ocr"])

core_names = {item.split(">=", 1)[0] for item in core_dependencies}
ocr_names = {item.split(">=", 1)[0] for item in ocr_dependencies}

with patch("pdfbooktree.optional_dependencies.find_spec", return_value=None):
    try:
        require_ocr_dependencies()
    except OptionalDependencyError as error:
        lazy_error = {
            "type": type(error).__name__,
            "extra": error.extra,
            "missing_packages": list(error.missing_packages),
            "install_command": error.install_command,
        }
    else:
        raise AssertionError(
            "OCR dependency가 없는데 OptionalDependencyError가 없었다."
        )

validation = {
    "tqdm_is_core": "tqdm" in core_names,
    "ocr_packages_not_core": not {"httpx", "pikepdf", "python-dotenv"} & core_names,
    "ocr_extra_exact": ocr_names == {"httpx", "pikepdf", "python-dotenv"},
    "stable_error_type": lazy_error["type"] == "OptionalDependencyError",
    "stable_extra": lazy_error["extra"] == "ocr",
    "stable_install_command": lazy_error["install_command"]
    == 'python -m pip install "pdfbooktree[ocr]"',
}
result = {
    "core_dependencies": list(core_dependencies),
    "ocr_dependencies": list(ocr_dependencies),
    "lazy_error": lazy_error,
    "validation": validation,
    "validation_passed": all(validation.values()),
}

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(result, ensure_ascii=False))

if not result["validation_passed"]:
    raise SystemExit(1)
