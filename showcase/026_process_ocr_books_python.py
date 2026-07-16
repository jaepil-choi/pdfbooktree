"""공개 Python 인터페이스로 OCR 책 세 권을 처리한다."""

from pathlib import Path

from pdfbooktree import OutlineQualityConfig, ProcessingConfig, Processor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "showcase" / "outputs" / "026_process_ocr_books_python"
BOOKS = (
    (
        "econometrics_note1",
        "016_econometrics_note1_ocr_overlay/kim_econometrics_note1_ocr.pdf",
        False,
    ),
    (
        "interest_economics",
        "017_interest_economics_ocr_overlay/interest_economics_ocr.pdf",
        False,
    ),
    (
        "statistics_principles",
        "018_statistics_principles_ocr_overlay/statistics_principles_ocr.pdf",
        True,
    ),
)

for name, relative_pdf, replace in BOOKS:
    pdf = ROOT / "showcase" / "outputs" / relative_pdf
    config = ProcessingConfig(
        outline_quality=OutlineQualityConfig(replace_when_low_quality=replace)
    )
    result = Processor(pdf, OUTPUT / name, config).run()
    print(
        f"{name}: {result.status}, bookmarks={result.bookmark_count}, "
        f"pdf={result.output_pdf}, markdown={result.output_markdown_dir}"
    )
