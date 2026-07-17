"""동작하지 않는 OCR policy를 설정 단계에서 거부하는 계약을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pdfbooktree.config import ConfigError, ProcessingConfig
from pdfbooktree.config_io import (
    config_schema,
    processing_config_from_data,
    processing_config_to_data,
    resolve_processing_config,
)


EXPERIMENT_ID = "107_ocr_policy_supported_contract"
OUTPUT_DIR = Path("experiments/outputs") / EXPERIMENT_ID
RESULT_PATH = OUTPUT_DIR / "result.json"
POLICIES = ("never", "auto", "always", "sometimes")


def observe_current_contract(policy: str) -> dict[str, Any]:
    """현재 direct/data/--set 경로가 policy를 받는지 기록한다."""

    observations: dict[str, Any] = {}

    try:
        ProcessingConfig(ocr_policy=policy)  # type: ignore[arg-type]
    except ConfigError as error:
        observations["direct"] = {"accepted": False, "error": str(error)}
    else:
        observations["direct"] = {"accepted": True}

    data = processing_config_to_data(ProcessingConfig())
    data["processing"]["ocr_policy"] = policy
    try:
        processing_config_from_data(data)
    except ConfigError as error:
        observations["data"] = {"accepted": False, "error": str(error)}
    else:
        observations["data"] = {"accepted": True}

    try:
        resolve_processing_config(set_overrides=[f"processing.ocr_policy={policy}"])
    except ConfigError as error:
        observations["set_override"] = {"accepted": False, "error": str(error)}
    else:
        observations["set_override"] = {"accepted": True}

    return observations


def validate_candidate_contract(policy: str) -> None:
    """실제 실행 가능한 policy만 public config로 인정하는 후보 규칙이다."""

    if policy != "never":
        raise ConfigError(
            "processing.ocr_policy는 현재 never만 지원한다. "
            "OCR은 ocr-overlay 또는 ocr-overlay-batch로 먼저 실행해야 한다."
        )


current = {policy: observe_current_contract(policy) for policy in POLICIES}
current_schema_enum = config_schema()["properties"]["processing"]["properties"][
    "ocr_policy"
]["enum"]

candidate: dict[str, dict[str, Any]] = {}
for policy in POLICIES:
    try:
        validate_candidate_contract(policy)
    except ConfigError as error:
        candidate[policy] = {"accepted": False, "error": str(error)}
    else:
        candidate[policy] = {"accepted": True}

assert current_schema_enum == ["never", "auto", "always"]
assert all(current["never"][path]["accepted"] for path in current["never"])
assert all(current["auto"][path]["accepted"] for path in current["auto"])
assert all(current["always"][path]["accepted"] for path in current["always"])
assert not any(current["sometimes"][path]["accepted"] for path in current["sometimes"])
assert candidate["never"]["accepted"] is True
assert candidate["auto"]["accepted"] is False
assert candidate["always"]["accepted"] is False
assert candidate["sometimes"]["accepted"] is False

result = {
    "experiment_id": EXPERIMENT_ID,
    "current_contract": {
        "schema_enum": current_schema_enum,
        "observations": current,
    },
    "candidate_contract": {
        "schema_enum": ["never"],
        "observations": candidate,
        "error_type": "ConfigError",
        "cli_exit_code": 2,
        "separate_ocr_workflow": ["ocr-overlay", "ocr-overlay-batch"],
    },
    "decision": (
        "processing.ocr_policy는 never만 public value로 유지하고 auto/always는 "
        "direct config, TOML, --set, JSON Schema에서 모두 조기 거부한다."
    ),
    "validation_passed": True,
}

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULT_PATH.write_text(
    json.dumps(result, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(json.dumps(result, ensure_ascii=False, indent=2))
