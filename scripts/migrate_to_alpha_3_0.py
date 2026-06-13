#!/usr/bin/env python3
"""scripts/migrate_to_alpha_3_0.py — Idempotent, additive migration.

What this does
──────────────
1. Seeds empty state files for HARVEST_3 and HARVEST_5 if missing.
2. Initializes docs/data/agent_staleness_params.json with defaults
   for every existing agent + the three account owners.
3. Initializes docs/data/verified_harvest_ledger.json (empty rows).
4. Initializes docs/data/harvest_accounts.json with a baseline rollup
   so the dashboard renders cleanly on the very first cycle after
   deploy, before any new Alpaca call has run.

What this does NOT do
─────────────────────
* Touch alpaca_paper_state.json (LEGACY data preserved).
* Touch grocery_ledgers.json (Bills Paid history preserved).
* Touch any agent portfolio, scoring, history, or compounder file.
* Delete anything. Anywhere. Ever.

Safe to re-run any number of times — it skips files that already exist
(except harvest_accounts.json which always gets rewritten on each
silmaril run anyway).

Usage
─────
  python scripts/migrate_to_alpha_3_0.py
  python scripts/migrate_to_alpha_3_0.py --dry-run    # just print what it would do
  python scripts/migrate_to_alpha_3_0.py --data-dir docs/data
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "docs" / "data"

# Agents we know exist in the system; add any new ones here as you create them.
KNOWN_AGENT_OWNERS = [
    # Voting agents
    "AEGIS", "FORGE", "THUNDERHEAD", "JADE", "VEIL", "KESTREL", "OBSIDIAN",
    "ZENITH", "WEAVER", "HEX", "SYNTH", "SPECK", "VESPA", "MAGUS", "TALON",
    "ATLAS", "NIGHTSHADE", "CICADA", "SHEPHERD", "NOMAD", "BARNACLE",
    "KESTREL+", "CONTRARIAN", "SHORT_ALPHA",
    # Specialists with $10K books
    "BARON", "STEADFAST",
    # Account owners
    "LEGACY", "HARVEST_3", "HARVEST_5",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_alpaca_state(data_dir: Path, filename: str, account_id: str,
                     principal: float, label: str, min_harvest: float,
                     dry: bool) -> bool:
    """Create a minimal stub state file if it doesn't exist."""
    p = data_dir / filename
    if p.exists():
        print(f"  · {filename}: already exists, leaving untouched")
        return False
    stub = {
        "version": "3.0",
        "enabled": False,
        "configured": False,
        "account_id": account_id,
        "label": label,
        "account": {},
        "principal_target": principal,
        "min_harvest_gain_pct": min_harvest,
        "savings": 0.0,
        "realized_savings": 0.0,
        "trading_capital": principal,
        "lifetime_realized_wins": 0,
        "lifetime_realized_losses": 0,
        "position_meta": {},
        "tickers_traded_this_cycle": [],
        "recent_alpaca_tickers": [],
        "orders": [],
        "orders_placed": [],
        "errors": [],
        "savings_vault": {
            "holdings": [], "total_market_value": 0.0,
            "primary_symbol": None, "primary_qty": 0.0,
            "primary_market_value": 0.0,
        },
        "reason": "Awaiting first run — populated by silmaril/execution/multi_account.py",
        "seeded_at": _now_iso(),
    }
    if dry:
        print(f"  · would create {filename}")
        return True
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(stub, indent=2, default=str))
    print(f"  ✓ created {filename}")
    return True


def seed_staleness_params(data_dir: Path, dry: bool) -> bool:
    p = data_dir / "agent_staleness_params.json"
    if p.exists():
        print(f"  · agent_staleness_params.json: already exists, leaving untouched")
        return False
    payload = {
        "params": {owner: 0.5 for owner in KNOWN_AGENT_OWNERS},
        "default": 0.5,
        "updated_at": _now_iso(),
        "note": ("Staleness aggression in [0,1]. 0=most patient, 1=twitchiest. "
                 "Senate breeder mutates this per generation."),
        "seeded_at": _now_iso(),
    }
    if dry:
        print(f"  · would create agent_staleness_params.json (defaults for "
              f"{len(KNOWN_AGENT_OWNERS)} owners)")
        return True
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2))
    print(f"  ✓ created agent_staleness_params.json")
    return True


def seed_verified_harvest_ledger(data_dir: Path, dry: bool) -> bool:
    p = data_dir / "verified_harvest_ledger.json"
    if p.exists():
        print(f"  · verified_harvest_ledger.json: already exists, leaving untouched")
        return False
    payload = {
        "version": "3.0",
        "generated_at": _now_iso(),
        "rows": [],
        "by_account": {},
        "seeded_at": _now_iso(),
    }
    if dry:
        print(f"  · would create verified_harvest_ledger.json (empty)")
        return True
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2))
    print(f"  ✓ created verified_harvest_ledger.json")
    return True


def seed_harvest_accounts_baseline(data_dir: Path, dry: bool) -> bool:
    """The dashboard needs *something* here on first load. Real runs rewrite it."""
    p = data_dir / "harvest_accounts.json"
    if p.exists():
        print(f"  · harvest_accounts.json: already exists, leaving untouched")
        return False
    baseline = {
        "version": "3.0",
        "generated_at": _now_iso(),
        "accounts": [
            {"account_id": "LEGACY", "label": "1.5% Trench-Warfare Harvester (legacy)",
             "configured": True, "enabled": False, "principal_target": 10000.0,
             "min_harvest_gain_pct": 0.015, "equity": 0, "cash": 0,
             "unrealized_above_baseline": 0, "verified_harvested": 0,
             "verified_ledger_total": 0,
             "live_vault": {"market_value": 0, "primary_symbol": None,
                            "primary_qty": 0, "holdings": [], "reconciled": True,
                            "delta": 0, "mode": "anchor_only"},
             "open_positions": 0, "oldest_position_age_days": None,
             "last_cycle": {"opened": 0, "closed": 0, "open_after": 0, "tickers": []},
             "lifetime_wins": 0, "lifetime_losses": 0,
             "time_basis": {"real_days": 0, "market_days": 0, "crypto_hours": 0,
                            "genesis_iso": ""},
             "reason": "awaiting first cycle", "errors": []},
            {"account_id": "HARVEST_3", "label": "3% Disciplined Harvester",
             "configured": False, "enabled": False, "principal_target": 10000.0,
             "min_harvest_gain_pct": 0.03, "equity": 0, "cash": 0,
             "unrealized_above_baseline": 0, "verified_harvested": 0,
             "verified_ledger_total": 0,
             "live_vault": {"market_value": 0, "primary_symbol": None,
                            "primary_qty": 0, "holdings": [], "reconciled": True,
                            "delta": 0, "mode": "anchor_only"},
             "open_positions": 0, "oldest_position_age_days": None,
             "last_cycle": {"opened": 0, "closed": 0, "open_after": 0, "tickers": []},
             "lifetime_wins": 0, "lifetime_losses": 0,
             "time_basis": {"real_days": 0, "market_days": 0, "crypto_hours": 0,
                            "genesis_iso": ""},
             "reason": "awaiting first cycle (will fail with auth error if "
                       "ALPACA_API_KEY_H3/_SECRET_H3 set; skip silently if unset)",
             "errors": []},
            {"account_id": "HARVEST_5", "label": "5% Conviction Harvester",
             "configured": False, "enabled": False, "principal_target": 10000.0,
             "min_harvest_gain_pct": 0.05, "equity": 0, "cash": 0,
             "unrealized_above_baseline": 0, "verified_harvested": 0,
             "verified_ledger_total": 0,
             "live_vault": {"market_value": 0, "primary_symbol": None,
                            "primary_qty": 0, "holdings": [], "reconciled": True,
                            "delta": 0, "mode": "anchor_only"},
             "open_positions": 0, "oldest_position_age_days": None,
             "last_cycle": {"opened": 0, "closed": 0, "open_after": 0, "tickers": []},
             "lifetime_wins": 0, "lifetime_losses": 0,
             "time_basis": {"real_days": 0, "market_days": 0, "crypto_hours": 0,
                            "genesis_iso": ""},
             "reason": "awaiting first cycle (similar to HARVEST_3)",
             "errors": []},
        ],
        "totals": {
            "equity_all": 0, "verified_all": 0, "unrealized_all": 0,
            "live_vault_all": 0, "configured_accounts": 1,
            "enabled_accounts": 0, "total_accounts": 3,
        },
        "seeded_at": _now_iso(),
    }
    if dry:
        print(f"  · would create harvest_accounts.json (baseline)")
        return True
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(baseline, indent=2, default=str))
    print(f"  ✓ created harvest_accounts.json (baseline)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help="Path to docs/data directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without writing")
    args = parser.parse_args()

    data_dir = args.data_dir
    print(f"Alpha 3.0 migration → {data_dir}{' (DRY RUN)' if args.dry_run else ''}")
    print("-" * 64)

    changed = 0
    if seed_alpaca_state(data_dir, "alpaca_h3_state.json", "HARVEST_3",
                         10_000.0, "3% Disciplined Harvester", 0.03,
                         args.dry_run):
        changed += 1
    if seed_alpaca_state(data_dir, "alpaca_h5_state.json", "HARVEST_5",
                         10_000.0, "5% Conviction Harvester", 0.05,
                         args.dry_run):
        changed += 1
    if seed_staleness_params(data_dir, args.dry_run):
        changed += 1
    if seed_verified_harvest_ledger(data_dir, args.dry_run):
        changed += 1
    if seed_harvest_accounts_baseline(data_dir, args.dry_run):
        changed += 1

    print("-" * 64)
    if changed == 0:
        print("✓ All Alpha 3.0 state files already in place. Nothing to do.")
    else:
        action = "Would create" if args.dry_run else "Created"
        print(f"✓ {action} {changed} new file(s). No existing data touched.")
    print()
    print("Existing data preserved:")
    print("  · alpaca_paper_state.json    (LEGACY account, untouched)")
    print("  · grocery_ledgers.json       (Bills Paid history, untouched)")
    print("  · agent_portfolios.json      (per-agent $10K books, untouched)")
    print("  · scoring.json, history.json, agent_beliefs.json (all untouched)")
    print()
    print("Next steps:")
    print("  1. Add GitHub secrets: ALPACA_API_KEY_H3, ALPACA_API_SECRET_H3,")
    print("     ALPACA_API_KEY_H5, ALPACA_API_SECRET_H5  (you already have these ✓)")
    print("  2. Trigger the next `Daily Run` workflow (or wait for cron).")
    print("  3. Open the HARVEST · ACCOUNTS tab — three account cards will appear.")
    print("  4. LEGACY shows live data immediately; H3/H5 light up on first")
    print("     successful Alpaca call against their secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
