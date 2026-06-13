"""silmaril.risk.hard_stops — Alpha 6.0 per-account drawdown enforcement.

What it does
────────────
The master directive demands hard, automatic risk limits that the
executor cannot ignore:

  • Per-account daily stop:    -3% from open-of-day peak → halt opens
  • Per-account weekly stop:   -6% from 5-day peak → halt opens + tighten close
  • System cohort stop:        -4% combined → SAFE_MODE for the cycle

These limits PERSIST in `docs/data/hard_stops.json` so a halt in one
cycle survives until the rebound rule fires. The executor consults
`policy.hard_stops[account_id]` BEFORE submitting any open.

Output schema (docs/data/hard_stops.json)
─────────────────────────────────────────
{
  "version": "6.0",
  "generated_at": "...",
  "accounts": {
    "LEGACY": {
      "daily_pct_change": -0.025,
      "weekly_pct_change": -0.018,
      "daily_halted": false,
      "weekly_halted": false,
      "halt_opens": false,
      "tighten_trail": 1.0,
      "rebound_pending": false,
      "rationale": "within both daily and weekly bands"
    }, ...
  },
  "system": {
    "cohort_daily_pct": -0.012,
    "cohort_safe_mode": false,
    "rationale": "..."
  }
}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


VERSION  = "6.0"
FILENAME = "hard_stops.json"

# Hard limits — these are intentionally tighter than the risk_engine's
# 8% per-AGENT limit because they're per-ACCOUNT and the dollar size is
# much larger (10k each, not per-agent paper).
DAILY_HALT_PCT     = 0.03      # -3% in one day → halt opens
DAILY_REBOUND_PCT  = 0.015     # need +1.5% from halt low to unhalt
WEEKLY_HALT_PCT    = 0.06      # -6% rolling 5d → halt + tight trail
WEEKLY_REBOUND_PCT = 0.025     # need +2.5% recovery
COHORT_HALT_PCT    = 0.04      # avg of accounts -4% → system-wide safe mode


def _safe_f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def _load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _equity_for(astate: Dict[str, Any]) -> float:
    if not isinstance(astate, dict):
        return 0.0
    return _safe_f((astate.get("account") or {}).get("equity")
                    or astate.get("equity"))


def evaluate_account(
    account_id: str,
    current_equity: float,
    prior_state: Dict[str, Any],
    today: str,
) -> Dict[str, Any]:
    """Compute today's hard-stop state for one account.

    Maintains:
      - daily_open_equity  (set at first run each calendar day)
      - rolling_5d         (deque of (date, equity_end_of_day))
      - daily_low_since_halt   (tracked for rebound rule)
      - weekly_low_since_halt
    """
    today_key = today[:10]
    # Carry forward or initialize.
    daily_open = _safe_f(prior_state.get("daily_open_equity"))
    daily_open_date = prior_state.get("daily_open_date") or ""
    rolling = prior_state.get("rolling_5d") or []
    daily_halted_prev = bool(prior_state.get("daily_halted"))
    weekly_halted_prev = bool(prior_state.get("weekly_halted"))
    daily_low = _safe_f(prior_state.get("daily_low_since_halt"))
    weekly_low = _safe_f(prior_state.get("weekly_low_since_halt"))

    # New day → reset daily anchor.
    if daily_open_date != today_key or daily_open <= 0:
        daily_open = current_equity
        daily_open_date = today_key

    # Track daily low.
    if current_equity < daily_low or daily_low <= 0:
        daily_low = current_equity

    # Update rolling 5d window.
    rolling = [(d, e) for (d, e) in rolling
               if isinstance(d, str) and d != today_key]
    rolling.append((today_key, current_equity))
    rolling = rolling[-5:]

    # Compute deltas.
    daily_pct = ((current_equity - daily_open) / daily_open) if daily_open > 0 else 0.0
    weekly_anchor = max((e for (_, e) in rolling), default=current_equity)
    weekly_pct = ((current_equity - weekly_anchor) / weekly_anchor) if weekly_anchor > 0 else 0.0

    # Daily halt logic.
    if daily_halted_prev:
        # In halt — check rebound (from low).
        rebound_pct = ((current_equity - daily_low) / daily_low) if daily_low > 0 else 0.0
        daily_halted = rebound_pct < DAILY_REBOUND_PCT
        if not daily_halted:
            daily_low = 0.0   # reset
    else:
        daily_halted = daily_pct <= -DAILY_HALT_PCT
        if daily_halted:
            daily_low = current_equity

    # Weekly halt logic (rolling 5d).
    if weekly_halted_prev:
        rebound_w = ((current_equity - weekly_low) / weekly_low) if weekly_low > 0 else 0.0
        weekly_halted = rebound_w < WEEKLY_REBOUND_PCT
        if not weekly_halted:
            weekly_low = 0.0
    else:
        weekly_halted = weekly_pct <= -WEEKLY_HALT_PCT
        if weekly_halted:
            weekly_low = current_equity

    halt_opens = bool(daily_halted or weekly_halted)
    tighten_trail = 1.0
    if daily_halted:
        tighten_trail = 0.50    # halve giveback tolerance during daily halt
    elif weekly_halted:
        tighten_trail = 0.70

    bits = []
    if daily_halted:
        bits.append(f"DAILY HALT ({daily_pct*100:+.2f}% ≤ -{DAILY_HALT_PCT*100:.0f}%)")
    elif daily_pct < -DAILY_HALT_PCT / 2:
        bits.append(f"daily watch {daily_pct*100:+.2f}%")
    if weekly_halted:
        bits.append(f"WEEKLY HALT ({weekly_pct*100:+.2f}% ≤ -{WEEKLY_HALT_PCT*100:.0f}%)")
    if not bits:
        bits.append(f"clear · daily {daily_pct*100:+.2f}% · weekly {weekly_pct*100:+.2f}%")

    return {
        "account_id":            account_id,
        "current_equity":        round(current_equity, 2),
        "daily_open_equity":     round(daily_open, 2),
        "daily_open_date":       daily_open_date,
        "daily_pct_change":      round(daily_pct, 4),
        "weekly_anchor_equity":  round(weekly_anchor, 2),
        "weekly_pct_change":     round(weekly_pct, 4),
        "rolling_5d":            rolling,
        "daily_halted":          daily_halted,
        "weekly_halted":         weekly_halted,
        "halt_opens":            halt_opens,
        "tighten_trail":         tighten_trail,
        "daily_low_since_halt":  round(daily_low, 2),
        "weekly_low_since_halt": round(weekly_low, 2),
        "rationale":             " · ".join(bits),
    }


def build_hard_stops(
    data_dir: Path,
    multi_account_results: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute + persist hard_stops.json.

    Called from cli.py after multi_account_results is finalized so the
    NEXT cycle's executor sees the right halts. For the FIRST cycle of a
    new halt event (e.g. account just hit -3% intraday), the current
    cycle's executor still got to open before this fires — that's fine,
    the daily peak protection is what the per-trade trailing stop is for.
    """
    n_now = now or datetime.now(timezone.utc)
    today = n_now.date().isoformat()
    prior = _load_json(data_dir / FILENAME) or {}
    prior_accounts = (prior.get("accounts") or {}) if isinstance(prior, dict) else {}

    accounts_out: Dict[str, Any] = {}
    cohort_pcts: List[float] = []
    if isinstance(multi_account_results, dict):
        for aid, astate in multi_account_results.items():
            if not isinstance(astate, dict) or not astate.get("enabled"):
                continue
            eq = _equity_for(astate)
            prev = prior_accounts.get(aid) or {}
            accounts_out[aid] = evaluate_account(aid, eq, prev, today)
            cohort_pcts.append(accounts_out[aid]["daily_pct_change"])

    cohort_avg = (sum(cohort_pcts) / len(cohort_pcts)) if cohort_pcts else 0.0
    prior_safe = bool((prior.get("system") or {}).get("cohort_safe_mode"))
    cohort_safe = cohort_avg <= -COHORT_HALT_PCT
    # Sticky once entered until cohort recovers half the threshold.
    if prior_safe and cohort_avg > -COHORT_HALT_PCT * 0.4:
        cohort_safe = False
    elif prior_safe:
        cohort_safe = True

    system_block = {
        "cohort_daily_pct":    round(cohort_avg, 4),
        "cohort_safe_mode":    cohort_safe,
        "rationale":          (f"SYSTEM SAFE_MODE — cohort {cohort_avg*100:+.2f}%"
                                  if cohort_safe else
                                  f"cohort {cohort_avg*100:+.2f}% within bands"),
    }

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "accounts":     accounts_out,
        "system":       system_block,
        "config": {
            "daily_halt_pct":     DAILY_HALT_PCT,
            "daily_rebound_pct":  DAILY_REBOUND_PCT,
            "weekly_halt_pct":    WEEKLY_HALT_PCT,
            "weekly_rebound_pct": WEEKLY_REBOUND_PCT,
            "cohort_halt_pct":    COHORT_HALT_PCT,
        },
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[hard_stops] write failed: {e}")
    return payload


def load_hard_stops(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "accounts": {}, "system": {"cohort_safe_mode": False}}


def get_account_stop(data_dir: Path, account_id: str) -> Dict[str, Any]:
    """Convenience lookup for the executor."""
    body = load_hard_stops(data_dir)
    return (body.get("accounts") or {}).get(account_id, {})


__all__ = [
    "VERSION", "DAILY_HALT_PCT", "WEEKLY_HALT_PCT", "COHORT_HALT_PCT",
    "evaluate_account", "build_hard_stops", "load_hard_stops",
    "get_account_stop",
]
