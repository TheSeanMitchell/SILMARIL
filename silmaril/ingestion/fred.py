"""
silmaril.ingestion.fred — Federal Reserve Economic Data (FRED) macro signals.

Free API key required: register at fred.stlouisfed.org/docs/api/api_key.html
Set FRED_API_KEY in GitHub secrets.

Fetches 4 macro signals used by CANDIDATE_GAMMA:
  1. Yield curve slope: T10Y2Y (10Y minus 2Y Treasury spread)
  2. Credit spread proxy: BAMLH0A0HYM2 - BAMLC0A0CM (HY minus IG OAS)
  3. Leading Economic Index direction: USSLIND (LEI MoM change)
  4. Fed Funds Rate direction: FEDFUNDS

Cached in docs/data/fred_signals.json for 6 hours to avoid rate limits.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger("silmaril.fred")

_API_KEY    = os.environ.get("FRED_API_KEY", "")
_BASE_URL   = "https://api.stlouisfed.org/fred/series/observations"
_CACHE_TTL  = 21600  # 6 hours
_CACHE_PATH = Path("docs/data/fred_signals.json")

# FRED series IDs
_SERIES = {
    "yield_curve":    "T10Y2Y",      # 10Y-2Y spread (negative = inverted)
    "hy_spread":      "BAMLH0A0HYM2", # HY OAS
    "ig_spread":      "BAMLC0A0CM",   # IG OAS
    "lei":            "USSLIND",      # Leading Economic Index
    "fed_funds":      "FEDFUNDS",     # Federal Funds Effective Rate
}


def _load_cache() -> Optional[Dict]:
    try:
        if _CACHE_PATH.exists():
            raw = json.loads(_CACHE_PATH.read_text())
            if time.time() - raw.get("_fetched_at", 0) < _CACHE_TTL:
                return raw
    except Exception:
        pass
    return None


def _save_cache(data: Dict) -> None:
    try:
        data["_fetched_at"] = time.time()
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(data, indent=2, default=str))
    except Exception:
        pass


def _fetch_latest(series_id: str) -> Optional[float]:
    """Fetch the most recent observation for a FRED series."""
    if not _API_KEY:
        return None
    try:
        import requests
        params = {
            "series_id":    series_id,
            "api_key":      _API_KEY,
            "file_type":    "json",
            "sort_order":   "desc",
            "limit":        5,
            "observation_start": (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d"),
        }
        resp = requests.get(_BASE_URL, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        obs = resp.json().get("observations", [])
        for o in obs:
            val = o.get("value", ".")
            if val not in (".", "", None):
                return float(val)
    except Exception as e:
        log.debug("fred: %s error: %s", series_id, e)
    return None


def get_macro_signals(force_refresh: bool = False) -> Dict:
    """
    Return macro regime signals from FRED.
    Cached for 6 hours. Returns safe defaults if API key missing.

    Returns:
      yield_curve_slope  — T10Y2Y spread (float, negative = inverted)
      credit_spread      — approximate HY spread (float, pct)
      lei_direction      — "up" | "down" | "flat"
      fed_cycle          — "tightening" | "easing" | "neutral"
      source             — "FRED" | "CACHED" | "DEFAULT"
    """
    if not force_refresh:
        cached = _load_cache()
        if cached:
            cached["source"] = "CACHED"
            return cached

    if not _API_KEY:
        log.debug("fred: FRED_API_KEY not set — returning defaults")
        return {
            "yield_curve_slope": 0.30,
            "credit_spread":     3.50,
            "lei_direction":     "flat",
            "fed_cycle":         "neutral",
            "source":            "DEFAULT",
        }

    signals: Dict = {}
    try:
        # 1. Yield curve slope
        t10y2y = _fetch_latest(_SERIES["yield_curve"])
        signals["yield_curve_slope"] = round(t10y2y, 3) if t10y2y is not None else 0.30

        # 2. HY spread (credit spread proxy)
        hy = _fetch_latest(_SERIES["hy_spread"])
        signals["credit_spread"] = round(hy, 3) if hy is not None else 3.50

        # 3. LEI direction — compare last two readings
        if not _API_KEY:
            signals["lei_direction"] = "flat"
        else:
            try:
                import requests
                params = {
                    "series_id": _SERIES["lei"],
                    "api_key":   _API_KEY,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 3,
                }
                resp = requests.get(_BASE_URL, params=params, timeout=10)
                obs = [o for o in resp.json().get("observations", [])
                       if o.get("value") not in (".", "")]
                if len(obs) >= 2:
                    latest  = float(obs[0]["value"])
                    prior   = float(obs[1]["value"])
                    signals["lei_direction"] = "up" if latest > prior else ("down" if latest < prior else "flat")
                else:
                    signals["lei_direction"] = "flat"
            except Exception:
                signals["lei_direction"] = "flat"

        # 4. Fed cycle — compare last two readings
        try:
            import requests
            params = {
                "series_id": _SERIES["fed_funds"],
                "api_key":   _API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 6,
            }
            resp = requests.get(_BASE_URL, params=params, timeout=10)
            obs = [o for o in resp.json().get("observations", [])
                   if o.get("value") not in (".", "")]
            if len(obs) >= 3:
                latest = float(obs[0]["value"])
                older  = float(obs[2]["value"])
                if latest > older + 0.1:
                    signals["fed_cycle"] = "tightening"
                elif latest < older - 0.1:
                    signals["fed_cycle"] = "easing"
                else:
                    signals["fed_cycle"] = "neutral"
            else:
                signals["fed_cycle"] = "neutral"
        except Exception:
            signals["fed_cycle"] = "neutral"

        signals["source"] = "FRED"
        signals["fetched_at"] = datetime.now(timezone.utc).isoformat()
        _save_cache(signals)
        log.info("fred: signals fetched — curve=%.2f spread=%.1f lei=%s fed=%s",
                 signals["yield_curve_slope"], signals["credit_spread"],
                 signals["lei_direction"], signals["fed_cycle"])

    except Exception as e:
        log.warning("fred: full fetch failed: %s", e)
        signals.setdefault("yield_curve_slope", 0.30)
        signals.setdefault("credit_spread",     3.50)
        signals.setdefault("lei_direction",     "flat")
        signals.setdefault("fed_cycle",         "neutral")
        signals["source"] = "DEFAULT"

    return signals
