"""bookmark plan JSON 파일을 읽고 검증한다.

``outline/plan.py``는 plan을 조립하는 순수 로직만 담고, 이 모듈은 그 결과를
디스크에서 다시 읽어 들이는 I/O와 입력 검증을 담당한다(``config.py`` /
``config_io.py``의 로직·I/O 분리 관례를 따른다).
"""

from __future__ import annotations

import json
from pathlib import Path

from pdfbooktree.models import BookmarkPlanItem


class PlanError(ValueError):
    """plan JSON 파일이 없거나 필수 field/타입이 잘못됐을 때 발생한다."""


def load_bookmark_plan_json(path: Path) -> list[BookmarkPlanItem]:
    """``title``/``level``/``pdf_page`` 필수 field와 타입을 검증하며 plan을 읽는다."""

    if not path.is_file():
        raise PlanError(f"plan 파일이 없다: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PlanError(
            f"plan JSON을 읽지 못했다: path={path}, reason={error}"
        ) from error
    if not isinstance(raw, list):
        raise PlanError(f"plan JSON은 list여야 한다: path={path}")

    plan: list[BookmarkPlanItem] = []
    for index, row in enumerate(raw, start=1):
        if not isinstance(row, dict):
            raise PlanError(f"plan {index}번째 항목은 object여야 한다: path={path}")
        plan.append(_parse_plan_item(row, index, path))
    return plan


def _parse_plan_item(
    row: dict[str, object], index: int, path: Path
) -> BookmarkPlanItem:
    title = row.get("title")
    level = row.get("level")
    pdf_page = row.get("pdf_page")
    if not isinstance(title, str) or not title.strip():
        raise PlanError(
            f"plan {index}번째 항목의 title이 비어 있거나 문자열이 아니다: path={path}"
        )
    if not isinstance(level, int) or isinstance(level, bool):
        raise PlanError(
            f"plan {index}번째 항목의 level이 정수가 아니다: path={path}, value={level!r}"
        )
    if not isinstance(pdf_page, int) or isinstance(pdf_page, bool):
        raise PlanError(
            f"plan {index}번째 항목의 pdf_page가 정수가 아니다: "
            f"path={path}, value={pdf_page!r}"
        )
    source = row.get("source", "typography")
    if not isinstance(source, str):
        raise PlanError(
            f"plan {index}번째 항목의 source가 문자열이 아니다: path={path}"
        )
    confidence = row.get("confidence", 0.0)
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        raise PlanError(
            f"plan {index}번째 항목의 confidence가 숫자가 아니다: path={path}"
        )
    evidence = row.get("evidence", [])
    if not isinstance(evidence, list) or not all(
        isinstance(item, str) for item in evidence
    ):
        raise PlanError(
            f"plan {index}번째 항목의 evidence는 문자열 list여야 한다: path={path}"
        )
    return BookmarkPlanItem(
        title=title,
        level=level,
        pdf_page=pdf_page,
        source=source,
        confidence=float(confidence),
        evidence=list(evidence),
    )
