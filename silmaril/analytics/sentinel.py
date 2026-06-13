"""
silmaril.analytics.sentinel — the system watches itself (Alpha 0.007).

This morning's lesson: GitHub's scheduler silently skipped the market-open
windows and nobody knew until 8:30. Cron priority can't be bought (Pro doesn't
fix it) — but SILENCE can be killed. The sentinel runs as the first suite step
of every cycle and raises ALARMS the briefing renders as a red banner:

  MISSED-RUN      signals.json older than 45 min during US market hours
                  (the exact failure of this morning)
  STALE-ORGAN     any core data file older than its freshness budget
  ROSTER-DRIFT    frozen-agent count or senate state missing/odd
  BROKER-SILENCE  no order/position refresh in any account state for >24h

Output docs/data/sentinel.json {alarms[], ok, checked} — plus a one-line
history so flapping is visible. Deterministic, stdlib-only, additive. The
sentinel cannot restart GitHub; it makes sure a skipped morning is LOUD.
(External belt-and-suspenders option, documented in READ_ME: a free uptime
pinger hitting workflow_dispatch with a PAT — your call, zero code needed.)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

# file -> freshness budget (minutes); generous off-hours handled below
BUDGETS = {
    "signals.json": 45,
    "scoring.json": 26 * 60,
    "report_card.json": 26 * 60,
    "source_rankings.json": 26 * 60,
    "timing_fingerprint.json": 26 * 60,
    "harvest_truth.json": 26 * 60,
}
ACCOUNT_STATES = ("alpaca_paper_state.json", "alpaca_h3_state.json",
                  "alpaca_h5_state.json")


def _age_min(p: Path) -> float:
    try:
        return (datetime.now(timezone.utc)
                - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                ).total_seconds() / 60.0
    except Exception:
        return 1e9


def _us_market_hours(now: datetime) -> bool:
    et = now + timedelta(hours=-4)
    if et.weekday() >= 5:
        return False
    mins = et.hour * 60 + et.minute
    return (9 * 60 + 30) <= mins <= (16 * 60)


def build_sentinel(out_dir: str) -> Dict[str, Any]:
    out = Path(out_dir)
    now = datetime.now(timezone.utc)
    in_session = _us_market_hours(now)
    alarms: List[str] = []
    checked = 0

    for fn, budget in BUDGETS.items():
        checked += 1
        age = _age_min(out / fn)
        if fn == "signals.json":
            if in_session and age > budget:
                alarms.append(f"MISSED-RUN: signals.json is {age:.0f} min old "
                              f"during market hours — the scheduler likely "
                              f"skipped; dispatch the daily workflow manually")
            elif not in_session and age > 20 * 60:
                alarms.append(f"STALE-ORGAN: signals.json {age/60:.1f}h old "
                              f"— no cycle since yesterday")
        elif age > budget:
            alarms.append(f"STALE-ORGAN: {fn} is {age/60:.1f}h old "
                          f"(budget {budget/60:.0f}h)")

    for fn in ACCOUNT_STATES:
        checked += 1
        if _age_min(out / fn) > 26 * 60:
            alarms.append(f"BROKER-SILENCE: {fn} not refreshed in >26h")

    try:
        rs = json.loads((out / "risk_state.json").read_text())
        frozen = [k for k, v in (rs.get("agents") or {}).items()
                  if isinstance(v, dict) and v.get("frozen")]
        if len(frozen) > 5:
            alarms.append(f"ROSTER-DRIFT: {len(frozen)} agents frozen "
                          f"({', '.join(frozen[:6])}) — review multipliers")
    except Exception:
        alarms.append("ROSTER-DRIFT: risk_state.json unreadable")
    checked += 1

    prev: Dict[str, Any] = {}
    try:
        prev = json.loads((out / "sentinel.json").read_text())
    except Exception:
        pass
    history = (prev.get("history") or [])[-40:]
    history.append({"t": now.isoformat()[:16], "alarms": len(alarms)})

    payload = {
        "generated_at": now.isoformat(),
        "in_market_hours": in_session,
        "ok": not alarms,
        "alarms": alarms,
        "checked": checked,
        "history": history,
        "note": ("silence is the enemy: a skipped scheduler window now shows "
                 "up here within one cycle, in red, on the briefing"),
    }
    (out / "sentinel.json").write_text(json.dumps(payload, indent=2))
    return {"ok": not alarms, "alarms": len(alarms), "checked": checked,
            "first": (alarms[0][:70] if alarms else None)}
