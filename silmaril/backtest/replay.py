"""
silmaril.backtest.replay

Day-by-day replay machinery. For each historical date, slices history with no
lookahead, computes technical indicators on the slice, builds an
AssetContext-shaped object, and runs each registered agent's judge() on it.

Critical no-lookahead rule: when replaying day D, agents only see data with
index < D. This is enforced in HistoryBundle.slice_as_of().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Protocol

import numpy as np
import pandas as pd

from .data_loader import HistoryBundle


class AgentLike(Protocol):
    """Duck-typed agent interface. Real silmaril.agents.base.Agent satisfies this."""
    name: str
    def judge(self, ctx: Any) -> Any: ...


@dataclass
class BacktestContext:
    """Mimics AssetContext shape but built from a strictly-prior history slice.

    Sentiment, headlines, and live-news fields are nulled out in backtest mode
    because we don't have a historical news archive. Agents that depend on
    those fields (VEIL, SPECK) will produce HOLD/ABSTAIN; this is expected and
    flagged in the metrics report.
    """
    ticker: str
    asset_class: str
    as_of: date

    # price / volume
    price: float
    prior_close: float
    open_today: float
    high_today: float
    low_today: float
    volume_today: float

    # window slices (DataFrame, OHLCV, indexed by date, ALL strictly before as_of)
    history: pd.DataFrame

    # technical indicators
    sma_20: Optional[float]
    sma_50: Optional[float]
    sma_200: Optional[float]
    rsi_14: Optional[float]
    atr_14: Optional[float]
    bband_width: Optional[float]
    macd_signal: Optional[float]
    momentum_20d: Optional[float]   # pct change over 20 days
    volatility_20d: Optional[float] # stdev of daily returns over 20 days

    # market state (populated by orchestrator from VIX/TNX series)
    vix_level: Optional[float] = None
    tnx_level: Optional[float] = None
    regime: str = "UNKNOWN"

    # nullable in backtest
    sentiment_score: float = 0.0
    headlines: List[Dict[str, Any]] = field(default_factory=list)

    # cross-asset hooks (populated by orchestrator if needed)
    market_state: Dict[str, Any] = field(default_factory=dict)

    # backtest metadata
    backtest_mode: bool = True
    sentiment_available: bool = False  # always False in backtest unless we wire historical news


def _safe_last(series: pd.Series) -> Optional[float]:
    if series is None or len(series) == 0:
        return None
    val = series.iloc[-1]
    if pd.isna(val) or not np.isfinite(val):
        return None
    return float(val)


def compute_indicators(df: pd.DataFrame) -> Dict[str, Optional[float]]:
    """Compute SMA/RSI/ATR/Bollinger from a price slice. Returns dict of latest values."""
    if df is None or df.empty or "Close" not in df.columns:
        return {k: None for k in ("sma_20", "sma_50", "sma_200", "rsi_14", "atr_14",
                                   "bband_width", "macd_signal", "momentum_20d", "volatility_20d")}

    close = df["Close"]
    high = df.get("High", close)
    low = df.get("Low", close)

    out: Dict[str, Optional[float]] = {}

    # Simple moving averages
    out["sma_20"]  = _safe_last(close.rolling(20).mean())  if len(close) >= 20 else None
    out["sma_50"]  = _safe_last(close.rolling(50).mean())  if len(close) >= 50 else None
    out["sma_200"] = _safe_last(close.rolling(200).mean()) if len(close) >= 200 else None

    # RSI 14
    if len(close) >= 15:
        delta = close.diff()
        gains = delta.where(delta > 0, 0.0).rolling(14).mean()
        losses = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gains / losses.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        out["rsi_14"] = _safe_last(rsi)
    else:
        out["rsi_14"] = None

    # ATR 14
    if len(close) >= 15:
        prev_close = close.shift(1)
        tr = pd.concat([(high - low),
                        (high - prev_close).abs(),
                        (low - prev_close).abs()], axis=1).max(axis=1)
        out["atr_14"] = _safe_last(tr.rolling(14).mean())
    else:
        out["atr_14"] = None

    # Bollinger band width (2 stdev / mean) over 20d
    if len(close) >= 20:
        ma20 = close.rolling(20).mean()
        sd20 = close.rolling(20).std()
        bb_width = (4 * sd20) / ma20  # upper-lower / mean
        out["bband_width"] = _safe_last(bb_width)
    else:
        out["bband_width"] = None

    # MACD signal-line cross approximation
    if len(close) >= 26:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        out["macd_signal"] = _safe_last(macd - signal)
    else:
        out["macd_signal"] = None

    # 20-day momentum + volatility
    if len(close) >= 21:
        rets = close.pct_change()
        out["momentum_20d"]   = float(close.iloc[-1] / close.iloc[-21] - 1.0)
        out["volatility_20d"] = _safe_last(rets.rolling(20).std())
    else:
        out["momentum_20d"]   = None
        out["volatility_20d"] = None

    return out


def classify_regime(vix: Optional[float], spy_momentum_20d: Optional[float]) -> str:
    """Coarse regime tag. Used for regime-sliced scoring later."""
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


def detect_asset_class(ticker: str) -> str:
    """Mirror of frontend detectAssetClass()."""
    t = ticker.upper()
    if t.endswith("-USD"):
        TOKENS = {"PEPE","FLOKI","BONK","WIF","MOG","TURBO","BRETT","POPCAT","SHIB",
                  "JTO","ENA","PYTH","TIA","DYM","ALT","STRK","MEW","PNUT","ARB"}
        base = t.replace("-USD", "")
        return "token" if base in TOKENS else "crypto"
    if t in {"UUP","UDN","FXE","FXY","FXF","FXB","FXC","FXA"}:
        return "fx"
    if t in {"GLD","IAU","GDX","GDXJ","SLV","SIVR","PPLT","PALL","CPER"}:
        return "commodities"
    if t in {"USO","BNO","UCO","SCO","DRIP","UNG","BOIL","KOLD",
             "XLE","XOP","OIH","GUSH","AMLP"}:
        return "energy"
    etf_prefixes = ("SPY","QQQ","IWM","DIA","VTI","EFA","EEM","XL","XOP","VOO",
                    "BND","TLT","HYG","LQD","IBB","XBI","IYR","SMH","SOXX","ARKK")
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
) -> Optional[BacktestContext]:
    """Builds a BacktestContext for `ticker` as of `as_of`. None if insufficient history."""
    history = bundle.slice_as_of(as_of, lookback_days=400)
    if history.empty:
        return None

    # Today's bar (the bar with date == as_of, if it exists in the original df)
    todays_row = bundle.df[bundle.df.index == pd.Timestamp(as_of)]
    if todays_row.empty:
        # Some assets don't trade today (holidays, etc). Skip.
        return None

    row = todays_row.iloc[0]
    indicators = compute_indicators(history)

    return BacktestContext(
        ticker=ticker,
        asset_class=detect_asset_class(ticker),
        as_of=as_of,
        price=float(history["Close"].iloc[-1]) if not history.empty else float(row["Close"]),
        prior_close=float(history["Close"].iloc[-1]) if not history.empty else float(row["Close"]),
        open_today=float(row.get("Open", row["Close"])),
        high_today=float(row.get("High", row["Close"])),
        low_today=float(row.get("Low", row["Close"])),
        volume_today=float(row.get("Volume", 0)),
        history=history,
        sma_20=indicators["sma_20"],
        sma_50=indicators["sma_50"],
        sma_200=indicators["sma_200"],
        rsi_14=indicators["rsi_14"],
        atr_14=indicators["atr_14"],
        bband_width=indicators["bband_width"],
        macd_signal=indicators["macd_signal"],
        momentum_20d=indicators["momentum_20d"],
        volatility_20d=indicators["volatility_20d"],
        vix_level=vix_level,
        tnx_level=tnx_level,
        regime=regime,
        market_state=market_state or {},
    )


def next_day_return(bundle: HistoryBundle, as_of: date) -> Optional[float]:
    """Compute the next-day price change for outcome scoring. Returns None if no next bar."""
    df = bundle.df
    idx = df.index.get_indexer([pd.Timestamp(as_of)], method=None)
    if len(idx) == 0 or idx[0] == -1 or idx[0] + 1 >= len(df):
        return None
    today_close = df["Close"].iloc[idx[0]]
    next_close = df["Close"].iloc[idx[0] + 1]
    if pd.isna(today_close) or pd.isna(next_close) or today_close == 0:
        return None
    return float(next_close / today_close - 1.0)
