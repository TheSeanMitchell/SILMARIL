"""silmaril.catalysts — Aggregator that writes the schema the dashboard expects.

THE BUG (fixed here):
    index.html:4076 reads c.daily and c.weekly from catalysts.json. The previous
    aggregator wrote a flat list of events. List has no .daily attribute → page
    rendered empty even though 1,500 events were on disk.

OUTPUT SCHEMA (what the dashboard reads):
    {
      "summary":  "Showing N catalysts in the next 30 days",
      "daily":    [{time, ticker, type, note, links: [...]}],   # today only
      "weekly":   [{date, ticker, type, note, links: [...]}],   # next 30 days
      "_diagnostic": { ... source-by-source status ... }
    }

This file replaces silmaril/catalysts/__init__.py.
Do NOT delete the other files in the catalysts/ folder. They're used by this one:
    earnings_calendar.py, opex.py, macro_releases.py, ex_dividend.py,
    crypto_unlocks.py, index_rebalance.py
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────
# Synthetic fallback (always works — no API)
# ─────────────────────────────────────────────────────────────────

# FOMC 2026 (manually curated public schedule)
_FOMC_2026 = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]


def _synthetic_catalysts(start_d: date, end_d: date) -> List[Dict[str, Any]]:
    """FOMC + month-end markers. Pure date math, can never fail."""
    out: List[Dict[str, Any]] = []

    # FOMC
    for d_str in _FOMC_2026:
        try:
            d = date.fromisoformat(d_str)
            if start_d <= d <= end_d:
                out.append({
                    "date": d_str,
                    "type": "fomc",
                    "ticker": "SPY",
                    "title": "FOMC meeting — rate decision + statement",
                    "note": "FOMC meeting — rate decision + statement",
                    "magnitude": "very_high",
                    "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                    "watchlist_tags": ["rates", "macro"],
                })
        except Exception:
            pass

    # Month-end last business day
    cur = start_d
    seen_months = set()
    while cur <= end_d:
        ym = (cur.year, cur.month)
        if ym not in seen_months:
            seen_months.add(ym)
            # Last day of this month
            next_month = (cur.replace(day=28) + timedelta(days=4))
            last_day = next_month - timedelta(days=next_month.day)
            while last_day.weekday() >= 5:  # Saturday=5, Sunday=6
                last_day -= timedelta(days=1)
            if start_d <= last_day <= end_d:
                out.append({
                    "date": last_day.isoformat(),
                    "type": "month_end",
                    "ticker": "SPY",
                    "title": f"Month-end rebalance ({last_day.strftime('%b %d')})",
                    "note": "Pension fund + index rebalance flows around month-end",
                    "magnitude": "medium",
                    "source_url": "",
                    "watchlist_tags": ["seasonal", "rebalance"],
                })
        cur = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)

    return out


# ─────────────────────────────────────────────────────────────────
# Source loaders — each returns (events_list, status_str)
# Each tries to import then call its module's primary function.
# Function names verified against actual repo source files.
# ─────────────────────────────────────────────────────────────────

def _load_earnings(start_d: date, end_d: date):
    try:
        from .earnings_calendar import fetch_earnings_calendar
        ev = fetch_earnings_calendar(start_date=start_d, end_date=end_d)
        return ev, f"OK ({len(ev)})"
    except Exception as e:
        return [], f"FAIL: {type(e).__name__}: {str(e)[:80]}"


def _load_opex(start_d: date, end_d: date):
    try:
        from .opex import fetch_opex_calendar
        ev = fetch_opex_calendar(start_date=start_d, end_date=end_d)
        return ev, f"OK ({len(ev)})"
    except Exception as e:
        return [], f"FAIL: {type(e).__name__}: {str(e)[:80]}"


def _load_macro(start_d: date, end_d: date):
    try:
        from .macro_releases import fetch_macro_calendar
        ev = fetch_macro_calendar(start_date=start_d, end_date=end_d)
        return ev, f"OK ({len(ev)})"
    except Exception as e:
        return [], f"FAIL: {type(e).__name__}: {str(e)[:80]}"


def _load_ex_div(start_d: date, end_d: date):
    try:
        from .ex_dividend import fetch_ex_dividend_calendar
        ev = fetch_ex_dividend_calendar(start_date=start_d, end_date=end_d)
        return ev, f"OK ({len(ev)})"
    except Exception as e:
        return [], f"FAIL: {type(e).__name__}: {str(e)[:80]}"


def _load_crypto_unlocks(start_d: date, end_d: date):
    try:
        from .crypto_unlocks import fetch_crypto_unlocks
        ev = fetch_crypto_unlocks(start_date=start_d, end_date=end_d)
        return ev, f"OK ({len(ev)})"
    except Exception as e:
        return [], f"FAIL: {type(e).__name__}: {str(e)[:80]}"


def _load_index_rebalance(start_d: date, end_d: date):
    try:
        from .index_rebalance import fetch_index_rebalances
        ev = fetch_index_rebalances(start_date=start_d, end_date=end_d)
        return ev, f"OK ({len(ev)})"
    except Exception as e:
        return [], f"FAIL: {type(e).__name__}: {str(e)[:80]}"


# ─────────────────────────────────────────────────────────────────
# Event normalization → dashboard schema (daily/weekly rows)
# ─────────────────────────────────────────────────────────────────

def _normalize_event(e: Dict[str, Any], today_iso: str) -> Dict[str, Any]:
    """Normalize an event from any source into a row the dashboard can render.
    Returns a dict with: date, time, ticker, type, note, links."""
    ev_date = (e.get("date") or "")[:10]
    ticker = e.get("ticker") or ""
    ev_type = e.get("type") or "event"
    note = e.get("note") or e.get("title") or ev_type
    src_url = e.get("source_url") or e.get("url") or ""
    time_str = e.get("time") or ""
    if not time_str and ev_date == today_iso:
        time_str = "All day"

    links = []
    if src_url:
        # Pick a friendly label by source domain
        label = "Source"
        if "finnhub" in src_url:
            label = "Finnhub"
        elif "federalreserve" in src_url:
            label = "Fed"
        elif "cboe" in src_url:
            label = "CBOE"
        elif "bls.gov" in src_url:
            label = "BLS"
        elif "eia.gov" in src_url:
            label = "EIA"
        links.append({"label": label, "url": src_url})

    return {
        "date": ev_date,
        "time": time_str,
        "ticker": ticker,
        "type": ev_type,
        "note": note,
        "links": links,
        "magnitude": e.get("magnitude") or "medium",
    }


def _filter_to_relevant(rows: List[Dict[str, Any]],
                        relevant_tickers: Optional[set] = None,
                        max_count: int = 80) -> List[Dict[str, Any]]:
    """Trim catalyst noise.
    Priority: high-magnitude events first, then events for relevant tickers,
    then everything else, capped at max_count."""
    if not rows:
        return rows

    relevant_tickers = relevant_tickers or set()

    def score(r: Dict[str, Any]) -> int:
        s = 0
        mag = r.get("magnitude") or "medium"
        if mag == "very_high":
            s += 100
        elif mag == "high":
            s += 50
        elif mag == "medium":
            s += 10
        if (r.get("ticker") or "").upper() in relevant_tickers:
            s += 30
        # Type boost for the events that actually move markets
        et = r.get("type") or ""
        if et in ("fomc", "macro", "opex_quarterly"):
            s += 25
        if et in ("earnings",) and (r.get("ticker") or "").upper() in relevant_tickers:
            s += 15
        return s

    rows.sort(key=lambda r: (-score(r), r.get("date", "")))
    return rows[:max_count]


# ─────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────

def write_catalysts_json(
    path: Path,
    today_iso: Optional[str] = None,
    relevant_tickers: Optional[set] = None,
) -> int:
    """Aggregate catalysts and write the schema the dashboard expects.

    relevant_tickers: optional set of tickers we currently care about (open
    positions, top-10 trade plans). When provided, the noise filter prefers
    catalysts involving these tickers.
    """
    today_d = date.fromisoformat(today_iso) if today_iso else date.today()
    end_d = today_d + timedelta(days=30)

    sources = [
        ("earnings", _load_earnings),
        ("opex", _load_opex),
        ("macro", _load_macro),
        ("ex_div", _load_ex_div),
        ("crypto_unlocks", _load_crypto_unlocks),
        ("index_rebalance", _load_index_rebalance),
    ]

    all_events: List[Dict[str, Any]] = []
    status: Dict[str, str] = {}

    for name, loader in sources:
        events, st = loader(today_d, end_d)
        all_events.extend(events)
        status[name] = st

    # Always add synthetic fallbacks
    syn = _synthetic_catalysts(today_d, end_d)
    seen_keys = {(e.get("date"), e.get("type"), e.get("ticker")) for e in all_events}
    added = 0
    for s in syn:
        k = (s.get("date"), s.get("type"), s.get("ticker"))
        if k not in seen_keys:
            all_events.append(s)
            seen_keys.add(k)
            added += 1
    status["synthetic"] = f"OK (+{added})"

    # Print diagnostic to CI logs
    print(f"[catalysts] sources status:")
    for src, st in status.items():
        print(f"  {src}: {st}")
    print(f"[catalysts] total raw events: {len(all_events)}")

    # Normalize into dashboard rows
    today_str = today_d.isoformat()
    rows = [_normalize_event(e, today_str) for e in all_events]

    # Trim noise — focus on what matters
    rows = _filter_to_relevant(rows, relevant_tickers, max_count=80)

    # Split into "today" (daily) and "next 30 days" (weekly)
    daily_rows = [r for r in rows if r.get("date") == today_str]
    weekly_rows = [r for r in rows if r.get("date") and r.get("date") > today_str]

    # Sort
    daily_rows.sort(key=lambda r: (r.get("time", ""), r.get("ticker", "")))
    weekly_rows.sort(key=lambda r: (r.get("date", ""), r.get("ticker", "")))

    # Final payload — schema matches index.html:4076 expectations
    payload = {
        "summary": (
            f"{len(daily_rows)} today, {len(weekly_rows)} upcoming"
            f" (showing top {len(rows)} of {len(all_events)} raw events)"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "daily": daily_rows,
        "weekly": weekly_rows,
        "_diagnostic": {
            "sources": status,
            "raw_event_count": len(all_events),
            "filtered_count": len(rows),
            "window_start": today_str,
            "window_end": end_d.isoformat(),
            "relevant_tickers": sorted(list(relevant_tickers or [])),
        },
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))

    print(f"[catalysts] wrote {len(daily_rows)} daily + {len(weekly_rows)} weekly events")
    return len(daily_rows) + len(weekly_rows)


__all__ = ["write_catalysts_json"]
