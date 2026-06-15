"""
scripts/train_from_backtest.py — Train ALL agents on backtest data.

Two modes:
  1) `--ingest-only`: read existing docs/data/backtest_report.json and
     update agent_beliefs.json with weighted observations. Fast (~1 sec).
  2) Default (`--run-backtest`): run a fresh backtest first over the
     specified date range, THEN ingest the new report. Slower (~5–15 min
     depending on date range and ticker count).

Tunables exposed via CLI flags:
  --weight       Each backtest call counts as this fraction of a live call.
                 Default 0.3. Range typically [0.1, 0.5]. Higher = backtest
                 has more influence on senate decisions; lower = autopilot
                 must observe more live calls before backtest is overridden.
  --start, --end ISO dates for the backtest window. Default: last 2 years.
  --dry-run      Compute the proposed updates and print a report, but
                 don't write agent_beliefs.json. Useful for sanity-checking
                 a new weight or window before committing.

Idempotency: each backtest run is hashed by (start, end, agents, tickers).
Re-running with the same config skips re-ingestion. Change a parameter to
get a new run_id.

Cap: backtest may not exceed MAX_BACKTEST_SHARE (50%) of an agent×regime's
total observations. This prevents a long backtest from permanently
dominating a young agent's belief posterior.

Usage:
    # Quick: ingest existing report
    python scripts/train_from_backtest.py --ingest-only

    # Run a 1-year backtest and ingest at 0.4 weight
    python scripts/train_from_backtest.py --start 2025-05-08 --end 2026-05-07 --weight 0.4

    # Preview a multi-year backtest with no writes
    python scripts/train_from_backtest.py --start 2024-01-01 --end 2026-05-07 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

# Make the silmaril package importable when invoked from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from silmaril.learning.backtest_to_beliefs import (
    ingest_backtest_report, DEFAULT_BACKTEST_WEIGHT, BACKTEST_OBS_CEILING,
)


DATA = Path("docs/data")
REPORT_PATH     = DATA / "backtest_report.json"
BELIEFS_PATH    = DATA / "agent_beliefs.json"
PROVENANCE_PATH = DATA / "backtest_provenance.json"


def _run_fresh_backtest(start: date, end: date) -> bool:
    """Invoke the existing backtest module against the date window."""
    print(f"[train] running fresh backtest {start} → {end}...")
    # The backtest module is invoked as `python -m silmaril.backtest`.
    # Use its existing CLI rather than re-implementing here.
    import subprocess
    result = subprocess.run(
        ["python", "-m", "silmaril.backtest",
         "--start", start.isoformat(),
         "--end",   end.isoformat()],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[train] backtest failed (exit {result.returncode}):")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        return False
    # Print just the summary lines from the backtest's output
    for line in (result.stdout or "").splitlines():
        if line.strip().startswith(("=", "Days replayed", "Tickers", "Total predictions", "Agent coverage")):
            print(f"  {line}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ingest-only", action="store_true",
        help="Skip running a fresh backtest; just ingest existing report")
    parser.add_argument("--start", type=str, default=None,
        help="Backtest start date (ISO). Default: 2 years before --end")
    parser.add_argument("--end", type=str, default=None,
        help="Backtest end date (ISO). Default: today")
    parser.add_argument("--weight", type=float, default=DEFAULT_BACKTEST_WEIGHT,
        help=f"Per-call backtest weight (live=1.0). Default: {DEFAULT_BACKTEST_WEIGHT}")
    parser.add_argument("--dry-run", action="store_true",
        help="Print summary but don't write agent_beliefs.json")
    args = parser.parse_args()

    if not 0.05 <= args.weight <= 1.0:
        print(f"[train] refusing weight={args.weight} — must be in [0.05, 1.0]")
        return 2

    # Step 1: optionally run a fresh backtest
    if not args.ingest_only:
        end_d   = date.fromisoformat(args.end) if args.end else date.today()
        start_d = date.fromisoformat(args.start) if args.start else end_d - timedelta(days=730)
        ok = _run_fresh_backtest(start_d, end_d)
        if not ok:
            return 3
    else:
        if not REPORT_PATH.exists():
            print(f"[train] --ingest-only specified but {REPORT_PATH} doesn't exist")
            print("        Run without --ingest-only to generate one first.")
            return 4

    # Step 2: ingest predictions into beliefs
    summary = ingest_backtest_report(
        report_path=REPORT_PATH,
        beliefs_path=BELIEFS_PATH,
        provenance_path=PROVENANCE_PATH,
        weight=args.weight,
        dry_run=args.dry_run,
    )

    print()
    print("=" * 60)
    print(f"BACKTEST → BELIEFS ({summary.get('status', '?').upper()})")
    print("=" * 60)
    print(f"  run_id:            {summary.get('run_id', '—')}")
    print(f"  weight:            {summary.get('weight')}× per call (live = 1.0×)")
    print(f"  predictions:       {summary.get('predictions_total', 0)}")
    print(f"  applied:           {summary.get('applied', 0)}")
    print(f"  skipped (capped):  {summary.get('skipped_capped', 0)} "
          f"(bucket already at {BACKTEST_OBS_CEILING}-obs ceiling)")
    print(f"  skipped (no ret):  {summary.get('skipped_no_return', 0)}")
    print(f"  agents updated:    {summary.get('agents', 0)}")
    print()
    rollup = summary.get("rollup", {}) or {}
    if rollup:
        # Top 8 agents by applied calls (the ones who got the most evidence)
        top = sorted(rollup.items(), key=lambda kv: -kv[1]["applied"])[:8]
        print("  Top 8 agents by backtest evidence:")
        for agent, r in top:
            wr = r["wins"] / r["applied"] if r["applied"] else 0.0
            print(f"    {agent:18s} {r['applied']:>5} calls   "
                  f"{r['wins']:>4}W / {r['losses']:>4}L   "
                  f"win-rate {wr*100:5.1f}%")
    print("=" * 60)

    if summary.get("status") == "skipped":
        print(f"  Reason: {summary.get('reason')}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
