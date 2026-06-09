from __future__ import annotations

from pdfbooktree.toc.parse import infer_level, parse_toc_line


def test_parse_toc_line_supports_basic_patterns() -> None:
    cases = [
        ("Chapter 1 Introduction ........ 3", 1, "Chapter 1 Introduction", 3),
        ("1.1 Motivation ................ 7", 2, "1.1 Motivation", 7),
        ("1.1.1 Details ................. 12", 3, "1.1.1 Details", 12),
        ("Appendix A Proofs ............. 251", 1, "Appendix A Proofs", 251),
        ("A.1 Proofs .................... 255", 2, "A.1 Proofs", 255),
    ]
    for raw_text, level, title, printed_page in cases:
        item = parse_toc_line(raw_text, source_pdf_page=5)
        assert item is not None
        assert item.level == level
        assert item.title == title
        assert item.printed_page == printed_page


def test_infer_level_defaults_to_one_for_unnumbered_title() -> None:
    assert infer_level("Preface") == 1
