"""
silmaril.catalysts.index_rebalance

Russell, S&P, and MSCI index rebalances. Billions of dollars get reallocated
on these dates as index funds rebalance. Predictable structural flow.

These are KNOWN DATES — they don't need an API. We hard-code the schedule.
The only API call needed is to detect new constituents (which stocks were
just added or removed); for that, the official S&P / Russell sites publish
PDFs and CSVs ahead of effective dates.

For now we expose the date schedule and a hook for ingesting constituent
changes when their PDFs are released. (LLM users can paste the PDF into
their handoff prompts and ask the model to extract additions/deletions.)

Effective dates (US):
  - S&P 500 quarterly rebalance: 3rd Friday of March, June, September, December
  - Russell reconstitution: last Friday of June (annual)
  - MSCI quarterly: end of February, May, August, November
  - Nasdaq-100 annual rebalance: 3rd Friday of December
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the date of the nth occurrence of `weekday` in (year, month).
    weekday: Mon=0..Sun=6"""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    # last day of month
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    last_day = nxt - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


def _last_business_day_of_month(year: int, month: int) -> date:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _sp500_quarterly_rebalance(year: int) -> List[date]:
    return [_nth_weekday(year, m, 4, 3) for m in (3, 6, 9, 12)]  # 3rd Friday


def _russell_reconstitution(year: int) -> date:
    # Last Friday of June
    return _last_weekday(year, 6, 4)


def _msci_quarterly(year: int) -> List[date]:
    return [_last_business_day_of_month(year, m) for m in (2, 5, 8, 11)]


def _nasdaq100_annual(year: int) -> date:
    return _nth_weekday(year, 12, 4, 3)  # 3rd Friday December


def fetch_index_rebalances(
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    start_date = start_date or date.today()
    end_date = end_date or (start_date + timedelta(days=180))

    out: List[Dict[str, Any]] = []
    years = sorted({start_date.year, end_date.year})

    for y in years:
        for d in _sp500_quarterly_rebalance(y):
            if start_date <= d <= end_date:
                out.append(_evt(d, "sp500_rebalance",
                    f"S&P 500 quarterly rebalance — index funds reweight",
                    "https://www.spglobal.com/spdji/en/indices/equity/sp-500/"))
        d = _russell_reconstitution(y)
        if start_date <= d <= end_date:
            out.append(_evt(d, "russell_reconstitution",
                "Russell index reconstitution — major small/mid-cap flows",
                "https://www.lseg.com/en/ftse-russell"))
        for d in _msci_quarterly(y):
            if start_date <= d <= end_date:
                out.append(_evt(d, "msci_rebalance",
                    "MSCI quarterly index review — global rebalance flows",
                    "https://www.msci.com/index-review-feb"))
        d = _nasdaq100_annual(y)
        if start_date <= d <= end_date:
            out.append(_evt(d, "ndx_rebalance",
                "Nasdaq-100 annual rebalance — top-100 reweight",
                "https://www.nasdaq.com/market-activity/quotes/nasdaq-100"))

    out.sort(key=lambda c: c["date"])
    return out


def _evt(d: date, type_: str, title: str, url: str) -> Dict[str, Any]:
    return {
        "date": d.isoformat(),
        "type": type_,
        "ticker": None,
        "title": title,
        "magnitude": "high",
        "source_url": url,
        "watchlist_tags": ["index_flow", "structural_pressure"],
    }
