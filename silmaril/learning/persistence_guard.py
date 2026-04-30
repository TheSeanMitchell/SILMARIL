"""
silmaril.learning.persistence_guard — Protects learning state from wipes.

ARCHITECTURAL PRINCIPLE:
    Learning is sacred. No workflow — daily, backtest, reset, or otherwise —
    is permitted to delete or overwrite any file in PROTECTED_LEARNING_FILES
    without going through this module's `safe_reset()` function, which by
    design preserves all learning artifacts.

This is the single source of truth for what counts as "agent training memory."
Every reset workflow MUST import from here. The reset.yml workflow checks
this list and explicitly skips these files.

Usage:
    from silmaril.learning.persistence_guard import (
        PROTECTED_LEARNING_FILES, is_protected, safe_reset, backup_learning_state
    )
"""
from __future__ import annotations

import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Set


# ---------------------------------------------------------------------------
# THE SACRED LIST — these files MUST persist across every workflow run.
# Adding to this list is fine. Removing from it requires explicit operator
# approval and a one-time export of the file's contents to backup.
# ---------------------------------------------------------------------------
PROTECTED_LEARNING_FILES: Set[str] = {
    # Bayesian belief states per agent per regime
    "agent_beliefs.json",
    # Contextual bandits per (regime, asset_class, vol_quartile)
    "regime_bandits.json",
    # Counterfactual outcomes (what dissents would have done)
    "counterfactuals.json",
    # Hysteresis state (current band states per agent per ticker)
    "hysteresis_state.json",
    # Live scoring (rolling per-agent win rates and EV)
    "scoring.json",
    # Per-agent $10K portfolio history and equity curves
    "agent_portfolios.json",
    # Per-compounder state (Scrooge, Midas, CryptoBro, JRR, Sports Bro)
    "scrooge.json", "midas.json", "cryptobro.json", "jrr_token.json", "sports_bro.json",
    # Specialist book history (Baron oil, Steadfast crown jewels)
    "baron.json", "steadfast.json",
    # Rolling 120-day equity history snapshots
    "history.json",
    # Operator reflections (manual learning injection)
    "reflections.json",
    # Agent evolution cards — gamified XP/level cards that ONLY GROW
    "agent_evolution_cards.json",
    # News quality feedback (which sources have produced reliable signal)
    "news_source_quality.json",
    # Anomaly detection state (recently-flagged anomalies, dedupe)
    "anomaly_state.json",
    # Drift detector state (sudden regime shifts in agent performance)
    "drift_state.json",
    # Adversarial stress test results (preserved across runs)
    "stress_test_results.json",
    # Correlation matrix history
    "correlation_history.json",
    # Time-of-day performance buckets
    "time_of_day_performance.json",
    # Pre-mortem rationale archive
    "premortem_archive.json",
    # Walk-forward backtest belief snapshots (per-window)
    "backtest_belief_snapshots.json",
    # Alpaca paper trading state (orders, positions, equity)
    "alpaca_paper_state.json",
    "alpaca_equity_curve.json",
}


def is_protected(filename: str) -> bool:
    """Returns True if a filename is on the sacred list."""
    return Path(filename).name in PROTECTED_LEARNING_FILES


def safe_reset(
    data_dir: Path,
    *,
    keep_protected: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    Reset the data directory while preserving all learning state.

    By default keeps everything in PROTECTED_LEARNING_FILES intact.
    Wipes only the daily-regenerated artifacts (signals, trade_plans, etc).

    Returns a report dict: {kept: [...], removed: [...], errors: [...]}
    """
    report = {"kept": [], "removed": [], "errors": []}
    if not data_dir.exists():
        return report

    for entry in sorted(data_dir.iterdir()):
        if not entry.is_file():
            continue
        if keep_protected and is_protected(entry.name):
            report["kept"].append(entry.name)
            continue
        if dry_run:
            report["removed"].append(entry.name + " (dry-run)")
            continue
        try:
            entry.unlink()
            report["removed"].append(entry.name)
        except Exception as e:
            report["errors"].append(f"{entry.name}: {type(e).__name__}: {e}")

    return report


def backup_learning_state(
    data_dir: Path,
    backup_dir: Path,
    *,
    label: str = "weekly",
) -> Path:
    """
    Snapshot all PROTECTED_LEARNING_FILES into a single .tar.gz.

    The backup filename embeds the UTC timestamp and label for sortability:
        learning_backup_2026-04-30_weekly.tar.gz

    Returns the path to the created archive. If no protected files exist,
    creates an empty archive (for audit purposes).
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    archive_name = f"learning_backup_{ts}_{label}.tar.gz"
    archive_path = backup_dir / archive_name

    with tarfile.open(archive_path, "w:gz") as tar:
        for fname in PROTECTED_LEARNING_FILES:
            fp = data_dir / fname
            if fp.exists():
                tar.add(fp, arcname=fname)

    return archive_path


def verify_persistence(data_dir: Path) -> dict:
    """
    Health-check: report which protected files exist and their sizes.
    Used by stress_test workflow and on-site monitoring panel.
    """
    report = {"total_protected": len(PROTECTED_LEARNING_FILES), "present": [], "missing": []}
    for fname in sorted(PROTECTED_LEARNING_FILES):
        fp = data_dir / fname
        if fp.exists():
            report["present"].append({
                "file": fname,
                "size_bytes": fp.stat().st_size,
                "modified": datetime.fromtimestamp(
                    fp.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            })
        else:
            report["missing"].append(fname)
    return report


def emit_persistence_status(data_dir: Path, output_path: Path) -> None:
    """Writes a JSON status file the dashboard can render."""
    report = verify_persistence(data_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str))
