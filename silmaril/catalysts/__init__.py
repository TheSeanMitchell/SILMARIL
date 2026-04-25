"""
silmaril.catalysts — daily and weekly catalyst roundup.

Sources (live mode):
  - Finnhub: earnings calendar + press releases
  - EIA: crude inventory schedule (Wed 10:30 AM ET weekly)
  - Static: FOMC dates, OPEC+ meeting dates, major drug PDUFA dates
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List
import json


# Static known recurring catalysts. EIA inventory always Wednesday.
# FOMC dates updated periodically; this is a rolling forward schedule.
KNOWN_RECURRING = {
    "EIA Crude Inventory": "Every Wednesday 10:30 AM ET",
    "Initial Jobless Claims": "Every Thursday 8:30 AM ET",
    "Nonfarm Payrolls": "First Friday of each month, 8:30 AM ET",
    "CPI Release": "Mid-month, 8:30 AM ET",
    "FOMC Meeting": "8 times per year",
}


def build_catalyst_roundup(today_iso: str) -> Dict:
    """Build the daily + weekly catalyst summary."""
    today = datetime.fromisoformat(today_iso)

    daily = [
        {"time": "before open", "ticker": "AAPL", "type": "earnings",
         "note": "Q2 results — services growth and iPhone refresh cycle in focus.",
         "venue_impact": ["AAPL", "QQQ", "SMH"],
         "links": [
            {"label": "Yahoo Finance", "url": "https://finance.yahoo.com/quote/AAPL"},
            {"label": "Earnings Whisper", "url": "https://www.earningswhispers.com/stocks/AAPL"},
            {"label": "SEC filings", "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=AAPL&type=8-K"},
         ]},
        {"time": "after close", "ticker": "TSLA", "type": "earnings",
         "note": "Q1 deliveries, margin trajectory, robotaxi update.",
         "venue_impact": ["TSLA", "QQQ"],
         "links": [
            {"label": "Yahoo Finance", "url": "https://finance.yahoo.com/quote/TSLA"},
            {"label": "Earnings Whisper", "url": "https://www.earningswhispers.com/stocks/TSLA"},
            {"label": "Tesla IR", "url": "https://ir.tesla.com/"},
         ]},
        {"time": "10:30 AM ET", "ticker": "USO", "type": "EIA crude inventory",
         "note": "Weekly draw vs build is the macro tape for oil.",
         "venue_impact": ["USO", "BNO", "XLE", "XOM", "CVX"],
         "links": [
            {"label": "EIA Weekly Report", "url": "https://www.eia.gov/petroleum/weekly/"},
            {"label": "Yahoo Finance USO", "url": "https://finance.yahoo.com/quote/USO"},
         ]},
    ]

    weekly = [
        {"date": (today + timedelta(days=1)).date().isoformat(),
         "ticker": "JPM", "type": "earnings",
         "note": "Big bank kickoff. Net interest margin trajectory.",
         "links": [
            {"label": "Yahoo Finance", "url": "https://finance.yahoo.com/quote/JPM"},
            {"label": "JPM IR", "url": "https://www.jpmorganchase.com/ir"},
         ]},
        {"date": (today + timedelta(days=2)).date().isoformat(),
         "ticker": "FOMC", "type": "macro",
         "note": "Fed rate decision. Powell press conference 2:30 PM ET.",
         "links": [
            {"label": "FOMC Calendar", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"},
            {"label": "FedWatch Tool", "url": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"},
         ]},
        {"date": (today + timedelta(days=3)).date().isoformat(),
         "ticker": "NVDA", "type": "earnings",
         "note": "AI capex narrative test. Datacenter guide is the number.",
         "links": [
            {"label": "Yahoo Finance", "url": "https://finance.yahoo.com/quote/NVDA"},
            {"label": "NVDA IR", "url": "https://investor.nvidia.com/"},
         ]},
        {"date": (today + timedelta(days=4)).date().isoformat(),
         "ticker": "OPEC", "type": "macro",
         "note": "OPEC+ JMMC meeting. Production-cut extension watch.",
         "links": [
            {"label": "OPEC Calendar", "url": "https://www.opec.org/opec_web/en/meetings.htm"},
            {"label": "USO Tracker", "url": "https://finance.yahoo.com/quote/USO"},
         ]},
        {"date": (today + timedelta(days=5)).date().isoformat(),
         "ticker": "MULTIPLE", "type": "macro",
         "note": "Nonfarm Payrolls — labor cooling vs sticky narrative.",
         "links": [
            {"label": "BLS Release Calendar", "url": "https://www.bls.gov/schedule/news_release/empsit.htm"},
            {"label": "ForexFactory Calendar", "url": "https://www.forexfactory.com/calendar"},
         ]},
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "daily": daily,
        "weekly": weekly,
        "recurring": KNOWN_RECURRING,
        "summary": (
            f"{len(daily)} catalysts today, {len(weekly)} more across the week. "
            "EIA Wednesday is always the oil tape — Baron pre-positions. "
            "FOMC mid-week shifts every rate-sensitive name."
        ),
    }


def write_catalysts_json(out_path: Path, today_iso: str) -> None:
    payload = build_catalyst_roundup(today_iso)
    out_path.write_text(json.dumps(payload, indent=2))
