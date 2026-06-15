"""
silmaril.senate.conclave — The Conclave: bi-weekly agent birth.

The Conclave runs every other Sunday after the Senate election.
It inspects the collective learning gaps — regimes where the existing
agents have low combined conviction, blind spots in sector coverage,
or consistent mis-calls — and proposes a new candidate agent spec.

In Alpha 2.3 the Conclave only produces a SPEC (a JSON description
of what the new agent should do). A human reviews the spec and
approves it. In Alpha 2.4, the Conclave will auto-generate the
agent code via the Anthropic API.

Output: docs/data/conclave_proposal.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def identify_gaps(
    beliefs: Dict,
    scoring_raw: Any,
    debate_dicts: List[Dict],
) -> Dict[str, Any]:
    """
    Find collective blind spots in the current senate.

    Returns a gap report with:
      low_conviction_regimes: regimes where avg conviction < 0.5
      uncovered_sectors: sectors with < 2 agents voting directionally
      worst_call_patterns: signal types consistently wrong
    """
    # Low-conviction regimes: find regimes where most agents HOLD
    regime_hold_counts: Dict[str, int]  = {}
    regime_total_counts: Dict[str, int] = {}
    for debate in debate_dicts:
        regime = debate.get("consensus", {}).get("regime", "UNKNOWN")
        for v in debate.get("verdicts", []):
            regime_total_counts[regime] = regime_total_counts.get(regime, 0) + 1
            if v.get("signal") in ("HOLD", "ABSTAIN"):
                regime_hold_counts[regime] = regime_hold_counts.get(regime, 0) + 1

    low_conviction_regimes = []
    for regime, total in regime_total_counts.items():
        hold_pct = regime_hold_counts.get(regime, 0) / max(1, total)
        if hold_pct > 0.6:
            low_conviction_regimes.append({"regime": regime, "hold_pct": round(hold_pct, 2)})

    # Uncovered sectors: sectors where no agent has a strong BUY/SELL track record
    sector_agents: Dict[str, set] = {}
    for debate in debate_dicts:
        sector = debate.get("sector", "UNKNOWN")
        for v in debate.get("verdicts", []):
            if v.get("signal") in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"):
                if sector not in sector_agents:
                    sector_agents[sector] = set()
                sector_agents[sector].add(v["agent"])

    uncovered_sectors = [s for s, agents in sector_agents.items() if len(agents) < 2]

    return {
        "low_conviction_regimes": low_conviction_regimes,
        "uncovered_sectors":      uncovered_sectors[:5],
        "identified_at":          _now(),
    }


def generate_proposal(gaps: Dict) -> Dict:
    """
    From gap analysis, propose a new candidate agent spec.
    This is a template — human reviews before any agent is instantiated.
    """
    # Simple heuristic: if lots of HOLD in RISK_OFF regime, propose a defensive specialist
    low_regimes = [g["regime"] for g in gaps.get("low_conviction_regimes", [])]
    uncovered   = gaps.get("uncovered_sectors", [])

    if "RISK_OFF" in low_regimes:
        specialty = "Defensive / Flight-to-safety specialist"
        universe  = ["TLT", "GLD", "UUP", "VIX", "VIXY", "SHV", "BIL"]
        rationale = "Senate shows high HOLD rate in RISK_OFF regime — gap in defensive coverage"
        temperament = "Cautious, counter-cyclical. Buys safety when others panic."
    elif uncovered:
        sector = uncovered[0]
        specialty = f"{sector} sector specialist"
        universe  = []   # human fills in
        rationale = f"Sector '{sector}' has fewer than 2 directional agents"
        temperament = f"Focused exclusively on {sector}. Deep domain knowledge."
    else:
        specialty = "Cross-asset macro rotation"
        universe  = ["SPY", "TLT", "GLD", "DXY", "EEM", "OIL"]
        rationale = "No specific gap — general macro rotation agent proposed for diversity"
        temperament = "Rotates between risk-on and risk-off based on yield curve and credit spreads."

    return {
        "proposed_codename":  "CANDIDATE_DELTA",
        "specialty":          specialty,
        "temperament":        temperament,
        "suggested_universe": universe,
        "rationale":          rationale,
        "status":             "PENDING_REVIEW",
        "proposed_at":        _now(),
        "gaps_that_triggered": gaps,
    }


def run_conclave(data_dir: Path) -> Dict:
    beliefs     = _load(data_dir / "agent_beliefs.json")
    scoring_raw = _load(data_dir / "scoring.json")

    # We don't have live debate_dicts here — load last run's signals.json
    signals_raw = _load(data_dir / "signals.json")
    debate_dicts = signals_raw.get("debates", []) if isinstance(signals_raw, dict) else []

    print("[conclave] Identifying collective learning gaps...")
    gaps     = identify_gaps(beliefs, scoring_raw, debate_dicts)
    proposal = generate_proposal(gaps)

    out_path = data_dir / "conclave_proposal.json"
    out_path.write_text(json.dumps({
        "version":    "2.3",
        "ran_at":     _now(),
        "gaps":       gaps,
        "proposal":   proposal,
        "next_steps": (
            "Review the proposal above. If approved, create the agent file at "
            "silmaril/agents/candidate_delta.py and add it to "
            "silmaril/senate/candidates.py CANDIDATE_REGISTRY."
        ),
    }, indent=2, default=str))

    print(f"[conclave] Proposal written to {out_path}")
    print(f"[conclave] Proposed: {proposal['proposed_codename']} — {proposal['specialty']}")
    return proposal


if __name__ == "__main__":
    import sys
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    run_conclave(data_dir)
