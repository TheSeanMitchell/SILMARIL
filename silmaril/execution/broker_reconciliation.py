"""
silmaril.execution.broker_reconciliation — Is our book the broker's book?

The dashboard once claimed LEGACY held 42 names while Alpaca held 0. Root cause:
`position_meta` (the per-symbol memo dict) is only pruned on the SELL path
(alpaca_paper.py ~L711 `position_meta.pop`). Positions that leave the book any
other way — a fill that closed elsewhere, a manual flatten, a stale entry from a
prior schema — never get pruned, so meta accumulates phantoms that the real
`positions_snapshot` does not contain.

This module is the truth check. For each account it diffs:
    position_meta keys   (what we THINK we hold / remember)
  vs positions_snapshot   (what the last broker pull actually returned)
and flags:
    • phantom_in_meta      held-in-memory but NOT in the broker snapshot
    • missing_meta         in the broker snapshot but no memo (rare)
    • configured anomaly   account is trading (orders/positions) yet configured:false
    • dormancy             days since the last order (skipped-account detector)
    • drawdown             trading_capital vs the $10k principal baseline

It is READ-ONLY. It writes docs/data/broker_reconciliation.json and emits a
RECOMMENDED gated fix (prune meta to the snapshot on the live path) but performs
no writes to any account state. Safe to run every cycle.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

RECON_VERSION = "broker-reconciliation-1.0"

# The three live paper accounts and their state files.
ACCOUNT_FILES = [
    ("LEGACY",    "alpaca_paper_state.json"),
    ("HARVEST_3", "alpaca_h3_state.json"),
    ("HARVEST_5", "alpaca_h5_state.json"),
]


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _dump(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(_sanitize(obj), f, indent=2, default=str, allow_nan=False)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _snapshot_symbols(state: Dict[str, Any]) -> List[str]:
    snap = state.get("positions_snapshot") or []
    syms = []
    for p in snap:
        if isinstance(p, dict):
            s = p.get("symbol") or p.get("ticker")
            if s:
                syms.append(str(s).upper())
        elif isinstance(p, str):
            syms.append(p.upper())
    return syms


def _latest_order_ts(state: Dict[str, Any]) -> Optional[str]:
    best = None
    for o in (state.get("orders") or []):
        if not isinstance(o, dict):
            continue
        ts = o.get("submitted_at") or o.get("created_at") or o.get("time") or o.get("ts")
        if ts and (best is None or str(ts) > str(best)):
            best = str(ts)
    return best


def _days_since(iso: Optional[str], ref: datetime) -> Optional[int]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (ref - dt).days
    except Exception:
        return None


def reconcile_account(account_id: str, state: Dict[str, Any], ref: datetime) -> Dict[str, Any]:
    meta = state.get("position_meta") or {}
    meta_syms = {str(k).upper() for k in meta.keys()}
    snap_syms = set(_snapshot_symbols(state))

    phantom = sorted(meta_syms - snap_syms)   # remembered but not actually held
    missing = sorted(snap_syms - meta_syms)   # held but no memo
    matched = sorted(meta_syms & snap_syms)

    orders = state.get("orders") or []
    has_orders = len(orders) > 0
    n_snap = len(snap_syms)
    configured = bool(state.get("configured", True))  # LEGACY file lacks the flag → treat as configured
    last_order = _latest_order_ts(state)
    last_run = state.get("last_run")
    dormant_days = _days_since(last_order, ref)

    cap = state.get("trading_capital")
    principal = state.get("principal_target") or 10000.0
    drawdown_pct = None
    if cap is not None and principal:
        drawdown_pct = round((float(cap) - float(principal)) / float(principal) * 100, 2)

    flags: List[Dict[str, str]] = []
    if phantom:
        flags.append({
            "level": "WARN",
            "code": "PHANTOM_POSITIONS",
            "detail": f"{len(phantom)} symbols in position_meta are NOT in the broker snapshot: "
                      + ", ".join(phantom[:12]) + ("…" if len(phantom) > 12 else ""),
        })
    if missing:
        flags.append({
            "level": "INFO",
            "code": "MISSING_META",
            "detail": f"{len(missing)} held symbols have no memo: " + ", ".join(missing[:12]),
        })
    if (has_orders or n_snap > 0) and not configured:
        flags.append({
            "level": "WARN",
            "code": "CONFIGURED_FALSE_WHILE_TRADING",
            "detail": f"{account_id} has {len(orders)} orders / {n_snap} positions but configured=false — "
                      "stale skipped-cycle flag or unset H3/H5 secrets. Live count is correct; flag is not.",
        })
    if dormant_days is not None and dormant_days >= 2:
        flags.append({
            "level": "WARN",
            "code": "DORMANT",
            "detail": f"No order in ~{dormant_days}d (last {str(last_order)[:10]}). "
                      "If unintended, confirm this account's Alpaca secrets are set in the repo.",
        })
    if not has_orders and n_snap == 0:
        flags.append({
            "level": "INFO",
            "code": "FLAT",
            "detail": "No orders and no positions — account is flat (all cash).",
        })

    return {
        "account_id": account_id,
        "configured": configured,
        "trading_capital": cap,
        "principal_target": principal,
        "drawdown_pct": drawdown_pct,
        "counts": {
            "meta": len(meta_syms),
            "snapshot": n_snap,
            "matched": len(matched),
            "phantom_in_meta": len(phantom),
            "missing_meta": len(missing),
            "orders": len(orders),
        },
        "phantom_in_meta": phantom,
        "missing_meta": missing,
        "last_order_at": last_order,
        "last_run": last_run,
        "dormant_days": dormant_days,
        "lifetime": {
            "wins": state.get("lifetime_realized_wins"),
            "losses": state.get("lifetime_realized_losses"),
        },
        "in_sync": (len(phantom) == 0 and len(missing) == 0),
        "flags": flags,
    }


def build_broker_reconciliation(out_dir: Path) -> Dict[str, Any]:
    out = Path(out_dir)
    ref = datetime.now(timezone.utc)

    accounts: List[Dict[str, Any]] = []
    for acct_id, fname in ACCOUNT_FILES:
        state = _load(out / fname, {})
        if not isinstance(state, dict) or not state:
            accounts.append({"account_id": acct_id, "error": f"{fname} unavailable", "flags": [
                {"level": "WARN", "code": "STATE_MISSING", "detail": f"{fname} not found or empty."}]})
            continue
        accounts.append(reconcile_account(acct_id, state, ref))

    total_phantom = sum(a.get("counts", {}).get("phantom_in_meta", 0) for a in accounts)
    in_sync = all(a.get("in_sync") for a in accounts if "counts" in a)
    live = [a["account_id"] for a in accounts
            if a.get("counts", {}).get("orders", 0) > 0 or a.get("counts", {}).get("snapshot", 0) > 0]

    recommended: List[Dict[str, str]] = []
    if total_phantom > 0:
        recommended.append({
            "track": "Track B (live path, gated)",
            "code": "PRUNE_META_TO_SNAPSHOT",
            "detail": "In alpaca_paper.py, after the post-trade positions refresh, prune position_meta "
                      "to only the symbols present in the fresh broker positions, so closed-elsewhere "
                      "names cannot persist as phantoms. One-line set-intersection; needs approval because "
                      "it writes account state.",
        })
    if any(a.get("counts", {}).get("orders", 0) > 0 and not a.get("configured", True) for a in accounts):
        recommended.append({
            "track": "Track B (orchestration, gated)",
            "code": "RECONCILE_CONFIGURED_FLAG",
            "detail": "In multi_account.py, write configured=true whenever an account successfully fetches "
                      "its Alpaca account object, independent of whether it traded this cycle, so a skipped "
                      "cycle cannot leave a trading account flagged configured=false.",
        })

    notes: List[str] = []
    notes.append(f"{len(live)}/3 accounts show trading activity: " + (", ".join(live) if live else "none") + ".")
    if in_sync:
        notes.append("All accounts: position_meta matches the broker snapshot. No phantoms.")
    else:
        notes.append(f"Out of sync: {total_phantom} phantom memo entries across accounts (see PRUNE_META_TO_SNAPSHOT). "
                     "Dashboards reading positions_snapshot are already correct; the memo dict is the stale layer.")
    dormant = [a["account_id"] for a in accounts if (a.get("dormant_days") or 0) >= 2]
    if dormant:
        notes.append("Dormant ≥2d (likely unset secrets): " + ", ".join(dormant) + ".")

    payload = {
        "version": RECON_VERSION,
        "generated_at": ref.isoformat(),
        "summary": {
            "accounts_live": len(live),
            "accounts_total": 3,
            "in_sync": in_sync,
            "total_phantom_meta": total_phantom,
        },
        "accounts": accounts,
        "recommended_fixes": recommended,
        "notes": notes,
    }
    _dump(out / "broker_reconciliation.json", payload)
    return {"accounts_live": len(live), "in_sync": in_sync, "total_phantom": total_phantom}


if __name__ == "__main__":  # pragma: no cover
    import sys
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    print(json.dumps(build_broker_reconciliation(base), indent=2))
