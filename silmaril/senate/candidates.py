"""
silmaril.senate.candidates — Candidate agent registry and shadow-mode tagging.

Candidates participate in every debate for scoring purposes but their
verdicts are EXCLUDED from the main consensus calculation. They build
a track record in isolation so the Senate can evaluate them fairly
before granting full voting rights.

Shadow mode means:
  • Verdict recorded with "shadow": True, "role": "CANDIDATE"
  • Excluded from _recompute_consensus_in_place() weighting
  • Scored by outcomes.py exactly like any other verdict
  • Hypothetical Alpaca tag: client_order_id prefix "CAND_<name>_"

The three built-in candidates are:
  ALPHA  — Form 4 insider flow + momentum
  BETA   — FINRA short squeeze + CBOE put/call sentiment
  GAMMA  — FRED macro regime specialist
"""
from __future__ import annotations

from typing import Dict, List, Optional

# Candidate codenames → module paths
CANDIDATE_REGISTRY: Dict[str, str] = {
    "CANDIDATE_ALPHA": "silmaril.agents.candidate_alpha",
    "CANDIDATE_BETA":  "silmaril.agents.candidate_beta",
    "CANDIDATE_GAMMA": "silmaril.agents.candidate_gamma",
}


def load_candidates() -> List:
    """Import and return all registered candidate agent instances."""
    agents = []
    for codename, module_path in CANDIDATE_REGISTRY.items():
        try:
            import importlib
            mod = importlib.import_module(module_path)
            # Each module exposes a module-level agent instance
            attr = codename.lower()   # e.g. "candidate_alpha"
            agent = getattr(mod, attr, None)
            if agent is not None:
                agents.append(agent)
                print(f"[senate] candidate loaded: {codename}")
            else:
                print(f"[senate] WARNING: {module_path} has no '{attr}' instance")
        except Exception as e:
            print(f"[senate] candidate {codename} failed to load: {e}")
    return agents


def tag_shadow_verdicts(debate_dicts: List[Dict]) -> None:
    """
    For every verdict from a candidate agent, add shadow=True and role=CANDIDATE.
    Mutates debate_dicts in place. Call AFTER debate runs, BEFORE consensus computation.
    """
    candidate_names = set(CANDIDATE_REGISTRY.keys())
    for debate in debate_dicts:
        for verdict in debate.get("verdicts", []):
            if verdict.get("agent") in candidate_names:
                verdict["shadow"]  = True
                verdict["role"]    = "CANDIDATE"


def filter_shadow_verdicts_for_consensus(verdicts: List[Dict]) -> List[Dict]:
    """Return only non-shadow verdicts. Used inside consensus recomputation."""
    return [v for v in verdicts if not v.get("shadow", False)]


def extract_candidate_summary(debate_dicts: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Pull out candidate verdicts from all debates for separate display.
    Returns {candidate_codename: [verdict_with_ticker, ...]}
    """
    candidate_names = set(CANDIDATE_REGISTRY.keys())
    summary: Dict[str, List[Dict]] = {name: [] for name in candidate_names}
    for debate in debate_dicts:
        ticker = debate.get("ticker", "")
        for verdict in debate.get("verdicts", []):
            if verdict.get("agent") in candidate_names:
                summary[verdict["agent"]].append({
                    "ticker":     ticker,
                    "signal":     verdict.get("signal"),
                    "conviction": verdict.get("conviction"),
                    "rationale":  verdict.get("rationale", ""),
                })
    return summary
