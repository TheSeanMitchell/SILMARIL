"""
silmaril.debate.arbiter — Adaptive consensus engine (Alpha 2.0).

Consensus is now a Thompson-sampled, posterior-weighted vote with the
GUARDIAN (formerly AEGIS) veto gated on rolling performance.

Inputs:
  - List of Verdicts from all agents
  - Current regime tag
  - AgentBeliefState dict (loaded from agent_beliefs.json)
  - Recent scoring (rolling 30d win rates)
  - Drift dampeners (agents in performance drift get reduced voice)

Outputs ArbiterResult with:
  - consensus_signal, consensus_conviction
  - agreement_score, dissents
  - guardian_vetoed, multipliers_used
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..learning.bayesian_winrate import AgentBeliefState
from ..learning.thompson_arbiter import (
    sample_conviction_multipliers,
    deterministic_multipliers,
)


SIGNAL_SCORE = {
    "STRONG_BUY":  +2.0,
    "BUY":         +1.0,
    "HOLD":         0.0,
    "ABSTAIN":      0.0,
    "SELL":        -1.0,
    "STRONG_SELL": -2.0,
}

STRONG_BUY_THRESHOLD = +1.20
BUY_THRESHOLD        = +0.40
SELL_THRESHOLD       = -0.40
STRONG_SELL_THRESHOLD = -1.20


@dataclass
class ArbiterResult:
    consensus_signal: str
    consensus_conviction: float
    agreement_score: float
    dissents: List[Dict] = field(default_factory=list)
    guardian_vetoed: bool = False
    guardian_veto_reason: Optional[str] = None
    weighted_score: float = 0.0
    multipliers_used: Dict[str, float] = field(default_factory=dict)
    drift_dampened: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "consensus_signal": self.consensus_signal,
            "consensus_conviction": round(self.consensus_conviction, 4),
            "agreement_score": round(self.agreement_score, 4),
            "dissents": self.dissents,
            "guardian_vetoed": self.guardian_vetoed,
            "guardian_veto_reason": self.guardian_veto_reason,
            "weighted_score": round(self.weighted_score, 4),
            "multipliers_used": {k: round(v, 3) for k, v in self.multipliers_used.items()},
            "drift_dampened": self.drift_dampened,
        }


def _verdict_score(signal: str, conviction: float) -> float:
    return SIGNAL_SCORE.get(signal, 0.0) * max(0.0, min(1.0, conviction))


def adjudicate(
    verdicts: List[Dict],
    *,
    regime: str = "NEUTRAL",
    beliefs: Optional[Dict[str, AgentBeliefState]] = None,
    rolling_winrates: Optional[Dict[str, float]] = None,
    drift_dampeners: Optional[Dict[str, float]] = None,
    deterministic: bool = False,
    guardian_codename: str = "GUARDIAN",
) -> ArbiterResult:
    """
    verdicts: list of dicts with {agent, signal, conviction, rationale}
    regime: current market regime tag
    beliefs: posterior Beta states per agent
    rolling_winrates: {agent_name: rolling_30d_winrate}
    drift_dampeners: {agent_name: multiplier in (0, 1]} for drifting agents
    deterministic: use posterior mean instead of sampling (backtests)
    """
    if not verdicts:
        return ArbiterResult(
            consensus_signal="HOLD",
            consensus_conviction=0.0,
            agreement_score=0.0,
        )

    # 1. Compute conviction multipliers from beliefs
    if beliefs:
        if deterministic:
            multipliers = deterministic_multipliers(beliefs, regime)
        else:
            multipliers = sample_conviction_multipliers(beliefs, regime)
    else:
        multipliers = {v.get("agent", "?"): 1.0 for v in verdicts}

    # 2. Apply drift dampeners
    drift_dampeners = drift_dampeners or {}
    drifted = []
    for agent, dampener in drift_dampeners.items():
        if agent in multipliers and dampener < 1.0:
            multipliers[agent] *= dampener
            drifted.append(agent)

    # 3. Compute weighted consensus score
    weighted_score = 0.0
    total_weight = 0.0
    bullish_count = 0
    bearish_count = 0
    neutral_count = 0
    guardian_verdict = None

    for v in verdicts:
        agent = v.get("agent", "UNKNOWN")
        signal = v.get("signal", "HOLD")
        conviction = float(v.get("conviction", 0.0) or 0.0)

        if signal == "ABSTAIN":
            continue

        mult = multipliers.get(agent, 1.0)
        score = _verdict_score(signal, conviction) * mult
        weighted_score += score
        total_weight += mult * conviction

        s = SIGNAL_SCORE.get(signal, 0.0)
        if s > 0:
            bullish_count += 1
        elif s < 0:
            bearish_count += 1
        else:
            neutral_count += 1

        if agent == guardian_codename:
            guardian_verdict = v

    if total_weight == 0:
        return ArbiterResult(
            consensus_signal="HOLD",
            consensus_conviction=0.0,
            agreement_score=0.0,
            multipliers_used=multipliers,
            drift_dampened=drifted,
        )

    avg_score = weighted_score / total_weight

    # 4. Map score to signal
    if avg_score >= STRONG_BUY_THRESHOLD:
        consensus_signal = "STRONG_BUY"
    elif avg_score >= BUY_THRESHOLD:
        consensus_signal = "BUY"
    elif avg_score <= STRONG_SELL_THRESHOLD:
        consensus_signal = "STRONG_SELL"
    elif avg_score <= SELL_THRESHOLD:
        consensus_signal = "SELL"
    else:
        consensus_signal = "HOLD"

    consensus_conviction = min(1.0, abs(avg_score) / 2.0)

    # 5. Conditional GUARDIAN veto
    guardian_vetoed = False
    guardian_veto_reason = None
    if guardian_verdict is not None:
        guardian_winrate = (rolling_winrates or {}).get(guardian_codename, 0.50)
        guardian_signal = guardian_verdict.get("signal")
        guardian_conviction = float(guardian_verdict.get("conviction", 0.0) or 0.0)

        if (guardian_winrate >= 0.50
                and guardian_conviction >= 0.65
                and guardian_signal in ("SELL", "STRONG_SELL")
                and consensus_signal in ("BUY", "STRONG_BUY")):
            consensus_signal = "HOLD"
            consensus_conviction *= 0.5
            guardian_vetoed = True
            guardian_veto_reason = (
                f"GUARDIAN veto applied (rolling {guardian_winrate:.1%} ≥ 50%, "
                f"conviction {guardian_conviction:.2f})"
            )
        elif (guardian_signal in ("SELL", "STRONG_SELL")
              and consensus_signal in ("BUY", "STRONG_BUY")
              and guardian_winrate < 0.50):
            guardian_veto_reason = (
                f"GUARDIAN dissent noted but veto withheld "
                f"(rolling {guardian_winrate:.1%} < 50% threshold)"
            )

    # 6. Agreement score
    voting_count = bullish_count + bearish_count + neutral_count
    if voting_count == 0:
        agreement_score = 0.0
    else:
        consensus_camp = (
            bullish_count if consensus_signal in ("BUY", "STRONG_BUY")
            else bearish_count if consensus_signal in ("SELL", "STRONG_SELL")
            else neutral_count
        )
        agreement_score = consensus_camp / voting_count

    # 7. Identify dissents
    dissents = []
    consensus_s = SIGNAL_SCORE.get(consensus_signal, 0.0)
    for v in verdicts:
        signal = v.get("signal", "HOLD")
        if signal == "ABSTAIN":
            continue
        s = SIGNAL_SCORE.get(signal, 0.0)
        if (s > 0 and consensus_s <= 0) or \
           (s < 0 and consensus_s >= 0) or \
           (s == 0 and consensus_s != 0):
            dissents.append({
                "agent": v.get("agent"),
                "signal": signal,
                "conviction": v.get("conviction"),
                "rationale": v.get("rationale", ""),
            })

    return ArbiterResult(
        consensus_signal=consensus_signal,
        consensus_conviction=consensus_conviction,
        agreement_score=agreement_score,
        dissents=dissents,
        guardian_vetoed=guardian_vetoed,
        guardian_veto_reason=guardian_veto_reason,
        weighted_score=avg_score,
        multipliers_used=multipliers,
        drift_dampened=drifted,
    )
