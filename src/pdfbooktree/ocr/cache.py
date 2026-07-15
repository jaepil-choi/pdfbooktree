"""OCR raw response와 표준 삽입 모델 cache를 관리한다."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pdfbooktree.ocr.models import (
    InsertableOcrElement,
    InsertableOcrLine,
    InsertableOcrPage,
    InsertableOcrWord,
    OcrBox,
)
from pdfbooktree.utils.hashing import file_sha256 as file_sha256
from pdfbooktree.utils.hashing import stable_json_hash
from pdfbooktree.utils.jsonio import to_jsonable


class OcrCache:
    """OCR raw response와 insertable page cache를 파일로 저장한다."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.raw_dir = cache_dir / "raw"
        self.insertable_dir = cache_dir / "insertable"

    def raw_cache_key(
        self,
        *,
        input_pdf_hash: str,
        pdf_page: int,
        render_dpi: int,
        engine: str,
        request_params: dict[str, Any],
    ) -> str:
        """raw OCR response cache key를 만든다."""

        return stable_json_hash(
            {
                "input_pdf_hash": input_pdf_hash,
                "pdf_page": pdf_page,
                "render_dpi": render_dpi,
                "engine": engine,
                "request_params": request_params,
            }
        )[:24]

    def insertable_cache_key(
        self,
        *,
        raw_cache_key: str,
        raw_response: dict[str, Any],
        adapter_version: str,
    ) -> str:
        """표준 삽입 모델 cache key를 만든다.

        표준 삽입 모델에는 원본 PDF page 번호와 page 좌표가 포함된다. 따라서 내용이
        같은 raw OCR 응답이라도 서로 다른 page의 모델을 공유하면 안 된다.
        ``raw_cache_key``는 입력 PDF와 1-based page를 포함하므로 이를 함께 사용한다.
        """

        return stable_json_hash(
            {
                "cache_version": 2,
                "raw_cache_key": raw_cache_key,
                "raw_hash": stable_json_hash(raw_response),
                "adapter_version": adapter_version,
            }
        )[:24]

    def read_raw(self, key: str) -> dict[str, Any] | None:
        path = self.raw_dir / f"{key}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_raw(self, key: str, response: dict[str, Any]) -> Path:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        path = self.raw_dir / f"{key}.json"
        path.write_text(
            json.dumps(to_jsonable(response), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def read_insertable(self, key: str) -> InsertableOcrPage | None:
        path = self.insertable_dir / f"{key}.json"
        if not path.exists():
            return None
        return insertable_page_from_json(json.loads(path.read_text(encoding="utf-8")))

    def write_insertable(self, key: str, page: InsertableOcrPage) -> Path:
        self.insertable_dir.mkdir(parents=True, exist_ok=True)
        path = self.insertable_dir / f"{key}.json"
        path.write_text(
            json.dumps(to_jsonable(asdict(page)), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path


def insertable_page_from_json(data: dict[str, Any]) -> InsertableOcrPage:
    """JSON dict를 InsertableOcrPage dataclass로 되돌린다."""

    return InsertableOcrPage(
        pdf_page=int(data["pdf_page"]),
        width_px=int(data["width_px"]),
        height_px=int(data["height_px"]),
        width_pt=float(data["width_pt"]),
        height_pt=float(data["height_pt"]),
        source_engine=str(data["source_engine"]),
        source_model=data.get("source_model"),
        warnings=list(data.get("warnings", [])),
        elements=[
            InsertableOcrElement(
                element_id=str(element["element_id"]),
                category=element.get("category"),
                bbox=_box_from_json(element["bbox"]),
                content_text=str(element.get("content_text", "")),
                overlay_mode=element["overlay_mode"],
                lines=[
                    InsertableOcrLine(
                        text=str(line.get("text", "")),
                        bbox=_box_from_json(line["bbox"]),
                        words=[
                            InsertableOcrWord(
                                text=str(word.get("text", "")),
                                bbox=_box_from_json(word["bbox"]),
                            )
                            for word in line.get("words", [])
                        ],
                    )
                    for line in element.get("lines", [])
                ],
            )
            for element in data.get("elements", [])
        ],
    )


def _box_from_json(data: dict[str, Any]) -> OcrBox:
    return OcrBox(
        x0=float(data["x0"]),
        y0=float(data["y0"]),
        x1=float(data["x1"]),
        y1=float(data["y1"]),
    )
