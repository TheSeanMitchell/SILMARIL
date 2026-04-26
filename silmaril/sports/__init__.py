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
DEMO_MARKETS: List[Dict] = [
    {
        "venue": "Polymarket",
        "market": "Will SPX close above 6000 by Dec 31?",
        "market_prob": 0.62,
        "model_prob": 0.71,
        "side": "YES",
        "category": "Markets",
        "volume": 2_400_000,
        "deadline": "2026-12-31",
    },
    {
        "venue": "Polymarket",
        "market": "Bitcoin reaches $150k in 2026?",
        "market_prob": 0.41,
        "model_prob": 0.34,
        "side": "NO",
        "category": "Crypto",
        "volume": 5_800_000,
        "deadline": "2026-12-31",
    },
    {
        "venue": "Kalshi",
        "market": "Fed cuts rates by July 2026?",
        "market_prob": 0.55,
        "model_prob": 0.68,
        "side": "YES",
        "category": "Macro",
        "volume": 1_100_000,
        "deadline": "2026-07-31",
    },
    {
        "venue": "Kalshi",
        "market": "US recession declared in 2026?",
        "market_prob": 0.18,
        "model_prob": 0.12,
        "side": "NO",
        "category": "Macro",
        "volume": 880_000,
        "deadline": "2026-12-31",
    },
    {
        "venue": "Polymarket",
        "market": "Tesla delivers 2M vehicles in 2026?",
        "market_prob": 0.28,
        "model_prob": 0.22,
        "side": "NO",
        "category": "Equities",
        "volume": 320_000,
        "deadline": "2026-12-31",
    },
]


def fetch_markets(mode: str = "demo") -> List[Dict]:
    """Return markets with edge calculations attached. Live mode would
    call the real APIs; demo returns the static set."""
    out = []
    for m in DEMO_MARKETS:
        edge = m["model_prob"] - m["market_prob"] if m.get("side") == "YES" else m["market_prob"] - m["model_prob"]
        out.append({**m, "edge": edge})
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
