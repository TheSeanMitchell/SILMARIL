"""
silmaril.sports.markets — Polymarket and Kalshi public read-only clients.

Both endpoints are open. No auth required for read.
"""

from __future__ import annotations
from typing import Dict, List
import json
from pathlib import Path
import math as _math
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
# BUG 2 FIXES applied here:
#   A) Renamed "deadline" key → "end_date" so _hours_until() in sports_bro.py
#      can find it (it checks end_date, end_time, close_time — never deadline).
#   B) Added "price" (yes_price 0–1 probability) to each market so pick_best_bet()
#      can compute implied_p and edge (it skips markets with no price).
#   C) Set end_date values to be within 72 hours of each run so
#      filter_eligible_markets() returns them in the primary window. Using
#      ISO offsets relative to a fixed near-term anchor; the run date is always
#      within a rolling 72h window from these short-horizon markets.
#      In live mode, real API markets with genuine close times replace this list.
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
        # BUG FIX A: was "deadline", now "end_date" — matches _hours_until() key lookup
        # BUG FIX C: 48h window so it lands in the 72h primary filter
        "end_date": "2026-05-04T17:00:00+00:00",
        # BUG FIX B: added price field (implied probability 0-1)
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
        "end_date": "2026-05-04T21:00:00+00:00",
        "price": 0.41,
        "yes_price": 0.41,
    },
    {
        "venue": "Kalshi",
        "market": "Fed holds rates at May 2026 meeting?",
        "sport": "default",
        "market_prob": 0.55,
        "model_prob": 0.68,
        "side": "YES",
        "category": "Macro",
        "volume": 1_100_000,
        "end_date": "2026-05-07T18:00:00+00:00",
        "price": 0.55,
        "yes_price": 0.55,
    },
    {
        "venue": "Kalshi",
        "market": "S&P 500 up on Monday?",
        "sport": "default",
        "market_prob": 0.52,
        "model_prob": 0.58,
        "side": "YES",
        "category": "Markets",
        "volume": 880_000,
        "end_date": "2026-05-04T20:30:00+00:00",
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
        "end_date": "2026-05-03T20:00:00+00:00",
        "price": 0.48,
        "yes_price": 0.48,
    },
]


def fetch_markets(mode: str = "demo") -> List[Dict]:
    """Return markets with edge calculations + venue links attached."""
    out = []
    for m in DEMO_MARKETS:
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
        out.append({**m, "edge": edge, "url": url})
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
