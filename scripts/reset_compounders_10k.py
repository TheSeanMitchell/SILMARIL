"""
scripts/reset_compounders_10k.py — Raise all compounders to $10,000 starting capital.

Run once manually or via GitHub Actions (workflow_dispatch).
Preserves history, deaths, current_life, and last_action_date.
Closes all open positions (fresh start at $10K).

Why $10K: the $250/week grocery target requires ~2.5% weekly returns.
At $10 starting capital, $250/week = 2500% returns — impossible.
At $10K, 2.5%/week is aggressive but achievable with momentum trading.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DATA = Path("docs/data")
TARGET_BALANCE = 10_000.00
REINCARNATION_THRESHOLD = 5_000.00

COMPOUNDER_PATHS = {
    "SCROOGE":    DATA / "scrooge.json",
    "MIDAS":      DATA / "midas.json",
    "CRYPTOBRO":  DATA / "cryptobro.json",
    "JRR_TOKEN":  DATA / "jrr_token.json",
    "SPORTS_BRO": DATA / "sports_bro.json",
}

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def reset_compounder(path: Path, codename: str) -> None:
    if not path.exists():
        print(f"[reset] {codename}: file not found — skipping")
        return

    with path.open() as f:
        data = json.load(f)

    old_balance = data.get("balance", 0)

    # Reset balance and close positions
    data["balance"]          = TARGET_BALANCE
    data["lifetime_peak"]    = max(float(data.get("lifetime_peak", 0)), TARGET_BALANCE)
    data["current_position"] = None
    data["last_action_date"] = ""   # allow trading on next run

    # For JRR Token's two-tier structure
    if "tiers" in data:
        tier_balance = TARGET_BALANCE / 2.0
        for tier_key in ("sub_100m", "over_100m"):
            if tier_key in data["tiers"]:
                data["tiers"][tier_key]["balance"]          = tier_balance
                data["tiers"][tier_key]["current_position"] = None

    # Log the reset in history
    history = data.get("history", [])
    history.append({
        "date":        _today(),
        "timestamp":   _now(),
        "action":      "CAPITAL_RESET",
        "old_balance": round(old_balance, 4),
        "new_balance": TARGET_BALANCE,
        "reason":      "Compounder capital raised to $10K for grocery harvest system",
    })
    data["history"] = history

    path.write_text(json.dumps(data, indent=2, default=str))
    print(f"[reset] {codename}: ${old_balance:,.4f} → ${TARGET_BALANCE:,.2f}")


def reset_agent_portfolios() -> None:
    """Ensure all agent portfolio principals are set to $10K."""
    path = DATA / "agent_portfolios.json"
    if not path.exists():
        print("[reset] agent_portfolios.json not found — skipping")
        return

    with path.open() as f:
        raw = json.load(f)

    count = 0
    for key, val in raw.items():
        if key.startswith("_") or not isinstance(val, dict):
            continue
        val["starting_equity"] = 10_000.00
        val["principal_target"] = 10_000.00
        if val.get("cash", 0) < 10_000.00:
            val["cash"]          = 10_000.00
            val["current_equity"] = 10_000.00
            val["current_position"] = None
        count += 1

    raw["_summary"] = {
        **raw.get("_summary", {}),
        "principal_target": 10_000.00,
        "reset_at": _now(),
        "note": "All agents raised to $10K principal for grocery harvest system",
    }
    path.write_text(json.dumps(raw, indent=2, default=str))
    print(f"[reset] agent_portfolios: {count} agents set to $10K principal")


if __name__ == "__main__":
    print("Raising all compounders to $10,000...")
    for codename, path in COMPOUNDER_PATHS.items():
        reset_compounder(path, codename)
    reset_agent_portfolios()
    print("\nDone. Run daily workflow to begin at $10K.")
