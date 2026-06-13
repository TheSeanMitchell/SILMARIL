"""
silmaril.portfolios.status_emitter — Compounder cycle status emitter.

Every run, each compounder ($1 and $10K) emits a standardized status
entry so the dashboard always has a fresh timestamp — even on cycles
where no trade was placed. This is the architectural fix for the
17:00 default-timestamp bug:

  Root cause: compounders only wrote to their history files when they
  ACTED (BUY, SELL, HODL). On cycles where they were gated (already
  acted today, or no signals), they wrote nothing. The dashboard
  interpreted the last written timestamp as "now", which showed as
  17:00 UTC (midnight UTC → 5pm Pacific fallback in the UI).

  Fix: emit a lightweight MARK entry every cycle, regardless of action.
  MARK = "I was alive this cycle, here's my current balance."

Status types:
  MARK    — alive, no new action, balance as-is
  ACTIVE  — acted this cycle (BUY/SELL/HODL recorded in agent's own history)
  FROZEN  — agent is in risk lockout
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def emit_compounder_status(
    compounder_states: Dict[str, Any],
    out_path: Path,
    cycle_date: Optional[str] = None,
) -> None:
    """
    Write a fresh status snapshot for every compounder this cycle.

    compounder_states: dict of {codename: state_dict} for
        SCROOGE, MIDAS, CRYPTOBRO, JRR_TOKEN, SPORTS_BRO

    out_path: where to write compounder_status.json (docs/data/)
    """
    today = cycle_date or _today()
    ts = _now()

    statuses: List[Dict] = []
    for codename, state in compounder_states.items():
        if not isinstance(state, dict):
            continue

        balance = state.get("balance", 0.0)
        history = state.get("history", [])

        # Determine if this compounder already acted today
        acted_today = any(
            h.get("date") == today and h.get("action") not in ("MARK", "HOLD")
            for h in history
        )

        status_type = "ACTIVE" if acted_today else "MARK"
        current_position = state.get("current_position")
        open_bets = state.get("open_bets")  # Sports Bro

        entry = {
            "codename": codename,
            "status": status_type,
            "date": today,
            "timestamp": ts,
            "balance": round(float(balance), 4),
            "current_position": current_position,
            "open_bets": open_bets,
            "current_life": state.get("current_life", 1),
            "lifetime_peak": round(float(state.get("lifetime_peak", balance)), 4),
        }
        statuses.append(entry)

    snapshot = {
        "cycle_date": today,
        "generated_at": ts,
        "compounders": {s["codename"]: s for s in statuses},
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2, default=str))


def emit_agent_portfolio_status(
    portfolios: Dict[str, Any],
    prices: Dict[str, float],
    out_path: Path,
    cycle_date: Optional[str] = None,
) -> None:
    """
    Write a cycle-level status snapshot for all $10K agent portfolios.
    Ensures every agent has a fresh timestamp in the dashboard even on
    non-trading cycles.
    """
    today = cycle_date or _today()
    ts = _now()

    statuses: Dict[str, Dict] = {}
    for agent_name, portfolio in portfolios.items():
        if hasattr(portfolio, "to_dict"):
            state = portfolio.to_dict()
        elif isinstance(portfolio, dict):
            state = portfolio
        else:
            continue

        cash = float(state.get("cash", 0))
        pos = state.get("current_position")
        mark_price = None
        if pos and prices:
            mark_price = prices.get(pos.get("ticker", ""))
        equity = cash + (pos.get("qty", 0) * mark_price if pos and mark_price else 0)

        history = state.get("history", [])
        acted_today = any(
            h.get("date") == today and h.get("action") not in ("MARK",)
            for h in history
        )

        statuses[agent_name] = {
            "agent": agent_name,
            "status": "ACTIVE" if acted_today else "MARK",
            "date": today,
            "timestamp": ts,
            "cash": round(cash, 2),
            "equity": round(equity, 2),
            "in_position": pos is not None,
            "position_ticker": pos.get("ticker") if pos else None,
        }

    snapshot = {
        "cycle_date": today,
        "generated_at": ts,
        "agents": statuses,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2, default=str))
