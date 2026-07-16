"""showcase 021: existing-outline quality policy와 infer/apply 공개 함수를 검증한다.

Phase 2 두 번째 증분에서 추가한 공개 인터페이스를 실제 책 2권으로 검증한다.

- ``resolve_existing_outline_action()``: 기존 outline이 있으면 품질을 항상
  판정하고, ``skip_existing_bookmarks``/``outline_quality.replace_when_low_quality``
  조합으로 재사용 여부를 정한다.
- ``analyze_pdf()`` / ``infer_bookmarks()`` / ``apply_plan()``: infer/apply CLI가
  내부적으로 호출하는 것과 같은 public 함수다.

두 책을 쓴다:
  1. 실험 102(``experiments/102_engine_bookmark_fuzzy_eval.py``)가 400권을 훑어
     `placeholder_or_tiny`로 분류한 실제 low-quality 예시("Viral Hero",
     embedded bookmark 1개 - 사용자가 예로 든 "bookmark가 1개뿐인" 경우
     그대로, 334쪽) - 기본 설정에서는 여전히 skip되지만 품질 판정이 결과에
     남는지, ``replace_when_low_quality=True``를 주면 실제로 typography
     추론 -> apply까지 이어지는지 확인한다. 실험 102 결과(results.jsonl)에서
     이 책은 production 예측이 258개로 비어 있지 않아 replace 경로를 실제로
     보여줄 수 있는 예시로 골랐다.
  2. embedded bookmark 29개인 실제 clean 책(Andrew Ang, Asset Management,
     717쪽) - 기본 설정에서 typography 추론을 아예 실행하지 않고 그대로
     skip하는지 확인한다(717쪽 전체를 추출하지 않아 showcase가 가볍다).

실행:
    uv run python showcase/021_infer_apply_existing_outline_policy.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz

from pdfbooktree import (
    MarkdownSplitConfig,
    OutlineQualityConfig,
    ProcessingConfig,
    analyze_pdf,
    apply_plan,
    infer_bookmarks,
    resolve_existing_outline_action,
    write_inference_artifacts,
)

try:  # 콘솔에서 한글이 깨지지 않게 한다.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT_DIR / "showcase" / "outputs" / "021_infer_apply_existing_outline_policy"
)
OUTPUT_PATH = OUTPUT_DIR / "result.json"
SHOWCASE_JSON = ROOT_DIR / "showcase" / "showcase.json"
SHOWCASE_ID = "021_infer_apply_existing_outline_policy"

BOOKS = [
    {
        "key": "low_quality_outline_book",
        "title": "Viral Hero (Travis Steffen)",
        "pdf": ROOT_DIR
        / "data"
        / "300STUDY"
        / "a_books"
        / "textbook"
        / "Travis  Steffen - Viral Hero (2019).pdf",
        "expect_low_quality": True,
    },
    {
        "key": "clean_outline_book",
        "title": "Asset Management (Andrew Ang)",
        "pdf": ROOT_DIR
        / "data"
        / "300STUDY"
        / "a_books"
        / (
            "(Financial Management Association Survey and Synthesis Series) "
            "Andrew Ang - Asset Management_ A Systematic Approach to Factor "
            "Investing-Oxford University Press (2014).pdf"
        ),
        "expect_low_quality": False,
    },
]


def process_book(spec: dict[str, Any]) -> dict[str, Any]:
    """existing-outline policy를 기본값과 replace_when_low_quality 두 설정으로 확인한다."""

    pdf: Path = spec["pdf"]
    if not pdf.exists():
        raise FileNotFoundError(f"입력 PDF가 없다: {pdf}")

    with fitz.open(pdf) as document:
        total_pages = document.page_count

    default_decision = resolve_existing_outline_action(
        pdf, total_pages, ProcessingConfig()
    )
    if default_decision.quality is None:
        raise RuntimeError(f"{spec['title']}에 embedded outline이 없다.")
    if default_decision.reuse_existing is not True:
        raise RuntimeError(
            f"{spec['title']}: 기본 설정에서는 항상 기존 outline을 재사용해야 한다."
        )
    if default_decision.quality.is_low_quality is not spec["expect_low_quality"]:
        raise RuntimeError(
            f"{spec['title']}: 예상 low-quality 판정과 다르다 - "
            f"expected={spec['expect_low_quality']}, "
            f"actual={default_decision.quality.is_low_quality}, "
            f"reasons={default_decision.quality.reasons}"
        )

    replacement: dict[str, Any] | None = None
    if default_decision.quality.is_low_quality:
        book_output = OUTPUT_DIR / spec["key"]
        typography_config = ProcessingConfig().typography
        replace_config = ProcessingConfig(
            outline_quality=OutlineQualityConfig(replace_when_low_quality=True),
            markdown_split=MarkdownSplitConfig(
                max_words=10_000, max_words_coverage=0.95
            ),
        )
        replace_decision = resolve_existing_outline_action(
            pdf, total_pages, replace_config
        )
        if replace_decision.reuse_existing is not False:
            raise RuntimeError(
                f"{spec['title']}: replace_when_low_quality=True인데도 기존 "
                "outline을 재사용했다."
            )

        analysis = analyze_pdf(pdf, typography_config)
        inference = infer_bookmarks(analysis, typography_config)
        write_inference_artifacts(book_output, inference, replace_decision.quality)
        apply_result = apply_plan(
            pdf,
            book_output,
            inference.plan,
            analysis.total_pages,
            replace_config.markdown_split,
        )
        if not apply_result.validation.valid or apply_result.output_pdf is None:
            raise RuntimeError(
                f"{spec['title']}: 교체 plan이 유효하지 않다: "
                f"warnings={apply_result.validation.warnings}"
            )
        replacement = {
            "reuse_existing": replace_decision.reuse_existing,
            "inferred_bookmark_count": len(inference.plan),
            "inferred_validation_valid": apply_result.validation.valid,
            "output_pdf": str(apply_result.output_pdf.relative_to(ROOT_DIR)),
            "output_markdown_dir": (
                str(apply_result.output_markdown_dir.relative_to(ROOT_DIR))
                if apply_result.output_markdown_dir is not None
                else None
            ),
        }

    return {
        "key": spec["key"],
        "title": spec["title"],
        "input_pdf": str(pdf.relative_to(ROOT_DIR)),
        "page_count": total_pages,
        "existing_outline_item_count": default_decision.quality.item_count,
        "default_reuse_existing": default_decision.reuse_existing,
        "is_low_quality": default_decision.quality.is_low_quality,
        "quality_reasons": default_decision.quality.reasons,
        "quality_evidence": default_decision.quality.evidence,
        "replace_when_low_quality_true": replacement,
    }


def record_showcase(summary: dict[str, Any]) -> None:
    """infer/apply existing-outline policy 결과를 showcase registry에 기록한다."""

    data = json.loads(SHOWCASE_JSON.read_text(encoding="utf-8"))
    entry = {
        "id": SHOWCASE_ID,
        "purpose": (
            "resolve_existing_outline_action()의 existing-outline quality 정책과 "
            "analyze_pdf/infer_bookmarks/apply_plan 공개 함수를 실제 책 2권"
            "(low-quality embedded outline 1권, clean embedded outline 1권)으로 "
            "검증한다."
        ),
        "inputs": [str(spec["pdf"].relative_to(ROOT_DIR)) for spec in BOOKS],
        "outputs": str(OUTPUT_PATH.relative_to(ROOT_DIR)),
        "finding": summary["finding"],
        "command": (
            "uv run python showcase/021_infer_apply_existing_outline_policy.py"
        ),
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    showcases = data["showcases"]
    for index, existing in enumerate(showcases):
        if existing.get("id") == SHOWCASE_ID:
            showcases[index] = entry
            break
    else:
        showcases.append(entry)
    SHOWCASE_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = [process_book(spec) for spec in BOOKS]
    finding_parts = []
    for result in results:
        part = (
            f"{result['title']}: existing_items={result['existing_outline_item_count']}, "
            f"default_reuse_existing={result['default_reuse_existing']}, "
            f"is_low_quality={result['is_low_quality']}, "
            f"reasons={result['quality_reasons']}"
        )
        if result["replace_when_low_quality_true"] is not None:
            replacement = result["replace_when_low_quality_true"]
            part += (
                f", replace_when_low_quality=True -> reuse_existing="
                f"{replacement['reuse_existing']}, "
                f"inferred_bookmark_count={replacement['inferred_bookmark_count']}"
            )
        finding_parts.append(part)
    summary = {
        "books": results,
        "finding": " | ".join(finding_parts),
    }
    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    record_showcase(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
