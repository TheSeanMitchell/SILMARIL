"""
silmaril.catalysts.crypto_unlocks

Token unlock schedules. When a project's vesting cliff passes, a known
quantity of tokens (often 5-15% of supply) becomes liquid. Holders dump,
price drops. This is one of the most predictable price-moving events in
crypto — purely mechanical.

Sources (free):
  - https://token.unlocks.app/  (web scrape, no API)
  - https://cryptorank.io/upcoming-token-unlocks  (web scrape, no API)
  - Foundation announcements (per-project)

This module currently provides a HARD-CODED schedule of major upcoming
unlocks. In a future iteration, scrape token.unlocks.app weekly via a
GitHub Action and emit the unlock dates as JSON. For now, the static data
seeds the catalyst feed.

Bitcoin halving (every ~4 years) is also tracked here. Next halving:
April 2028 (estimated, based on 210,000 blocks × 10min target).

Data is illustrative — verify against live sources before trading.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional


# Hand-curated upcoming unlocks (illustrative — replace with scraper output)
# Format: (ISO date, ticker, % of supply, notes)
UPCOMING_UNLOCKS = [
    # 2026 schedule samples — verify against live data
    ("2026-05-01", "ARB-USD",   2.0,  "Arbitrum monthly unlock ~2% supply"),
    ("2026-05-15", "PYTH-USD",  5.0,  "Pyth Network unlock"),
    ("2026-06-10", "STRK-USD",  4.5,  "Starknet quarterly cliff"),
    ("2026-06-30", "TIA-USD",   3.0,  "Celestia unlock"),
    ("2026-07-22", "DYM-USD",   8.5,  "Dymension cliff (large)"),
]

# Bitcoin halvings: structural, predictable, every ~4 years
BTC_HALVINGS = [
    "2028-04-15",  # estimate; refine as block height approaches
    "2032-04-10",  # estimate
]


def fetch_crypto_unlocks(
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    start_date = start_date or date.today()
    end_date = end_date or (start_date + timedelta(days=180))

    out: List[Dict[str, Any]] = []

    for d_str, ticker, pct, note in UPCOMING_UNLOCKS:
        try:
            d = date.fromisoformat(d_str)
        except Exception:
            continue
        if not (start_date <= d <= end_date):
            continue
        out.append({
            "date": d_str,
            "type": "token_unlock",
            "ticker": ticker,
            "title": f"{ticker} token unlock — {pct}% of supply ({note})",
            "magnitude": "high" if pct >= 5 else "medium",
            "source_url": "https://token.unlocks.app/",
            "supply_pct": pct,
            "watchlist_tags": ["mechanical_supply_shock", "unlock_pressure"],
        })

    for d_str in BTC_HALVINGS:
        try:
            d = date.fromisoformat(d_str)
        except Exception:
            continue
        if not (start_date <= d <= end_date):
            continue
        out.append({
            "date": d_str,
            "type": "btc_halving",
            "ticker": "BTC-USD",
            "title": "Bitcoin halving — block reward halved (structural supply shock)",
            "magnitude": "very_high",
            "source_url": "https://www.bitcoin.com/halving/",
            "watchlist_tags": ["structural", "btc_halving"],
        })

    out.sort(key=lambda c: c["date"])
    return out
