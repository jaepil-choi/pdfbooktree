"""처리 파이프라인의 설정 모델과 공통 validation을 정의한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


CONFIG_SCHEMA_VERSION = 1


class ConfigError(ValueError):
    """설정 파일과 public config 값이 유효하지 않을 때 발생한다."""


def _setting(
    default: Any,
    *,
    description: str,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
    exclusive_minimum: bool = False,
) -> Any:
    """schema와 explain 명령에 쓸 metadata를 포함한 dataclass field다."""

    return field(
        default=default,
        metadata={
            "description": description,
            "minimum": minimum,
            "maximum": maximum,
            "exclusive_minimum": exclusive_minimum,
        },
    )


def _require_number(
    name: str,
    value: int | float,
    *,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
    exclusive_minimum: bool = False,
) -> None:
    """숫자 설정의 공통 범위를 검증한다."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{name}은 숫자여야 한다: value={value!r}")
    if minimum is not None:
        invalid = value <= minimum if exclusive_minimum else value < minimum
        if invalid:
            operator = ">" if exclusive_minimum else ">="
            raise ConfigError(
                f"{name}은 {operator} {minimum}이어야 한다: value={value}"
            )
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name}은 <= {maximum}이어야 한다: value={value}")


@dataclass(frozen=True)
class TypographyConfig:
    """책 전체 typography 기반 outline 추론 설정이다."""

    heading_candidate_mode: Literal["position", "font", "position_and_font"] = _setting(
        "font",
        description="heading 후보를 position/font 신호 중 어떤 방식으로 고를지 정한다.",
    )
    body_font_text_coverage: float = _setting(
        0.95,
        description="text length 누적으로 본문 font tier를 포함할 목표 비율이다.",
        minimum=0.0,
        maximum=1.0,
        exclusive_minimum=True,
    )
    body_font_max_words: int = _setting(
        20,
        description="font 골격 heading 후보로 볼 최대 단어 수다.",
        minimum=1,
    )
    position_min_repeated_pages: int = _setting(
        5,
        description="동일 anchor pattern이 반복되어야 하는 최소 page 수다.",
        minimum=1,
    )
    line_y_tolerance_ratio: float = _setting(
        0.55,
        description="span을 같은 시각적 line으로 묶는 y 허용 비율이다.",
        minimum=0.0,
        exclusive_minimum=True,
    )
    min_tier_gap: float = _setting(
        2.0,
        description="인접 typography tier를 분리할 최소 signal 간격이다.",
        minimum=0.0,
    )
    min_tier_count: int = _setting(
        5,
        description="희소 typography tier를 병합하기 위한 최소 line 수다.",
        minimum=1,
    )
    max_heading_tier: int = _setting(
        3,
        description="heading 후보로 인정할 최대 tier 번호다.",
        minimum=1,
    )
    max_heading_length: int = _setting(
        160,
        description="heading 후보 text의 최대 문자 수다.",
        minimum=1,
    )
    min_heading_confidence: float = _setting(
        0.45,
        description="heading 후보로 보존할 최소 heuristic score다.",
        minimum=0.0,
        maximum=1.0,
    )
    heading_merge_gap_ratio: float = _setting(
        1.5,
        description="인접 heading line을 병합할 최대 상대 간격이다.",
        minimum=0.0,
        exclusive_minimum=True,
    )
    bpe_min_pair_count: int = _setting(
        15,
        description="BPE pair 병합을 수행할 최소 반복 횟수다.",
        minimum=1,
    )
    bpe_max_iterations: int = _setting(
        50,
        description="BPE 반복 병합의 최대 iteration 수다.",
        minimum=1,
    )
    bpe_max_node_words: int = _setting(
        30,
        description="이 단어 수를 초과한 BPE node를 hierarchy에서 낮추는 기준이다.",
        minimum=1,
    )
    bpe_level_pollution_ratio: float = _setting(
        0.30,
        description="장문 node가 이 비율을 넘는 bookmark level을 제외하는 기준이다.",
        minimum=0.0,
        maximum=1.0,
    )
    margin_band_ratio: float = _setting(
        0.12,
        description="반복 header/footer를 찾을 page 상·하단 영역 비율이다.",
        minimum=0.0,
        maximum=0.25,
        exclusive_minimum=True,
    )
    margin_position_tolerance_ratio: float = _setting(
        0.015,
        description="margin line 위치를 같은 slot으로 볼 page-relative 허용 비율이다.",
        minimum=0.0,
        exclusive_minimum=True,
    )
    margin_min_consecutive_pages: int = _setting(
        10,
        description="인쇄 page offset이 연속으로 유지되어야 하는 최소 page 수다.",
        minimum=2,
    )
    margin_min_repeated_lines: int = _setting(
        3,
        description="같은 margin text가 반복되어야 하는 최소 line 수다.",
        minimum=1,
    )
    margin_max_page_number: int = _setting(
        3000,
        description="margin의 숫자를 인쇄 page 번호로 볼 최대값이다.",
        minimum=1,
    )
    position_fallback_enabled: bool = _setting(
        True,
        description="body-tier heading을 반복 위치 신호로 복구할지 정한다.",
    )
    position_fallback_tolerance: float = _setting(
        2.0,
        description="body-tier position fallback의 current-anchor 2D 허용 오차다.",
        minimum=0.0,
        exclusive_minimum=True,
    )
    position_fallback_min_isolation_ratio: float = _setting(
        1.0,
        description="다른 반복 위치 cluster로부터 요구할 최소 isolation 비율이다.",
        minimum=0.0,
    )
    position_fallback_body_font_ratio_low: float = _setting(
        0.97,
        description="fallback 후보 font/body font 비율의 하한이다.",
        minimum=0.0,
        exclusive_minimum=True,
    )
    position_fallback_body_font_ratio_high: float = _setting(
        1.03,
        description="fallback 후보 font/body font 비율의 상한이다.",
        minimum=0.0,
        exclusive_minimum=True,
    )
    position_fallback_title_dedupe_threshold: float = _setting(
        0.8,
        description="fallback title을 기존 font plan과 중복으로 볼 유사도 기준이다.",
        minimum=0.0,
        maximum=1.0,
    )

    def __post_init__(self) -> None:
        if self.heading_candidate_mode not in {
            "position",
            "font",
            "position_and_font",
        }:
            raise ConfigError(
                "typography.heading_candidate_mode은 position, font, "
                f"position_and_font 중 하나여야 한다: value={self.heading_candidate_mode!r}"
            )
        ranges = {
            "body_font_text_coverage": (0.0, 1.0, True),
            "body_font_max_words": (1, None, False),
            "position_min_repeated_pages": (1, None, False),
            "line_y_tolerance_ratio": (0.0, None, True),
            "min_tier_gap": (0.0, None, False),
            "min_tier_count": (1, None, False),
            "max_heading_tier": (1, None, False),
            "max_heading_length": (1, None, False),
            "min_heading_confidence": (0.0, 1.0, False),
            "heading_merge_gap_ratio": (0.0, None, True),
            "bpe_min_pair_count": (1, None, False),
            "bpe_max_iterations": (1, None, False),
            "bpe_max_node_words": (1, None, False),
            "bpe_level_pollution_ratio": (0.0, 1.0, False),
            "margin_band_ratio": (0.0, 0.25, True),
            "margin_position_tolerance_ratio": (0.0, None, True),
            "margin_min_consecutive_pages": (2, None, False),
            "margin_min_repeated_lines": (1, None, False),
            "margin_max_page_number": (1, None, False),
            "position_fallback_tolerance": (0.0, None, True),
            "position_fallback_min_isolation_ratio": (0.0, None, False),
            "position_fallback_body_font_ratio_low": (0.0, None, True),
            "position_fallback_body_font_ratio_high": (0.0, None, True),
            "position_fallback_title_dedupe_threshold": (0.0, 1.0, False),
        }
        for name, (minimum, maximum, exclusive) in ranges.items():
            _require_number(
                f"typography.{name}",
                getattr(self, name),
                minimum=minimum,
                maximum=maximum,
                exclusive_minimum=exclusive,
            )
        if not isinstance(self.position_fallback_enabled, bool):
            raise ConfigError("typography.position_fallback_enabled는 bool이어야 한다.")
        if (
            self.position_fallback_body_font_ratio_low
            > self.position_fallback_body_font_ratio_high
        ):
            raise ConfigError(
                "typography.position_fallback_body_font_ratio_low는 high보다 "
                "클 수 없다."
            )


@dataclass(frozen=True)
class MarkdownSplitConfig:
    """계층 bookmark를 길이 제약 Markdown 파일로 나누는 공개 정책이다."""

    max_words: int = _setting(
        10_000,
        description="하나의 Markdown 파일에 허용할 목표 최대 단어 수다.",
        minimum=1,
    )
    max_words_coverage: float = _setting(
        0.95,
        description="max_words 이하 파일이 되어야 하는 목표 비율이다.",
        minimum=0.0,
        maximum=1.0,
        exclusive_minimum=True,
    )
    prefer: Literal["coarsest"] = _setting(
        "coarsest",
        description="조건을 만족하는 level 중 선택할 우선순위 정책이다.",
    )

    def __post_init__(self) -> None:
        _require_number("markdown.max_words", self.max_words, minimum=1)
        _require_number(
            "markdown.max_words_coverage",
            self.max_words_coverage,
            minimum=0.0,
            maximum=1.0,
            exclusive_minimum=True,
        )
        if self.prefer != "coarsest":
            raise ConfigError("markdown.prefer는 coarsest만 지원한다.")


@dataclass(frozen=True)
class OutlineQualityConfig:
    """기존 outline이 실제 목차가 아닐 가능성을 판정하고 대응하는 정책이다."""

    min_item_count: int = _setting(
        4,
        description=(
            "outline item 수가 이 값보다 적으면 low quality로 본다"
            "(실험 102의 placeholder_or_tiny 기준 <=3을 그대로 따른다)."
        ),
        minimum=1,
    )
    max_item_to_page_ratio: float = _setting(
        0.9,
        description=(
            "outline item 수가 총 page 수 대비 이 비율 이상이면 스캔 도구가 매 "
            "page에 붙인 일련번호로 본다(실험 102의 per_page_scan_filenames 기준)."
        ),
        minimum=0.0,
        maximum=1.0,
        exclusive_minimum=True,
    )
    flag_numeric_only_titles: bool = _setting(
        True,
        description="title이 숫자로만 이뤄진 item이 하나라도 있으면 low quality로 본다.",
    )
    replace_when_low_quality: bool = _setting(
        False,
        description=(
            "low quality로 판정되면 기존 outline을 건너뛰지 않고 typography "
            "추론 결과로 교체한다."
        ),
    )

    def __post_init__(self) -> None:
        _require_number(
            "outline_quality.min_item_count", self.min_item_count, minimum=1
        )
        _require_number(
            "outline_quality.max_item_to_page_ratio",
            self.max_item_to_page_ratio,
            minimum=0.0,
            maximum=1.0,
            exclusive_minimum=True,
        )
        if not isinstance(self.flag_numeric_only_titles, bool):
            raise ConfigError(
                "outline_quality.flag_numeric_only_titles는 bool이어야 한다."
            )
        if not isinstance(self.replace_when_low_quality, bool):
            raise ConfigError(
                "outline_quality.replace_when_low_quality는 bool이어야 한다."
            )


@dataclass(frozen=True)
class ProcessingConfig:
    """단일 PDF 처리 설정이다."""

    skip_existing_bookmarks: bool = _setting(
        True,
        description="기존 outline이 있으면 typography 추론을 건너뛸지 정한다.",
    )
    write_artifacts: bool = _setting(
        True,
        description="검토 가능한 중간 JSON/JSONL artifact를 저장할지 정한다.",
    )
    ocr_policy: Literal["never", "auto", "always"] = _setting(
        "never",
        description="OCR 전처리 정책이다. 현재 Processor에는 아직 연결되지 않았다.",
    )
    typography: TypographyConfig = field(
        default_factory=TypographyConfig,
        metadata={"description": "typography 기반 bookmark 추론 설정이다."},
    )
    markdown_split: MarkdownSplitConfig | None = field(
        default=None,
        metadata={"description": "지정하면 coverage 기반 Markdown split을 사용한다."},
    )
    outline_quality: OutlineQualityConfig = field(
        default_factory=OutlineQualityConfig,
        metadata={"description": "기존 outline 품질 판정과 자동 교체 정책이다."},
    )

    def __post_init__(self) -> None:
        if not isinstance(self.skip_existing_bookmarks, bool):
            raise ConfigError("processing.skip_existing_bookmarks는 bool이어야 한다.")
        if not isinstance(self.write_artifacts, bool):
            raise ConfigError("processing.write_artifacts는 bool이어야 한다.")
        if self.ocr_policy not in {"never", "auto", "always"}:
            raise ConfigError(
                "processing.ocr_policy는 never, auto, always 중 하나여야 한다."
            )
        if not isinstance(self.typography, TypographyConfig):
            raise ConfigError("processing.typography는 TypographyConfig여야 한다.")
        if self.markdown_split is not None and not isinstance(
            self.markdown_split, MarkdownSplitConfig
        ):
            raise ConfigError(
                "processing.markdown_split은 MarkdownSplitConfig 또는 None이어야 한다."
            )
        if not isinstance(self.outline_quality, OutlineQualityConfig):
            raise ConfigError(
                "processing.outline_quality는 OutlineQualityConfig여야 한다."
            )
