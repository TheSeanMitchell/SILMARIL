"""
scripts/heal_starting_balance.py — Backfill the `starting_balance` field
into every compounder + agent_portfolio state file WITHOUT resetting
current balances or history.

This is the gentle migration counterpart to reset_compounders_10k.py.
Use this when:
  - Migration has already happened, balances are correct ($10K)
  - But the dashboard leaderboard still shows wild +99,900% returns
    because the JSON files don't have a `starting_balance` field for
    the new HTML to read.

Run once via Actions → workflow_dispatch on heal_starting_balance.yml,
or locally:
    python scripts/heal_starting_balance.py
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path("docs/data")
TARGET = 10_000.00

COMPOUNDERS = [
    "scrooge.json",
    "midas.json",
    "cryptobro.json",
    "jrr_token.json",
    "sports_bro.json",
]


def heal_compounder(name: str) -> None:
    path = DATA / name
    if not path.exists():
        print(f"[heal] {name}: not found — skipping")
        return
    data = json.loads(path.read_text())
    changed = False

    if "starting_balance" not in data:
        data["starting_balance"] = TARGET
        changed = True
    if "principal_target" not in data:
        data["principal_target"] = TARGET
        changed = True

    # If the most recent CAPITAL_RESET entry is newer than life_start_date,
    # anchor life_start_date to the reset. This fixes the "LIFE #1 · 3d"
    # artifact where the day counter kept counting from the original life
    # start even though the compounder was reset to $10K mid-life.
    history = data.get("history", []) or []
    last_reset = None
    for h in reversed(history):
        if h.get("action") in ("CAPITAL_RESET", "RESET"):
            last_reset = h.get("date") or h.get("timestamp", "")[:10]
            break
    if last_reset:
        cur_start = data.get("life_start_date", "")
        if cur_start and cur_start < last_reset:
            data["life_start_date"] = last_reset
            data["days_alive"] = 0
            changed = True
            print(f"[heal] {name}: life_start_date {cur_start} → {last_reset} (anchored to last reset)")

    # JRR Token two-tier
    if "tiers" in data:
        for k, t in data["tiers"].items():
            if isinstance(t, dict) and "starting_balance" not in t:
                t["starting_balance"] = TARGET / 2.0
                changed = True

    if changed:
        path.write_text(json.dumps(data, indent=2, default=str))
        print(f"[heal] {name}: starting_balance set to ${TARGET:,.2f}")
    else:
        print(f"[heal] {name}: already healed")


def heal_agent_portfolios() -> None:
    path = DATA / "agent_portfolios.json"
    if not path.exists():
        print("[heal] agent_portfolios.json: not found — skipping")
        return
    raw = json.loads(path.read_text())
    count = 0
    for k, v in raw.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        # Already a $10K agent_portfolio — just make sure starting_equity
        # is set so the leaderboard can compute return correctly.
        if "starting_equity" not in v or v.get("starting_equity") in (0, None):
            v["starting_equity"] = TARGET
            count += 1
    if count:
        path.write_text(json.dumps(raw, indent=2, default=str))
        print(f"[heal] agent_portfolios.json: backfilled starting_equity on {count} agents")
    else:
        print("[heal] agent_portfolios.json: already healed")


if __name__ == "__main__":
    print("Healing starting_balance field across all compounders...")
    for name in COMPOUNDERS:
        heal_compounder(name)
    heal_agent_portfolios()
    print("Done. Dashboard leaderboard will now show correct % return on next reload.")
