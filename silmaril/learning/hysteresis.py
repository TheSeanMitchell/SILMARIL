"""
silmaril.learning.hysteresis

Hysteresis bands prevent signal flickering on borderline indicator values.
Without hysteresis: RSI=70.1 fires SELL, RSI=69.9 fires BUY, oscillates.
With hysteresis: SELL fires when RSI > 70, doesn't reset until RSI < 65.

Critical for 10-minute cadence — without this, agents would flip-flop
all day on borderline indicators.

Storage: docs/data/hysteresis_state.json (PROTECTED — never reset)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class HysteresisBand:
    enter_threshold: float
    exit_threshold: float

    def __post_init__(self):
        if self.enter_threshold == self.exit_threshold:
            raise ValueError("Hysteresis requires enter != exit thresholds")


def with_hysteresis(
    state_path: Path,
    agent: str,
    ticker: str,
    indicator_name: str,
    indicator_value: float,
    band: HysteresisBand,
    above: bool = True,
) -> bool:
    """
    Returns True if the agent's threshold condition is currently 'on'.
    above=True: condition turns on at enter, off at exit (exit < enter)
    above=False: condition turns on at enter, off at exit (exit > enter)
    """
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except Exception:
            state = {}

    key = f"{agent}::{ticker}::{indicator_name}"
    currently_on = bool(state.get(key, False))

    if above:
        if currently_on:
            new_on = indicator_value > band.exit_threshold
        else:
            new_on = indicator_value > band.enter_threshold
    else:
        if currently_on:
            new_on = indicator_value < band.exit_threshold
        else:
            new_on = indicator_value < band.enter_threshold

    if new_on != currently_on:
        state[key] = new_on
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2))

    return new_on


# Pre-baked common bands
RSI_OVERBOUGHT = HysteresisBand(enter_threshold=70.0, exit_threshold=65.0)
RSI_OVERSOLD = HysteresisBand(enter_threshold=30.0, exit_threshold=35.0)
VIX_PANIC = HysteresisBand(enter_threshold=30.0, exit_threshold=25.0)
VIX_CALM = HysteresisBand(enter_threshold=15.0, exit_threshold=18.0)
