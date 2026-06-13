"""
scripts/reset_alpaca_grocery_to_truth.py

One-shot ledger reset. Anchors the ALPACA grocery harvest ledger to
ground truth from alpaca_paper_state.json:

    lifetime_harvested = max(0, account.equity - principal_target)

Run this once after deploying the trading-book cap fix. It clears the
inflated counter (prior bookkeeping-only "harvests") and replaces it
with the real spendable savings the user can actually see in their
Alpaca account.

Per-agent ledgers (AEGIS, FORGE, etc.) are NOT touched — those reflect
genuine $10K-portfolio mark-to-market harvests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from silmaril.portfolios.grocery import (
    load_ledger, save_ledger, build_leaderboard,
)

DATA = Path("docs/data")
ALPACA_STATE_PATH = DATA / "alpaca_paper_state.json"


def main() -> int:
    if not ALPACA_STATE_PATH.exists():
        print(f"[reset] {ALPACA_STATE_PATH} missing — nothing to anchor against")
        return 1

    state = json.loads(ALPACA_STATE_PATH.read_text())
    account = state.get("account") or {}
    equity = float(account.get("equity") or 0)
    principal = float(state.get("principal_target") or 10_000.0)
    truth = max(0.0, equity - principal)

    print(f"[reset] Alpaca equity:    ${equity:,.2f}")
    print(f"[reset] Principal target: ${principal:,.2f}")
    print(f"[reset] Real savings:     ${truth:,.2f}")

    ledger = load_ledger(DATA, "ALPACA", 10_000.0)
    old_lifetime = ledger.lifetime_harvested
    print(f"[reset] Old lifetime in ledger: ${old_lifetime:,.2f}")

    if abs(old_lifetime - truth) < 0.01:
        print("[reset] Already truthful — no-op")
        return 0

    # Reset weekly to 0 and lifetime to truth. We zero weekly because the
    # inflated weekly value also includes ghost harvests; from this point
    # forward the new code will accumulate weekly correctly.
    ledger.lifetime_harvested = round(truth, 4)
    ledger.weekly_harvested = 0.0
    ledger.harvest_history.append({
        "date":           ledger.week_start,
        "timestamp":      "",
        "amount":         round(truth - old_lifetime, 4),
        "reason":         (f"RESET TO TRUTH: was ${old_lifetime:.2f} (inflated bookkeeping), "
                           f"now ${truth:.2f} (real Alpaca equity − principal)"),
        "ticker":         "",
        "weekly_total":   0.0,
        "lifetime_total": round(truth, 4),
        "kind":           "reset_to_truth",
    })
    save_ledger(DATA, ledger)
    print(f"[reset] Ledger anchored at ${truth:,.2f}")

    leaderboard = build_leaderboard(DATA)
    out_path = DATA / "grocery_leaderboard.json"
    out_path.write_text(json.dumps(leaderboard, indent=2, default=str))
    print(f"[reset] Rebuilt {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
