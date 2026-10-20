"""Sliding-window voting that turns per-frame matches into stable IDs."""

from __future__ import annotations

from collections import Counter, deque
from typing import Deque, Optional, Tuple

from .types import MatchResult, StableMatch

# (template_id, display_name, confidence, template_index)
_Entry = Tuple[Optional[str], Optional[str], float, Optional[int]]


class TemporalVoteFilter:
    """Require repeated agreement before reporting an exhibit.

    ``window`` and ``hold_results`` count *matching results*, not video frames.
    Use :meth:`from_seconds` when the matching rate is known so changing
    ``--match-every`` does not change the effective smoothing duration.
    """

    @classmethod
    def from_seconds(
        cls,
        window_s: float,
        min_vote_ratio: float,
        hold_s: float,
        match_rate: float,
    ) -> "TemporalVoteFilter":
        """Build a count-based filter from time-based settings.

        ``match_rate`` is matching results per second (for example
        ``video_fps / match_every``).
        """

        if match_rate <= 0:
            raise ValueError("match_rate must be positive")
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        if not 0.0 < min_vote_ratio <= 1.0:
            raise ValueError("min_vote_ratio must be in (0, 1]")
        if hold_s < 0:
            raise ValueError("hold_s must be non-negative")
        window = max(1, int(round(window_s * match_rate)))
        min_votes = max(1, min(window, int(round(min_vote_ratio * window))))
        hold_results = max(0, int(round(hold_s * match_rate)))
        return cls(window=window, min_votes=min_votes, hold_results=hold_results)

    def __init__(self, window: int = 5, min_votes: int = 3, hold_results: int = 8) -> None:
        if window < 1:
            raise ValueError("window must be at least 1")
        if not 1 <= min_votes <= window:
            raise ValueError("min_votes must be between 1 and window")
        if hold_results < 0:
            raise ValueError("hold_results must be non-negative")
        self.window = int(window)
        self.min_votes = int(min_votes)
        self.hold_results = int(hold_results)
        self._history: Deque[_Entry] = deque(maxlen=self.window)
        self._stable_id: Optional[str] = None
        self._stable_name: Optional[str] = None
        self._stable_index: Optional[int] = None
        self._stable_confidence = 0.0
        self._since_stable = 0

    def reset(self) -> None:
        self._history.clear()
        self._clear_stable()
        self._since_stable = 0

    def update(self, result: Optional[MatchResult]) -> StableMatch:
        accepted = bool(result is not None and result.accepted and result.best is not None)
        if accepted:
            best = result.best
            self._history.append(
                (best.template_id, best.display_name, best.confidence, best.info.index)
            )
        else:
            self._history.append((None, None, 0.0, None))

        counts = Counter(entry[0] for entry in self._history if entry[0] is not None)
        if counts:
            top_id, votes = counts.most_common(1)[0]
            if votes >= self.min_votes:
                entries = [entry for entry in self._history if entry[0] == top_id]
                self._stable_id = top_id
                self._stable_name = entries[-1][1]
                self._stable_index = entries[-1][3]
                self._stable_confidence = sum(entry[2] for entry in entries) / float(len(entries))
                self._since_stable = 0
                return StableMatch(
                    template_id=self._stable_id,
                    display_name=self._stable_name,
                    confidence=self._stable_confidence,
                    raw_accepted=True,
                    reason=None,
                    template_index=self._stable_index,
                )

        self._since_stable += 1
        if self._since_stable > self.hold_results:
            self._clear_stable()

        reason = None
        if self._stable_id is None:
            if result is not None and result.unknown_reason:
                reason = result.unknown_reason
            else:
                reason = "no_stable_match"
        return StableMatch(
            template_id=self._stable_id,
            display_name=self._stable_name,
            confidence=self._stable_confidence,
            raw_accepted=accepted,
            reason=reason,
            template_index=self._stable_index,
        )

    def _clear_stable(self) -> None:
        self._stable_id = None
        self._stable_name = None
        self._stable_index = None
        self._stable_confidence = 0.0


__all__ = ["TemporalVoteFilter"]
