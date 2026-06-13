"""silmaril.diagnostics.time_basis — Unified day counting.

Why this exists
───────────────
Different agents in the system have been computing "days alive" in three
slightly different ways:

  * Equity compounders (SCROOGE/MIDAS) used `(today_utc - life_start).days`
  * Crypto compounders (CRYPTOBRO/JRR) did the same — but crypto trades 24/7,
    so a raw day count overstates "trading days" for a fair comparison.
  * Sports Bro used the same raw count.

The screenshots from 2026-05-10 showed equity compounders at "4d" while the
JRR Token memecoin wallet showed "6d". They were both correct under their
own definitions — but the user can't compare them. So we publish ALL three
counts from one helper and let the dashboard pick whichever it wants.

Backward compatibility
──────────────────────
The existing `days_alive` field on every agent JSON is untouched. This
module is purely *additive* — it produces a `time_basis` block that can
be appended without removing or renaming anything.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, Optional, Union


# US market holidays we care about for trading-day counts.
# Hard-coded for 2025-2026 because exhaustive holiday packages are not in
# requirements.txt. If a date isn't here it's treated as a normal weekday.
# Easy to extend; we only need the years we're alive in.
_US_MARKET_HOLIDAYS: set = {
    # 2025
    date(2025, 1, 1),   date(2025, 1, 20),  date(2025, 2, 17),
    date(2025, 4, 18),  date(2025, 5, 26),  date(2025, 6, 19),
    date(2025, 7, 4),   date(2025, 9, 1),   date(2025, 11, 27),
    date(2025, 12, 25),
    # 2026
    date(2026, 1, 1),   date(2026, 1, 19),  date(2026, 2, 16),
    date(2026, 4, 3),   date(2026, 5, 25),  date(2026, 6, 19),
    date(2026, 7, 3),   date(2026, 9, 7),   date(2026, 11, 26),
    date(2026, 12, 25),
    # 2027 (placeholder, fixed dates only — observance shifts not modeled)
    date(2027, 1, 1),   date(2027, 7, 5),   date(2027, 12, 24),
}


def _coerce_date(value: Union[str, date, datetime, None]) -> Optional[date]:
    """Accept whatever the caller has — string ISO, date, datetime, None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        # Be liberal: split on 'T' or space to drop time component if present
        s = str(value).split("T", 1)[0].split(" ", 1)[0]
        return date.fromisoformat(s)
    except Exception:
        return None


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def real_elapsed_days(genesis: Union[str, date, None],
                      now: Optional[date] = None) -> int:
    """Wall-clock calendar days since genesis. Crypto/sports basis."""
    g = _coerce_date(genesis)
    if g is None:
        return 0
    n = now or _today_utc()
    return max(0, (n - g).days)


def market_trading_days(genesis: Union[str, date, None],
                        now: Optional[date] = None) -> int:
    """US-market trading days since genesis (exclusive of genesis,
    inclusive of today if today is a trading day)."""
    g = _coerce_date(genesis)
    if g is None:
        return 0
    n = now or _today_utc()
    if n <= g:
        return 0
    count = 0
    d = g + timedelta(days=1)
    while d <= n:
        if d.weekday() < 5 and d not in _US_MARKET_HOLIDAYS:
            count += 1
        d += timedelta(days=1)
    return count


def crypto_continuous_hours(genesis_iso: Union[str, None],
                            now_iso: Optional[str] = None) -> int:
    """Continuous hours since genesis. Crypto runs 24/7 so hours are the
    fairest comparison if you want to know 'how much time has the market
    actually been open under this agent's feet'."""
    if not genesis_iso:
        return 0
    try:
        # Tolerate both date-only ("2026-05-04") and full ISO timestamps.
        s = str(genesis_iso)
        if "T" not in s and " " not in s:
            s = s + "T00:00:00+00:00"
        # Python's fromisoformat handles +00:00 since 3.11; fallback for older.
        try:
            g = datetime.fromisoformat(s)
        except ValueError:
            g = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if g.tzinfo is None:
            g = g.replace(tzinfo=timezone.utc)
        n = (datetime.fromisoformat(now_iso) if now_iso
             else datetime.now(timezone.utc))
        if n.tzinfo is None:
            n = n.replace(tzinfo=timezone.utc)
        delta = n - g
        return max(0, int(delta.total_seconds() // 3600))
    except Exception:
        return 0


@dataclass
class TimeBasis:
    """Three coexisting answers to 'how old is this agent?'."""
    real_days:          int = 0   # calendar days
    market_days:        int = 0   # US trading days (Mon–Fri minus holidays)
    crypto_hours:       int = 0   # continuous hours (24/7)
    genesis_iso:        str = ""  # echo of the input so the dashboard can audit

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build(genesis_iso: Union[str, None]) -> TimeBasis:
    """Build a TimeBasis from an ISO date or datetime string."""
    return TimeBasis(
        real_days=real_elapsed_days(genesis_iso),
        market_days=market_trading_days(genesis_iso),
        crypto_hours=crypto_continuous_hours(genesis_iso),
        genesis_iso=str(genesis_iso or ""),
    )


def label_for(agent_codename: str) -> str:
    """Pick the right label for a given agent class.

    Equity agents → market days are the honest comparison.
    Crypto / 24-7 agents → real days are more accurate (markets never close).
    Sports → real days.
    """
    name = (agent_codename or "").upper()
    if name in {"CRYPTOBRO", "JRR_TOKEN", "MIDAS"}:
        return "real_days"
    if name in {"SPORTS_BRO"}:
        return "real_days"
    return "market_days"


__all__ = [
    "TimeBasis",
    "build",
    "label_for",
    "real_elapsed_days",
    "market_trading_days",
    "crypto_continuous_hours",
]
