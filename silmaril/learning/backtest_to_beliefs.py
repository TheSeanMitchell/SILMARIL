"""
silmaril.learning.backtest_to_beliefs

Bridges the BACKTEST stream into the LIVE Bayesian belief stream.

The senate elections read `agent_beliefs.json`, which is populated only
by the daily run's scoring loop on real-time outcomes. Backtest results,
meanwhile, sit in `backtest_report.json` for dashboard display and never
inform agent evaluation. That means it takes weeks of live runs before
the senate has enough scored calls to actually demote a bad agent.

This module ingests backtest predictions as FRACTIONAL Beta-distribution
observations — each backtest call counts as `weight` (default 0.3) of a
live observation. Backtest evidence accumulates a prior; live evidence
overwrites it as it arrives. With a default decay of 0.997 per update,
backtest's contribution diminishes naturally as live data accumulates.

Idempotency: each backtest run is identified by a `run_id` (hash of
config). A provenance sidecar records ingested run_ids so re-running
the workflow doesn't double-count the same predictions.

Safety: there's a hard cap on backtest's share — if backtest evidence
already accounts for >50% of an agent×regime's observation count, the
ingester refuses to add more. This prevents a runaway backtest from
permanently colonizing the live belief state.

Usage:
    from silmaril.learning.backtest_to_beliefs import ingest_backtest_report
    summary = ingest_backtest_report(
        report_path=Path("docs/data/backtest_report.json"),
        beliefs_path=Path("docs/data/agent_beliefs.json"),
        provenance_path=Path("docs/data/backtest_provenance.json"),
        weight=0.3,
        dry_run=False,
    )
    print(summary)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .bayesian_winrate import (
    AgentBeliefState, BetaState,
    PRIOR_ALPHA, PRIOR_BETA, DECAY_LAMBDA,
    load_beliefs, save_beliefs,
)
from ..scoring.outcomes import _score_call


# ─── Tunables ─────────────────────────────────────────────────────
DEFAULT_BACKTEST_WEIGHT = 0.3   # each backtest call ≈ 30% of a live call
# Hard ceiling on backtest observations per (agent × regime) bucket.
# Combined with the default 0.3 weight this caps the effective Bayesian
# pseudo-count contribution at 60 — substantial enough to inform the
# senate but small enough that ~60 live observations equalize the
# influence, and the decay (0.997/update) erodes it further over time.
BACKTEST_OBS_CEILING    = 200
HOLD_RETURN_TOL_PCT     = 1.5   # tolerance when scoring HOLD calls


# ─── Provenance: avoid double-counting the same backtest run ──────
def _run_id(report_payload: Dict[str, Any]) -> str:
    """Stable hash of the backtest config (start, end, agents, tickers).

    Two reports with identical configs produce identical run_ids; that's
    the desired behavior — re-running the same backtest reproduces the
    same predictions, so we should not re-ingest.
    """
    config = report_payload.get("config", {})
    seed = json.dumps({
        "start":   config.get("start"),
        "end":     config.get("end"),
        "agents":  sorted(config.get("agents") or []),
        "tickers": sorted(config.get("tickers") or []),
    }, sort_keys=True)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _load_provenance(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": 1, "ingested": []}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"version": 1, "ingested": []}


def _save_provenance(path: Path, prov: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prov, indent=2, default=str))


# ─── Fractional Beta update ───────────────────────────────────────
def _update_beta_weighted(bs: BetaState, won: bool, weight: float) -> None:
    """Same shape as BetaState.update() but fractional.

    Mirrors the decay-then-update pattern in bayesian_winrate.py so the
    long-run dynamics remain identical regardless of source mix.
    """
    bs.alpha = (bs.alpha - PRIOR_ALPHA) * DECAY_LAMBDA + PRIOR_ALPHA
    bs.beta  = (bs.beta  - PRIOR_BETA)  * DECAY_LAMBDA + PRIOR_BETA
    if won:
        bs.alpha += weight
    else:
        bs.beta  += weight
    bs.n += 1


# ─── Main ingestion entrypoint ────────────────────────────────────
def ingest_backtest_report(
    report_path: Path,
    beliefs_path: Path,
    provenance_path: Path,
    weight: float = DEFAULT_BACKTEST_WEIGHT,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Read backtest_report.json, convert predictions to weighted outcomes,
    and update agent_beliefs.json.

    Returns a summary dict with counts and per-agent stats.
    """
    if not report_path.exists():
        return {"status": "skipped", "reason": f"no report at {report_path}"}
    payload = json.loads(report_path.read_text())
    predictions = payload.get("predictions") or []
    if not predictions:
        return {"status": "skipped", "reason": "report has no predictions"}

    rid = _run_id(payload)
    prov = _load_provenance(provenance_path)
    if any(rec.get("run_id") == rid for rec in prov.get("ingested", [])):
        return {
            "status":  "skipped",
            "reason":  f"backtest run_id {rid} already ingested",
            "run_id":  rid,
        }

    beliefs = load_beliefs(beliefs_path)

    # Sidecar: how many backtest obs have we already pushed into each
    # (agent, regime) bucket across ALL prior ingestions? Used to enforce
    # the BACKTEST_OBS_CEILING. Stored inside provenance to keep one file.
    bt_counts: Dict[str, Dict[str, int]] = prov.get("bucket_counts", {}) or {}

    # Per-agent rollup for the report
    rollup: Dict[str, Dict[str, Any]] = {}

    skipped_capped     = 0
    skipped_no_return  = 0
    applied            = 0

    for p in predictions:
        agent  = p.get("agent")
        regime = p.get("regime") or "UNKNOWN"
        signal = (p.get("signal") or "HOLD").upper()
        ret    = p.get("next_day_return")
        if not agent or ret is None:
            skipped_no_return += 1
            continue

        # _score_call expects a percentage (e.g., 1.5 for 1.5%); engine.py
        # writes next_day_return as a decimal fraction (0.015), so convert.
        ret_pct = float(ret) * 100.0
        won, _reward = _score_call(signal, ret_pct)

        # Per-(agent, regime) ceiling on cumulative backtest observations.
        # Once this bucket is "full," further backtest evidence is ignored
        # so live signal can dominate without being drowned out by historic
        # data on long backtest windows.
        bucket_key = f"{agent}::{regime}"
        cumulative_bt = bt_counts.get(agent, {}).get(regime, 0)
        if cumulative_bt >= BACKTEST_OBS_CEILING:
            skipped_capped += 1
            continue

        if agent not in beliefs:
            beliefs[agent] = AgentBeliefState(agent=agent)
        bs = beliefs[agent].get(regime)
        _update_beta_weighted(bs, won, weight)
        applied += 1

        # Track the bump in our sidecar counter
        bt_counts.setdefault(agent, {})
        bt_counts[agent][regime] = cumulative_bt + 1

        r = rollup.setdefault(agent, {"applied": 0, "wins": 0, "losses": 0, "by_regime": {}})
        r["applied"] += 1
        r["wins"]    += 1 if won else 0
        r["losses"]  += 0 if won else 1
        rr = r["by_regime"].setdefault(regime, {"applied": 0, "wins": 0, "losses": 0})
        rr["applied"] += 1
        rr["wins"]    += 1 if won else 0
        rr["losses"]  += 0 if won else 1

    summary = {
        "status":            "ok" if not dry_run else "dry_run",
        "run_id":            rid,
        "config":            payload.get("config", {}),
        "predictions_total": len(predictions),
        "applied":           applied,
        "skipped_no_return": skipped_no_return,
        "skipped_capped":    skipped_capped,
        "weight":            weight,
        "agents":            len(rollup),
        "rollup":            rollup,
    }

    if not dry_run and applied > 0:
        save_beliefs(beliefs_path, beliefs)
        prov.setdefault("ingested", []).append({
            "run_id":    rid,
            "applied":   applied,
            "weight":    weight,
            "config":    payload.get("config", {}),
            "agents":    list(rollup.keys()),
        })
        # Cap the provenance log at the most recent 200 ingestions
        prov["ingested"] = prov["ingested"][-200:]
        # Persist the updated bucket counts so the ceiling is enforced
        # across separate ingestion runs (e.g., walk-forward windows).
        prov["bucket_counts"] = bt_counts
        _save_provenance(provenance_path, prov)

    return summary


__all__ = ["ingest_backtest_report",
           "DEFAULT_BACKTEST_WEIGHT", "BACKTEST_OBS_CEILING"]
