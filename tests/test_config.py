"""public config가 생성 시점에 공통 제약을 검증하는지 확인한다."""

from __future__ import annotations

import pytest

from pdfbooktree.config import (
    ConfigError,
    MarkdownSplitConfig,
    ProcessingConfig,
    TypographyConfig,
)


def test_default_processing_config는_기존_기본값을_유지한다() -> None:
    config = ProcessingConfig()

    assert config.skip_existing_bookmarks is True
    assert config.write_artifacts is True
    assert config.ocr_policy == "never"
    assert config.markdown_content_mode == "direct"
    assert config.typography.heading_candidate_mode == "font"
    assert config.typography.position_fallback_enabled is True
    assert config.markdown_split is not None
    assert config.markdown_split.enabled is True
    assert config.markdown_split.max_words == 10_000


def test_markdown_split은_명시적으로_비활성화할_수_있다() -> None:
    config = ProcessingConfig(
        markdown_split=MarkdownSplitConfig(enabled=False),
    )

    assert config.markdown_split is not None
    assert config.markdown_split.enabled is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"body_font_text_coverage": 0.0}, "body_font_text_coverage"),
        ({"body_font_max_words": 0}, "body_font_max_words"),
        ({"margin_band_ratio": 0.3}, "margin_band_ratio"),
        ({"position_fallback_tolerance": 0.0}, "position_fallback_tolerance"),
        (
            {
                "position_fallback_body_font_ratio_low": 1.1,
                "position_fallback_body_font_ratio_high": 1.0,
            },
            "ratio_low",
        ),
    ],
)
def test_typography_config는_잘못된_범위를_즉시_거절한다(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        TypographyConfig(**kwargs)


def test_markdown_config는_잘못된_coverage를_거절한다() -> None:
    with pytest.raises(ConfigError, match="max_words_coverage"):
        MarkdownSplitConfig(max_words_coverage=1.1)


@pytest.mark.parametrize("ocr_policy", ["auto", "always", "sometimes"])
def test_processing_config는_지원하지_않는_ocr_policy를_조기_거절한다(
    ocr_policy: str,
) -> None:
    with pytest.raises(ConfigError, match="현재 never만 지원"):
        ProcessingConfig(ocr_policy=ocr_policy)  # type: ignore[arg-type]


def test_processing_config는_잘못된_markdown_literal을_거절한다() -> None:

    with pytest.raises(ConfigError, match="markdown_content_mode"):
        ProcessingConfig(markdown_content_mode="nested")
