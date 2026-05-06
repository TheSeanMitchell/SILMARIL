"""
silmaril.senate.elections — Weekly Senate elections.

Runs every Sunday at 06:00 UTC via senate.yml workflow.

Election rules
──────────────
Promotion: CANDIDATE → PROBATIONARY VOTER
  All must be true:
    • Beta posterior mean   > 0.54
    • Beta 95% CI lower     > 0.50  (not just lucky variance)
    • Rolling 30-day win %  > 52%
    • Minimum scored calls  ≥ 40

Demotion: VOTER → PROBATIONARY
  Any triggers:
    • Rolling 30-day win %  < 44% for 2 consecutive Sundays
    • Beta posterior mean   < 0.47

Emeritus (permanent):
    • Probationary ≥ 4 consecutive elections with no recovery
    • OR manual flag in senate_state.json

Graduation: PROBATIONARY → VOTER
    • 2 consecutive elections without demotion trigger
    • Beta posterior mean > 0.50

Status values: VOTER | PROBATIONARY | CANDIDATE | EMERITUS
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── thresholds ──────────────────────────────────────────────────
PROMOTE_BETA_MEAN         = 0.54
PROMOTE_BETA_CI_LOWER     = 0.50
PROMOTE_WIN_RATE          = 0.52
PROMOTE_MIN_CALLS         = 40

DEMOTE_WIN_RATE           = 0.44
DEMOTE_BETA_MEAN          = 0.47
DEMOTE_CONSEC_WEEKS       = 2

GRADUATE_CONSEC_CLEAN     = 2
GRADUATE_BETA_MEAN        = 0.50

EMERITUS_CONSEC_PROB      = 4

DEFAULT_STATUS            = "VOTER"   # agents not in senate_state default to VOTER


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ─── Beta posterior helpers ───────────────────────────────────────

def _beta_mean(alpha: float, beta: float) -> float:
    return alpha / (alpha + beta) if (alpha + beta) > 0 else 0.5

def _beta_ci_lower(alpha: float, beta: float, confidence: float = 0.95) -> float:
    """Wilson-score approximation to Beta 95% CI lower bound. Fast, no scipy needed."""
    n = alpha + beta - 2   # effective sample size
    if n <= 0:
        return 0.0
    p = _beta_mean(alpha, beta)
    z = 1.645  # 95% one-sided
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (center - spread) / denom)

def _best_regime_posterior(agent_beliefs: Dict) -> Tuple[float, float]:
    """Return the (mean, ci_lower) from the agent's strongest-evidence regime."""
    best_mean = 0.5
    best_ci   = 0.0
    best_n    = 0
    for regime, v in agent_beliefs.items():
        a = float(v.get("alpha", 1))
        b = float(v.get("beta",  1))
        n = int(v.get("n", 0))
        if n > best_n:
            best_n   = n
            best_mean = _beta_mean(a, b)
            best_ci   = _beta_ci_lower(a, b)
    return best_mean, best_ci


# ─── Scoring helpers ──────────────────────────────────────────────

def _rolling_win_rate(outcomes: List[Dict], days: int = 30) -> Optional[float]:
    """Rolling win rate over the last N days from scoring.json outcomes list."""
    if not outcomes:
        return None
    cutoff_ts = None
    try:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        recent = [o for o in outcomes if (o.get("scored_at") or o.get("date", "")) >= cutoff
                  and o.get("signal") not in ("HOLD", "ABSTAIN")]
        if len(recent) < 5:
            return None
        wins = sum(1 for o in recent if o.get("correct") or o.get("won"))
        return wins / len(recent)
    except Exception:
        return None

def _total_directional_calls(outcomes: List[Dict]) -> int:
    return sum(1 for o in outcomes if o.get("signal") not in ("HOLD", "ABSTAIN", None))


# ─── State I/O ────────────────────────────────────────────────────

def load_senate_state(path: Path) -> Dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {
        "version": "2.3",
        "created_at": _now_iso(),
        "last_election": None,
        "agents": {},
    }

def save_senate_state(state: Dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str))

def get_agent_status(state: Dict, agent: str) -> str:
    return state.get("agents", {}).get(agent, {}).get("status", DEFAULT_STATUS)


# ─── Core election logic ──────────────────────────────────────────

def _evaluate_agent(
    agent: str,
    agent_beliefs: Dict,
    outcomes: List[Dict],
    current_state: Dict,
) -> Dict[str, Any]:
    """Compute all metrics for one agent."""
    current_status = get_agent_status(current_state, agent)
    agent_entry    = current_state.get("agents", {}).get(agent, {})

    beta_mean, beta_ci = _best_regime_posterior(agent_beliefs)
    win_rate_30d       = _rolling_win_rate(outcomes, days=30)
    total_calls        = _total_directional_calls(outcomes)
    consec_demote      = int(agent_entry.get("consecutive_demotion_triggers", 0))
    consec_clean       = int(agent_entry.get("consecutive_clean_elections", 0))
    consec_prob        = int(agent_entry.get("consecutive_probationary_elections", 0))

    return {
        "agent":           agent,
        "status_before":   current_status,
        "beta_mean":       round(beta_mean, 4),
        "beta_ci_lower":   round(beta_ci, 4),
        "win_rate_30d":    round(win_rate_30d, 4) if win_rate_30d is not None else None,
        "total_calls":     total_calls,
        "consec_demote":   consec_demote,
        "consec_clean":    consec_clean,
        "consec_prob":     consec_prob,
    }


def _decide_transition(metrics: Dict) -> Tuple[str, str]:
    """
    Given metrics dict, return (new_status, reason).
    Returns current status if no transition warranted.
    """
    status       = metrics["status_before"]
    beta_mean    = metrics["beta_mean"]
    beta_ci      = metrics["beta_ci_lower"]
    win_rate     = metrics["win_rate_30d"]
    total_calls  = metrics["total_calls"]
    consec_prob  = metrics["consec_prob"]
    consec_demote= metrics["consec_demote"]
    consec_clean = metrics["consec_clean"]

    # EMERITUS: manual lock — never auto-change
    if status == "EMERITUS":
        return "EMERITUS", "Permanent emeritus — manual only to change"

    # CANDIDATE → PROBATIONARY (promotion)
    if status == "CANDIDATE":
        if (beta_mean > PROMOTE_BETA_MEAN
                and beta_ci > PROMOTE_BETA_CI_LOWER
                and win_rate is not None and win_rate > PROMOTE_WIN_RATE
                and total_calls >= PROMOTE_MIN_CALLS):
            return "PROBATIONARY", (
                f"Promoted: β={beta_mean:.3f} CI={beta_ci:.3f} "
                f"win%={win_rate:.1%} calls={total_calls}"
            )
        return "CANDIDATE", "Insufficient track record for promotion"

    # PROBATIONARY → VOTER (graduation)
    if status == "PROBATIONARY":
        if consec_prob >= EMERITUS_CONSEC_PROB:
            return "EMERITUS", f"Emeritus: {consec_prob} consecutive probationary elections"
        if consec_clean >= GRADUATE_CONSEC_CLEAN and beta_mean > GRADUATE_BETA_MEAN:
            return "VOTER", f"Graduated: {consec_clean} clean elections, β={beta_mean:.3f}"
        return "PROBATIONARY", "Still probationary"

    # VOTER: check for demotion
    if status == "VOTER":
        demote_trigger = (
            (win_rate is not None and win_rate < DEMOTE_WIN_RATE)
            or beta_mean < DEMOTE_BETA_MEAN
        )
        if demote_trigger:
            new_consec = consec_demote + 1
            if new_consec >= DEMOTE_CONSEC_WEEKS:
                return "PROBATIONARY", (
                    f"Demoted: β={beta_mean:.3f} win%={win_rate:.1%} "
                    f"({new_consec} consecutive weak elections)"
                )
            return "VOTER", f"Warning: weak election #{new_consec} — watching"
        return "VOTER", f"Healthy: β={beta_mean:.3f} win%={win_rate:.1%}"

    return status, "No change"


def run_election(data_dir: Path) -> Dict:
    """
    Main entry point. Reads state, evaluates all agents, writes results.
    Returns the full results dict.
    """
    today         = _today()
    beliefs_path  = data_dir / "agent_beliefs.json"
    scoring_path  = data_dir / "scoring.json"
    state_path    = data_dir / "senate_state.json"
    results_path  = data_dir / "senate_results.json"

    # Load all data
    beliefs = {}
    if beliefs_path.exists():
        try: beliefs = json.loads(beliefs_path.read_text())
        except Exception: pass

    scoring_raw = {}
    if scoring_path.exists():
        try: scoring_raw = json.loads(scoring_path.read_text())
        except Exception: pass

    state = load_senate_state(state_path)

    # All agents known: union of beliefs keys + state keys
    all_agents = set(beliefs.keys()) | set(state.get("agents", {}).keys())

    results: List[Dict] = []
    new_agents_state: Dict[str, Dict] = dict(state.get("agents", {}))

    for agent in sorted(all_agents):
        agent_beliefs  = beliefs.get(agent, {})
        outcomes       = scoring_raw.get(agent, {}).get("outcomes", []) if isinstance(scoring_raw.get(agent), dict) else []
        # Fallback: flat list of outcomes keyed by agent name
        if not outcomes and isinstance(scoring_raw, dict):
            outcomes = [o for o in scoring_raw.get("outcomes", []) if o.get("agent") == agent]

        metrics   = _evaluate_agent(agent, agent_beliefs, outcomes, state)
        new_status, reason = _decide_transition(metrics)

        old_entry = new_agents_state.get(agent, {})
        old_status = metrics["status_before"]

        # Update counters
        consec_demote  = old_entry.get("consecutive_demotion_triggers", 0)
        consec_clean   = old_entry.get("consecutive_clean_elections", 0)
        consec_prob    = old_entry.get("consecutive_probationary_elections", 0)

        if new_status in ("PROBATIONARY", "EMERITUS") and old_status == "VOTER":
            consec_demote += 1
            consec_clean   = 0
        elif new_status == "VOTER" and old_status == "VOTER":
            consec_demote  = 0
            consec_clean  += 1
        if new_status == "PROBATIONARY":
            consec_prob += 1
        else:
            consec_prob = 0

        new_agents_state[agent] = {
            "status": new_status,
            "since":  old_entry.get("since", today) if new_status == old_status else today,
            "elections_survived": old_entry.get("elections_survived", 0) + 1,
            "consecutive_demotion_triggers": consec_demote,
            "consecutive_clean_elections":   consec_clean,
            "consecutive_probationary_elections": consec_prob,
        }

        transition = new_status != old_status
        results.append({
            **metrics,
            "status_after":  new_status,
            "reason":        reason,
            "transitioned":  transition,
        })
        if transition:
            print(f"[senate] {agent}: {old_status} → {new_status}  ({reason})")
        else:
            print(f"[senate] {agent}: {new_status}  ({reason})")

    # Write updated state
    state["last_election"]   = today
    state["election_count"]  = state.get("election_count", 0) + 1
    state["agents"]          = new_agents_state
    save_senate_state(state, state_path)

    # Write results
    promoted   = [r for r in results if r["status_before"] == "CANDIDATE"   and r["status_after"] == "PROBATIONARY"]
    demoted    = [r for r in results if r["status_before"] == "VOTER"        and r["status_after"] == "PROBATIONARY"]
    graduated  = [r for r in results if r["status_before"] == "PROBATIONARY" and r["status_after"] == "VOTER"]
    emeritus   = [r for r in results if r["status_after"] == "EMERITUS"      and r["status_before"] != "EMERITUS"]

    election_results = {
        "election_date":  today,
        "generated_at":   _now_iso(),
        "election_number": state["election_count"],
        "summary": {
            "promoted":  [r["agent"] for r in promoted],
            "demoted":   [r["agent"] for r in demoted],
            "graduated": [r["agent"] for r in graduated],
            "emeritus":  [r["agent"] for r in emeritus],
            "total_evaluated": len(results),
        },
        "full_results":   results,
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(election_results, indent=2, default=str))

    print(f"\n[senate] Election #{state['election_count']} complete.")
    print(f"  Promoted: {[r['agent'] for r in promoted]}")
    print(f"  Demoted:  {[r['agent'] for r in demoted]}")
    print(f"  Graduated:{[r['agent'] for r in graduated]}")
    print(f"  Emeritus: {[r['agent'] for r in emeritus]}")
    return election_results


if __name__ == "__main__":
    import sys
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    results = run_election(data_dir)
    print(json.dumps(results["summary"], indent=2))
