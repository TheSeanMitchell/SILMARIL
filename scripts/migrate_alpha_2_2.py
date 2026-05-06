"""
scripts/migrate_alpha_2_2.py — One-shot Alpha 2.2 migration.

What this does:
  1. Archives the current agent_beliefs.json, creating a .bak before touching it
  2. Resets the 8 corrupted agents' Beta posteriors to clean Beta(1,1) prior
  3. Equalizes all main-voter agent portfolios to $10K starting capital
     (resets cash to $10K, clears open positions, preserves history and XP)
  4. Equalizes the 5 compounders (Scrooge, Midas, CryptoBro, JRR Token, Sports Bro)
     to $10 starting balance — resetting current_position, preserving history
  5. Writes a migration report to docs/data/migration_alpha_2_2.json

Run once, on demand, via migrate_alpha_2_2.yml workflow.
After running: re-enable Daily Run and Weekly Backup.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

# ─── paths ───────────────────────────────────────────────────────
DATA = Path("docs/data")
BELIEFS_PATH = DATA / "agent_beliefs.json"
PORTFOLIOS_PATH = DATA / "agent_portfolios.json"
SCROOGE_PATH = DATA / "scrooge.json"
MIDAS_PATH = DATA / "midas.json"
CRYPTOBRO_PATH = DATA / "cryptobro.json"
JRR_PATH = DATA / "jrr_token.json"
SPORTS_PATH = DATA / "sports_bro.json"
REPORT_PATH = DATA / "migration_alpha_2_2.json"

# ─── constants ───────────────────────────────────────────────────
CORRUPTED_AGENTS = {
    "CICADA", "SHEPHERD", "BARON", "SYNTH",
    "ZENITH", "VEIL", "TALON", "HEX",
}
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0
AGENT_TARGET_CASH = 10_000.0
COMPOUNDER_TARGET_BALANCE = 10.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"[migrate] WARNING: could not read {path}: {e}")
        return {}


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _backup(path: Path) -> str:
    if not path.exists():
        return "file did not exist — no backup needed"
    bak = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, bak)
    return str(bak)


# ─────────────────────────────────────────────────────────────────
# Step 1: Reset corrupted Bayesian posteriors
# ─────────────────────────────────────────────────────────────────

def reset_corrupted_beliefs() -> Dict:
    report = {"step": "reset_beliefs", "reset": [], "kept": [], "errors": []}
    bak = _backup(BELIEFS_PATH)
    report["backup"] = bak

    beliefs = _load_json(BELIEFS_PATH)
    if not beliefs:
        report["note"] = "agent_beliefs.json not found or empty — created fresh"
        _save_json(BELIEFS_PATH, {})
        return report

    for agent in list(beliefs.keys()):
        if agent in CORRUPTED_AGENTS:
            # Wipe all regime posteriors to clean Beta(1,1)
            cleaned_regimes = {}
            for regime in beliefs[agent].keys():
                cleaned_regimes[regime] = {
                    "alpha": PRIOR_ALPHA,
                    "beta": PRIOR_BETA,
                    "n": 0,
                }
            beliefs[agent] = cleaned_regimes
            report["reset"].append(agent)
        else:
            report["kept"].append(agent)

    _save_json(BELIEFS_PATH, beliefs)
    print(f"[migrate] Reset posteriors for: {sorted(report['reset'])}")
    print(f"[migrate] Preserved posteriors for: {sorted(report['kept'])}")
    return report


# ─────────────────────────────────────────────────────────────────
# Step 2: Equalize main-voter agent portfolios to $10K
# ─────────────────────────────────────────────────────────────────

def equalize_agent_portfolios() -> Dict:
    report = {"step": "equalize_portfolios", "equalized": [], "errors": []}
    bak = _backup(PORTFOLIOS_PATH)
    report["backup"] = bak

    raw = _load_json(PORTFOLIOS_PATH)
    if not raw:
        report["note"] = "agent_portfolios.json not found — skipping"
        return report

    # The file has a _summary key and per-agent keys
    updated = {}
    for key, val in raw.items():
        if key.startswith("_"):
            updated[key] = val
            continue
        if not isinstance(val, dict):
            updated[key] = val
            continue

        old_cash = val.get("cash", AGENT_TARGET_CASH)
        old_equity = val.get("current_equity", AGENT_TARGET_CASH)

        # Reset cash to $10K, close any open position, preserve history + savings
        val["cash"] = AGENT_TARGET_CASH
        val["current_equity"] = AGENT_TARGET_CASH
        val["starting_equity"] = AGENT_TARGET_CASH
        val["current_position"] = None  # Force close — fresh start
        # Preserve history, equity_curve, savings, inception_date
        # Add a MIGRATION entry to history
        history = val.get("history", [])
        history.append({
            "date": datetime.now(timezone.utc).date().isoformat(),
            "timestamp": _now(),
            "action": "MIGRATION",
            "reason": "Alpha 2.2 equalization — reset to $10K principal",
            "old_cash": round(old_cash, 2),
            "old_equity": round(old_equity, 2),
            "new_cash": AGENT_TARGET_CASH,
        })
        val["history"] = history
        # Reset savings separately — agents keep earnings from before migration
        # (savings are already realized gains, so we don't reset those)
        updated[key] = val
        report["equalized"].append(key)

    # Rewrite summary
    agent_count = sum(1 for k in updated if not k.startswith("_"))
    updated["_summary"] = {
        "total_savings_all_agents": 0.0,
        "total_lifetime_value": round(agent_count * AGENT_TARGET_CASH, 2),
        "agent_count": agent_count,
        "generated_at": _now(),
        "migration_note": "Alpha 2.2 equalization applied",
    }

    _save_json(PORTFOLIOS_PATH, updated)
    print(f"[migrate] Equalized {len(report['equalized'])} agent portfolios to $10K")
    return report


# ─────────────────────────────────────────────────────────────────
# Step 3: Equalize compounders to $10 starting balance
# ─────────────────────────────────────────────────────────────────

def _reset_compounder_balance(path: Path, codename: str, target: float) -> Dict:
    result = {"codename": codename, "path": str(path)}
    bak = _backup(path)
    result["backup"] = bak

    state = _load_json(path)
    if not state:
        result["note"] = "state file not found — skipping"
        return result

    old_balance = state.get("balance", target)
    result["old_balance"] = old_balance

    state["balance"] = target
    state["lifetime_peak"] = target
    state["current_position"] = None  # Close open positions

    # Preserve history, deaths, current_life
    history = state.get("history", [])
    history.append({
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": _now(),
        "action": "MIGRATION",
        "reason": f"Alpha 2.2 equalization — reset to ${target}",
        "old_balance": round(old_balance, 4),
        "new_balance": target,
    })
    state["history"] = history

    _save_json(path, state)
    result["new_balance"] = target
    print(f"[migrate] {codename}: ${old_balance:.4f} → ${target:.2f}")
    return result


def _reset_jrr_token(path: Path) -> Dict:
    """JRR Token has a two-tier structure — needs special handling."""
    result = {"codename": "JRR_TOKEN", "path": str(path)}
    bak = _backup(path)
    result["backup"] = bak

    state = _load_json(path)
    if not state:
        result["note"] = "jrr_token.json not found — skipping"
        return result

    old_balance = state.get("balance", COMPOUNDER_TARGET_BALANCE)
    result["old_balance"] = old_balance

    state["balance"] = COMPOUNDER_TARGET_BALANCE
    state["lifetime_peak"] = COMPOUNDER_TARGET_BALANCE
    state["current_position"] = None

    # Reset both tiers
    tier_balance = COMPOUNDER_TARGET_BALANCE / 2.0
    tiers = state.get("tiers", {})
    for tier_key in ("sub_100m", "over_100m"):
        if tier_key in tiers:
            tiers[tier_key]["balance"] = tier_balance
            tiers[tier_key]["current_position"] = None
    state["tiers"] = tiers

    history = state.get("history", [])
    history.append({
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": _now(),
        "action": "MIGRATION",
        "reason": "Alpha 2.2 equalization — reset to $10",
        "old_balance": round(old_balance, 4),
        "new_balance": COMPOUNDER_TARGET_BALANCE,
    })
    state["history"] = history

    _save_json(path, state)
    result["new_balance"] = COMPOUNDER_TARGET_BALANCE
    print(f"[migrate] JRR_TOKEN: ${old_balance:.4f} → ${COMPOUNDER_TARGET_BALANCE:.2f} (tiers equalized)")
    return result


def equalize_compounders() -> Dict:
    report = {"step": "equalize_compounders", "results": []}

    compounders = [
        (SCROOGE_PATH, "SCROOGE"),
        (MIDAS_PATH, "MIDAS"),
        (CRYPTOBRO_PATH, "CRYPTOBRO"),
        (SPORTS_PATH, "SPORTS_BRO"),
    ]
    for path, codename in compounders:
        r = _reset_compounder_balance(path, codename, COMPOUNDER_TARGET_BALANCE)
        report["results"].append(r)

    # JRR Token special case
    report["results"].append(_reset_jrr_token(JRR_PATH))
    return report


# ─────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────

def run_migration() -> Dict:
    print("[migrate] ═══════════════════════════════════════════════")
    print("[migrate] SILMARIL Alpha 2.2 Migration — starting")
    print(f"[migrate] UTC: {_now()}")
    print("[migrate] ═══════════════════════════════════════════════")

    report = {
        "version": "alpha_2_2",
        "ran_at": _now(),
        "steps": {},
    }

    # Step 1: beliefs
    print("\n[migrate] Step 1: Resetting corrupted Bayesian posteriors...")
    report["steps"]["beliefs"] = reset_corrupted_beliefs()

    # Step 2: agent portfolios
    print("\n[migrate] Step 2: Equalizing agent portfolios to $10K...")
    report["steps"]["portfolios"] = equalize_agent_portfolios()

    # Step 3: compounders
    print("\n[migrate] Step 3: Equalizing compounders to $10...")
    report["steps"]["compounders"] = equalize_compounders()

    # Write report
    _save_json(REPORT_PATH, report)
    print(f"\n[migrate] Report written to {REPORT_PATH}")
    print("[migrate] ═══════════════════════════════════════════════")
    print("[migrate] Migration complete. You may now enable Daily Run.")
    print("[migrate] ═══════════════════════════════════════════════")
    return report


if __name__ == "__main__":
    import sys
    report = run_migration()
    print(json.dumps(report, indent=2, default=str))
    sys.exit(0)
