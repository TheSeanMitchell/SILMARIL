"""silmaril.diagnostics.harvest_accounts_status — Rollup for the new tab.

Combines per-account state dicts (from execution.multi_account) into a
single JSON shape the dashboard can render directly without N round-trips.

Output: docs/data/harvest_accounts.json:
{
  "version": "3.0",
  "generated_at": "...",
  "accounts": [
    {
      "account_id": "LEGACY",
      "label": "1.5% Trench-Warfare Harvester (legacy)",
      "configured": true,
      "enabled": true,
      "principal_target": 10000,
      "equity": 10308.87,
      "cash": -10089.16,
      "buying_power": 219.71,
      "unrealized_above_baseline": 308.87,
      "verified_harvested": 0.0,
      "open_positions": 14,
      "oldest_position_age_days": 3,
      "daily_cap_used": null,
      "min_harvest_gain_pct": 0.015,
      "last_cycle": { "opened": 0, "closed": 0, "open_after": 14 },
      "time_basis": { "real_days": 4, "market_days": 3 },
      "reason": "",            // populated when not enabled
      "errors": [...]
    },
    ...
  ],
  "totals": {
    "equity_all": ...,
    "verified_all": ...,
    "unrealized_all": ...,
  }
}
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import time_basis


def _safe_float(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def _oldest_position_age_days(state: Dict[str, Any]) -> Optional[int]:
    """Inspect position_meta for the earliest first_seen timestamp."""
    meta = state.get("position_meta") or {}
    if not meta:
        return None
    today = datetime.now(timezone.utc).date()
    ages = []
    for sym, m in meta.items():
        fs = m.get("first_seen") or m.get("entered_at")
        if not fs:
            continue
        try:
            d = date.fromisoformat(str(fs).split("T", 1)[0])
            ages.append((today - d).days)
        except Exception:
            continue
    return max(ages) if ages else None


def _genesis_for_account(state: Dict[str, Any], account_id: str) -> Optional[str]:
    """Pick the most reliable 'when did this account start trading' anchor.

    Prefer the account's first recorded order's time; fall back to
    state.get('first_seen') or today. The intent: stable across runs."""
    orders = state.get("orders") or []
    if orders:
        # 'time' is ISO timestamp on every order record
        timestamps = [o.get("time") for o in orders if o.get("time")]
        if timestamps:
            return min(timestamps)
    if state.get("genesis_at"):
        return state["genesis_at"]
    return None


def build_rollup(
    multi_account_results: Dict[str, Dict[str, Any]],
    verified_harvest_summary: Optional[Dict[str, Dict[str, float]]] = None,
    vault_reconciliation: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the harvest_accounts.json rollup. Pure function — no I/O.

    vault_reconciliation: optional per-account dict from
        verified_harvest.reconcile_with_live_vault(...). When present, the
        rollup reports live SGOV market value as the verified figure (the
        honest "what's actually parked in treasuries right now"), and flags
        whether the on-disk ledger agrees.
    """
    accounts_out: List[Dict[str, Any]] = []
    totals_equity = 0.0
    totals_unrealized = 0.0
    totals_verified = 0.0
    totals_live_vault = 0.0
    configured_count = 0
    enabled_count = 0

    for account_id, state in multi_account_results.items():
        if not isinstance(state, dict):
            continue
        acct = state.get("account") or {}
        last_cycle = state.get("last_cycle_summary") or {}
        principal = _safe_float(state.get("principal_target"), 10_000.0)
        equity = _safe_float(acct.get("equity"))
        cash = _safe_float(acct.get("cash"))
        unrealized = max(0.0, equity - principal) if equity > 0 else 0.0
        verified_ledger = 0.0
        if verified_harvest_summary:
            bucket = verified_harvest_summary.get(account_id) or {}
            verified_ledger = _safe_float(bucket.get("verified"))

        # Live SGOV vault — the trustworthy verified figure
        recon = (vault_reconciliation or {}).get(account_id) or {}
        live_vault_value = _safe_float(recon.get("live_market_value"), 0.0)
        # "Verified" surfaced to the dashboard = live vault if held, else
        # the ledger sum (which today is 0 until SGOV buys are wired in).
        verified = live_vault_value if live_vault_value > 0 else verified_ledger

        genesis = _genesis_for_account(state, account_id)
        tb = time_basis.build(genesis) if genesis else None

        row = {
            "account_id": account_id,
            "label": state.get("label", account_id),
            "configured": bool(state.get("configured", True)),
            "enabled": bool(state.get("enabled", False)),
            "principal_target": round(principal, 2),
            "equity": round(equity, 2),
            "cash": round(cash, 2),
            "trading_capital": round(_safe_float(state.get("trading_capital"), principal), 2),
            "unrealized_above_baseline": round(unrealized, 2),
            "verified_harvested": round(verified, 2),
            "verified_ledger_total": round(verified_ledger, 2),
            "live_vault": {
                "market_value":   round(live_vault_value, 2),
                "primary_symbol": recon.get("primary_symbol"),
                "primary_qty":    recon.get("primary_qty", 0.0),
                "holdings":       recon.get("holdings", []),
                "reconciled":     bool(recon.get("reconciled", live_vault_value <= 0)),
                "delta":          round(_safe_float(recon.get("delta"), 0.0), 2),
                "mode":           recon.get("mode", "anchor_only"),
            },
            "sgov_sweep": state.get("sgov_sweep_last_cycle") or {"attempted": False},
            "open_positions": int(last_cycle.get("open_after", 0) or 0),
            "oldest_position_age_days": _oldest_position_age_days(state),
            "min_harvest_gain_pct": _safe_float(state.get("min_harvest_gain_pct"), 0.015),
            "last_cycle": {
                "opened": int(last_cycle.get("opened", 0) or 0),
                "closed": int(last_cycle.get("closed", 0) or 0),
                "open_after": int(last_cycle.get("open_after", 0) or 0),
                "tickers": last_cycle.get("tickers_traded", []),
                "time": last_cycle.get("time"),
            },
            "lifetime_wins":   int(state.get("lifetime_realized_wins", 0) or 0),
            "lifetime_losses": int(state.get("lifetime_realized_losses", 0) or 0),
            "time_basis": tb.to_dict() if tb else {
                "real_days": 0, "market_days": 0, "crypto_hours": 0, "genesis_iso": ""
            },
            "reason": state.get("reason", "") if not state.get("enabled") else "",
            "errors": (state.get("errors", []) or [])[-5:],
        }
        accounts_out.append(row)

        if row["configured"]:
            configured_count += 1
        if row["enabled"]:
            enabled_count += 1
            totals_equity += equity
            totals_unrealized += unrealized
            totals_verified += verified
            totals_live_vault += live_vault_value

    return {
        "version": "3.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accounts": accounts_out,
        "totals": {
            "equity_all":      round(totals_equity, 2),
            "verified_all":    round(totals_verified, 2),
            "unrealized_all":  round(totals_unrealized, 2),
            "live_vault_all":  round(totals_live_vault, 2),
            "configured_accounts": configured_count,
            "enabled_accounts":    enabled_count,
            "total_accounts":      len(accounts_out),
        },
    }


def write_rollup(
    data_dir: Path,
    multi_account_results: Dict[str, Dict[str, Any]],
    verified_harvest_summary: Optional[Dict[str, Dict[str, float]]] = None,
    vault_reconciliation: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    rollup = build_rollup(
        multi_account_results, verified_harvest_summary, vault_reconciliation)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "harvest_accounts.json").write_text(
        json.dumps(rollup, indent=2, default=str))
    return rollup


__all__ = ["build_rollup", "write_rollup"]
