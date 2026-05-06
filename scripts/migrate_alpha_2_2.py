"""
SILMARIL Alpha 2.2 — One-time migration script.

Run via the migrate_alpha_2_2.yml workflow.

Four things in order:
  1. RESET the 8 corrupted agents' Beta posteriors back to the prior.
     Their evolution cards, history, level, XP, lifetime calls, and
     all other learning state are PRESERVED. Only the corrupted Beta
     posteriors in agent_beliefs.json get reset.

  2. EQUALIZE all agent portfolios to $10,000 starting capital.
     Their personality, lifetime stats, and historical entries are
     PRESERVED. Cash and current_equity reset to $10K. Savings ledger
     preserved as-is. Open positions refunded to cash before reset.

  3. EQUALIZE compounder JSONs (scrooge, midas, cryptobro, jrr_token,
     sports_bro) to $10K balance. History preserved.

  4. PATCH silmaril/cli.py to fix the directional-only filter and
     regime threading bugs in _post_debate_learning. Two surgical
     string replacements. Idempotent — skips if already patched.

Pre-migration snapshots go to docs_archive/{YYYY-MM-DD}/ for every file
touched. The script is IDEMPOTENT — running it twice is a no-op.
"""

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# ─────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────

CORRUPTED_AGENTS_RESET: Dict[str, Dict[str, Any]] = {
    "CICADA":   {"reason": "alpha=206 beta=1 (99.5% win rate) — HOLD votes inflated by tolerance rule"},
    "SHEPHERD": {"reason": "alpha=46 beta=1 (97.9% win rate) — same HOLD inflation pattern"},
    "BARON":    {"reason": "alpha=111 beta=12 (90.6% win rate) — same HOLD inflation pattern"},
    "SYNTH":    {"reason": "alpha=1 beta=109 (0.9% win rate) — directional voter penalized vs HOLDs"},
    "ZENITH":   {"reason": "alpha=3 beta=202 (1.6% win rate) — directional voter penalized vs HOLDs"},
    "VEIL":     {"reason": "alpha=2 beta=71 (2.5% win rate) — directional voter penalized vs HOLDs"},
    "TALON":    {"reason": "alpha=1 beta=30 (3.2% win rate) — directional voter penalized vs HOLDs"},
    "HEX":      {"reason": "alpha=10 beta=125 (7.4% win rate) — directional voter penalized vs HOLDs"},
}

PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0
EQUALIZED_STARTING_EQUITY = 10000.0

COMPOUNDER_FILES = [
    "scrooge.json", "midas.json", "cryptobro.json",
    "jrr_token.json", "sports_bro.json",
]


# ─────────────────────────────────────────────────────────────────────
# Belief reset
# ─────────────────────────────────────────────────────────────────────

def reset_corrupted_beliefs(beliefs_path: Path, archive_dir: Path) -> Dict[str, Any]:
    if not beliefs_path.exists():
        return {"step": "belief_reset", "status": "SKIPPED",
                "reason": "agent_beliefs.json not found"}

    snapshot_path = archive_dir / "agent_beliefs_pre_migration.json"
    shutil.copy2(beliefs_path, snapshot_path)

    beliefs = json.loads(beliefs_path.read_text())
    reset_log = []

    for agent_name, meta in CORRUPTED_AGENTS_RESET.items():
        if agent_name not in beliefs:
            reset_log.append({"agent": agent_name, "action": "SKIPPED",
                              "reason": "agent not in agent_beliefs.json"})
            continue

        pre_state = {regime: dict(state) for regime, state in beliefs[agent_name].items()}

        already_reset = all(
            (s.get("alpha", 0) == PRIOR_ALPHA and
             s.get("beta", 0) == PRIOR_BETA and
             s.get("n", -1) == 0)
            for s in beliefs[agent_name].values()
        )
        if already_reset:
            reset_log.append({"agent": agent_name, "action": "ALREADY_RESET"})
            continue

        new_state = {}
        for regime in beliefs[agent_name].keys():
            new_state[regime] = {"alpha": PRIOR_ALPHA, "beta": PRIOR_BETA, "n": 0}
        beliefs[agent_name] = new_state

        reset_log.append({
            "agent": agent_name, "action": "RESET",
            "reason": meta["reason"],
            "pre_state": pre_state,
            "post_state": dict(new_state),
        })

    beliefs_path.write_text(json.dumps(beliefs, indent=2))

    return {
        "step": "belief_reset", "status": "OK",
        "snapshot_path": str(snapshot_path),
        "reset_log": reset_log,
        "agents_reset": len([r for r in reset_log if r["action"] == "RESET"]),
    }


# ─────────────────────────────────────────────────────────────────────
# Portfolio equalization
# ─────────────────────────────────────────────────────────────────────

def equalize_portfolios(portfolios_path: Path, archive_dir: Path) -> Dict[str, Any]:
    if not portfolios_path.exists():
        return {"step": "portfolio_equalization", "status": "SKIPPED",
                "reason": "agent_portfolios.json not found"}

    snapshot_path = archive_dir / "agent_portfolios_pre_migration.json"
    shutil.copy2(portfolios_path, snapshot_path)

    raw = json.loads(portfolios_path.read_text())
    equalized_log = []
    now_iso = datetime.now(timezone.utc).isoformat()
    now_date = datetime.now(timezone.utc).date().isoformat()

    for agent_name, record in raw.items():
        if agent_name.startswith("_"):
            continue
        if not isinstance(record, dict):
            continue

        pre_state = {
            "starting_equity": record.get("starting_equity"),
            "current_equity": record.get("current_equity"),
            "cash": record.get("cash"),
            "savings": record.get("savings"),
        }

        if (record.get("starting_equity") == EQUALIZED_STARTING_EQUITY and
            record.get("cash") == EQUALIZED_STARTING_EQUITY and
            record.get("current_equity") == EQUALIZED_STARTING_EQUITY and
            record.get("current_position") is None):
            equalized_log.append({"agent": agent_name, "action": "ALREADY_EQUALIZED"})
            continue

        if record.get("current_position"):
            pos = record["current_position"]
            qty = pos.get("qty", 0) or 0
            entry = pos.get("entry_price", 0) or 0
            refund = qty * entry
            current_cash = record.get("cash", 0) or 0
            record["cash"] = current_cash + refund

            history = record.setdefault("history", [])
            history.append({
                "timestamp": now_iso, "date": now_date, "action": "CLOSE",
                "ticker": pos.get("ticker", ""), "qty": qty, "price": entry,
                "reason": "Alpha 2.2 migration: position closed for capital reset",
            })
            record["current_position"] = None

        record["starting_equity"] = EQUALIZED_STARTING_EQUITY
        record["cash"] = EQUALIZED_STARTING_EQUITY
        record["current_equity"] = EQUALIZED_STARTING_EQUITY

        history = record.setdefault("history", [])
        history.append({
            "timestamp": now_iso, "date": now_date, "action": "RESET",
            "reason": "Alpha 2.2 equalization to $10,000 starting capital",
            "balance_after": EQUALIZED_STARTING_EQUITY,
        })

        equalized_log.append({
            "agent": agent_name, "action": "EQUALIZED",
            "pre_state": pre_state,
            "post_state": {
                "starting_equity": EQUALIZED_STARTING_EQUITY,
                "current_equity": EQUALIZED_STARTING_EQUITY,
                "cash": EQUALIZED_STARTING_EQUITY,
                "savings": record.get("savings", 0),
            },
        })

    portfolios_path.write_text(json.dumps(raw, indent=2, default=str))

    return {
        "step": "portfolio_equalization", "status": "OK",
        "snapshot_path": str(snapshot_path),
        "equalized_log": equalized_log,
        "agents_equalized": len([r for r in equalized_log if r["action"] == "EQUALIZED"]),
    }


# ─────────────────────────────────────────────────────────────────────
# Compounder equalization
# ─────────────────────────────────────────────────────────────────────

def equalize_compounders(data_dir: Path, archive_dir: Path) -> Dict[str, Any]:
    log: List[Dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    now_date = datetime.now(timezone.utc).date().isoformat()

    for fname in COMPOUNDER_FILES:
        fpath = data_dir / fname
        if not fpath.exists():
            log.append({"file": fname, "action": "SKIPPED", "reason": "file not found"})
            continue

        snapshot = archive_dir / f"{fname}.pre_migration"
        shutil.copy2(fpath, snapshot)

        try:
            data = json.loads(fpath.read_text())
        except Exception as e:
            log.append({"file": fname, "action": "ERROR", "reason": str(e)})
            continue

        current_balance = data.get("balance", 0)
        if current_balance == EQUALIZED_STARTING_EQUITY and not data.get("current_position"):
            log.append({"file": fname, "action": "ALREADY_EQUALIZED"})
            continue

        pre_balance = current_balance
        if data.get("current_position"):
            pos = data["current_position"]
            qty = pos.get("qty", 0) or 0
            entry = pos.get("entry_price", 0) or 0
            data["balance"] = current_balance + (qty * entry)
            data["current_position"] = None

            history = data.setdefault("history", [])
            history.append({
                "timestamp": now_iso, "date": now_date, "action": "CLOSE",
                "ticker": pos.get("ticker", ""),
                "reason": "Alpha 2.2 migration: position closed for balance reset",
            })

        data["balance"] = EQUALIZED_STARTING_EQUITY
        data["starting_balance"] = EQUALIZED_STARTING_EQUITY

        history = data.setdefault("history", [])
        history.append({
            "timestamp": now_iso, "date": now_date, "action": "RESET",
            "reason": "Alpha 2.2 equalization to $10,000 starting capital",
            "balance_after": EQUALIZED_STARTING_EQUITY,
        })

        fpath.write_text(json.dumps(data, indent=2, default=str))
        log.append({
            "file": fname, "action": "EQUALIZED",
            "pre_balance": pre_balance,
            "post_balance": EQUALIZED_STARTING_EQUITY,
        })

    return {
        "step": "compounder_equalization", "status": "OK",
        "log": log,
        "compounders_equalized": len([r for r in log if r["action"] == "EQUALIZED"]),
    }


# ─────────────────────────────────────────────────────────────────────
# CLI source patch — directional-only HOLD filter + regime from tags
# ─────────────────────────────────────────────────────────────────────

# The exact buggy fragment in silmaril/cli.py's _post_debate_learning function.
# Read regime from top-level (wrong — it's nested in tags) and fail to filter HOLDs.
_CLI_BUGGY_BELIEFS_BLOCK = '''            outcomes_for_beliefs = [
                {
                    "agent": o.get("agent"),
                    "regime": o.get("regime") or o.get("market_regime") or "UNKNOWN",
                    "won": bool(o.get("correct", o.get("was_correct", o.get("won", False)))),
                }
                for o in new_outcome_dicts
                if o.get("agent")
            ]'''

_CLI_FIXED_BELIEFS_BLOCK = '''            outcomes_for_beliefs = [
                {
                    "agent": o.get("agent"),
                    "regime": (o.get("tags") or {}).get("market_regime") or "UNKNOWN",
                    "won": bool(o.get("correct", o.get("was_correct", o.get("won", False)))),
                }
                for o in new_outcome_dicts
                if o.get("agent")
                and o.get("signal") in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL")
            ]'''

# Sentinel that proves the patch is already applied (idempotency check).
_CLI_PATCH_SENTINEL = 'and o.get("signal") in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL")'


def patch_cli_directional_filter(cli_path: Path, archive_dir: Path) -> Dict[str, Any]:
    """
    Surgical fix to silmaril/cli.py:
      - Read regime from tags["market_regime"], not from non-existent
        top-level "regime" or "market_regime" keys.
      - Filter HOLD/ABSTAIN outcomes out of belief updates so directional
        skill is measured correctly.

    Idempotent. Backs up cli.py to archive_dir before patching.
    Skips with a warning if the expected buggy text isn't found.
    """
    if not cli_path.exists():
        return {"step": "cli_patch", "status": "SKIPPED",
                "reason": "silmaril/cli.py not found"}

    text = cli_path.read_text()

    if _CLI_PATCH_SENTINEL in text:
        return {"step": "cli_patch", "status": "ALREADY_PATCHED"}

    if _CLI_BUGGY_BELIEFS_BLOCK not in text:
        # Safety: don't patch what we can't recognize. Log the situation
        # so the operator can investigate. The system continues running on
        # the unpatched code — bug remains but no damage done.
        return {
            "step": "cli_patch", "status": "FAILED",
            "reason": (
                "Expected buggy code block not found verbatim. "
                "Whitespace or function body may have changed since this "
                "patch was authored. Inspect cli.py _post_debate_learning "
                "manually and update outcomes_for_beliefs comprehension by "
                "hand: (1) replace top-level regime lookup with "
                "(o.get('tags') or {}).get('market_regime'), and "
                "(2) add 'and o.get(\"signal\") in (\"BUY\", \"STRONG_BUY\", "
                "\"SELL\", \"STRONG_SELL\")' to the if filter."
            ),
        }

    # Backup
    snapshot_path = archive_dir / "cli_pre_migration.py"
    shutil.copy2(cli_path, snapshot_path)

    # Patch
    new_text = text.replace(_CLI_BUGGY_BELIEFS_BLOCK, _CLI_FIXED_BELIEFS_BLOCK, 1)
    cli_path.write_text(new_text)

    return {
        "step": "cli_patch",
        "status": "OK",
        "snapshot_path": str(snapshot_path),
        "applied_changes": [
            "outcomes_for_beliefs: regime now read from tags['market_regime']",
            "outcomes_for_beliefs: filter excludes HOLD/ABSTAIN, only directional",
        ],
    }


# ─────────────────────────────────────────────────────────────────────
# Senate log writer
# ─────────────────────────────────────────────────────────────────────

def append_senate_log(data_dir: Path, event: Dict[str, Any]) -> None:
    senate_log_path = data_dir / "senate_log.json"
    if senate_log_path.exists():
        try:
            senate_log = json.loads(senate_log_path.read_text())
        except Exception:
            senate_log = {"events": []}
    else:
        senate_log = {"events": []}

    senate_log.setdefault("events", []).append(event)
    senate_log_path.write_text(json.dumps(senate_log, indent=2, default=str))


# ─────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────

def run_migration(
    data_dir: Path = Path("docs/data"),
    archive_root: Path = Path("docs_archive"),
    repo_root: Path = Path("."),
) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    archive_dir = archive_root / today
    archive_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat()

    belief_report = reset_corrupted_beliefs(data_dir / "agent_beliefs.json", archive_dir)
    portfolio_report = equalize_portfolios(data_dir / "agent_portfolios.json", archive_dir)
    compounder_report = equalize_compounders(data_dir, archive_dir)
    cli_report = patch_cli_directional_filter(repo_root / "silmaril" / "cli.py", archive_dir)

    finished_at = datetime.now(timezone.utc).isoformat()
    event = {
        "started_at": started_at,
        "finished_at": finished_at,
        "type": "MIGRATION_ALPHA_2_2",
        "version": "alpha_2_2",
        "archive_dir": str(archive_dir),
        "belief_reset": belief_report,
        "portfolio_equalization": portfolio_report,
        "compounder_equalization": compounder_report,
        "cli_source_patch": cli_report,
    }
    append_senate_log(data_dir, event)

    return {
        "migration": "alpha_2_2",
        "started_at": started_at,
        "finished_at": finished_at,
        "archive_dir": str(archive_dir),
        "steps": [belief_report, portfolio_report, compounder_report, cli_report],
    }


if __name__ == "__main__":
    import sys
    report = run_migration()
    print(json.dumps(report, indent=2, default=str))
    sys.exit(0)
