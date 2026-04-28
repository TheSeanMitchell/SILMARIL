"""
silmaril.catalysts.opex

Options expiration calendar. The 3rd Friday of every month is monthly OPEX;
March/June/September/December are quarterly OPEX which is much larger
(includes index futures expiry, "triple witching"). These dates produce
predictable pin risk and gamma-related volatility.

Specifically:
  - In the days leading up to OPEX, dealer gamma forces market-maker hedging
    that can dampen or amplify moves depending on positioning.
  - Stocks pinned near a heavy strike often gravitate toward that strike.
  - The Monday after OPEX often has a "vol crush" reset.

These are deterministic dates. Only the calendar logic is needed.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional


def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    fri_offset = (4 - first.weekday()) % 7  # Friday is weekday 4
    return first + timedelta(days=fri_offset + 14)


def fetch_opex_calendar(
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    start_date = start_date or date.today()
    end_date = end_date or (start_date + timedelta(days=120))

    out: List[Dict[str, Any]] = []
    cur = date(start_date.year, start_date.month, 1)
    while cur <= end_date:
        d = _third_friday(cur.year, cur.month)
        if start_date <= d <= end_date:
            quarterly = cur.month in (3, 6, 9, 12)
            out.append({
                "date": d.isoformat(),
                "type": "opex_quarterly" if quarterly else "opex_monthly",
                "ticker": None,
                "title": ("Quarterly OPEX (triple witching) — index/equity/futures expire"
                          if quarterly else
                          "Monthly OPEX — equity options expire"),
                "magnitude": "high" if quarterly else "medium",
                "source_url": "https://www.cboe.com/about/hours/holiday-calendar-and-trading-hours/",
                "watchlist_tags": ["pin_risk", "gamma_unwind", "vol_event"]
                                  + (["triple_witching"] if quarterly else []),
            })
        # next month
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)

    return out
