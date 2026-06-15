"""
silmaril.backtest.data_loader

Loads multi-year OHLC history from yfinance with on-disk caching so backtests
don't re-download 4 years × 348 tickers every run. Cache lives at
~/.cache/silmaril_backtest/ and is keyed by (ticker, start, end).

Why cache: a fresh download of the full universe takes ~10 minutes and gets
yfinance throttled. Cached on second run = ~3 seconds.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

CACHE_DIR = Path(os.environ.get("SILMARIL_BACKTEST_CACHE", Path.home() / ".cache" / "silmaril_backtest"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class HistoryBundle:
    """Per-ticker OHLC history loaded once, sliced many times during replay."""
    ticker: str
    df: pd.DataFrame  # index: DatetimeIndex (UTC-naive), cols: Open, High, Low, Close, Volume
    source: str       # "yfinance" or "cache"

    def slice_as_of(self, as_of: date, lookback_days: int = 400) -> pd.DataFrame:
        """Return the df sliced strictly before `as_of` (no lookahead).
        Lookback is generous (400 days) so SMA-200 has room to settle."""
        cutoff = pd.Timestamp(as_of)
        start_floor = cutoff - timedelta(days=lookback_days)
        sliced = self.df[(self.df.index >= start_floor) & (self.df.index < cutoff)]
        return sliced


def _cache_path(ticker: str, start: date, end: date) -> Path:
    safe = ticker.replace("/", "_").replace("^", "IDX_")
    return CACHE_DIR / f"{safe}_{start.isoformat()}_{end.isoformat()}.parquet"


def load_ticker_history(
    ticker: str,
    start: date,
    end: date,
    *,
    use_cache: bool = True,
    yf_module=None,
) -> Optional[HistoryBundle]:
    """Load one ticker's OHLC history. Cache-first, then yfinance.

    Returns None on failure rather than raising — backtests should be tolerant
    of delisted/illiquid tickers in the universe.
    """
    cache_file = _cache_path(ticker, start, end)
    if use_cache and cache_file.exists():
        try:
            df = pd.read_parquet(cache_file)
            if not df.empty:
                return HistoryBundle(ticker=ticker, df=df, source="cache")
        except Exception:
            pass  # fall through to live fetch

    if yf_module is None:
        try:
            import yfinance as yf  # type: ignore
            yf_module = yf
        except ImportError:
            raise RuntimeError(
                "yfinance not installed. Run: pip install yfinance pandas pyarrow"
            )

    try:
        raw = yf_module.download(
            ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            progress=False,
            auto_adjust=False,
            threads=False,
        )
    except Exception as e:
        print(f"[backtest] yfinance error for {ticker}: {e}")
        return None

    if raw is None or raw.empty:
        return None

    # yfinance sometimes returns a multi-index column frame for single tickers
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]

    keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in raw.columns]
    df = raw[keep].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df.dropna(subset=["Close"])

    if df.empty:
        return None

    if use_cache:
        try:
            df.to_parquet(cache_file)
        except Exception as e:
            print(f"[backtest] cache write failed for {ticker}: {e}")

    return HistoryBundle(ticker=ticker, df=df, source="yfinance")


def load_universe_history(
    tickers: Iterable[str],
    start: date,
    end: date,
    *,
    use_cache: bool = True,
    rate_limit_sleep: float = 0.05,
) -> Dict[str, HistoryBundle]:
    """Load history for an entire universe. Returns ticker -> HistoryBundle."""
    out: Dict[str, HistoryBundle] = {}
    tickers = list(tickers)
    n = len(tickers)
    print(f"[backtest] loading {n} tickers from {start} to {end}")
    for i, t in enumerate(tickers, 1):
        bundle = load_ticker_history(t, start, end, use_cache=use_cache)
        if bundle is not None:
            out[t] = bundle
        if i % 25 == 0:
            print(f"[backtest]   {i}/{n} loaded ({len(out)} successful)")
        if bundle and bundle.source == "yfinance":
            time.sleep(rate_limit_sleep)  # be nice to yfinance
    print(f"[backtest] universe load complete: {len(out)}/{n} tickers")
    return out


def load_vix_series(start: date, end: date) -> Optional[pd.Series]:
    """Loads ^VIX close as a daily series for regime tagging."""
    bundle = load_ticker_history("^VIX", start, end)
    if bundle is None:
        return None
    return bundle.df["Close"]


def load_tnx_series(start: date, end: date) -> Optional[pd.Series]:
    """Loads ^TNX (10Y treasury yield) for SHEPHERD and macro agents."""
    bundle = load_ticker_history("^TNX", start, end)
    if bundle is None:
        return None
    return bundle.df["Close"]


def trading_days_between(start: date, end: date) -> List[date]:
    """Return the list of US-equity trading days in [start, end). Uses SPY as the
    reference calendar — if SPY didn't trade, neither did the rest."""
    spy = load_ticker_history("SPY", start, end)
    if spy is None:
        # fallback: weekdays only (will include some holidays but better than nothing)
        cur = start
        days: List[date] = []
        while cur < end:
            if cur.weekday() < 5:
                days.append(cur)
            cur += timedelta(days=1)
        return days
    return [d.date() for d in spy.df.index]
