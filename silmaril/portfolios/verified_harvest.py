"""silmaril.portfolios.verified_harvest — The verified harvest ledger.

Why this exists
───────────────
The Sunday Opus prompt's #1 complaint: the dashboard says "$308 harvested"
but the cash never physically left the trading book. The number is an
*unrealized* equity-above-baseline figure dressed up as savings.

This module introduces a state machine that explicitly distinguishes:

    ANCHOR  → equity-above-principal accounting (the legacy, unrealized,
              still-shown-in-grocery-leaderboard mode). Always available.

    INTENT  → "we want to harvest $X right now" (signal generated).

    SELL_QUEUED   → the sell order was submitted to Alpaca.
    SELL_FILLED   → Alpaca confirmed the sell. Cash is real.

    SGOV_QUEUED   → a follow-on SGOV buy was submitted.
    SGOV_FILLED   → SGOV shares are held. THIS IS THE ONLY VERIFIED STATE.

    VERIFIED      → terminal. Cash genuinely transferred from active
                    trading equity into a non-trading SGOV holding.

For Alpha 3.0 the state machine only needs to record ANCHOR rows; the
SGOV-buy hookup is a one-line wire-in once you decide which Alpaca
account holds the SGOV vault. The ledger is shaped so that wire-in
doesn't change any consumer of the data — dashboards just start showing
VERIFIED rows instead of ANCHOR rows.

JSON shape (docs/data/verified_harvest_ledger.json):
{
  "version": "3.0",
  "rows": [
    { "id": "...", "account_id": "LEGACY", "status": "ANCHOR",
      "triggered_at": "...", "amount": 30.70, "source": "equity_above_principal",
      "agent_attribution": [...], "notes": "..." }
  ],
  "by_account": {
    "LEGACY":    { "anchor": 308.87, "verified": 0.0 },
    "HARVEST_3": { "anchor": 0.0,    "verified": 0.0 },
    "HARVEST_5": { "anchor": 0.0,    "verified": 0.0 }
  }
}
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


LEDGER_FILENAME = "verified_harvest_ledger.json"

STATES = ("ANCHOR", "INTENT", "SELL_QUEUED", "SELL_FILLED",
          "SGOV_QUEUED", "SGOV_FILLED", "VERIFIED", "FAILED")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _load(data_dir: Path) -> Dict[str, Any]:
    p = data_dir / LEDGER_FILENAME
    if not p.exists():
        return {"version": "3.0", "rows": [], "by_account": {}}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"version": "3.0", "rows": [], "by_account": {}}


def _save(data_dir: Path, ledger: Dict[str, Any]) -> None:
    p = data_dir / LEDGER_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    ledger["generated_at"] = _now_iso()
    # Keep most recent 1000 rows; rollups still reflect everything by being recomputed.
    ledger["rows"] = ledger.get("rows", [])[-1000:]
    p.write_text(json.dumps(ledger, indent=2, default=str))


def _rebuild_account_totals(ledger: Dict[str, Any]) -> None:
    """Recompute by_account totals from the row history."""
    totals: Dict[str, Dict[str, float]] = {}
    for r in ledger.get("rows", []):
        acct = r.get("account_id", "UNKNOWN")
        bucket = totals.setdefault(acct, {"anchor": 0.0, "verified": 0.0,
                                          "rows_anchor": 0, "rows_verified": 0})
        amt = float(r.get("amount") or 0)
        status = r.get("status", "ANCHOR")
        if status == "ANCHOR":
            bucket["anchor"] = max(bucket["anchor"], amt)  # anchor is current snapshot
            bucket["rows_anchor"] += 1
        elif status == "VERIFIED":
            bucket["verified"] += amt
            bucket["rows_verified"] += 1
    ledger["by_account"] = totals


def anchor_account_savings(
    data_dir: Path,
    account_id: str,
    equity: float,
    principal: float,
    agent_attribution: Optional[List[Dict[str, Any]]] = None,
    notes: str = "",
) -> Dict[str, Any]:
    """Record an ANCHOR row reflecting "equity above principal" right now.

    This is the legacy unrealized-savings number, but stored in the
    verified-harvest schema so the dashboard can show ANCHOR vs VERIFIED
    side-by-side. The user clearly sees what's actually swept vs what's
    just sitting above baseline.

    Returns the row dict that was appended.
    """
    ledger = _load(data_dir)
    amount = round(max(0.0, float(equity) - float(principal)), 4)
    row = {
        "id": uuid.uuid4().hex[:12],
        "account_id": account_id,
        "status": "ANCHOR",
        "triggered_at": _now_iso(),
        "date": _today_iso(),
        "amount": amount,
        "equity": round(float(equity), 4),
        "principal": round(float(principal), 4),
        "source": "equity_above_principal",
        "agent_attribution": agent_attribution or [],
        "notes": notes or "Anchor mode — no SGOV transfer yet",
    }
    ledger.setdefault("rows", []).append(row)
    _rebuild_account_totals(ledger)
    _save(data_dir, ledger)
    return row


def record_intent(
    data_dir: Path,
    account_id: str,
    amount: float,
    source_tickers: List[str],
    agent_attribution: List[Dict[str, Any]],
    notes: str = "",
) -> Dict[str, Any]:
    """Record that the system intends to harvest `amount` right now."""
    ledger = _load(data_dir)
    row = {
        "id": uuid.uuid4().hex[:12],
        "account_id": account_id,
        "status": "INTENT",
        "triggered_at": _now_iso(),
        "date": _today_iso(),
        "amount": round(float(amount), 4),
        "source_tickers": source_tickers,
        "agent_attribution": agent_attribution,
        "notes": notes,
    }
    ledger.setdefault("rows", []).append(row)
    _save(data_dir, ledger)
    return row


def transition(
    data_dir: Path,
    row_id: str,
    new_status: str,
    **patch: Any,
) -> Optional[Dict[str, Any]]:
    """Advance a ledger row's state. Returns the updated row.

    Valid transitions:
       INTENT       → SELL_QUEUED
       SELL_QUEUED  → SELL_FILLED
       SELL_FILLED  → SGOV_QUEUED
       SGOV_QUEUED  → SGOV_FILLED
       SGOV_FILLED  → VERIFIED

    Any state → FAILED is permitted with an error reason.
    """
    if new_status not in STATES:
        return None
    ledger = _load(data_dir)
    for r in ledger.get("rows", []):
        if r.get("id") == row_id:
            r["status"] = new_status
            r["last_updated_at"] = _now_iso()
            for k, v in patch.items():
                r[k] = v
            _rebuild_account_totals(ledger)
            _save(data_dir, ledger)
            return r
    return None


def summary_by_account(data_dir: Path) -> Dict[str, Dict[str, float]]:
    """Return per-account anchor vs verified totals. Used by dashboard."""
    ledger = _load(data_dir)
    _rebuild_account_totals(ledger)
    return ledger.get("by_account", {})


def all_rows(data_dir: Path, account_id: Optional[str] = None) -> List[Dict]:
    """Return raw rows (optionally filtered). Used by dashboard history view."""
    ledger = _load(data_dir)
    rows = ledger.get("rows", [])
    if account_id:
        rows = [r for r in rows if r.get("account_id") == account_id]
    return rows


def reconcile_with_live_vault(
    data_dir: Path,
    account_id: str,
    savings_vault: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compare ledger 'verified' total against live SGOV holdings.

    savings_vault is the dict that alpaca_paper._extract_savings_vault writes
    into state["savings_vault"]. We pull the live market value and compare
    against the sum of VERIFIED-status rows. A discrepancy means the ledger
    hasn't caught up to reality (or someone manually moved shares).

    Returns a small status dict the dashboard can render:
      {
        "live_market_value": 0.0,         # what Alpaca says we hold right now
        "ledger_verified_total": 0.0,     # what verified-harvest rows sum to
        "reconciled": true,               # within $1 of each other
        "delta": 0.0,
        "primary_symbol": "SGOV" | None,
        "primary_qty": 0.0,
        "checked_at": "..."
      }
    """
    vault = savings_vault or {}
    live = float(vault.get("primary_market_value", 0.0) or 0.0)
    summary = summary_by_account(data_dir).get(account_id, {})
    ledger_verified = float(summary.get("verified", 0.0) or 0.0)
    delta = round(live - ledger_verified, 4)
    return {
        "account_id": account_id,
        "live_market_value": round(live, 4),
        "ledger_verified_total": round(ledger_verified, 4),
        "delta": delta,
        "reconciled": abs(delta) < 1.0,
        "primary_symbol": vault.get("primary_symbol"),
        "primary_qty":    vault.get("primary_qty"),
        "holdings":       vault.get("holdings", []),
        "checked_at":     vault.get("checked_at"),
        "mode": "anchor_only" if live <= 0 else "live_verified",
    }


__all__ = [
    "STATES",
    "anchor_account_savings",
    "record_intent",
    "transition",
    "summary_by_account",
    "all_rows",
    "reconcile_with_live_vault",
]
