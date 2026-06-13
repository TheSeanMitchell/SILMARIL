"""
silmaril.ingestion.prices — Price ingestion: yfinance history + keyed fresh quotes.

Batch-downloads OHLCV *history* for the entire universe from yfinance in one
call (stable daily bars, used for technicals), then — ALPHA 7.0 — overlays a
*fresh real-time quote* onto the `price` field from a keyed data provider so
the price the learning loop scores against is current.

WHY THE OVERLAY EXISTS
──────────────────────
Previously yfinance daily closes were the entire price stack. In GitHub
Actions, yfinance is frequently rate-limited/blocked and returns the same
last close on repeated runs; on weekends/after-hours the "latest" bar is
unchanged. The scorer then saw entry == exit (~89% of outcomes flagged
stale_price_suspected), which corrupted win rates and the learning loop.
A fresh quote on the `price` field makes entry != exit across runs/days,
so far more outcomes are clean.

FRESH-QUOTE PROVIDERS (tried in batch-friendly order; first hit wins per ticker)
  1. FMP            /api/v3/quote/{symbols}        (true batch)   FMP_API_KEY
  2. Tiingo IEX     /iex/?tickers={symbols}        (true batch)   TIINGO_API_KEY
  3. Twelve Data    /quote?symbol={symbols}        (batch, small) TWELVEDATA_API_KEY
  4. Finnhub        /quote?symbol={sym}            (per-ticker)   FINNHUB_API_KEY

The overlay is BEST-EFFORT and fully guarded: any missing key, HTTP error,
rate limit, or parse failure leaves that ticker on its yfinance value. With
no keys at all, behaviour is identical to the previous yfinance-only stack.
Only plausibly-equity symbols are overlaid; indices ("^VIX") and crypto
("SOL-USD") keep their yfinance price. Each snapshot records `source` and
`as_of` so downstream/diagnostics can see provenance. The scorer's stale
guard remains the final safety net regardless of source.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
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
    # ALPHA 7.0 provenance: where `price` came from and as-of when.
    source: str = "yfinance"     # "fmp" | "tiingo" | "twelvedata" | "finnhub" | "yfinance"
    as_of: str = ""              # ISO timestamp of the fresh quote, "" if yfinance close

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

    # ALPHA 7.0: overlay fresh real-time quotes onto the `price` field so the
    # scorer sees current prices instead of a repeated daily close. Fully
    # guarded — on ANY failure the yfinance values are retained unchanged.
    try:
        _overlay_fresh_quotes(snapshots)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("fresh-quote overlay skipped (yfinance prices retained): %s", e)

    return snapshots


# ──────────────────────────────────────────────────────────────────
# ALPHA 7.0 — keyed fresh-quote overlay
# ──────────────────────────────────────────────────────────────────

import re as _re

_OVERLAY_TIMEOUT = 8          # seconds per HTTP call
_OVERLAY_CHUNK = 90           # symbols per batch request
_EQUITY_RE = _re.compile(r"^[A-Z]{1,6}$")   # plain equities/ETFs only


def _overlay_eligible(tickers: List[str]) -> List[str]:
    """Plain equity/ETF symbols only — skip indices (^VIX), crypto (SOL-USD),
    FX, and share-class tickers (BRK-B) whose symbol format differs per provider."""
    return [t for t in tickers if _EQUITY_RE.match(t or "")]


def _chunks(seq: List[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _fmp_quotes(tickers: List[str], key: str) -> Dict[str, float]:
    """FMP batch quote: /api/v3/quote/SYM1,SYM2,..."""
    import requests
    out: Dict[str, float] = {}
    for chunk in _chunks(tickers, _OVERLAY_CHUNK):
        url = f"https://financialmodelingprep.com/api/v3/quote/{','.join(chunk)}"
        try:
            r = requests.get(url, params={"apikey": key}, timeout=_OVERLAY_TIMEOUT)
            if r.status_code != 200:
                continue
            for row in r.json() or []:
                sym = row.get("symbol")
                px = row.get("price")
                if sym and isinstance(px, (int, float)) and px > 0:
                    out[sym] = float(px)
        except Exception as e:
            log.debug("FMP quote chunk failed: %s", e)
    return out


def _tiingo_quotes(tickers: List[str], key: str) -> Dict[str, float]:
    """Tiingo IEX batch: /iex/?tickers=SYM1,SYM2,..."""
    import requests
    out: Dict[str, float] = {}
    for chunk in _chunks(tickers, _OVERLAY_CHUNK):
        try:
            r = requests.get(
                "https://api.tiingo.com/iex/",
                params={"tickers": ",".join(chunk), "token": key},
                headers={"Content-Type": "application/json"},
                timeout=_OVERLAY_TIMEOUT,
            )
            if r.status_code != 200:
                continue
            for row in r.json() or []:
                sym = (row.get("ticker") or "").upper()
                px = row.get("last") or row.get("tngoLast") or row.get("lastSalePrice")
                if sym and isinstance(px, (int, float)) and px > 0:
                    out[sym] = float(px)
        except Exception as e:
            log.debug("Tiingo quote chunk failed: %s", e)
    return out


def _twelvedata_quotes(tickers: List[str], key: str) -> Dict[str, float]:
    """Twelve Data batch quote: /quote?symbol=SYM1,SYM2,... (small chunks)."""
    import requests
    out: Dict[str, float] = {}
    for chunk in _chunks(tickers, 40):
        try:
            r = requests.get(
                "https://api.twelvedata.com/quote",
                params={"symbol": ",".join(chunk), "apikey": key},
                timeout=_OVERLAY_TIMEOUT,
            )
            if r.status_code != 200:
                continue
            data = r.json() or {}
            # Single symbol → one object; multiple → dict keyed by symbol.
            rows = data.values() if (isinstance(data, dict) and "symbol" not in data) else [data]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sym = (row.get("symbol") or "").upper()
                raw = row.get("close") or row.get("price")
                try:
                    px = float(raw)
                except (TypeError, ValueError):
                    continue
                if sym and px > 0:
                    out[sym] = px
        except Exception as e:
            log.debug("TwelveData quote chunk failed: %s", e)
    return out


def _finnhub_quotes(tickers: List[str], key: str) -> Dict[str, float]:
    """Finnhub per-symbol quote: /quote?symbol=SYM. Capped to avoid rate limits."""
    import requests
    out: Dict[str, float] = {}
    for sym in tickers[:120]:   # 60/min free tier — cap to stay safe per cycle
        try:
            r = requests.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": sym, "token": key},
                timeout=_OVERLAY_TIMEOUT,
            )
            if r.status_code != 200:
                continue
            px = (r.json() or {}).get("c")   # current price
            if isinstance(px, (int, float)) and px > 0:
                out[sym] = float(px)
        except Exception as e:
            log.debug("Finnhub quote failed for %s: %s", sym, e)
    return out


def _overlay_fresh_quotes(snapshots: Dict[str, "PriceSnapshot"]) -> None:
    """Overlay fresh real-time quotes onto snapshot.price in place.

    Tries batch-friendly providers in order; the first provider to return a
    price for a ticker wins. Untouched tickers keep their yfinance close.
    """
    if not snapshots:
        return
    eligible = _overlay_eligible(list(snapshots.keys()))
    if not eligible:
        return

    providers = [
        ("fmp",        os.getenv("FMP_API_KEY"),        _fmp_quotes),
        ("tiingo",     os.getenv("TIINGO_API_KEY"),     _tiingo_quotes),
        ("twelvedata", os.getenv("TWELVEDATA_API_KEY"), _twelvedata_quotes),
        ("finnhub",    os.getenv("FINNHUB_API_KEY"),    _finnhub_quotes),
    ]
    if not any(key for _, key, _ in providers):
        log.info("fresh-quote overlay: no provider keys set — using yfinance closes")
        return

    fresh: Dict[str, float] = {}        # ticker -> price
    src_of: Dict[str, str] = {}         # ticker -> provider name
    for name, key, fn in providers:
        if not key:
            continue
        remaining = [t for t in eligible if t not in fresh]
        if not remaining:
            break
        try:
            got = fn(remaining, key)
        except Exception as e:
            log.debug("fresh-quote provider %s failed wholesale: %s", name, e)
            got = {}
        for t, px in got.items():
            if t not in fresh and isinstance(px, (int, float)) and px > 0:
                fresh[t] = float(px)
                src_of[t] = name
        if got:
            log.info("fresh-quote overlay: %s supplied %d quotes", name, len(got))

    if not fresh:
        log.warning("fresh-quote overlay: providers returned nothing — yfinance retained")
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    applied = 0
    for ticker, px in fresh.items():
        snap = snapshots.get(ticker)
        if snap is None:
            continue
        # Recompute change_pct against the prior daily close (closes[-2]).
        prev = snap.closes[-2] if len(snap.closes) >= 2 else (
            snap.closes[-1] if snap.closes else None)
        snap.price = px
        snap.change_pct = ((px / prev) - 1.0) * 100.0 if prev else snap.change_pct
        snap.source = src_of.get(ticker, "yfinance")
        snap.as_of = now_iso
        applied += 1

    log.info(
        "fresh-quote overlay: applied %d/%d fresh prices (%d kept on yfinance)",
        applied, len(eligible), len(eligible) - applied,
    )


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
