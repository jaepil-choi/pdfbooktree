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


# LLM TOC range reviewer system prompt 기본값. config로 통째로 교체할 수 있다.
# experiment 016에서 검증한 프롬프트다.
DEFAULT_TOC_RANGE_REVIEW_SYSTEM_PROMPT = (
    "당신은 PDF 책의 페이지가 목차(Table of Contents) 페이지인지 판정하는 분류기다.\n"
    "규칙:\n"
    "- 상세 목차(Contents)와 간략 목차(Contents in brief / Brief Contents)는 모두 목차로 본다.\n"
    "- 목차 항목은 장/절 제목과 함께 '책 본문의 페이지 번호'를 가리킨다.\n"
    "  제목 옆/끝에 본문 페이지 번호(예: ...... 23)가 줄마다 붙어 있는 형태가 핵심 신호다.\n"
    "- 페이지 번호 없이 외부 웹사이트 자료나 노트 제목만 나열한 목록은 목차가 아니다.\n"
    "- 표지, 헌사, 판권지, 서문/머리말, 본문 첫 페이지는 목차가 아니다.\n"
    "- is_toc_start는 '이 페이지부터 목차가 시작'할 때만 true다.\n"
    "- 반드시 주어진 JSON schema로만 답한다."
)


@dataclass(frozen=True)
class LlmRangeReviewConfig:
    """LLM 3단계 TOC range fallback 설정이다.

    PRD §7.8~7.11(15.1)의 start accept / backtrack_start / sequential recovery
    구조를 따른다. experiment 016에서 검증한 파라미터를 기본값으로 둔다.
    LLM은 Upstage Solar chat(solar-pro3) 텍스트 경로만 쓴다(IE는 과금이라 금지).
    """

    # 모델과 엔드포인트
    model: str = "solar-pro3"
    base_url: str = "https://api.upstage.ai/v1"
    api_key_env: str = "UPSTAGE_API_KEY"
    request_timeout: float | None = None
    temperature: float = 0.0

    # fallback 탐색 파라미터
    scan_pages: int = 40  # 앞부분 몇 page까지 page text를 미리 확보할지
    max_backtrack: int = 8  # backward merge / 2단계 backtrack 최대 page 수
    max_sequential: int = 40  # 3단계 sequential recovery 최대 검토 page 수
    max_end_expand: int = 30  # end expansion 시 anchor 기준 최대 span
    end_gap_tolerance: int = 0  # 확장 중 허용하는 연속 non-TOC page 수
    prompt_max_chars: int = 4500

    system_prompt: str = DEFAULT_TOC_RANGE_REVIEW_SYSTEM_PROMPT


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
    # LLM 3단계 TOC range reviewer 설정. use_llm=True일 때만 호출한다.
    llm_range_review: "LlmRangeReviewConfig" = field(
        default_factory=lambda: LlmRangeReviewConfig()
    )
    # LLM TOC item 추출 설정. 결정적 파서가 0개를 뽑으면 fallback으로 호출한다.
    llm_extraction: "LlmTocExtractionConfig" = field(
        default_factory=lambda: LlmTocExtractionConfig()
    )
    # TOC item LLM fallback 구현체. staged는 글씨 height tier를 코드가 고정하고
    # LLM이 tier만 복사하게 해 OCR/한글 목차의 계층 안정성을 높인다.
    llm_item_extraction_strategy: Literal["staged", "basic"] = "staged"
    llm_staged_extraction: "LlmStagedTocExtractionConfig" = field(
        default_factory=lambda: LlmStagedTocExtractionConfig()
    )


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

    # 모델 (config로 쉽게 교체). 정책상 solar-pro3 텍스트 경로만 쓴다.
    # image_model(information-extract)은 과금이라 runtime에서 호출하지 않는다.
    text_model: str = "solar-pro3"
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


# staged extractor 1단계 schema prompt. experiment 021에서 검증한 제약이다.
DEFAULT_STAGED_SCHEMA_SYSTEM_PROMPT = (
    "너는 책 목차의 '첫 페이지'를 보고 이 책 목차의 계층 스키마를 정의하는 도구다. "
    "각 줄 앞 [Tn]은 글씨 크기 tier다(T1이 가장 큰 글씨).\n"
    "중요: 계층 레벨 수는 이미 글씨 크기 클러스터로 정해졌다. 사용자가 알려주는 tier "
    "개수만큼만 레벨을 정의하고, 같은 글씨 크기를 번호·문장부호만으로 더 쪼개거나 합치지 "
    "마라. 큰 글씨 tier가 상위 레벨(1)이다.\n"
    "각 레벨에 level(1부터), name(예: 장/절/소절, chapter/section), cues(그 레벨을 알아보는 "
    "신호: 어떤 글씨 tier인지 등), examples(첫 페이지에서 그 레벨에 해당하는 제목 1~3개)를 "
    "적는다. '목차'/'Contents' 같은 페이지 머리말은 레벨에서 제외한다. 이 스키마는 이후 이 "
    "책의 모든 목차 페이지에 똑같이 적용된다."
)


# staged extractor 2단계 page extraction prompt. level은 LLM이 아니라 코드가 부여한다.
DEFAULT_STAGED_EXTRACT_SYSTEM_PROMPT = (
    "너는 책 목차 페이지에서 항목을 추출하는 도구다. 아래 [계층 스키마]는 이 책 전체에 "
    "일관 적용되는 레벨 정의이고, 각 줄 앞 [Tn]은 그 줄의 글씨 크기 tier다.\n"
    "절대 규칙: 계층/레벨/tier는 네가 정하지 않는다. 각 항목의 tier는 그 항목이 나온 줄의 "
    "[Tn] 숫자(n)를 그대로 복사만 한다. tier를 바꾸거나 새로 만들거나 추론하지 마라. "
    "한 줄을 여러 항목으로 쪼개면 모든 조각은 그 줄과 같은 tier를 받는다.\n"
    "너가 하는 일은 다음뿐이다.\n"
    "- 깨진 OCR 글씨 복원: 깨진 제목을 깨끗하게 고친다(예: '살펴보는일을멈춈야할때-細龜'→"
    "'살펴보는 일을 멈춰야 할 때', '미래여區-園 O 뜨퍄'→'미래를 내다보라'). 보이는 글자만 "
    "살려 복원하고 없는 내용을 지어내지 않는다.\n"
    "- 항목 분리: 한 줄에 여러 항목이 'I'/'|'/'·'/'•' 구분자와 페이지 번호로 합쳐져 있으면 "
    "각 항목으로 분리한다. 예: '비서 문제 • 24 I 37%는 어디에서 • 28' → 항목 2개.\n"
    "- 페이지 번호: printed_page는 제목 뒤(또는 '•'/'·' 뒤)의 인쇄 페이지 번호. 없으면 null.\n"
    "- 글씨가 깨진 줄도 빼지 말고 반드시 항목으로 낸다.\n"
    "- '목차'/'Contents' 같은 머리말 한 마디 줄은 항목으로 만들지 않는다.\n"
    "- 항목은 이 페이지에 나온 순서 그대로 반환한다."
)


@dataclass(frozen=True)
class LlmStagedTocExtractionConfig:
    """글씨 height tier 기반 staged LLM TOC item 추출 설정이다.

    experiment 017/021에서 검증한 흐름을 제품 코드로 옮긴다. height tier와
    tier->level 매핑은 코드가 결정하고, LLM은 페이지별 추출에서 tier만 복사한다.
    """

    model: str = "solar-pro3"
    base_url: str = "https://api.upstage.ai/v1"
    api_key_env: str = "UPSTAGE_API_KEY"
    request_timeout: float | None = None
    temperature: float = 0.0
    max_completion_tokens: int | None = None
    default_item_confidence: float = 0.8
    schema_system_prompt: str = DEFAULT_STAGED_SCHEMA_SYSTEM_PROMPT
    extract_system_prompt: str = DEFAULT_STAGED_EXTRACT_SYSTEM_PROMPT
