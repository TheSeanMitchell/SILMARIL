"""
silmaril.catalysts.earnings_calendar

Live earnings calendar via Finnhub free tier.
Endpoint: https://finnhub.io/api/v1/calendar/earnings
Auth: ?token={FINNHUB_API_KEY} (env var, also in repo secrets)
Free tier: 60 req/min — plenty for a daily run.

For "whisper numbers" there's no free aggregator API. EarningsWhispers.com has
a paid feed; Estimize.com offers a free tier. The current implementation
returns consensus only and tags whisper as None — CICADA gracefully abstains
on that case.

Returns: list[dict] sorted by date ascending.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional


def fetch_earnings_calendar(
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Returns earnings events between [start_date, end_date].

    If api_key is None, reads FINNHUB_API_KEY env var. If that's also missing,
    returns an empty list (no exception) so the orchestrator can keep running.
    """
    start_date = start_date or date.today()
    end_date = end_date or (start_date + timedelta(days=14))

    api_key = api_key or os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        print("[catalysts] FINNHUB_API_KEY not set; earnings calendar empty")
        return []

    try:
        import requests
    except ImportError:
        print("[catalysts] requests not installed; earnings calendar empty")
        return []

    url = "https://finnhub.io/api/v1/calendar/earnings"
    params = {
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "token": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[catalysts] earnings calendar fetch failed: {e}")
        return []

    data = resp.json() or {}
    events = data.get("earningsCalendar", []) or []
    out: List[Dict[str, Any]] = []

    for ev in events:
        sym = ev.get("symbol")
        d = ev.get("date")
        if not sym or not d:
            continue

        eps_est = ev.get("epsEstimate")
        rev_est = ev.get("revenueEstimate")
        hour = ev.get("hour", "")  # bmo / amc / dmh

        title_parts = [f"{sym} earnings"]
        if hour == "bmo":
            title_parts.append("(before market open)")
        elif hour == "amc":
            title_parts.append("(after market close)")
        if eps_est is not None:
            title_parts.append(f"EPS est ${eps_est:.2f}")
        if rev_est:
            title_parts.append(f"Rev est ${rev_est/1e9:.2f}B")

        out.append({
            "date": d,
            "type": "earnings",
            "ticker": sym,
            "title": " ".join(title_parts),
            "magnitude": "high" if eps_est else "medium",
            "source_url": f"https://finance.yahoo.com/quote/{sym}/analysis",
            "consensus": {
                "eps_est": eps_est,
                "revenue_est": rev_est,
            },
            "whisper": None,  # not provided by Finnhub free tier
            "watchlist_tags": ["earnings_setup", "high_iv"],
            "hour": hour,
            "year": ev.get("year"),
            "quarter": ev.get("quarter"),
        })

    out.sort(key=lambda c: c["date"])
    return out


def days_to_earnings(ticker: str, calendar: List[Dict[str, Any]],
                     ref_date: Optional[date] = None) -> Optional[int]:
    """Helper for agents (CICADA): days until next earnings event for ticker.
    Returns None if not within the calendar window."""
    ref = ref_date or date.today()
    for ev in calendar:
        if ev.get("ticker") != ticker:
            continue
        try:
            ev_date = date.fromisoformat(ev["date"])
        except Exception:
            continue
        if ev_date < ref:
            continue
        return (ev_date - ref).days
    return None
