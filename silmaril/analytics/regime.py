"""
silmaril.analytics.regime — Market regime classifier.

Classifies today's market into one of three regimes:
  RISK_ON   — trend up + calm volatility
  NEUTRAL   — mixed signals or consolidation
  RISK_OFF  — broken trend + elevated volatility

Inputs are SPY's price relative to its 200-day SMA and the VIX level.
Every agent sees the regime and adjusts accordingly. AEGIS uses it
directly in its veto logic.
"""

from __future__ import annotations

from typing import Optional


def classify_regime(
    spy_price: Optional[float],
    spy_sma_50: Optional[float],
    spy_sma_200: Optional[float],
    vix: Optional[float],
) -> str:
    """Return 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF'."""
    if not spy_price or not spy_sma_200:
        # Insufficient data — default to NEUTRAL
        return "NEUTRAL"

    spy_above_200 = spy_price > spy_sma_200
    spy_above_50 = spy_sma_50 and spy_price > spy_sma_50

    # Without VIX, degrade to trend-only
    if vix is None:
        return "RISK_ON" if (spy_above_200 and spy_above_50) else (
            "RISK_OFF" if not spy_above_200 else "NEUTRAL"
        )

    # RISK_OFF conditions — any one triggers it
    if vix >= 28:
        return "RISK_OFF"
    if not spy_above_200:
        return "RISK_OFF"

    # RISK_ON conditions — all must be true
    if spy_above_200 and spy_above_50 and vix < 18:
        return "RISK_ON"

    return "NEUTRAL"


def spy_trend_label(spy_price: Optional[float], spy_sma_50: Optional[float]) -> str:
    """Return 'UP' | 'DOWN' | 'FLAT'."""
    if not spy_price or not spy_sma_50:
        return "FLAT"
    pct = (spy_price - spy_sma_50) / spy_sma_50
    if pct > 0.02:
        return "UP"
    if pct < -0.02:
        return "DOWN"
    return "FLAT"
