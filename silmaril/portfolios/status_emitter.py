"""
silmaril.portfolios.status_emitter — The single source of truth for
agent status entries.

Every compounder ($1 SCROOGE, $1 MIDAS, $1 CRYPTOBRO, $1 JRR_TOKEN,
$1 SPORTS_BRO — soon all $10K) and every $10K career agent must route
their status writes through emit_status() in this module.

Why one emitter:
  - Every entry uses datetime.now(timezone.utc).isoformat(). No date-only
    strings. No hardcoded hour fallbacks. The "17:00 default timestamp"
    bug becomes mathematically impossible.
  - Every agent emits a status entry every cycle, including when they
    HOLD or are FROZEN. Stale-looking timelines (King Midas showing no
    activity) become impossible because there is always an entry.
  - Action types are enumerated. No drift between agent state machines.

Action types:
  BUY     — opened a long position
  SELL    — opened a short position
  CLOSE   — closed an existing position
  HOLD    — voted HOLD this cycle (no action taken, no position held)
  MARK    — holding an open position, marked-to-market for the cycle
  FROZEN  — agent is locked by AgentRiskState (drawdown trigger)
  RESET   — agent reincarnated (compounders only, hits at -50% drawdown)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


VALID_ACTIONS = {"BUY", "SELL", "CLOSE", "HOLD", "MARK", "FROZEN", "RESET"}


def emit_status(
    *,
    history: List[Dict[str, Any]],
    action: str,
    ticker: Optional[str] = None,
    price: Optional[float] = None,
    qty: Optional[float] = None,
    pnl: Optional[float] = None,
    pnl_pct: Optional[float] = None,
    balance_before: Optional[float] = None,
    balance_after: Optional[float] = None,
    current_position: Optional[Dict[str, Any]] = None,
    signal: Optional[str] = None,
    reason: str = "",
    ts: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Append one normalized status entry to history. Returns the entry.
    Required: history list, action.
    Always writes a full ISO timestamp via datetime.now(timezone.utc),
    or `ts` if explicitly provided. Never writes a date-only string.
    """
    if action not in VALID_ACTIONS:
        raise ValueError(
            f"emit_status: invalid action {action!r}. "
            f"Valid actions: {sorted(VALID_ACTIONS)}"
        )

    when = ts if ts is not None else datetime.now(timezone.utc)
    entry: Dict[str, Any] = {
        "timestamp": when.isoformat(),
        "date": when.date().isoformat(),
        "action": action,
    }

    if ticker is not None:
        entry["ticker"] = ticker
    if price is not None:
        entry["price"] = price
    if qty is not None:
        entry["qty"] = qty
    if pnl is not None:
        entry["pnl"] = round(pnl, 4)
    if pnl_pct is not None:
        entry["pnl_pct"] = round(pnl_pct, 2)
    if balance_before is not None:
        entry["balance_before"] = round(balance_before, 4)
    if balance_after is not None:
        entry["balance_after"] = round(balance_after, 4)
    if current_position is not None:
        entry["current_position"] = current_position
    if signal is not None:
        entry["signal"] = signal
    if reason:
        entry["reason"] = reason

    history.append(entry)
    return entry


def emit_hold(
    history: List[Dict[str, Any]],
    balance: float,
    reason: str = "No qualifying signal",
) -> Dict[str, Any]:
    """Convenience: agent voted HOLD this cycle, no action taken."""
    return emit_status(
        history=history, action="HOLD",
        balance_before=balance, balance_after=balance, reason=reason,
    )


def emit_mark(
    history: List[Dict[str, Any]],
    balance: float,
    current_position: Dict[str, Any],
    reason: str = "Mark-to-market",
) -> Dict[str, Any]:
    """Convenience: agent is holding a position, mark-to-market for the cycle."""
    return emit_status(
        history=history, action="MARK",
        balance_after=balance, current_position=current_position, reason=reason,
    )


def emit_frozen(
    history: List[Dict[str, Any]],
    balance: float,
    reason: str,
) -> Dict[str, Any]:
    """Convenience: agent is locked by risk state."""
    return emit_status(
        history=history, action="FROZEN",
        balance_before=balance, balance_after=balance, reason=reason,
    )


def latest_status(history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the most recent status entry, or None if history is empty."""
    return history[-1] if history else None


def cycles_since_last_action(history: List[Dict[str, Any]]) -> int:
    """
    Count how many consecutive HOLD/MARK/FROZEN entries are at the tail.
    Used by the dashboard to flag agents that haven't acted recently.
    """
    count = 0
    for entry in reversed(history):
        if entry.get("action") in ("HOLD", "MARK", "FROZEN"):
            count += 1
        else:
            break
    return count
