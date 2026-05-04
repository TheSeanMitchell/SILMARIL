"""silmaril.catalysts — Robust aggregator with correct module function names.

v4.1 fix: uses fetch_* function names (not get_*) which match the
actual catalyst submodules. Verified against repo source.
"""
from __future__ import annotations
import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


# FOMC dates (manually maintained, public schedule)
FOMC_2026 = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]


def _synthetic_catalysts(start_d: date, end_d: date) -> List[Dict[str, Any]]:
    """Always-works fallback: FOMC, end-of-month rebalance."""
    out = []
    for d_str in FOMC_2026:
        try:
            d = date.fromisoformat(d_str)
            if start_d <= d <= end_d:
                out.append({
                    "date": d_str, "type": "fomc",
                    "ticker": "SPY",
                    "title": "FOMC meeting — rate decision + statement",
                    "magnitude": "very_high",
                    "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                    "watchlist_tags": ["rates", "macro"],
                })
        except Exception: pass
    # Month-end last business day
    cur = start_d
    while cur <= end_d:
        next_month = cur.replace(day=28) + timedelta(days=4)
        last_day = next_month - timedelta(days=next_month.day)
        while last_day.weekday() >= 5:
            last_day -= timedelta(days=1)
        if start_d <= last_day <= end_d:
            out.append({
                "date": last_day.isoformat(), "type": "month_end",
                "ticker": "SPY",
                "title": f"Month-end rebalance ({last_day.strftime('%b %d')})",
                "magnitude": "medium",
                "source_url": "",
                "watchlist_tags": ["seasonal", "rebalance"],
            })
        cur = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
    return out


def write_catalysts_json(path: Path, today_iso: Optional[str] = None) -> int:
    """Aggregate catalysts. Always writes a non-empty file."""
    today_d = date.fromisoformat(today_iso) if today_iso else date.today()
    end_d = today_d + timedelta(days=30)
    all_events: List[Dict[str, Any]] = []
    status = {}

    # 1. Earnings (Finnhub) — fetch_earnings_calendar
    try:
        from .earnings_calendar import fetch_earnings_calendar
        ev = fetch_earnings_calendar(start_date=today_d, end_date=end_d)
        all_events.extend(ev)
        status["earnings"] = f"OK ({len(ev)})"
    except Exception as e:
        status["earnings"] = f"FAIL: {type(e).__name__}: {e}"

    # 2. OPEX dates — fetch_opex_calendar (NOT get_opex_dates)
    try:
        from .opex import fetch_opex_calendar
        ev = fetch_opex_calendar(start_date=today_d, end_date=end_d)
        all_events.extend(ev)
        status["opex"] = f"OK ({len(ev)})"
    except Exception as e:
        status["opex"] = f"FAIL: {type(e).__name__}: {e}"

    # 3. Macro releases — fetch_macro_calendar
    try:
        from .macro_releases import fetch_macro_calendar
        ev = fetch_macro_calendar(start_date=today_d, end_date=end_d)
        all_events.extend(ev)
        status["macro"] = f"OK ({len(ev)})"
    except Exception as e:
        status["macro"] = f"FAIL: {type(e).__name__}: {e}"

    # 4. Ex-dividend
    try:
        from .ex_dividend import fetch_ex_dividend_calendar
        ev = fetch_ex_dividend_calendar(start_date=today_d, end_date=end_d)
        all_events.extend(ev)
        status["ex_div"] = f"OK ({len(ev)})"
    except Exception as e:
        status["ex_div"] = f"FAIL: {type(e).__name__}: {e}"

    # 5. Crypto unlocks — fetch_crypto_unlocks
    try:
        from .crypto_unlocks import fetch_crypto_unlocks
        ev = fetch_crypto_unlocks(start_date=today_d, end_date=end_d)
        all_events.extend(ev)
        status["crypto_unlocks"] = f"OK ({len(ev)})"
    except Exception as e:
        status["crypto_unlocks"] = f"FAIL: {type(e).__name__}: {e}"

    # 6. Index rebalance — fetch_index_rebalances
    try:
        from .index_rebalance import fetch_index_rebalances
        ev = fetch_index_rebalances(start_date=today_d, end_date=end_d)
        all_events.extend(ev)
        status["index_rebalance"] = f"OK ({len(ev)})"
    except Exception as e:
        status["index_rebalance"] = f"FAIL: {type(e).__name__}: {e}"

    # 7. Synthetic fallback (always works)
    try:
        syn = _synthetic_catalysts(today_d, end_d)
        existing = {(c.get("date"), c.get("type")) for c in all_events}
        added = 0
        for s in syn:
            if (s["date"], s["type"]) not in existing:
                all_events.append(s)
                added += 1
        status["synthetic"] = f"OK (+{added})"
    except Exception as e:
        status["synthetic"] = f"FAIL: {e}"

    # Dedupe + sort
    seen = set()
    unique = []
    for e in all_events:
        key = (e.get("date", ""), e.get("ticker", ""), e.get("type", ""), e.get("title", ""))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    unique.sort(key=lambda c: (c.get("date", ""), c.get("ticker", "") or ""))

    # Print diagnostic
    print(f"[catalysts] sources status:")
    for src, st in status.items():
        print(f"  {src}: {st}")
    print(f"[catalysts] total unique events: {len(unique)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(unique, indent=2, default=str))

    diag_path = path.parent / "catalysts_diagnostic.json"
    diag_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(unique),
        "sources_status": status,
        "window_start": today_d.isoformat(),
        "window_end": end_d.isoformat(),
    }, indent=2, default=str))

    return len(unique)


__all__ = ["write_catalysts_json"]
