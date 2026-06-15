"""silmaril.portfolios.bills_leaderboard_v2 — Corrected per-account ranking.

Replaces (additively — does not delete v1) the bills_paid leaderboard,
sourcing truth from two reliable feeds instead of the legacy
`grocery_ledgers.json` rollup:

  1. `harvest_accounts.json`       — per-account equity, principal, label
  2. `verified_harvest_ledger.json` — per-account ANCHOR vs VERIFIED amounts

The legacy leaderboard combined all Alpaca accounts incorrectly and
double-counted anchor-only (unrealized) savings with realized SGOV
holdings. This v2 keeps them separate and reports:

  - `verified_savings` = sum of VERIFIED rows for that account
                         (real SGOV cash, not pretend)
  - `anchor_savings`   = current equity-above-principal snapshot
                         (unrealized; will become verified after sweep)
  - `bills_paid` is derived ONLY from `verified_savings` so the
                         dashboard's bills bars reflect protected gains,
                         not at-risk paper PnL.

Output: docs/data/bills_paid_leaderboard.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

WEEKLY_TARGET = 250.00
BILLS: List[Dict[str, Any]] = [
    {"name": "groceries", "cost": 50.00},
    {"name": "gas",       "cost": 40.00},
    {"name": "utilities", "cost": 75.00},
    {"name": "phone",     "cost": 35.00},
    {"name": "internet",  "cost": 50.00},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _week_start_iso() -> str:
    d = datetime.now(timezone.utc).date()
    return (d - timedelta(days=d.weekday())).isoformat()


def _bills_for(amount: float) -> List[Dict[str, Any]]:
    """Allocate `amount` to bills in order. Returns rich list w/ both
    legacy keys (status/cost/covered) and dashboard keys (paid_pct/amount/target).
    """
    remaining = max(0.0, float(amount))
    out: List[Dict[str, Any]] = []
    for b in BILLS:
        cost = b["cost"]
        covered = min(remaining, cost)
        remaining -= covered
        status = "PAID" if covered >= cost else ("PARTIAL" if covered > 0 else "UNPAID")
        out.append({
            "name":      b["name"],
            # legacy
            "status":    status,
            "cost":      cost,
            "covered":   round(covered, 2),
            # dashboard
            "target":    cost,
            "amount":    round(covered, 2),
            "paid_pct":  round((covered / cost) * 100.0, 1) if cost > 0 else 0.0,
        })
    return out


def _load_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def build_leaderboard_v2(data_dir: Path) -> Dict[str, Any]:
    harvest = _load_json(data_dir / "harvest_accounts.json")
    vh      = _load_json(data_dir / "verified_harvest_ledger.json")
    sweep   = _load_json(data_dir / "sweep_protection.json")

    by_account_vh = (vh or {}).get("by_account", {})
    accounts_block = (harvest or {}).get("accounts") or (harvest or {}).get("by_account") or {}

    rows: List[Dict[str, Any]] = []
    week_start = _week_start_iso()

    for aid, ainfo in accounts_block.items() if isinstance(accounts_block, dict) else []:
        if not isinstance(ainfo, dict):
            continue
        if not ainfo.get("enabled", ainfo.get("configured", True)):
            # Show as disabled with zeroed bills, so the operator still
            # sees the row and can audit which accounts are configured.
            verified = 0.0
            anchor = 0.0
        else:
            vh_acc = by_account_vh.get(aid, {})
            verified = float(vh_acc.get("verified", 0) or 0)
            anchor   = float(vh_acc.get("anchor", 0) or 0)

        equity     = float((ainfo.get("account") or {}).get("equity", ainfo.get("equity", 0)) or 0)
        principal  = float(ainfo.get("principal_target", 10_000) or 0)
        label      = ainfo.get("label") or aid

        weekly_harvest = verified  # source of truth for "bills paid"
        bills          = _bills_for(weekly_harvest)
        progress_pct   = min(100.0, round((weekly_harvest / WEEKLY_TARGET) * 100, 1)) if WEEKLY_TARGET else 0.0

        # Pull most recent sweep_protection signals for visibility
        spblock = ((sweep or {}).get("accounts") or {}).get(aid) or {}
        instant_count = len([r for r in spblock.get("instant_sweeps", []) if r.get("ok")])
        stale_count   = len([r for r in spblock.get("stale_closes", [])   if r.get("ok")])
        force_block   = spblock.get("force_sweep")  or {}
        evening_block = spblock.get("evening_shield") or {}

        rows.append({
            "rank": 0,
            "harvester": aid,
            "label": label,
            "principal": principal,
            "equity": round(equity, 2),
            "verified_savings": round(verified, 2),
            "anchor_savings":   round(anchor, 2),
            # legacy field names so the old dashboard chart still finds them
            "weekly_harvested": round(weekly_harvest, 2),
            "weekly_target":    WEEKLY_TARGET,
            "lifetime_harvested": round(verified, 2),
            "efficiency": round(verified / principal, 6) if principal > 0 else 0.0,
            "best_week": 0.0,
            "progress_pct": progress_pct,
            "bills_status": {b["name"]: b["status"] for b in bills},
            "bills_paid": {b["name"]: b for b in bills},  # NEW richer shape
            "bills": bills,                               # ordered list
            "surplus":   round(max(0, weekly_harvest - WEEKLY_TARGET), 2),
            "shortfall": round(max(0, WEEKLY_TARGET - weekly_harvest), 2),
            "fed_family": progress_pct >= 100.0,
            "protection": {
                "instant_sweeps_this_cycle": instant_count,
                "stale_closes_this_cycle":   stale_count,
                "force_sweep_triggered":     bool(force_block.get("triggered")),
                "evening_shield_triggered":  bool(evening_block.get("triggered")),
            },
            "week_start": week_start,
        })

    # Sort by verified savings desc (the only number that counts)
    rows.sort(key=lambda r: r["verified_savings"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    result = {
        "version": "3.1",
        "generated_at": _now_iso(),
        "weekly_target": WEEKLY_TARGET,
        "total_verified": round(sum(r["verified_savings"] for r in rows), 2),
        "total_anchor":   round(sum(r["anchor_savings"]   for r in rows), 2),
        "combined_progress": round(
            min(100.0, sum(r["weekly_harvested"] for r in rows) / WEEKLY_TARGET * 100), 1
        ) if WEEKLY_TARGET else 0.0,
        "families_fed": sum(1 for r in rows if r["fed_family"]),
        "leaderboard": rows,
        "note": ("v2: per-account, verified (SGOV) savings only. Anchor "
                 "(unrealized equity-above-principal) is reported but NOT "
                 "counted in bills-paid. Bills bars never lie."),
    }
    try:
        (data_dir / "bills_paid_leaderboard.json").write_text(
            json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(f"[bills_v2] write failed: {e}")
    return result


__all__ = ["build_leaderboard_v2", "WEEKLY_TARGET", "BILLS"]
