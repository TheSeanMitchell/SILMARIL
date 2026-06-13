"""
silmaril.execution.fill_policy_governor — Alpha 6.3 P4.2 SHADOW governor.

OBSERVATIONAL ONLY. This computes what a future bounded execution-quality
controller WOULD nudge, and writes it to
`case.execution.forensics.fill_policy_shadow` with `applied=false`. It NEVER
mutates order_quality, the executor, risk, scoring, or allocation, and it never
touches `defer_to_next_cycle` or any freeze/safe-mode authority.

Pipeline (see P4.2 contract):
  S0 eligibility gate (HARD null-gate — short-circuits BEFORE any arithmetic)
  S1 sanitize (finite float in [0,1]; never coerce)
  S2 EWMA smoothing (eligible cycles only; epoch-gated prior)
     └ W2 warmup: first eligible same-epoch sample SEEDS only; no output until 2
  S3 conservative hysteresis deadband on the smoothed-quality "degraded" state
  S4 bounded governor map (worse quality → larger nudge), via confidence_governor
  S5 slew limit (epoch-gated prior nudge)
  S6 clamp to [0, MAX_NUDGE_BPS]; defer_delta ALWAYS 0

LOCKED CONSTANTS (P4.2):
  EWMA_ALPHA = 0.35 · MAX_NUDGE_BPS = 8 · MAX_SLEW_BPS = 4 · WARMUP_SAMPLES = 2
  HYST_ENTER = 0.85 (enter "degraded") · HYST_EXIT = 0.92 (clear "degraded")

PERMANENT AUTHORITY SCOPE (never widened): limit_buffer_bps ONLY; defer always 0;
no freeze/safe-mode/risk interaction EVER.

The governor's ONLY external signal is `fill_quality_confidence` (broker-derived).
Its cross-cycle EWMA/slew/hysteresis values are controller state, NOT a feedback of
its own output into the measured signal (the shadow output never re-enters input).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

from ..risk.control import ewma, slew_limit, hysteresis_active, confidence_governor

VERSION = "P4.2-shadow"
EWMA_ALPHA = 0.35
MAX_NUDGE_BPS = 8.0
MAX_SLEW_BPS = 4.0
WARMUP_SAMPLES = 2
HYST_ENTER = 0.85          # smoothed < 0.85 → enter "degraded"
HYST_EXIT = 0.92           # smoothed ≥ 0.92 → clear "degraded"
DEGRADATION_DEADBAND = 0.02   # below this normalized degradation → no nudge


def _shadow(*, eligible, reason, input_conf, smoothed, governor_output, delta,
            epoch, state_carried, sample_count, degraded) -> Dict[str, Any]:
    return {
        "mode": "shadow",
        "applied": False,                       # INVARIANT
        "eligible": bool(eligible),
        "ineligible_reason": reason,            # null|cross_epoch|no_basis|warmup|none
        "input_confidence": input_conf,         # float|null
        "smoothed_quality": smoothed,           # float|null
        "governor_output": governor_output,     # float|null in [0,1]
        "would_be_limit_buffer_delta_bps": round(float(delta), 4),  # [0,MAX_NUDGE_BPS]
        "would_be_defer": False,                # INVARIANT — never touched
        "clamp_bounds_bps": [0, MAX_NUDGE_BPS],
        "epoch": epoch or "",
        "state_carried": bool(state_carried),
        "sample_count": int(sample_count),      # eligible same-epoch samples
        "degraded": bool(degraded),             # hysteresis memory (epoch-gated)
        "version": VERSION,
    }


def compute_fill_policy_shadow(
    forensics: Dict[str, Any],
    entry_epoch: str,
    prior_shadow: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Pure shadow-governor step. Never raises on normal inputs; never mutates
    anything. Returns the `fill_policy_shadow` block."""
    entry_epoch = str(entry_epoch or "")
    basis = forensics.get("fill_quality_basis")
    epoch_match = forensics.get("intended_entry_epoch_match")
    conf = forensics.get("fill_quality_confidence")

    # ── epoch-gated prior governor state (load ONLY when same epoch) ──
    ps = prior_shadow if isinstance(prior_shadow, dict) else None
    state_carried = bool(ps) and bool(entry_epoch) and (str(ps.get("epoch") or "") == entry_epoch)
    if state_carried:
        prior_smoothed = ps.get("smoothed_quality")
        prior_nudge = ps.get("would_be_limit_buffer_delta_bps", 0.0) or 0.0
        prior_samples = int(ps.get("sample_count", 0) or 0)
        prior_degraded = bool(ps.get("degraded", False))
    else:
        prior_smoothed, prior_nudge, prior_samples, prior_degraded = None, 0.0, 0, False

    # ── S0 HARD null/eligibility gate (BEFORE any arithmetic) ──
    eligible = (basis == "held_snapshot_avg_entry"
                and epoch_match is True
                and conf is not None)
    if not eligible:
        reason = ("null" if conf is None
                  else "cross_epoch" if epoch_match is not True
                  else "no_basis")
        # HOLD-NEUTRAL: governor state is preserved unchanged (no new sample),
        # but only when same-epoch; cross-epoch reseeds to warmup.
        return _shadow(
            eligible=False, reason=reason, input_conf=conf,
            smoothed=(prior_smoothed if state_carried else None),
            governor_output=None, delta=0.0, epoch=entry_epoch,
            state_carried=state_carried,
            sample_count=(prior_samples if state_carried else 0),
            degraded=(prior_degraded if state_carried else False),
        )

    # ── S1 sanitize (eligible ⇒ conf must be a finite float) ──
    if not (isinstance(conf, (int, float)) and math.isfinite(conf)):
        # defensive: treat malformed as ineligible null (never coerce)
        return _shadow(eligible=False, reason="null", input_conf=None,
                       smoothed=(prior_smoothed if state_carried else None),
                       governor_output=None, delta=0.0, epoch=entry_epoch,
                       state_carried=state_carried,
                       sample_count=(prior_samples if state_carried else 0),
                       degraded=(prior_degraded if state_carried else False))
    conf = float(conf)

    # ── S2 EWMA smoothing (eligible only) ──
    smoothed = ewma(prior_smoothed if state_carried else None, conf, EWMA_ALPHA)
    samples = prior_samples + 1

    # ── W2 warmup: seed only, no output until 2 eligible same-epoch samples ──
    if samples < WARMUP_SAMPLES:
        return _shadow(eligible=True, reason="warmup", input_conf=conf,
                       smoothed=round(smoothed, 4), governor_output=None,
                       delta=0.0, epoch=entry_epoch, state_carried=state_carried,
                       sample_count=samples, degraded=False)

    # ── S3 conservative hysteresis deadband on "degraded" state ──
    degraded = hysteresis_active(prior_degraded, smoothed, HYST_ENTER, HYST_EXIT)

    # ── S4 bounded governor map (only nudge while degraded) ──
    if not degraded:
        gov = 0.0
    else:
        # normalized degradation: quality∈[0.5,1] → degradation∈[0,1]
        degradation = max(0.0, min(1.0, (1.0 - smoothed) / 0.5))
        # confidence_governor clamps to [0,1] and zeroes below the deadband
        gov = confidence_governor(1.0, degradation, confidence_floor=DEGRADATION_DEADBAND)

    # ── S5 slew-limit the nudge (bps), epoch-gated prior ──
    target_nudge = gov * MAX_NUDGE_BPS
    nudge = slew_limit(prior_nudge if state_carried else 0.0, target_nudge, MAX_SLEW_BPS)

    # ── S6 clamp ──
    delta = max(0.0, min(MAX_NUDGE_BPS, nudge))

    return _shadow(eligible=True, reason="none", input_conf=conf,
                   smoothed=round(smoothed, 4), governor_output=round(gov, 4),
                   delta=delta, epoch=entry_epoch, state_carried=state_carried,
                   sample_count=samples, degraded=degraded)


__all__ = ["compute_fill_policy_shadow", "VERSION", "MAX_NUDGE_BPS",
           "EWMA_ALPHA", "WARMUP_SAMPLES"]
