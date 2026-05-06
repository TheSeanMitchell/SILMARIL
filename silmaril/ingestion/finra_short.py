"""
silmaril.ingestion.finra_short — FINRA daily short volume data.

FINRA publishes daily short sale volume data for all equity securities
at finra.org/investors/finra-data/short-sale. The data is free,
public, and available as a text file by trading date.

We calculate the short volume ratio: short_vol / total_vol.
A ratio > 0.40 means more than 40% of volume was short sales — high pressure.
A ratio > 0.55 is extreme and historically associated with squeeze setups.

Cached for the trading day.
"""
from __future__ import annotations

import csv
import io
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

log = logging.getLogger("silmaril.finra_short")

_BASE_URL  = "https://cdn.finra.org/equity/regsho/daily/"
_CACHE: Dict[str, float] = {}  # ticker → short_ratio
_CACHE_DATE: str = ""


def _today_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _most_recent_trading_day() -> str:
    """Return the most recent weekday date string in YYYYMMDD format."""
    d = datetime.now(timezone.utc)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def _load_finra_daily(date_str: str) -> Dict[str, float]:
    """
    Download and parse FINRA daily short volume file for given date.
    Returns {ticker: short_volume_ratio}.
    """
    url = f"{_BASE_URL}CNMSshvol{date_str}.txt"
    try:
        import requests
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            # Try previous trading day
            d = datetime.strptime(date_str, "%Y%m%d") - timedelta(days=1)
            while d.weekday() >= 5:
                d -= timedelta(days=1)
            prev = d.strftime("%Y%m%d")
            url2 = f"{_BASE_URL}CNMSshvol{prev}.txt"
            resp = requests.get(url2, timeout=15)
            if resp.status_code != 200:
                log.debug("finra: no data for %s or %s", date_str, prev)
                return {}

        ratios: Dict[str, float] = {}
        reader = csv.DictReader(io.StringIO(resp.text), delimiter="|")
        for row in reader:
            ticker   = (row.get("Symbol") or row.get("SYMBOL") or "").strip()
            short_vol = row.get("ShortVolume") or row.get("SHORT VOLUME") or "0"
            total_vol = row.get("TotalVolume") or row.get("TOTAL VOLUME") or "0"
            try:
                sv = float(short_vol.replace(",", ""))
                tv = float(total_vol.replace(",", ""))
                if tv > 0:
                    ratios[ticker] = round(sv / tv, 4)
            except ValueError:
                continue
        log.info("finra: loaded %d tickers for %s", len(ratios), date_str)
        return ratios
    except Exception as e:
        log.debug("finra: fetch error: %s", e)
        return {}


def _ensure_cache() -> None:
    global _CACHE, _CACHE_DATE
    today = _most_recent_trading_day()
    if _CACHE_DATE != today:
        _CACHE      = _load_finra_daily(today)
        _CACHE_DATE = today


def get_short_ratio(ticker: str) -> float:
    """
    Return the short volume ratio (0.0–1.0) for a ticker.
    0.0 if ticker not found in FINRA data.
    """
    _ensure_cache()
    return _CACHE.get(ticker.upper(), 0.0)


def get_high_short_tickers(threshold: float = 0.45) -> Dict[str, float]:
    """Return all tickers with short ratio above threshold."""
    _ensure_cache()
    return {t: r for t, r in _CACHE.items() if r >= threshold}
