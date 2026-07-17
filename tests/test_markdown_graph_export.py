"""progressive disclosure Markdown graph의 production 계약을 검증한다."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import fitz
import yaml

from pdfbooktree.export.markdown import export_markdown_tree
from pdfbooktree.models import BookmarkPlanItem

PAGE_MARKER_RE = re.compile(r"<!-- pdf_page (\d+) -->")


def _make_pdf(path: Path) -> None:
    document = fitz.open()
    try:
        for page_number in range(1, 6):
            page = document.new_page()
            page.insert_text((72, 72), f"Page {page_number} body", fontsize=12)
        document.save(path)
    finally:
        document.close()


def _plan() -> list[BookmarkPlanItem]:
    return [
        BookmarkPlanItem(
            title='Chapter: "yes"',
            level=1,
            pdf_page=2,
            source="typography",
            confidence=0.8,
            evidence=["font_tier=1", "bold=true"],
        ),
        BookmarkPlanItem(
            title="CON",
            level=2,
            pdf_page=2,
            source="position_fallback",
            confidence=0.4,
            evidence=["top_band=true"],
        ),
        BookmarkPlanItem(
            title="Topic | details ]",
            level=2,
            pdf_page=4,
            source="typography",
            confidence=0.7,
        ),
    ]


def _read_front_matter(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    end_index = lines.index("---", 1)
    loaded = yaml.safe_load("\n".join(lines[1:end_index]))
    assert isinstance(loaded, dict)
    return loaded


def test_tree_export는_yaml_graph와_direct_page_소유권을_생성한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)

    result = export_markdown_tree(pdf, tmp_path / "out", _plan(), total_pages=5)

    assert result.export_mode == "tree_graph"
    assert result.constraint_satisfied is True
    assert result.file_count == 3
    assert result.manifest_path is not None and result.manifest_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["content_mode"] == "direct"
    assert manifest["validation"]["valid"] is True
    assert manifest["validation"]["yaml_parse_error_count"] == 0
    assert manifest["validation"]["dangling_link_count"] == 0
    assert manifest["validation"]["parent_child_asymmetry_count"] == 0
    assert manifest["validation"]["previous_next_asymmetry_count"] == 0
    assert manifest["coverage"]["duplicated_page_count"] == 0
    assert manifest["coverage"]["unassigned_pages"] == [1]
    assert manifest["coverage"]["navigation_only_node_count"] == 1
    assert manifest["warnings"]["same_page_boundary_count"] == 1

    node_paths = [result.output_dir / row["relative_path"] for row in manifest["nodes"]]
    assert len({path.name.casefold() for path in node_paths}) == 3
    assert any(path.name.endswith("_CON.md") for path in node_paths)
    metadata = [_read_front_matter(path) for path in node_paths]
    assert metadata[0]["title"] == 'Chapter: "yes"'
    assert metadata[0]["content_start_page"] is None
    assert metadata[0]["children"]
    assert metadata[1]["parent_id"] == "n0001"
    assert metadata[1]["source"] == "position_fallback"
    assert metadata[1]["confidence"] == 0.4
    assert metadata[1]["evidence_count"] == 1
    assert metadata[1]["evidence_ref"] == "../bookmark_plan.json#n0002"

    occurrences: Counter[int] = Counter()
    for path in node_paths:
        occurrences.update(
            int(value)
            for value in PAGE_MARKER_RE.findall(path.read_text(encoding="utf-8"))
        )
    assert occurrences == Counter({2: 1, 3: 1, 4: 1, 5: 1})
    toc = (result.output_dir / "toc.md").read_text(encoding="utf-8")
    assert toc.count("[[") >= 3
    plan_snapshot = json.loads(
        (result.output_dir / "bookmark_plan.json").read_text(encoding="utf-8")
    )
    assert plan_snapshot[0]["node_id"] == "n0001"
    assert plan_snapshot[0]["evidence"] == ["font_tier=1", "bold=true"]


def test_tree_export는_inclusive_호환_mode를_manifest에_기록한다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)

    result = export_markdown_tree(
        pdf,
        tmp_path / "out",
        _plan(),
        total_pages=5,
        content_mode="inclusive",
    )

    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["content_mode"] == "inclusive"
    assert manifest["validation"]["valid"] is True
    assert manifest["coverage"]["duplicated_page_count"] > 0
    assert manifest["coverage"]["navigation_only_node_count"] == 0


def test_tree_export는_같은_input에서_mapping과_manifest가_결정적이다(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)

    first = export_markdown_tree(pdf, tmp_path / "first", _plan(), total_pages=5)
    second = export_markdown_tree(pdf, tmp_path / "second", _plan(), total_pages=5)

    assert first.manifest_path is not None
    assert second.manifest_path is not None
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
