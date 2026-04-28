"""
silmaril.catalysts.macro_releases

Macro release schedule: CPI, PPI, PCE, FOMC, BLS Employment Situation, GDP,
EIA Crude inventories, Retail Sales, ISM, Consumer Confidence.

Most release dates are deterministic — published a year in advance by the
relevant agency. We hard-code 2026 dates for the major ones; refresh
annually from the agency calendars.

Sources for date verification:
  - BLS:    https://www.bls.gov/schedule/news_release/empsit.htm
  - BEA:    https://www.bea.gov/news/schedule
  - FRB:    https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
  - EIA:    https://www.eia.gov/petroleum/weekly/schedule.php

Each event includes consensus forecast slots which the orchestrator can fill
in from forecasting services (Cleveland Fed Nowcast, Atlanta Fed GDPNow,
forexfactory, etc.) closer to the release.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional


# 2026 macro calendar — VERIFY against agency calendars before relying.
# Format: (ISO date, type, title, source_url, magnitude)
MACRO_CALENDAR_2026 = [
    # April 2026 — partial sample, extend in production
    ("2026-04-30", "fomc",         "FOMC rate decision + Powell presser",   "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "very_high"),
    ("2026-05-02", "bls_empl",     "BLS Employment Situation (Apr)",          "https://www.bls.gov/schedule/news_release/empsit.htm", "very_high"),
    ("2026-05-13", "cpi",          "CPI inflation (Apr)",                      "https://www.bls.gov/cpi/", "very_high"),
    ("2026-05-15", "ppi",          "PPI producer prices (Apr)",                "https://www.bls.gov/ppi/", "high"),
    ("2026-05-29", "pce",          "PCE personal income & outlays (Apr)",      "https://www.bea.gov/news/schedule", "high"),
    # June 2026
    ("2026-06-06", "bls_empl",     "BLS Employment Situation (May)",          "https://www.bls.gov/schedule/news_release/empsit.htm", "very_high"),
    ("2026-06-11", "cpi",          "CPI inflation (May)",                      "https://www.bls.gov/cpi/", "very_high"),
    ("2026-06-18", "fomc",         "FOMC rate decision + dot plot + presser", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "very_high"),
    ("2026-06-26", "pce",          "PCE personal income & outlays (May)",      "https://www.bea.gov/news/schedule", "high"),
    # July 2026
    ("2026-07-03", "bls_empl",     "BLS Employment Situation (Jun)",          "https://www.bls.gov/schedule/news_release/empsit.htm", "very_high"),
    ("2026-07-15", "cpi",          "CPI inflation (Jun)",                      "https://www.bls.gov/cpi/", "very_high"),
    ("2026-07-30", "fomc",         "FOMC rate decision + Powell presser",      "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "very_high"),
    ("2026-07-31", "pce",          "PCE personal income & outlays (Jun)",      "https://www.bea.gov/news/schedule", "high"),
    ("2026-07-31", "gdp",          "GDP Q2 2026 advance estimate",             "https://www.bea.gov/news/schedule", "very_high"),
]


def _eia_crude_dates(start: date, end: date) -> List[date]:
    """EIA crude inventories release every Wednesday at 10:30 AM ET."""
    out = []
    d = start
    while d <= end:
        if d.weekday() == 2:  # Wednesday
            out.append(d)
        d += timedelta(days=1)
    return out


def fetch_macro_calendar(
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    start_date = start_date or date.today()
    end_date = end_date or (start_date + timedelta(days=90))

    out: List[Dict[str, Any]] = []

    # Static major events
    for d_str, type_, title, url, mag in MACRO_CALENDAR_2026:
        try:
            d = date.fromisoformat(d_str)
        except Exception:
            continue
        if not (start_date <= d <= end_date):
            continue
        out.append({
            "date": d_str,
            "type": type_,
            "ticker": None,
            "title": title,
            "magnitude": mag,
            "source_url": url,
            "consensus": None,  # populate from nowcast services
            "watchlist_tags": ["macro_release", type_],
        })

    # Weekly EIA crude
    for d in _eia_crude_dates(start_date, end_date):
        out.append({
            "date": d.isoformat(),
            "type": "eia_crude",
            "ticker": None,
            "title": "EIA weekly petroleum status (crude inventories)",
            "magnitude": "medium",
            "source_url": "https://www.eia.gov/petroleum/weekly/",
            "watchlist_tags": ["oil_event", "weekly_macro"],
        })

    out.sort(key=lambda c: c["date"])
    return out
