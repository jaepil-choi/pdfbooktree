"""PDF 책 구조화 패키지의 공개 API다."""

from pdfbooktree.alignment.offset import (
    OffsetEstimationError,
    estimate_page_offset,
)
from pdfbooktree.batch import BatchProcessor
from pdfbooktree.config import (
    LlmTocExtractionConfig,
    OffsetEstimationConfig,
    ProcessingConfig,
)
from pdfbooktree.models import (
    BookmarkedPdfTocBatchResult,
    OffsetEstimate,
    ProcessingResult,
    TocItem,
    TocPageDatasetRow,
)
from pdfbooktree.processor import Processor
from pdfbooktree.toc.bookmark_batch import BookmarkTocBatchDetector
from pdfbooktree.toc.llm_extract import LlmTocExtractor

__all__ = [
    "BatchProcessor",
    "BookmarkedPdfTocBatchResult",
    "BookmarkTocBatchDetector",
    "LlmTocExtractionConfig",
    "LlmTocExtractor",
    "OffsetEstimate",
    "OffsetEstimationConfig",
    "OffsetEstimationError",
    "ProcessingConfig",
    "ProcessingResult",
    "Processor",
    "TocItem",
    "TocPageDatasetRow",
    "estimate_page_offset",
]
