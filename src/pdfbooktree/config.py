"""처리 파이프라인의 기본 설정값을 정의한다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessingConfig:
    """단일 PDF 처리에 필요한 v0.1 기본 설정이다."""

    max_toc_search_pages: int = 80
    heading_search_window: int = 3
    skip_existing_bookmarks: bool = True
    use_llm: bool = False
    low_confidence_threshold: float = 0.7
    write_intermediates: bool = True
