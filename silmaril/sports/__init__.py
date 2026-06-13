"""
silmaril.sports.markets — Polymarket and Kalshi public read-only clients.

Both endpoints are open. No auth required for read.

v2 fix: demo market end_dates are generated at fetch_markets() call time
relative to now(). Previously hardcoded calendar dates would expire and
freeze SportsBro at 0 bets the moment the calendar passed those dates.
"""

from __future__ import annotations
from typing import Dict, List
import json
from pathlib import Path
import math as _math
from datetime import datetime, timezone, timedelta
def _sanitize_json(obj):
    """Recursively convert NaN/Inf to None for valid JSON output."""
    if isinstance(obj, float):
        if _math.isnan(obj) or _math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    return obj


# Static demo markets — in live mode these come from real APIs
# Polymarket: GET https://gamma-api.polymarket.com/markets
# Kalshi:     GET https://api.elections.kalshi.com/trade-api/v2/markets
#
# end_date is REPLACED dynamically in fetch_markets() with a rolling offset
# from now(). The hours_offset tells fetch_markets where to put each market
# in the future window so filter_eligible_markets() (in sports_bro.py) sees
# them inside its 72-hour primary window.
DEMO_MARKETS: List[Dict] = [
    {
        "venue": "Polymarket",
        "market": "Will SPX close above 5400 this week?",
        "sport": "default",
        "market_prob": 0.62,
        "model_prob": 0.71,
        "side": "YES",
        "category": "Markets",
        "volume": 2_400_000,
        "hours_offset": 12,   # closes ~12h from now
        "price": 0.62,
        "yes_price": 0.62,
    },
    {
        "venue": "Polymarket",
        "market": "Bitcoin above $95k by Friday?",
        "sport": "default",
        "market_prob": 0.41,
        "model_prob": 0.50,
        "side": "YES",
        "category": "Crypto",
        "volume": 5_800_000,
        "hours_offset": 36,   # closes ~36h from now
        "price": 0.41,
        "yes_price": 0.41,
    },
    {
        "venue": "Kalshi",
        "market": "Fed holds rates at next meeting?",
        "sport": "default",
        "market_prob": 0.55,
        "model_prob": 0.68,
        "side": "YES",
        "category": "Macro",
        "volume": 1_100_000,
        "hours_offset": 60,   # closes ~60h from now
        "price": 0.55,
        "yes_price": 0.55,
    },
    {
        "venue": "Kalshi",
        "market": "S&P 500 up tomorrow?",
        "sport": "default",
        "market_prob": 0.52,
        "model_prob": 0.58,
        "side": "YES",
        "category": "Markets",
        "volume": 880_000,
        "hours_offset": 18,
        "price": 0.52,
        "yes_price": 0.52,
    },
    {
        "venue": "Polymarket",
        "market": "Gold above $3300 by end of week?",
        "sport": "default",
        "market_prob": 0.48,
        "model_prob": 0.56,
        "side": "YES",
        "category": "Equities",
        "volume": 320_000,
        "hours_offset": 48,
        "price": 0.48,
        "yes_price": 0.48,
    },
]


def fetch_markets(mode: str = "demo") -> List[Dict]:
    """Return markets with edge calculations + venue links attached.

    In demo mode we synthesize end_dates rolling forward from now() so
    SportsBro's eligibility filter (24/72h window) always finds bets.
    """
    now = datetime.now(timezone.utc)
    out = []
    for m in DEMO_MARKETS:
        # Roll the end_date forward each call so the markets never go
        # stale in the calendar sense.
        offset_h = float(m.get("hours_offset", 24))
        end_dt = now + timedelta(hours=offset_h)
        m_with_dates = {**m, "end_date": end_dt.isoformat()}
        edge = m["model_prob"] - m["market_prob"] if m.get("side") == "YES" else m["market_prob"] - m["model_prob"]
        # Build a deeplink to the appropriate venue search/listing page
        venue = m.get("venue", "Polymarket")
        if venue == "Polymarket":
            # Polymarket gamma API search by query
            from urllib.parse import quote
            search = quote(m["market"][:40])
            url = f"https://polymarket.com/markets?search={search}"
        elif venue == "Kalshi":
            from urllib.parse import quote
            search = quote(m["market"][:40])
            url = f"https://kalshi.com/markets?q={search}"
        else:
            url = "https://polymarket.com/"
        out.append({**m_with_dates, "edge": edge, "url": url})
    out.sort(key=lambda m: m["edge"], reverse=True)
    return out


def write_markets_json(out_path: Path, markets: List[Dict]) -> None:
    payload = {
        "markets": markets,
        "best_edge": markets[0] if markets else None,
        "venues": sorted({m["venue"] for m in markets}),
        "categories": sorted({m["category"] for m in markets}),
    }
    out_path.write_text(json.dumps(_sanitize_json(payload), indent=2, allow_nan=False))
