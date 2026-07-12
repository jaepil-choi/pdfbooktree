import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from notion_upload_catalog import Entry, collect_entries, update_links
from pdf_to_chapters import Candidate, parse_chapter_line
from pdf_toc import parse_toc_subsections


class StructureTests(unittest.TestCase):
    def test_chapter_parser_accepts_korean_and_roman_english_headings(self):
        self.assertEqual(parse_chapter_line("제2장 검색엔진"), (2, "검색엔진", False))
        number, title, standalone = parse_chapter_line("Chapter IV Networks")
        self.assertEqual((number, title, standalone), (4, "Networks", False))

    def test_toc_subsections_map_pipe_style_entries_to_body_pages(self):
        pages = [
            "목차\n• 검색엔진 인덱싱 • 4\n• 페이지랭크 • 5",
            "",
            "",
            "검색엔진 인덱싱\n본문 시작\n4",
            "페이지랭크\n본문 계속\n5",
        ]
        boundaries = [
            Candidate(
                page=4,
                number=1,
                title="검색엔진",
                score=10,
                standalone=False,
                toc_like=False,
                raw_line="1장 검색엔진",
                reasons=[],
            )
        ]

        result = parse_toc_subsections(pages, boundaries)

        self.assertEqual([section.title for section in result[1]], ["검색엔진 인덱싱", "페이지랭크"])
        self.assertEqual([section.page for section in result[1]], [4, 5])
        self.assertEqual([section.number for section in result[1]], ["1.1", "1.2"])


class NotionCatalogTests(unittest.TestCase):
    def test_collect_entries_prefers_subsections_and_sets_chapter_label(self):
        with tempfile.TemporaryDirectory() as temp:
            book_dir = Path(temp) / "algorithms-nine"
            chapter_dir = book_dir / "ch-01"
            chapter_dir.mkdir(parents=True)
            (book_dir / "ch-01.md").write_text("# 1장 전체\n", encoding="utf-8")
            (chapter_dir / "intro.md").write_text("# 1장 도입\n", encoding="utf-8")
            (chapter_dir / "section-1-1.md").write_text("# 1.1 첫 소챕터\n", encoding="utf-8")

            entries = collect_entries(book_dir)

        self.assertEqual([entry.title for entry in entries], ["1장 도입", "1.1 첫 소챕터"])
        self.assertEqual({entry.chapter_label for entry in entries}, {"1장"})
        self.assertEqual(entries[0].book, "미래를 바꾼 아홉 가지 알고리즘")

    def test_update_links_keeps_previous_empty_and_sets_next_relation(self):
        entry = Entry(
            book="책",
            chapter=1,
            chapter_label="1장",
            path=Path("section.md"),
            title="1.1 소챕터",
        )
        with patch("notion_upload_catalog.notion_request") as request:
            update_links(
                entry,
                page_id="current-id",
                previous_id="previous-id",
                next_id="next-id",
                book_property_name="책 제목",
                chapter_property_name="챕터",
                previous_property_name="이전 (소)챕터",
                next_property_name="이후 (소)챕터",
                token="test-token",
                notion_version="2026-03-11",
            )

        payload = request.call_args.args[2]
        properties = payload["properties"]
        self.assertEqual(properties["이전 (소)챕터"], {"relation": []})
        self.assertEqual(properties["이후 (소)챕터"], {"relation": [{"id": "next-id"}]})
        self.assertEqual(properties["챕터"], {"rich_text": [{"text": {"content": "1장"}}]})


if __name__ == "__main__":
    unittest.main()
