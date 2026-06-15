"""
silmaril.risk.control — Alpha 6.3 Phase-2a generic control primitives.

These are pure, domain-agnostic control-system primitives. They import
NOTHING from silmaril and know nothing about scoring, freezes, attribution,
execution, or regime. They are reusable mathematical building blocks only.

Phase-2a contract: this module is UNWIRED. Nothing in the live path calls it
yet. Phase-2b applies ONLY `hysteresis_active` + `dwell_satisfied` to the
existing weight kill-switch exit. The remaining primitives (slew_limit, ewma,
confidence_governor) are implemented and tested in isolation here and are NOT
wired into any live authority flow.

Every primitive is:
  • bounded      — output cannot exceed declared limits
  • reversible    — no internal mutation; deterministic from inputs
  • explainable   — single responsibility, documented contract
  • testable      — pure function of arguments
"""
from __future__ import annotations

from typing import Optional


def hysteresis_active(
    prev_active: bool,
    value: float,
    enter: float,
    exit: float,
) -> bool:
    """Schmitt-trigger / deadband comparator for a 'suppression' state.

    Models a state that ENTERS (becomes active, e.g. frozen) when `value`
    falls below `enter`, and only EXITS (clears) when `value` rises to/above
    `exit`. Requires exit >= enter to form a deadband; if exit == enter this
    degrades to a plain threshold (no hysteresis).

    Pure: returns the new active state given the previous one. Values strictly
    between `enter` and `exit` HOLD the previous state (the deadband).

        not active, value <  enter  -> True   (enter suppression)
        not active, value >= enter  -> False  (stay clear)
        active,     value >= exit   -> False  (exit suppression)
        active,     value <  exit   -> True   (hold suppression)
    """
    if exit < enter:
        raise ValueError(f"exit ({exit}) must be >= enter ({enter}) for a valid deadband")
    if not prev_active:
        return value < enter
    return not (value >= exit)


def dwell_satisfied(cycles_in_state: int, min_dwell: int) -> bool:
    """True once a state has persisted for at least `min_dwell` cycles.

    Prevents single-cycle flicker. Pure.
    """
    return cycles_in_state >= max(0, int(min_dwell))


def slew_limit(prev: float, target: float, max_delta: float) -> float:
    """Limit how far a value may move toward `target` in one step.

    Bounds the per-cycle rate of change to ±max_delta. Pure.
    NOTE (Phase-2a): implemented and tested in isolation only. NOT wired into
    any live authority flow in this phase.
    """
    if max_delta < 0:
        raise ValueError("max_delta must be >= 0")
    delta = target - prev
    if delta > max_delta:
        return prev + max_delta
    if delta < -max_delta:
        return prev - max_delta
    return target


def ewma(prev: Optional[float], x: float, alpha: float) -> float:
    """Exponentially-weighted moving average. alpha in [0,1].

    alpha=1 tracks `x` instantly; alpha→0 is heavily smoothed. With no prior
    value, seeds at `x`. Pure.
    """
    if not (0.0 <= alpha <= 1.0):
        raise ValueError("alpha must be in [0,1]")
    if prev is None:
        return float(x)
    return alpha * float(x) + (1.0 - alpha) * float(prev)


def confidence_governor(
    influence: float,
    confidence: float,
    *,
    floor: float = 0.0,
    ceil: float = 1.0,
    confidence_floor: float = 0.0,
) -> float:
    """Scale an influence by confidence, clamped to [floor, ceil].

    When confidence <= confidence_floor, output decays to 0 (no influence from
    low-evidence signals). Otherwise influence is scaled linearly by confidence
    and clamped. Pure. NOT wired in Phase-2a.
    """
    c = max(0.0, min(1.0, confidence))
    if c <= confidence_floor:
        return 0.0
    scaled = influence * c
    return max(floor, min(ceil, scaled))


__all__ = [
    "hysteresis_active",
    "dwell_satisfied",
    "slew_limit",
    "ewma",
    "confidence_governor",
]
