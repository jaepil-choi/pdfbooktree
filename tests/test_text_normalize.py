from __future__ import annotations

from pdfbooktree.utils.text_normalize import normalize_for_match, normalize_text


def test_normalize_text_collapses_control_characters_and_spaces() -> None:
    assert normalize_text("A\x08  \n B") == "A B"


def test_normalize_for_match_removes_dot_leaders_and_trailing_page_number() -> None:
    assert normalize_for_match("1.1 ﬁnance ............ 27") == "1 1 finance"
