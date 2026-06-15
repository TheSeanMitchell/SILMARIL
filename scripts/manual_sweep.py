#!/usr/bin/env python3
"""scripts/manual_sweep.py — Manually trigger the SWEEP switch.

Use this when you decide a strong market day has reached its peak and you
want every Alpaca account to immediately:

  1. Liquidate every non-vault holding at market.
  2. Park cash above $10,000 into SGOV.

Two ways to invoke:
  - Direct CLI:  python scripts/manual_sweep.py [--floor 10000]
  - Indirect:    create a `docs/data/sweep_switch.flag` file with any text;
                 the next normal Silmaril cron run will pick it up and
                 consume (delete) it after sweeping.

The direct path runs sweep_protection.apply_post_cycle_protections against
each configured Alpaca account using its env-var keys. The indirect path
just creates the flag file and exits — useful from a GitHub workflow_dispatch
job that doesn't have Alpaca secrets in its env.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger Silmaril SWEEP switch.")
    parser.add_argument("--data-dir", default="docs/data",
                        help="Path to docs/data (where state JSON lives)")
    parser.add_argument("--flag-only", action="store_true",
                        help="Only drop the sweep_switch.flag file; don't sweep here")
    parser.add_argument("--floor", type=float, default=10_000.0,
                        help="Cash floor to retain per account (default 10000)")
    parser.add_argument("--reason", default="manual_sweep CLI",
                        help="Reason recorded in the sweep summary")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    if args.flag_only:
        flag = data_dir / "sweep_switch.flag"
        flag.write_text(f"{_now_iso()} :: {args.reason}\n")
        print(f"[manual_sweep] flag dropped at {flag}")
        return 0

    # Direct sweep path: load multi-account state, then run sweep_protection.
    try:
        from silmaril.execution.multi_account import HARVEST_ACCOUNTS
        from silmaril.portfolios.sweep_protection import apply_post_cycle_protections
    except ImportError as e:
        print(f"[manual_sweep] import failed: {e}", file=sys.stderr)
        return 2

    # Build a minimal "results" dict from on-disk state files so
    # apply_post_cycle_protections has something to walk.
    results = {}
    for cfg in HARVEST_ACCOUNTS:
        p = data_dir / cfg.state_filename
        if not p.exists():
            continue
        try:
            results[cfg.account_id] = json.loads(p.read_text())
        except Exception:
            pass
        # Make sure 'enabled' is preserved so the orchestrator processes it
        if cfg.account_id in results and not isinstance(results[cfg.account_id], dict):
            results.pop(cfg.account_id, None)

    # Force the switch ON for this invocation
    os.environ["SILMARIL_SWEEP_SWITCH"] = "1"
    summary = apply_post_cycle_protections(data_dir, results, plans=[])
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
