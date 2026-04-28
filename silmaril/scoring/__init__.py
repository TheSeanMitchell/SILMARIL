"""SILMARIL v2 scoring extensions.

Regime-aware performance accounting for live-mode predictions.
The backtest module has its own metrics; this module is for the live
prediction log so the dashboard can answer 'who's good in chop?'.
"""

from .regime_sliced import (
    classify_live_regime,
    slice_by_regime,
    rank_agents_by_regime,
    build_regime_leaderboard,
)

__all__ = [
    "classify_live_regime",
    "slice_by_regime",
    "rank_agents_by_regime",
    "build_regime_leaderboard",
]
