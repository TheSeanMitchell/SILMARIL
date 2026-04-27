"""
silmaril.ingestion.prices — Price data ingestion via yfinance.

Batch-downloads OHLCV history for the entire universe in one call. Falls
back gracefully when individual tickers fail (delisted, symbol change,
weekend/holiday data gap).

yfinance is our entire price stack. It is:
  - Free (Yahoo Finance is the data source)
  - Widely supported (millions of tickers across asset classes)
  - Fast for batch downloads (concurrent underneath)
  - Reliable enough that we cache and retry on transient failures

No API keys anywhere. No paid tiers. No rate limits beyond what's sensible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

log = logging.getLogger("silmaril.prices")


@dataclass
class PriceSnapshot:
    """OHLCV + derived fields for one ticker."""
    ticker: str
    price: float
    change_pct: float
    volume: int
    avg_volume_30d: int
    closes: List[float]          # last 220 closes (enough for SMA-200 + buffer)
    highs: List[float]
    lows: List[float]

    def has_enough_history(self, min_days: int = 200) -> bool:
        return len(self.closes) >= min_days


def fetch_universe_prices(
    tickers: List[str],
    period: str = "14mo",
) -> Dict[str, PriceSnapshot]:
    """Batch-download prices for every ticker. Returns {ticker: PriceSnapshot}.

    Tickers that fail to download (rare, usually symbol issues) are silently
    omitted. The caller should handle missing tickers as 'no opinion possible'.
    """
    if not tickers:
        return {}

    # yfinance import is lazy so the rest of the package imports cleanly
    # even in environments without the dep installed yet
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed; run: pip install yfinance")
        return {}

    snapshots: Dict[str, PriceSnapshot] = {}

    try:
        # Batch download — much faster than looping
        data = yf.download(
            tickers=" ".join(tickers),
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            prepost=False,
            threads=True,
            progress=False,
        )
    except Exception as e:
        log.exception("Batch yfinance download failed: %s", e)
        return {}

    for ticker in tickers:
        try:
            # When a single ticker is requested, data has flat columns;
            # for multi-ticker, data is grouped by ticker as the top level.
            if len(tickers) == 1:
                df = data
            else:
                if ticker not in data.columns.levels[0]:
                    continue
                df = data[ticker]

            # Drop rows that are all NaN (e.g. market-closed days)
            df = df.dropna(subset=["Close"])
            if df.empty or len(df) < 2:
                continue

            closes = df["Close"].tolist()
            highs = df["High"].tolist()
            lows = df["Low"].tolist()
            volumes = df["Volume"].tolist()

            price = float(closes[-1])
            prev = float(closes[-2])
            change_pct = ((price / prev) - 1.0) * 100.0 if prev else 0.0

            volume = int(volumes[-1]) if volumes[-1] and volumes[-1] == volumes[-1] else 0
            recent_vols = [v for v in volumes[-30:] if v and v == v]
            avg_vol = int(sum(recent_vols) / len(recent_vols)) if recent_vols else 0

            snapshots[ticker] = PriceSnapshot(
                ticker=ticker,
                price=price,
                change_pct=change_pct,
                volume=volume,
                avg_volume_30d=avg_vol,
                closes=[float(c) for c in closes[-220:]],
                highs=[float(h) for h in highs[-220:]],
                lows=[float(l) for l in lows[-220:]],
            )
        except Exception as e:
            log.warning("Could not parse %s: %s", ticker, e)
            continue

    log.info("Fetched prices for %d/%d tickers", len(snapshots), len(tickers))
    return snapshots


def fetch_vix() -> Optional[float]:
    """Fetch latest VIX close. Returns None if unavailable."""
    snap = fetch_universe_prices(["^VIX"], period="5d")
    v = snap.get("^VIX")
    return v.price if v else None


def fetch_earnings_dates(tickers: List[str]) -> Dict[str, Optional[str]]:
    """Fetch next earnings date per ticker via yfinance calendar.

    Best-effort. Tickers without known earnings (ETFs, indices, crypto) return None.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {t: None for t in tickers}

    results: Dict[str, Optional[str]] = {}
    for tkr in tickers:
        try:
            ticker_obj = yf.Ticker(tkr)
            cal = ticker_obj.calendar
            if cal is None or (hasattr(cal, "empty") and cal.empty):
                results[tkr] = None
                continue
            # yfinance returns either a DataFrame or dict depending on version
            if isinstance(cal, dict):
                date = cal.get("Earnings Date")
                if isinstance(date, list) and date:
                    results[tkr] = str(date[0])[:10]
                else:
                    results[tkr] = None
            else:
                # DataFrame path
                if "Earnings Date" in cal.index:
                    val = cal.loc["Earnings Date"].iloc[0]
                    results[tkr] = str(val)[:10] if val else None
                else:
                    results[tkr] = None
        except Exception:
            results[tkr] = None

    return results
