"""clean wheel 설치 후 실제 PDF 처리와 package skill을 검증한다."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "showcase" / "outputs" / "031_wheel_install_smoke"
RESULT_PATH = OUTPUT_DIR / "result.json"
SMOKE_SCRIPT = ROOT / "scripts" / "smoke-test-wheel.ps1"
SAMPLE_PDF = (
    ROOT
    / "data"
    / "300STUDY"
    / "b_nonbooks"
    / "b_lecture"
    / "MIT OCW 18.06 Linear Algebra"
    / "18-06sc-fall-2011"
    / "18-06sc-fall-2011"
    / "contents"
    / "resource-index"
    / "problem-solving-eigenvalues-and-eigenvectors"
    / "mVeuZzJdd1w.pdf"
)


def main() -> None:
    """실제 wheel smoke script를 실행하고 showcase 결과를 기록한다."""

    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        raise RuntimeError("PowerShell 실행 파일을 찾지 못했다.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-File",
            str(SMOKE_SCRIPT),
            "-SamplePdf",
            str(SAMPLE_PDF),
            "-OutputRoot",
            "showcase/outputs/031_wheel_install_smoke/runs",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "wheel smoke 실패: "
            f"exit_code={completed.returncode}, stderr={completed.stderr[-2000:]}"
        )

    smoke_result = json.loads(completed.stdout)
    result = {
        "showcase_id": "031_wheel_install_smoke",
        "input_pdf": str(SAMPLE_PDF.relative_to(ROOT)),
        "input_pdf_size": SAMPLE_PDF.stat().st_size,
        "smoke_result": smoke_result,
        "build_log_tail": completed.stderr.splitlines()[-20:],
        "validation": {
            "clean_wheel_installed": smoke_result["status"] == "passed",
            "version_available": smoke_result["version"] == "pdfbooktree 0.1.0",
            "mit_license_packaged": (
                smoke_result["license_expression"] == "MIT"
                and "LICENSE" in smoke_result["license_files"]
            ),
            "real_pdf_processed": smoke_result["process_status"] == "processed",
            "markdown_manifest_created": Path(
                smoke_result["markdown_manifest"]
            ).is_file(),
            "package_skill_complete": (smoke_result["installed_skill_file_count"] == 5),
        },
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    result["validation_passed"] = all(result["validation"].values())
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
