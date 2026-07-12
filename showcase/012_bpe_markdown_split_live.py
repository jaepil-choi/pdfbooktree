"""BPE hierarchy와 coverage Markdown split 공개 인터페이스를 실제 PDF로 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

from pdfbooktree.config import MarkdownSplitConfig, ProcessingConfig, TypographyConfig
from pdfbooktree.processor import Processor
from pdfbooktree.utils.jsonio import to_jsonable


ROOT_DIR = Path(__file__).resolve().parents[1]
PDF_PATH = (
    ROOT_DIR
    / "data"
    / "300STUDY"
    / "textbooks"
    / "Zvi Bodie, Alex Kane, Alan Marcus - Investments-McGraw Hill (2021)[finance].pdf"
)
OUTPUT_DIR = ROOT_DIR / "showcase" / "outputs" / "012_bpe_markdown_split_live"


def main() -> None:
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"실제 PDF가 없습니다: {PDF_PATH}")
    result = Processor(
        PDF_PATH,
        OUTPUT_DIR,
        ProcessingConfig(
            skip_existing_bookmarks=False,
            typography=TypographyConfig(bpe_min_pair_count=15),
            markdown_split=MarkdownSplitConfig(
                max_words=10_000,
                max_words_coverage=0.95,
            ),
        ),
    ).run()
    if result.markdown_export is None:
        raise RuntimeError("Markdown split 결과가 없습니다")
    payload = {
        "processing_result": to_jsonable(result),
        "chosen_level": result.markdown_export.chosen_level,
        "constraint_satisfied": result.markdown_export.constraint_satisfied,
        "file_count": result.markdown_export.file_count,
        "word_count_stats": result.markdown_export.word_count_stats,
        "overflow_files": to_jsonable(result.markdown_export.overflow_files),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
