"""PDF 책 구조화 패키지의 공개 API다."""

from pdfbooktree.alignment.offset import (
    OffsetEstimationError,
    estimate_page_offset,
)
from pdfbooktree.batch import BatchProcessor
from pdfbooktree.config import (
    LlmRangeReviewConfig,
    LlmStagedTocExtractionConfig,
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
    TocRangeReview,
    TocVisualLine,
)
from pdfbooktree.processor import Processor
from pdfbooktree.toc.bookmark_batch import BookmarkTocBatchDetector
from pdfbooktree.toc.llm_extract import LlmTocExtractor
from pdfbooktree.toc.llm_range_review import LlmTocRangeReviewer
from pdfbooktree.toc.staged_llm_extract import SizeAwareStagedTocExtractor

__all__ = [
    "BatchProcessor",
    "BookmarkedPdfTocBatchResult",
    "BookmarkTocBatchDetector",
    "LlmRangeReviewConfig",
    "LlmStagedTocExtractionConfig",
    "LlmTocExtractionConfig",
    "LlmTocExtractor",
    "LlmTocRangeReviewer",
    "OffsetEstimate",
    "OffsetEstimationConfig",
    "OffsetEstimationError",
    "ProcessingConfig",
    "ProcessingResult",
    "Processor",
    "SizeAwareStagedTocExtractor",
    "TocItem",
    "TocPageDatasetRow",
    "TocRangeReview",
    "TocVisualLine",
    "estimate_page_offset",
]
