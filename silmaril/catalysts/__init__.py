"""silmaril.catalysts — Robust catalyst aggregator.

Tries every available source. Logs failures verbosely. If everything
fails, falls back to synthetic catalysts (FOMC dates, OPEX dates,
end-of-month effects) so the dashboard is NEVER blank.
"""
from __future__ import annotations
import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─── Synthetic fallback (always works) ────────────────────────

# Approximate FOMC meeting dates — public schedule, manually maintained
FOMC_2026 = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]

def _next_opex(today: date) -> date:
    """3rd Friday of the current or next month."""
    y, m = today.year, today.month
    for offset in (0, 1):
        yy = y + ((m + offset - 1) // 12)
        mm = ((m + offset - 1) % 12) + 1
        d = date(yy, mm, 1)
        while d.weekday() != 4:
            d += timedelta(days=1)
        d += timedelta(days=14)  # 3rd Friday
        if d >= today:
            return d
    return today + timedelta(days=30)

def _synthetic_catalysts(start_d: date, end_d: date) -> List[Dict[str, Any]]:
    out = []
    # FOMC meetings
    for d_str in FOMC_2026:
        try:
            d = date.fromisoformat(d_str)
            if start_d <= d <= end_d:
                out.append({
                    "date": d_str, "type": "fomc",
                    "ticker": "SPY", "title": "FOMC meeting — rate decision + statement",
                    "magnitude": "very_high",
                    "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                    "watchlist_tags": ["rates", "macro"],
                })
        except Exception: pass
    # Next OPEX
    opex = _next_opex(start_d)
    if start_d <= opex <= end_d:
        out.append({
            "date": opex.isoformat(), "type": "opex",
            "ticker": "SPY", "title": f"Monthly OPEX — options expiration ({opex.strftime('%b')})",
            "magnitude": "high",
            "source_url": "https://www.cboe.com/us/options/symboldir/equity_index_options/",
            "watchlist_tags": ["volatility", "gamma"],
        })
    # End-of-month effect
    cur = start_d
    while cur <= end_d:
        # Last business day of month
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


# ─── Main aggregator ────────────────────────────────────────────

def write_catalysts_json(path: Path, today_iso: Optional[str] = None) -> int:
    """Aggregate every catalyst source, write to path, return count.
    Always produces non-empty output (synthetic fallback)."""
    today_d = date.fromisoformat(today_iso) if today_iso else date.today()
    end_d = today_d + timedelta(days=30)
    all_events: List[Dict[str, Any]] = []
    status = {}

    # 1. Earnings (Finnhub)
    try:
        from .earnings_calendar import fetch_earnings_calendar
        ev = fetch_earnings_calendar(start_date=today_d, end_date=end_d)
        all_events.extend(ev)
        status["earnings"] = f"OK ({len(ev)})"
    except Exception as e:
        status["earnings"] = f"FAIL: {type(e).__name__}: {e}"
        print(f"[catalysts] earnings failed: {e}")

    # 2. OPEX dates
    try:
        from .opex import get_opex_dates
        ev = get_opex_dates(today_d, end_d)
        all_events.extend(ev)
        status["opex"] = f"OK ({len(ev)})"
    except Exception as e:
        status["opex"] = f"FAIL: {e}"

    # 3. Macro releases
    try:
        from .macro_releases import get_macro_release_dates
        ev = get_macro_release_dates(today_d, end_d)
        all_events.extend(ev)
        status["macro"] = f"OK ({len(ev)})"
    except Exception as e:
        status["macro"] = f"FAIL: {e}"

    # 4. Ex-dividend
    try:
        from .ex_dividend import fetch_ex_dividend_calendar
        ev = fetch_ex_dividend_calendar(start_date=today_d, end_date=end_d)
        all_events.extend(ev)
        status["ex_div"] = f"OK ({len(ev)})"
    except Exception as e:
        status["ex_div"] = f"FAIL: {e}"

    # 5. Crypto unlocks
    try:
        from .crypto_unlocks import get_crypto_unlocks
        ev = get_crypto_unlocks(today_d, end_d)
        all_events.extend(ev)
        status["crypto_unlocks"] = f"OK ({len(ev)})"
    except Exception as e:
        status["crypto_unlocks"] = f"FAIL: {e}"

    # 6. Index rebalance
    try:
        from .index_rebalance import get_index_rebalance_dates
        ev = get_index_rebalance_dates(today_d, end_d)
        all_events.extend(ev)
        status["index_rebalance"] = f"OK ({len(ev)})"
    except Exception as e:
        status["index_rebalance"] = f"FAIL: {e}"

    # 7. ALWAYS add synthetic fallbacks (FOMC, OPEX, month-end)
    # Even if other sources worked, these provide reliable anchors
    try:
        syn = _synthetic_catalysts(today_d, end_d)
        # Avoid duplicates by date+type
        existing_keys = {(c.get("date"), c.get("type")) for c in all_events}
        added = 0
        for s in syn:
            if (s["date"], s["type"]) not in existing_keys:
                all_events.append(s)
                added += 1
        status["synthetic"] = f"OK (+{added})"
    except Exception as e:
        status["synthetic"] = f"FAIL: {e}"

    # Sort and dedupe
    seen = set()
    unique = []
    for e in all_events:
        key = (e.get("date", ""), e.get("ticker", ""), e.get("type", ""), e.get("title", ""))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    unique.sort(key=lambda c: (c.get("date", ""), c.get("ticker", "")))

    # Print diagnostic so we can see in CI logs what's actually failing
    print(f"[catalysts] sources status:")
    for src, st in status.items():
        print(f"  {src}: {st}")
    print(f"[catalysts] total unique events: {len(unique)}")

    # Write — list at top level for backward compat
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(unique, indent=2, default=str))

    # Sidecar diagnostic file
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
