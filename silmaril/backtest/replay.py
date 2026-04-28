"""
silmaril.backtest.replay

Builds point-in-time AssetContext objects from historical OHLCV data
so the real SILMARIL agents can be replayed against past markets.

Key invariant: as of date `D`, every field on the context is computed
from data strictly available at the close of `D` (or earlier). The
next-day return is computed separately for outcome scoring and is
NEVER visible to the agent at decision time.

Sentiment, headlines, and news fields are nulled out in backtest mode
because we don't have a historical news archive. Agents that depend
on those (VEIL, SPECK) will produce HOLD/ABSTAIN — expected behavior,
flagged in the metrics report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .data_loader import HistoryBundle

# Import the REAL AssetContext that the SILMARIL agents read.
from silmaril.agents.base import AssetContext


def _safe_last(series: pd.Series) -> Optional[float]:
    if series is None or len(series) == 0:
        return None
    val = series.iloc[-1]
    if pd.isna(val) or not np.isfinite(val):
        return None
    return float(val)


def compute_indicators(df: pd.DataFrame) -> Dict[str, Optional[float]]:
    """Compute SMA/RSI/ATR/Bollinger from a price slice. Latest value of each."""
    if df is None or df.empty or "Close" not in df.columns:
        return {k: None for k in ("sma_20", "sma_50", "sma_200", "rsi_14", "atr_14",
                                   "bb_width", "macd_signal", "momentum_20d", "volatility_20d")}

    close = df["Close"]
    high = df.get("High", close)
    low = df.get("Low", close)

    out: Dict[str, Optional[float]] = {}

    out["sma_20"]  = _safe_last(close.rolling(20).mean())  if len(close) >= 20 else None
    out["sma_50"]  = _safe_last(close.rolling(50).mean())  if len(close) >= 50 else None
    out["sma_200"] = _safe_last(close.rolling(200).mean()) if len(close) >= 200 else None

    if len(close) >= 15:
        delta = close.diff()
        gains = delta.where(delta > 0, 0.0).rolling(14).mean()
        losses = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gains / losses.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        out["rsi_14"] = _safe_last(rsi)
    else:
        out["rsi_14"] = None

    if len(close) >= 15:
        prev_close = close.shift(1)
        tr = pd.concat([(high - low),
                        (high - prev_close).abs(),
                        (low - prev_close).abs()], axis=1).max(axis=1)
        out["atr_14"] = _safe_last(tr.rolling(14).mean())
    else:
        out["atr_14"] = None

    if len(close) >= 20:
        ma20 = close.rolling(20).mean()
        sd20 = close.rolling(20).std()
        bb_width = (4 * sd20) / ma20
        out["bb_width"] = _safe_last(bb_width)
    else:
        out["bb_width"] = None

    if len(close) >= 26:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        out["macd_signal"] = _safe_last(macd - signal)
    else:
        out["macd_signal"] = None

    if len(close) >= 21:
        rets = close.pct_change()
        out["momentum_20d"]   = float(close.iloc[-1] / close.iloc[-21] - 1.0)
        out["volatility_20d"] = _safe_last(rets.rolling(20).std())
    else:
        out["momentum_20d"]   = None
        out["volatility_20d"] = None

    return out


def classify_regime(vix: Optional[float], spy_momentum_20d: Optional[float]) -> str:
    """Coarse regime tag for regime-sliced scoring."""
    if vix is None and spy_momentum_20d is None:
        return "UNKNOWN"
    v = vix if vix is not None else 18.0
    m = spy_momentum_20d if spy_momentum_20d is not None else 0.0
    if v >= 28:
        return "BEAR"
    if v >= 20 and m < 0:
        return "BEAR"
    if v < 16 and m > 0.02:
        return "BULL"
    if abs(m) < 0.02:
        return "CHOP"
    return "BULL" if m > 0 else "BEAR"


# Map backtest regime strings to the live regime strings agents expect.
# Live: RISK_ON / RISK_OFF / NEUTRAL
# Backtest: BULL / BEAR / CHOP / UNKNOWN
_REGIME_MAP = {
    "BULL": "RISK_ON",
    "BEAR": "RISK_OFF",
    "CHOP": "NEUTRAL",
    "UNKNOWN": "NEUTRAL",
}


def _regime_to_live(regime: str) -> str:
    return _REGIME_MAP.get(regime, "NEUTRAL")


def detect_asset_class(ticker: str) -> str:
    """Classify a ticker. Mirrors silmaril.universe.core.asset_class_of()."""
    t = ticker.upper()
    if t.endswith("-USD"):
        return "crypto"
    if t in {"UUP", "UDN", "FXE", "FXY", "FXF", "FXB", "FXC", "FXA"}:
        return "fx"
    if t in {"GLD", "IAU", "GDX", "GDXJ", "SLV", "SIVR", "PPLT", "PALL", "CPER",
             "USO", "BNO", "UCO", "SCO", "UNG"}:
        return "commodity"
    etf_prefixes = ("SPY", "QQQ", "IWM", "DIA", "VTI", "EFA", "EEM", "XL", "XOP",
                    "VOO", "BND", "TLT", "HYG", "LQD", "IBB", "XBI", "IYR", "SMH",
                    "SOXX", "ARKK", "AGG", "IEF", "SHY")
    if any(t.startswith(p) for p in etf_prefixes):
        return "etf"
    return "equity"


def build_context(
    ticker: str,
    bundle: HistoryBundle,
    as_of: date,
    *,
    vix_level: Optional[float] = None,
    tnx_level: Optional[float] = None,
    regime: str = "UNKNOWN",
    market_state: Optional[Dict[str, Any]] = None,
) -> Optional[AssetContext]:
    """Build a real AssetContext for `ticker` as of `as_of`.

    Returns None if there isn't enough history to make a meaningful
    decision (less than 30 trading days available).
    """
    history = bundle.slice_as_of(as_of, lookback_days=400)
    if history.empty or len(history) < 30:
        return None

    todays_row = bundle.df[bundle.df.index == pd.Timestamp(as_of)]
    if todays_row.empty:
        return None  # asset didn't trade today

    row = todays_row.iloc[0]
    indicators = compute_indicators(history)

    # Price history as a list of floats (what real agents expect)
    price_history: List[float] = [
        float(c) for c in history["Close"].tolist() if pd.notna(c)
    ]

    # Day-over-day change percentage
    if len(history) >= 2:
        prev_close = float(history["Close"].iloc[-2])
        today_close = float(row["Close"])
        change_pct = (today_close - prev_close) / prev_close * 100.0 if prev_close else 0.0
    else:
        change_pct = 0.0

    # Average volume (best-effort 30-day rolling)
    avg_volume_30d = None
    if "Volume" in history.columns and len(history) >= 30:
        avg_volume_30d = int(history["Volume"].tail(30).mean())

    return AssetContext(
        ticker=ticker,
        name=ticker,                                  # we don't have name lookup in backtest
        sector=None,
        asset_class=detect_asset_class(ticker),
        price=float(row["Close"]),
        change_pct=change_pct,
        volume=int(row.get("Volume", 0) or 0),
        avg_volume_30d=avg_volume_30d,
        price_history=price_history,
        sma_20=indicators["sma_20"],
        sma_50=indicators["sma_50"],
        sma_200=indicators["sma_200"],
        rsi_14=indicators["rsi_14"],
        atr_14=indicators["atr_14"],
        bb_width=indicators["bb_width"],
        sentiment_score=None,                         # no historical news in backtest
        article_count=0,
        source_count=0,
        recent_headlines=[],
        earnings_date=None,
        days_to_earnings=None,
        event_flags=[],
        correlations={},
        market_regime=_regime_to_live(regime),
        vix=vix_level,
    )


def next_day_return(bundle: HistoryBundle, as_of: date) -> Optional[float]:
    """Next-day price change for outcome scoring. None if no next bar."""
    df = bundle.df
    idx = df.index.get_indexer([pd.Timestamp(as_of)], method=None)
    if len(idx) == 0 or idx[0] == -1 or idx[0] + 1 >= len(df):
        return None
    today_close = df["Close"].iloc[idx[0]]
    next_close = df["Close"].iloc[idx[0] + 1]
    if pd.isna(today_close) or pd.isna(next_close) or today_close == 0:
        return None
    return float(next_close / today_close - 1.0)
