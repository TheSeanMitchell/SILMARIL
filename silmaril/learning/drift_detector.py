"""
silmaril.learning.drift_detector

When an agent's win rate suddenly drops vs its rolling baseline, that's
regime change or strategy decay. We flag it for human review and
optionally apply an automatic conviction-dampener until performance recovers.

Detection: CUSUM-style cumulative deviation test.

Storage: docs/data/drift_state.json (PROTECTED)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def detect_drift(
    rolling_30d_winrate: float,
    lifetime_winrate: float,
    n_recent_calls: int,
    threshold_drop: float = 0.07,
    min_calls: int = 30,
) -> Dict:
    """
    Returns drift status dict.
    A 'drift event' fires when rolling_30d drops > threshold_drop below lifetime
    AND we have at least min_calls recent observations to trust the sample.
    """
    if n_recent_calls < min_calls:
        return {"drifting": False, "reason": "insufficient recent calls"}

    delta = lifetime_winrate - rolling_30d_winrate

    if delta > threshold_drop:
        severity = "MILD" if delta < 0.10 else "MODERATE" if delta < 0.15 else "SEVERE"
        return {
            "drifting": True,
            "severity": severity,
            "delta": round(delta, 4),
            "rolling_30d": rolling_30d_winrate,
            "lifetime": lifetime_winrate,
            "n_recent_calls": n_recent_calls,
            "recommended_dampener": (
                0.85 if severity == "MILD" else
                0.70 if severity == "MODERATE" else
                0.50
            ),
        }
    return {"drifting": False, "delta": round(delta, 4)}


def update_drift_state(
    state_path: Path,
    by_agent_drift: Dict[str, Dict],
) -> None:
    state = {"timeline": []}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except Exception:
            pass

    snapshot = {
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "agents": by_agent_drift,
    }
    state.setdefault("timeline", []).append(snapshot)
    state["timeline"] = state["timeline"][-100:]
    state["current"] = by_agent_drift

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))


def get_drift_dampeners(state_path: Path) -> Dict[str, float]:
    """
    Returns {agent: multiplier} for agents currently in drift.
    Multiplier < 1.0 reduces their conviction in the arbiter.
    """
    if not state_path.exists():
        return {}
    try:
        state = json.loads(state_path.read_text())
    except Exception:
        return {}
    current = state.get("current", {})
    return {
        agent: info.get("recommended_dampener", 1.0)
        for agent, info in current.items()
        if info.get("drifting")
    }
