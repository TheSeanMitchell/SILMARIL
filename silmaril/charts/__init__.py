"""
silmaril.charts — price history bundles for chart rendering.

Generates per-asset OHLC-ish series for the dashboard's chart panel.
In demo mode synthesizes from the price_history list. In live mode this
would pull yfinance multi-timeframe.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List
import json
import math


def build_chart_series(ticker: str, price_history: List[float], current_price: float) -> Dict:
    """Build chart data for a single ticker."""
    if not price_history or len(price_history) < 5:
        # synthesize a flat series so the UI can still render something
        price_history = [current_price] * 30
    series = []
    end = datetime.now(timezone.utc)
    n = len(price_history)
    for i, p in enumerate(price_history):
        ts = end - timedelta(days=n - 1 - i)
        series.append({
            "t": ts.date().isoformat(),
            "o": round(p * 0.998, 6),
            "h": round(p * 1.005, 6),
            "l": round(p * 0.995, 6),
            "c": round(p, 6),
        })
    high_52w = max(price_history)
    low_52w = min(price_history)
    return {
        "ticker": ticker,
        "series": series,
        "current_price": round(current_price, 6),
        "high_52w": round(high_52w, 6),
        "low_52w": round(low_52w, 6),
        "first_price": round(price_history[0], 6),
        "ytd_change_pct": round(((current_price / price_history[0]) - 1) * 100, 2) if price_history[0] else 0,
    }


def write_charts_json(out_path: Path, debate_dicts, ctx_lookup) -> None:
    """Build chart bundle for all debate tickers."""
    bundles = {}
    for d in debate_dicts:
        ticker = d["ticker"]
        ctx = ctx_lookup.get(ticker)
        if not ctx:
            continue
        ph = list(getattr(ctx, "price_history", []) or [])
        bundles[ticker] = build_chart_series(ticker, ph, ctx.price)
    out_path.write_text(json.dumps({"charts": bundles}, indent=2))
