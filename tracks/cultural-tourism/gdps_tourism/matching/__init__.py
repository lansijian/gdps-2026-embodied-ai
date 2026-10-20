"""Feature matching and temporal vote filtering."""

from __future__ import annotations

from .feature_matcher import ExhibitMatcher, TemplateLibrary
from .prefilter import CoarsePrefilter, PrefilterResult
from .temporal_filter import TemporalVoteFilter
from .types import MatchCandidate, MatchResult, StableMatch, TemplateInfo

__all__ = [
    "CoarsePrefilter",
    "ExhibitMatcher",
    "MatchCandidate",
    "MatchResult",
    "PrefilterResult",
    "StableMatch",
    "TemplateInfo",
    "TemplateLibrary",
    "TemporalVoteFilter",
]
