from __future__ import annotations

from pdfbooktree.utils.text_normalize import (
    normalize_for_match,
    normalize_text,
    title_similarity,
)


def test_normalize_text_collapses_control_characters_and_spaces() -> None:
    assert normalize_text("A\x08  \n B") == "A B"


def test_normalize_for_match_removes_dot_leaders_and_trailing_page_number() -> None:
    assert normalize_for_match("1.1 ﬁnance ............ 27") == "1 1 finance"


def test_title_similarity_returns_one_for_case_insensitive_match() -> None:
    assert title_similarity("Chapter 1", "chapter 1") == 1.0


def test_title_similarity_returns_one_for_containment() -> None:
    assert title_similarity("Introduction", "1.1 Introduction to Finance") == 1.0


def test_title_similarity_returns_zero_for_empty_input() -> None:
    assert title_similarity("", "Chapter 1") == 0.0


def test_title_similarity_scores_unrelated_titles_low() -> None:
    assert title_similarity("Chapter 1: Finance", "Appendix B: Glossary") < 0.3
