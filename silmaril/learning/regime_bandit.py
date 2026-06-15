"""
silmaril.learning.regime_bandit

Contextual bandit per (regime, asset_class, vol_quartile).

Each agent's effectiveness varies across contexts. CORRELATOR might be 58%
in low-vol equities but 47% in high-vol crypto. The system learns WHERE
each agent has edge and only weights them in those contexts.

Storage: docs/data/regime_bandits.json (PROTECTED — never reset)
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Optional

from .bayesian_winrate import BetaState, PRIOR_ALPHA, PRIOR_BETA


def _vol_quartile(realized_vol: Optional[float]) -> str:
    if realized_vol is None:
        return "VQ_UNKNOWN"
    if realized_vol < 0.10:
        return "VQ_LOW"
    if realized_vol < 0.20:
        return "VQ_MID"
    if realized_vol < 0.40:
        return "VQ_HIGH"
    return "VQ_EXTREME"


def context_key(regime: str, asset_class: str, vol: Optional[float]) -> str:
    return f"{regime}|{asset_class}|{_vol_quartile(vol)}"


class RegimeBanditStore:
    def __init__(self, path: Path):
        self.path = path
        self._data: Dict[str, Dict[str, Dict]] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text())
            except Exception:
                self._data = {}

    def get(self, agent: str, ctx_key: str) -> BetaState:
        agent_map = self._data.setdefault(agent, {})
        if ctx_key not in agent_map:
            agent_map[ctx_key] = {"alpha": PRIOR_ALPHA, "beta": PRIOR_BETA, "n": 0}
        d = agent_map[ctx_key]
        return BetaState(alpha=d["alpha"], beta=d["beta"], n=d.get("n", 0))

    def update(self, agent: str, ctx_key: str, won: bool) -> None:
        bs = self.get(agent, ctx_key)
        bs.update(won)
        self._data.setdefault(agent, {})[ctx_key] = asdict(bs)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2))

    def best_contexts(self, agent: str, top_k: int = 3) -> list:
        agent_map = self._data.get(agent, {})
        scored = []
        for ctx, params in agent_map.items():
            if params.get("n", 0) >= 20:
                bs = BetaState(alpha=params["alpha"], beta=params["beta"], n=params["n"])
                scored.append((ctx, bs.mean, bs.n))
        scored.sort(key=lambda r: r[1], reverse=True)
        return scored[:top_k]
