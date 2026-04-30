"""
silmaril.learning.bayesian_winrate

Each agent maintains a Beta(alpha, beta) distribution over its win rate
in each regime bucket. After every scored outcome, alpha or beta increments.

Why Beta? Because win/loss is binary and Beta is the conjugate prior of
a Bernoulli process. The posterior mean alpha / (alpha + beta) IS the
agent's adaptive win rate. The posterior variance gives us uncertainty.

Storage: docs/data/agent_beliefs.json (PROTECTED — never reset)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict


PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0
DECAY_LAMBDA = 0.997  # half-life ~230 observations — stable but adaptive


@dataclass
class BetaState:
    alpha: float = PRIOR_ALPHA
    beta: float = PRIOR_BETA
    n: int = 0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        a, b = self.alpha, self.beta
        return (a * b) / (((a + b) ** 2) * (a + b + 1))

    @property
    def std(self) -> float:
        return self.variance ** 0.5

    def update(self, won: bool) -> None:
        # Apply gentle decay so old data doesn't dominate forever.
        # We decay AROUND the prior, not toward zero, so the posterior
        # always reverts toward the uninformative prior absent evidence.
        self.alpha = (self.alpha - PRIOR_ALPHA) * DECAY_LAMBDA + PRIOR_ALPHA
        self.beta = (self.beta - PRIOR_BETA) * DECAY_LAMBDA + PRIOR_BETA
        if won:
            self.alpha += 1.0
        else:
            self.beta += 1.0
        self.n += 1


@dataclass
class AgentBeliefState:
    """Per-agent map from regime -> BetaState."""
    agent: str
    by_regime: Dict[str, BetaState] = field(default_factory=dict)

    def get(self, regime: str) -> BetaState:
        if regime not in self.by_regime:
            self.by_regime[regime] = BetaState()
        return self.by_regime[regime]

    def overall_mean(self) -> float:
        if not self.by_regime:
            return 0.5
        total_n = sum(s.n for s in self.by_regime.values())
        if total_n == 0:
            return 0.5
        return sum(s.mean * s.n for s in self.by_regime.values()) / total_n


def load_beliefs(path: Path) -> Dict[str, AgentBeliefState]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return {}
    out = {}
    for agent, regimes in raw.items():
        state = AgentBeliefState(agent=agent)
        for regime, params in regimes.items():
            state.by_regime[regime] = BetaState(
                alpha=params.get("alpha", PRIOR_ALPHA),
                beta=params.get("beta", PRIOR_BETA),
                n=params.get("n", 0),
            )
        out[agent] = state
    return out


def save_beliefs(path: Path, beliefs: Dict[str, AgentBeliefState]) -> None:
    out = {
        agent: {
            regime: asdict(state) for regime, state in s.by_regime.items()
        }
        for agent, s in beliefs.items()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2))


def update_beliefs(
    beliefs: Dict[str, AgentBeliefState],
    outcomes: list,
) -> Dict[str, AgentBeliefState]:
    """
    outcomes: list of dicts with keys {agent, regime, won}
    """
    for o in outcomes:
        agent = o.get("agent")
        regime = o.get("regime", "UNKNOWN")
        won = bool(o.get("won", False))
        if not agent:
            continue
        if agent not in beliefs:
            beliefs[agent] = AgentBeliefState(agent=agent)
        beliefs[agent].get(regime).update(won)
    return beliefs
