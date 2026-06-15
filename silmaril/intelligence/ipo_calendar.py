"""
SILMARIL — IPO Calendar & Pipeline (the self-rotating foundation)
=================================================================

The permanent registry of the IPO pipeline, ordered by size. This is the brain
that decides WHICH IPO the Event Recorder is currently tracking. When the active
IPO finishes its window, tracking rotates automatically to the next dated IPO —
no manual change, no fabricated dates.

Design rules (the operator's "everything real, always"):
  - Confirmed/dated IPOs carry a real, verified date. Anticipated ones carry
    status="anticipated" and date=None with an honest expected-window note —
    NEVER a made-up date. They become "active" only once a real date is set here.
  - The ACTIVE IPO = the dated, in-window IPO closest to its debut (min |days|).
    SpaceX (2026-06-12) is active now; when it exits its post-window the next
    dated IPO takes over automatically.
  - Each IPO carries its own "complex" — real public tickers connected to its
    narrative — so the recorder knows what to watch. Unknown/unlisted tickers are
    simply skipped by the recorder (shown as not-in-universe).

Sources for dates/valuations: Reuters / CNBC / WSJ / Capital.com / dealroom /
Benzinga / US News (mid-2026 reporting). Estimates are labeled as estimates.

No LLM, no external calls, deterministic.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

# Standard market-rotation watch (where broad money goes during a mega-IPO)
_ROTATION = ["SPY", "QQQ", "IWM", "DIA", "XLK"]

# ───────────────────────────────────────────────────────────────────────────
# THE PIPELINE — ordered by expected valuation (largest first).
# valuation_usd / raise_usd are reported estimates, used for ordering + display.
# ───────────────────────────────────────────────────────────────────────────
IPO_PIPELINE: List[Dict[str, Any]] = [
    {
        "id": "spacex_ipo",
        "company": "SpaceX",
        "ticker": "SPCX",
        "status": "confirmed",
        "date": "2026-06-12",            # first day of trading (Nasdaq) — VERIFIED
        "pricing_date": "2026-06-11",    # priced after close the prior day
        "exchange": "Nasdaq",
        "valuation_usd": 1_900_000_000_000,   # ~$1.75-2T reported
        "raise_usd": 75_000_000_000,           # ~$75B — largest IPO in history
        "underwriters": ["GS", "MS", "BAC", "C", "JPM"],
        "sector": "Space / AI",
        "window_before": 30,
        "window_after": 120,
        "note": "Largest IPO in history. SpaceX now contains xAI/Starlink/Grok (Feb-2026 merger). The linchpin of the 2026 pipeline.",
        "complex": {
            "the_stock":       ["SPCX"],
            "space_defense":   ["BA", "LMT", "RTX", "NOC", "GD"],
            "ai_xai_complex":  ["NVDA", "AMD", "AVGO", "TSM", "MU", "PLTR", "MSFT", "GOOGL", "META"],
            "musk_adjacent":   ["TSLA"],
            "underwriters":    ["GS", "MS", "BAC", "C", "JPM"],
            "market_rotation": _ROTATION,
        },
    },
    {
        "id": "openai_ipo",
        "company": "OpenAI",
        "ticker": None,
        "status": "anticipated",
        "date": None,                     # NO confirmed date — do not fabricate
        "pricing_date": None,
        "exchange": None,
        "valuation_usd": 1_000_000_000_000,    # ~$1T talked
        "raise_usd": None,
        "underwriters": [],
        "sector": "AI",
        "window_before": 30,
        "window_after": 120,
        "note": "~$25B annualized revenue; Wall Street expects a listing before year-end 2026. Date TBD — activates here when confirmed.",
        "complex": {
            "ai_complex":      ["NVDA", "MSFT", "AMD", "AVGO", "GOOGL", "META", "PLTR", "TSM", "MU"],
            "market_rotation": _ROTATION,
        },
    },
    {
        "id": "anthropic_ipo",
        "company": "Anthropic",
        "ticker": None,
        "status": "anticipated",
        "date": None,
        "pricing_date": None,
        "exchange": None,
        "valuation_usd": 900_000_000_000,      # ~$900B reported in raise talks
        "raise_usd": None,
        "underwriters": [],
        "sector": "AI",
        "window_before": 30,
        "window_after": 120,
        "note": "In talks to raise ~$50B at ~$900B; reports of an IPO as early as October 2026. Date TBD. Public stakeholders include AMZN and GOOGL.",
        "complex": {
            "ai_complex":          ["NVDA", "MSFT", "AMD", "AVGO", "GOOGL", "META", "PLTR", "TSM"],
            "public_stakeholders": ["AMZN", "GOOGL"],
            "market_rotation":     _ROTATION,
        },
    },
    {
        "id": "databricks_ipo",
        "company": "Databricks",
        "ticker": None,
        "status": "anticipated",
        "date": None,
        "pricing_date": None,
        "exchange": None,
        "valuation_usd": 134_000_000_000,      # ~$134B last round
        "raise_usd": None,
        "underwriters": ["GS", "MS"],          # reported joint leads
        "sector": "AI / Data Infrastructure",
        "window_before": 30,
        "window_after": 120,
        "note": "~$4.8B revenue run-rate, +55% YoY, FCF-positive. S-1 expected mid-summer 2026; Q3 2026 window. Date TBD.",
        "complex": {
            "data_cloud":      ["SNOW", "MDB", "DDOG", "NET", "ORCL", "PLTR"],
            "ai":              ["NVDA", "MSFT"],
            "underwriters":    ["GS", "MS"],
            "market_rotation": _ROTATION,
        },
    },
    {
        "id": "stripe_ipo",
        "company": "Stripe",
        "ticker": None,
        "status": "anticipated",
        "date": None,
        "pricing_date": None,
        "exchange": None,
        "valuation_usd": 120_000_000_000,      # ~$106-150B reported
        "raise_usd": None,
        "underwriters": [],
        "sector": "Fintech / Payments",
        "window_before": 30,
        "window_after": 120,
        "note": "Largest private fintech; running employee tender offers (a common pre-IPO signal). 'In no rush'; late-2026 window. Date TBD.",
        "complex": {
            "fintech":         ["V", "MA", "PYPL", "COIN"],
            "market_rotation": _ROTATION,
        },
    },
]


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _days_until(date_str: Optional[str], today: date) -> Optional[int]:
    if not date_str:
        return None
    try:
        return (datetime.strptime(date_str[:10], "%Y-%m-%d").date() - today).days
    except Exception:
        return None


def phase_of(ipo: Dict[str, Any], today: Optional[date] = None) -> str:
    """upcoming_undated | upcoming | pre_event | event_window | post_event_decay | completed"""
    today = today or _today()
    du = _days_until(ipo.get("date"), today)
    if du is None:
        return "upcoming_undated"
    wb = ipo.get("window_before", 30)
    wa = ipo.get("window_after", 120)
    if du > wb:
        return "upcoming"
    if du > 1:
        return "pre_event"
    if -1 <= du <= 1:
        return "event_window"
    if du >= -wa:
        return "post_event_decay"
    return "completed"


def is_trackable(ipo: Dict[str, Any], today: Optional[date] = None) -> bool:
    """Dated and within [-window_after, +window_before] of its debut."""
    today = today or _today()
    du = _days_until(ipo.get("date"), today)
    if du is None:
        return False
    return (-ipo.get("window_after", 120)) <= du <= ipo.get("window_before", 30)


def active_ipo(today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """The IPO to deeply record now: the dated, in-window IPO closest to its
    debut (min |days_until|). None if nothing is currently trackable."""
    today = today or _today()
    candidates = [ipo for ipo in IPO_PIPELINE if is_trackable(ipo, today)]
    if not candidates:
        return None
    return min(candidates, key=lambda ipo: abs(_days_until(ipo["date"], today)))


def pipeline_status(today: Optional[date] = None) -> List[Dict[str, Any]]:
    """The full ordered pipeline with computed phase + days_until, for display."""
    today = today or _today()
    active = active_ipo(today)
    active_id = active["id"] if active else None
    rows = []
    for ipo in IPO_PIPELINE:
        rows.append({
            "id": ipo["id"],
            "company": ipo["company"],
            "ticker": ipo.get("ticker"),
            "status": ipo.get("status"),
            "date": ipo.get("date"),
            "pricing_date": ipo.get("pricing_date"),
            "exchange": ipo.get("exchange"),
            "valuation_usd": ipo.get("valuation_usd"),
            "raise_usd": ipo.get("raise_usd"),
            "underwriters": ipo.get("underwriters", []),
            "sector": ipo.get("sector"),
            "note": ipo.get("note", ""),
            "days_until": _days_until(ipo.get("date"), today),
            "phase": phase_of(ipo, today),
            "is_active": ipo["id"] == active_id,
        })
    return rows


def completed_ipos(today: Optional[date] = None) -> List[Dict[str, Any]]:
    today = today or _today()
    return [ipo for ipo in IPO_PIPELINE if phase_of(ipo, today) == "completed"]


if __name__ == "__main__":
    a = active_ipo()
    print("ACTIVE:", a["company"] if a else None)
    for r in pipeline_status():
        du = r["days_until"]
        print(f"  {r['company']:12} {r['status']:11} {str(r['date']):12} "
              f"{'T'+(('%+d'%du) if du is not None else 'BD'):>6}  {r['phase']:18} "
              f"{'<<ACTIVE' if r['is_active'] else ''}")
