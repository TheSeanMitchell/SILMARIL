"""
silmaril.learning.position_sizing — Volatility-targeted Kelly variant.

The Moondev video and the assessment both flag this: position sizing is
the single biggest determinant of equity-curve survival.

We use a fractional Kelly variant:
  kelly_fraction = (edge × posterior_winrate - (1 - posterior_winrate)) / vol_estimate
  position_pct = min(MAX_POSITION_PCT, KELLY_FRACTION_MULTIPLIER × kelly_fraction)

Conservative caps:
  - Per-position max: 5% of portfolio
  - Per-day risk budget: 10% (sum of all entries)
  - Kelly fraction multiplier: 0.5 (half-Kelly — sustainable, less explosive)

Used by all $1 compounders, agent portfolios, and Alpaca paper bridge.
"""
from __future__ import annotations

from typing import Optional


MAX_POSITION_PCT = 0.05
DAILY_RISK_BUDGET_PCT = 0.10
KELLY_FRACTION_MULTIPLIER = 0.5
MIN_EDGE_TO_TRADE = 0.02  # need at least 2% expected edge


def kelly_position_pct(
    posterior_winrate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    realized_vol: Optional[float] = None,
    conviction: float = 1.0,
) -> float:
    """
    Standard Kelly criterion adapted with a conviction multiplier.

    f* = (bp - q) / b
    where b = avg_win/avg_loss, p = winrate, q = 1-p

    Returns: fraction of portfolio to allocate, capped at MAX_POSITION_PCT.
    Returns 0 if expected value is negative or below minimum-edge threshold.
    """
    if avg_loss_pct <= 0 or avg_win_pct <= 0:
        return 0.0

    p = posterior_winrate
    q = 1.0 - p
    b = avg_win_pct / avg_loss_pct
    f_star = (b * p - q) / b

    # Edge check
    expected_value = p * avg_win_pct - q * avg_loss_pct
    if expected_value < MIN_EDGE_TO_TRADE:
        return 0.0
    if f_star <= 0:
        return 0.0

    # Apply fractional Kelly + conviction scaling
    f = f_star * KELLY_FRACTION_MULTIPLIER * conviction

    # Volatility scaling: reduce size in high-vol environments
    if realized_vol is not None:
        if realized_vol > 0.40:
            f *= 0.5
        elif realized_vol > 0.25:
            f *= 0.75

    return min(MAX_POSITION_PCT, max(0.0, f))


def can_open_position(
    proposed_size_pct: float,
    today_total_risk_pct: float,
) -> bool:
    """Check if proposed size fits within daily risk budget."""
    return today_total_risk_pct + proposed_size_pct <= DAILY_RISK_BUDGET_PCT
