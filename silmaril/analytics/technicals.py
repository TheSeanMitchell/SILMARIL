"""
silmaril.analytics.technicals — Pure-Python technical indicators.

Computes SMA, RSI, ATR, and Bollinger-band width from a list of closes
(or highs/lows/closes where applicable). No numpy required — we keep it
dependency-free for portability and for ease of reasoning.

Performance is not a concern: even 100 tickers × 5 indicators = 500 quick
loops over ~200-point arrays.
"""

from __future__ import annotations

from typing import List, Optional


def sma(closes: List[float], period: int) -> Optional[float]:
    """Simple moving average over the last `period` closes."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    return sum(window) / period


def rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """Relative Strength Index (Wilder's smoothing)."""
    if len(closes) < period + 1:
        return None

    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        if delta > 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-delta)

    # Initial average over the first `period` diffs
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder's smoothing for the rest
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
    """Average True Range over `period` bars. Skips NaN data points."""
    import math
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        h, l, c_prev = highs[i], lows[i], closes[i - 1]
        if any(x is None or (isinstance(x, float) and math.isnan(x)) for x in (h, l, c_prev)):
            continue
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        trs.append(tr)
    if len(trs) < period:
        return None
    atr_val = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr_val = (atr_val * (period - 1) + trs[i]) / period
    if math.isnan(atr_val) or math.isinf(atr_val):
        return None
    return atr_val


def bollinger_width(closes: List[float], period: int = 20, stdev_mult: float = 2.0) -> Optional[float]:
    """Width of Bollinger bands as a fraction of the middle band.

    Returns (upper - lower) / middle, a unitless measure of volatility.
    A narrow value (< 0.05) means the bands are coiled — often precedes a breakout.
    """
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    stdev = variance ** 0.5
    if mean == 0:
        return None
    return (2 * stdev_mult * stdev) / mean


def percent_above(price: float, reference: Optional[float]) -> Optional[float]:
    """Return (price - reference) / reference. None-safe."""
    if not reference or reference == 0:
        return None
    return (price - reference) / reference


def n_period_return(closes: List[float], n_bars: int) -> Optional[float]:
    """Return (closes[-1] / closes[-1-n_bars]) - 1.0.

    Alpha 3.2 — used by the 3-month downtrend filter and the conviction
    engine's momentum quality score. Returns None when there isn't enough
    history. Treats `n_bars` as a count of bars BACK from the most recent
    close — so n_bars=63 on daily closes ≈ 3 calendar months.
    """
    if not closes or n_bars <= 0:
        return None
    if len(closes) < n_bars + 1:
        return None
    past = closes[-1 - n_bars]
    last = closes[-1]
    if not past or past == 0:
        return None
    try:
        return (last / past) - 1.0
    except Exception:
        return None


def three_month_return(closes: List[float]) -> Optional[float]:
    """Convenience wrapper: ~3 calendar months ≈ 63 trading days."""
    return n_period_return(closes, 63)


def consecutive_drops(snapshots: List[float], threshold: float = -0.005) -> int:
    """Count how many of the most recent consecutive interval-returns are at
    or below `threshold` (default -0.5%). Returns 0 if fewer than 2 snapshots.

    Used by the 30-minute bleed-exit detector in
    `silmaril.portfolios.bleed_exit` to decide whether a held position has
    been bleeding for four consecutive 30-min windows.
    """
    if not snapshots or len(snapshots) < 2:
        return 0
    streak = 0
    # Walk pairs from latest backwards
    for i in range(len(snapshots) - 1, 0, -1):
        prev = snapshots[i - 1]
        cur = snapshots[i]
        if not prev or prev == 0:
            break
        ret = (cur - prev) / prev
        if ret <= threshold:
            streak += 1
        else:
            break
    return streak


def highest_in(closes: List[float], lookback: int) -> Optional[float]:
    """Highest close in the last `lookback` bars."""
    if len(closes) < lookback:
        return None
    return max(closes[-lookback:])


def lowest_in(closes: List[float], lookback: int) -> Optional[float]:
    """Lowest close in the last `lookback` bars."""
    if len(closes) < lookback:
        return None
    return min(closes[-lookback:])


def compute_all(closes: List[float], highs: List[float], lows: List[float]) -> dict:
    """Compute every indicator. Returns dict with None for anything too short
    or numerically degenerate (NaN/Inf)."""
    import math
    raw = {
        "sma_20":   sma(closes, 20),
        "sma_50":   sma(closes, 50),
        "sma_200":  sma(closes, 200),
        "rsi_14":   rsi(closes, 14),
        "atr_14":   atr(highs, lows, closes, 14),
        "bb_width": bollinger_width(closes, 20),
    }
    out = {}
    for k, v in raw.items():
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            out[k] = None
        else:
            out[k] = v
    return out
