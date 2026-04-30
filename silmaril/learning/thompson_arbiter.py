"""
silmaril.learning.thompson_arbiter — Thompson Sampling for arbiter weighting.

Instead of weighting each agent by their point-estimate win rate,
we sample from each agent's posterior Beta distribution. Agents
with high uncertainty get more variable voice (exploring), agents
with high confidence get stable voice (exploiting).

This is the same algorithm that powers production multi-armed bandit
recommendation systems.
"""
from __future__ import annotations

import random
from typing import Dict

from .bayesian_winrate import AgentBeliefState

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


def _sample_beta(alpha: float, beta: float) -> float:
    if _HAS_NUMPY:
        return float(np.random.beta(alpha, beta))
    return random.betavariate(max(0.001, alpha), max(0.001, beta))


def sample_conviction_multipliers(
    beliefs: Dict[str, AgentBeliefState],
    regime: str,
    floor: float = 0.4,
    ceiling: float = 1.6,
) -> Dict[str, float]:
    """
    For each agent, sample from their Beta posterior for the current regime.
    Map the sample [0, 1] to a multiplier [floor, ceiling] centered at 1.0.
    """
    multipliers = {}
    for agent_name, state in beliefs.items():
        beta_state = state.get(regime)
        sample = _sample_beta(beta_state.alpha, beta_state.beta)
        if sample <= 0.5:
            mult = floor + (1.0 - floor) * (sample / 0.5)
        else:
            mult = 1.0 + (ceiling - 1.0) * ((sample - 0.5) / 0.5)
        multipliers[agent_name] = mult
    return multipliers


def deterministic_multipliers(
    beliefs: Dict[str, AgentBeliefState],
    regime: str,
    floor: float = 0.4,
    ceiling: float = 1.6,
) -> Dict[str, float]:
    """Non-sampling variant for backtests where determinism matters."""
    multipliers = {}
    for agent_name, state in beliefs.items():
        beta_state = state.get(regime)
        mean = beta_state.mean
        if mean <= 0.5:
            mult = floor + (1.0 - floor) * (mean / 0.5)
        else:
            mult = 1.0 + (ceiling - 1.0) * ((mean - 0.5) / 0.5)
        multipliers[agent_name] = mult
    return multipliers
