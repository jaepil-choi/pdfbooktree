"""처리 파이프라인의 기본 설정값을 정의한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class OffsetEstimationConfig:
    """header/footer page number 기반 page offset 추정 설정이다.

    experiment 015에서 검증한 추출/병합 파라미터와 clean 게이트 임계값을 모두
    config로 노출한다. clean하지 않으면 fast-fail하며 fallback은 두지 않는다.
    """

    # band 추출
    band_ratio: float = 0.10
    line_y_tolerance_ratio: float = 0.6
    merge_gap_ratio: float = 1.0
    max_number: int = 3000
    max_scan_pages: int | None = None

    # clean 게이트(최빈 우세 기준). 둘 다 만족해야 offset을 신뢰한다.
    min_modal_count: int = 5
    min_dominance_ratio: float = 1.5


@dataclass(frozen=True)
class ProcessingConfig:
    """단일 PDF 처리에 필요한 v0.1 기본 설정이다."""

    max_toc_search_pages: int = 80
    heading_search_window: int = 3
    skip_existing_bookmarks: bool = True
    use_llm: bool = False
    low_confidence_threshold: float = 0.7
    write_intermediates: bool = True
    # offset 추정 설정. Processor가 estimate_page_offset에 그대로 넘긴다.
    offset: OffsetEstimationConfig = field(default_factory=OffsetEstimationConfig)


# LLM 목차 추출기 system prompt 기본값. config로 통째로 교체할 수 있다.
DEFAULT_TOC_EXTRACTION_SYSTEM_PROMPT = (
    "너는 책 목차(Table of Contents) 페이지에서 목차 항목을 구조화해 추출하는 도구다. "
    "주어진 텍스트/이미지는 한 책의 목차 페이지다. 각 목차 항목을 title, level, "
    "printed_page로 추출하라. 규칙:\n"
    "- title: 항목 제목. 번호(예: '1.1', '제2장', 'Chapter 3', 'Appendix A')가 있으면 포함한다.\n"
    "- level: 'Chapter N'/'제N장'/'N부'/'Part'/'Appendix'/최상위 번호(예: '1 ')는 1, "
    "'1.1'은 2, '1.1.1'은 3. 들여쓰기와 번호 깊이를 함께 본다.\n"
    "- printed_page: 항목 줄 끝(또는 우측)에 인쇄된 페이지 번호. 점선 leader가 깨졌어도 "
    "숫자를 찾는다. 페이지 번호가 없으면 null.\n"
    "- source_pdf_page: 그 항목이 나타난 목차 PDF page. 입력의 '--- PDF page N ---' "
    "마커 기준 N을 그대로 쓴다.\n"
    "- 목차 항목이 아닌 머리말/그림/표지 텍스트, running header, 페이지 번호만 있는 줄은 제외한다.\n"
    "- title은 OCR 노이즈를 정리해 깨끗한 제목으로 복원한다. 잘못 인식된 기호/문자를 "
    "바로잡되(예: 'FIXEl:l·INCOME SE(UR!TIES' → 'FIXED-INCOME SECURITIES', "
    "'PRICll'JG' → 'PRICING', 'fVIoney' → 'Money', 'J .2' → '1.2'), 의미는 바꾸지 말고 "
    "없는 항목이나 단어를 지어내지 않는다.\n"
    "- 번호(장/절 번호)가 OCR로 깨졌으면 앞뒤 항목의 연속된 번호 문맥으로 올바른 번호를 "
    "복원한다(예: 'Char:.ter O' 가 Chapter 9와 11 사이면 'Chapter 10').\n"
    "- 항목은 목차에 나온 순서대로 반환한다."
)


@dataclass(frozen=True)
class LlmTocExtractionConfig:
    """Upstage LLM 기반 TOC item 추출 설정이다.

    모델, 하이퍼파라미터, 엔드포인트, 임계값을 모두 이 config로 교체한다.
    experiment 014에서 solar-pro2 텍스트 경로가 가장 안정적이라 기본값으로 둔다.
    """

    # 추출 경로: "text"는 OCR 텍스트->solar-pro2, "image"는 페이지 이미지->information-extract.
    mode: Literal["text", "image"] = "text"

    # 모델 (config로 쉽게 교체)
    text_model: str = "solar-pro2"
    image_model: str = "information-extract"

    # 엔드포인트와 인증
    chat_base_url: str = "https://api.upstage.ai/v1"
    image_base_url: str = "https://api.upstage.ai/v1/information-extraction"
    api_key_env: str = "UPSTAGE_API_KEY"
    request_timeout: float | None = None

    # 생성 하이퍼파라미터
    temperature: float = 0.0
    max_completion_tokens: int | None = None

    # 항목 변환
    default_item_confidence: float = 0.8

    # 이미지 경로 전용
    max_image_pages: int = 12
    image_dpi: int = 150
    image_mime: str = "application/octet-stream"

    # 프롬프트
    system_prompt: str = DEFAULT_TOC_EXTRACTION_SYSTEM_PROMPT
