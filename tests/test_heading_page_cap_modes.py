"""max_headings_per_page가 heading candidate mode와 무관하게 동작하는지 검증한다.

이 knob을 font 후보 경로에만 걸면 ``position`` mode에서는 오류도 경고도 없이
무반응이 된다. agent가 값을 바꿔도 결과가 같은 knob은 재시도 예산만 낭비시키고
잘못된 인과를 학습시키므로, 저장소는 이미 같은 이유로 소비자 없는 공개 config
key를 제거한 적이 있다(`typography.min_tier_gap`).
"""

from __future__ import annotations

import inspect

from pdfbooktree.typography import geometry


def test_page_상한은_mode_선택_뒤_최종_집합에_적용된다() -> None:
    """page 상한이 mode 분기보다 뒤에서 selected_ids에 걸리는지 확인한다."""

    source = inspect.getsource(geometry.select_geometry_headings)

    mode_at = source.index('heading_candidate_mode == "position"')
    cap_at = source.index("max_headings_per_page > 0")

    assert mode_at < cap_at, (
        "page 상한이 mode 분기보다 앞에 있으면 position mode에서 무반응이 된다"
    )

    cap_block = source[cap_at:]
    assert "for chunk_id in selected_ids" in cap_block, (
        "page 상한은 font 전용 집합이 아니라 최종 선택집합을 걸러야 한다"
    )


def test_page_상한_적용부는_font_전용_집합을_다시_참조하지_않는다() -> None:
    """상한 블록이 font_ids를 다시 좁히는 예전 구조로 되돌아가지 않았는지 본다."""

    source = inspect.getsource(geometry.select_geometry_headings)
    cap_block = source[source.index("max_headings_per_page > 0") :]
    reassigns_font_ids = "font_ids = {" in cap_block

    assert not reassigns_font_ids, (
        "상한이 font_ids를 재할당하면 position mode 경로를 다시 비켜간다"
    )
