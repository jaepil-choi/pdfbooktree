"""책 전체 typography 신호 추출 패키지다."""

from pdfbooktree.typography.geometry import (
    FontCoverageProfile,
    GeometryContext,
    build_geometry_context,
    classify_font_tiers_by_text_coverage,
    compute_geometry_font_tier_set,
    extract_geometry_headings,
    select_geometry_headings,
)
from pdfbooktree.typography.position_fallback import (
    PositionFallbackCandidate,
    select_body_tier_position_fallback,
)

__all__ = [
    "FontCoverageProfile",
    "GeometryContext",
    "PositionFallbackCandidate",
    "build_geometry_context",
    "classify_font_tiers_by_text_coverage",
    "compute_geometry_font_tier_set",
    "extract_geometry_headings",
    "select_body_tier_position_fallback",
    "select_geometry_headings",
]
