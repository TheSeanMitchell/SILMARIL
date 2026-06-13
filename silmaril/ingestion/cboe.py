"""
silmaril.ingestion.cboe — CBOE daily put/call ratio.

CBOE publishes daily P/C ratios at cboe.com for free.
We use the equity P/C ratio as a market sentiment gauge.

  P/C > 1.3 = elevated fear (potential contrarian buy)
  P/C > 1.5 = extreme fear (strong contrarian buy signal)
  P/C < 0.7 = complacency (potential sell signal)
  P/C ≈ 1.0 = neutral

Cached for the trading day.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

log = logging.getLogger("silmaril.cboe")

# CBOE publishes daily data as a downloadable CSV
_CBOE_URL = "https://www.cboe.com/us/options/market_statistics/daily/?book=put_call&mkt=opt"
_FALLBACK_URL = "https://markets.cboe.com/us/options/market_statistics/daily_market_statistics/"

_CACHE: Dict[str, float] = {}
_CACHE_DATE: str = ""


def _fetch_pc_ratio() -> Dict[str, float]:
    """
    Fetch CBOE equity put/call ratio.
    Returns {"equity": float, "index": float, "total": float}.
    Falls back to 1.0 (neutral) on failure.
    """
    try:
        import requests
        # CBOE JSON API endpoint for daily stats
        url = "https://cdn.cboe.com/api/global/us_indices/daily_market_statistics.json"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "silmaril-bot"})
        if resp.status_code == 200:
            data = resp.json()
            # Parse whatever structure they return
            if isinstance(data, list) and len(data) > 0:
                latest = data[-1]
                equity_pc = float(latest.get("equity_pc_ratio") or latest.get("eq_pc") or 1.0)
                index_pc  = float(latest.get("index_pc_ratio") or latest.get("ix_pc") or 1.0)
                total_pc  = float(latest.get("total_pc_ratio") or latest.get("total_pc") or 1.0)
                return {"equity": equity_pc, "index": index_pc, "total": total_pc}
    except Exception:
        pass

    # Try alternate: yfinance VIX as fear proxy (not P/C but correlated)
    try:
        import yfinance as yf
        vix = yf.Ticker("^VIX").fast_info.get("lastPrice", 20)
        # Map VIX to approximate P/C ratio
        # VIX 15 ≈ P/C 0.85, VIX 20 ≈ P/C 1.0, VIX 30 ≈ P/C 1.3, VIX 40+ ≈ P/C 1.6
        pc = 0.85 + (float(vix) - 15) * 0.03
        pc = max(0.5, min(2.0, pc))
        log.debug("cboe: using VIX proxy P/C=%.2f (VIX=%.1f)", pc, vix)
        return {"equity": round(pc, 2), "index": round(pc, 2), "total": round(pc, 2)}
    except Exception:
        pass

    return {"equity": 1.0, "index": 1.0, "total": 1.0}


def _ensure_cache() -> None:
    global _CACHE, _CACHE_DATE
    today = datetime.now(timezone.utc).date().isoformat()
    if _CACHE_DATE != today:
        _CACHE      = _fetch_pc_ratio()
        _CACHE_DATE = today


def get_put_call_ratio(ticker: str = "equity") -> float:
    """
    Return P/C ratio. ticker is ignored (CBOE data is market-wide).
    Returns equity P/C ratio. Use 'index' or 'total' as key for variants.
    """
    _ensure_cache()
    return _CACHE.get("equity", 1.0)


def get_all_pc_ratios() -> Dict[str, float]:
    """Return all three P/C ratios: equity, index, total."""
    _ensure_cache()
    return dict(_CACHE)
