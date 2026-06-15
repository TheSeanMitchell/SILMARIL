"""
silmaril.execution.fill_policy_telemetry — Alpha 6.3 P4.3 observational layer.

OBSERVATIONAL ONLY. Builds the dry-run diff, cohort telemetry, signal-density
audit, flag-only drift/oscillation detectors, and the activation readiness
scorecard. NOTHING here writes order_quality, the executor, risk, scoring, or
allocation. It reads the LIVE `limit_buffer_bps` purely to report a hypothetical
diff; it never mutates it. The readiness scorecard is an audit dashboard, never a
policy input.

Outputs:
  • per case  → case.execution.forensics.fill_policy_shadow.diff
  • cohort    → payload.fill_policy_audit { telemetry, signal_density,
                                            anomalies, readiness }

All numbers are bounded; null/ineligible cases contribute 0 to deltas and never
amplify anything. Cross-epoch cases reseed (no telemetry-continuity leak).
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .fill_policy_governor import MAX_NUDGE_BPS

_HISTORY_LEN = 8           # bounded per-case delta history (oscillation window)
_GROWTH_LEN = 50           # bounded cohort growth series
# readiness thresholds (audit-only; never policy)
_MIN_MEASURABLE = 5
_MIN_PCT_MEASURABLE = 30.0
_MAX_CLAMP_RATE = 0.5
_MAX_RESEED_RATE = 0.5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 1. DRY-RUN DIFF (per case) ──────────────────────────────────────────────
def compute_diff(shadow: Dict[str, Any], live_buffer_bps: float,
                 prior_diff: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Observational diff between live and hypothetical-shadow buffer. NO write."""
    delta = float(shadow.get("would_be_limit_buffer_delta_bps", 0.0) or 0.0)
    live = float(live_buffer_bps)
    reason = shadow.get("ineligible_reason")
    actionable = bool(shadow.get("eligible")) and reason == "none"
    clamp_hit = actionable and (delta >= MAX_NUDGE_BPS - 1e-9)

    # epoch-gated delta history: reset when governor state did not carry
    carried = bool(shadow.get("state_carried"))
    hist = list((prior_diff or {}).get("delta_history") or []) if carried else []
    hist.append(round(delta, 4))
    hist = hist[-_HISTORY_LEN:]

    return {
        "applied": False,                                  # reaffirm invariant
        "live_limit_buffer_bps": round(live, 4),
        "hypothetical_limit_buffer_bps": round(live + delta, 4),  # governor only ADDS
        "delta_bps": round(delta, 4),
        "percent_change": round((delta / live * 100.0) if live > 0 else 0.0, 3),
        "clamp_hit": bool(clamp_hit),
        "warmup": reason == "warmup",
        "eligibility_reason": reason,
        "delta_history": hist,
    }


# ── 4. DRIFT / OSCILLATION DETECTORS (flag-only) ────────────────────────────
def _oscillating(hist: List[float]) -> bool:
    """≥2 direction reversals in the recent delta history."""
    diffs = [b - a for a, b in zip(hist, hist[1:]) if abs(b - a) > 1e-9]
    signs = [1 if d > 0 else -1 for d in diffs]
    reversals = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
    return reversals >= 2


def _clamp_saturated(hist: List[float]) -> bool:
    return len(hist) >= 3 and all(d >= MAX_NUDGE_BPS - 1e-9 for d in hist[-3:])


def detect_anomalies(shadows: List[Dict[str, Any]]) -> Dict[str, Any]:
    osc = clamp_sat = low_sample = stale = warmup_churn = 0
    for s in shadows:
        diff = s.get("diff") or {}
        hist = diff.get("delta_history") or []
        if _oscillating(hist):
            osc += 1
        if _clamp_saturated(hist):
            clamp_sat += 1
        # low-sample instability: actionable nudge on only 2 samples with big delta
        if (s.get("ineligible_reason") == "none"
                and int(s.get("sample_count", 0)) <= 2
                and diff.get("delta_bps", 0.0) >= MAX_NUDGE_BPS * 0.75):
            low_sample += 1
        if s.get("ineligible_reason") == "cross_epoch":
            stale += 1
        if s.get("state_carried") is False and s.get("ineligible_reason") == "warmup":
            warmup_churn += 1
    n = len(shadows) or 1
    return {
        "oscillation_flags": osc,
        "clamp_saturation_flags": clamp_sat,
        "low_sample_instability_flags": low_sample,
        "stale_state_flags": stale,
        "perpetual_warmup_reset_flags": warmup_churn,
        "excessive_reseed": (sum(1 for s in shadows if s.get("state_carried") is False) / n) > _MAX_RESEED_RATE,
        "note": "flag-only; never corrective; never influences governor output",
    }


# ── 2+3. COHORT TELEMETRY + SIGNAL DENSITY + 6. READINESS ───────────────────
def build_audit(open_cases: List[Dict[str, Any]],
                prior_audit: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    shadows = [c["execution"]["forensics"].get("fill_policy_shadow")
               for c in open_cases
               if isinstance(c.get("execution"), dict)
               and isinstance(c["execution"].get("forensics"), dict)]
    shadows = [s for s in shadows if isinstance(s, dict)]
    n = len(shadows)

    def by(reason): return [s for s in shadows if s.get("ineligible_reason") == reason]
    measurable = [s for s in shadows if s.get("eligible") and s.get("ineligible_reason") == "none"]
    warmup, nulls, cross = by("warmup"), by("null"), by("cross_epoch")
    eligible = [s for s in shadows if s.get("eligible")]
    deltas = [float(s.get("would_be_limit_buffer_delta_bps", 0.0) or 0.0) for s in measurable]
    reseeds = [s for s in shadows if s.get("state_carried") is False]
    clamp_hits = [s for s in measurable if (s.get("diff") or {}).get("clamp_hit")]

    telemetry = {
        "open_positions": len(open_cases),
        "eligible_count": len(eligible),
        "measurable_count": len(measurable),
        "warmup_count": len(warmup),
        "null_count": len(nulls),
        "cross_epoch_count": len(cross),
        "avg_delta_bps": round(statistics.mean(deltas), 4) if deltas else 0.0,
        "median_delta_bps": round(statistics.median(deltas), 4) if deltas else 0.0,
        "max_delta_bps": round(max(deltas), 4) if deltas else 0.0,
        "clamp_hit_rate": round(len(clamp_hits) / len(measurable), 4) if measurable else 0.0,
        "state_reseed_rate": round(len(reseeds) / n, 4) if n else 0.0,
    }
    # measurable_fill_growth_over_time (cohort series; bounded; restart-safe)
    series = list((prior_audit or {}).get("telemetry", {}).get("measurable_fill_growth_over_time") or [])
    series.append({"t": _now(), "measurable": len(measurable), "open": len(open_cases)})
    telemetry["measurable_fill_growth_over_time"] = series[-_GROWTH_LEN:]

    # signal density
    opens_n = len(open_cases)
    pct_meas = (len(measurable) / opens_n * 100.0) if opens_n else 0.0
    warm_done = (len(measurable) / (len(measurable) + len(warmup)) * 100.0
                 if (measurable or warmup) else 0.0)
    # same-epoch continuity = eligible same-epoch sample_count of measurable cases
    cont = [int(s.get("sample_count", 0)) for s in measurable]
    signal_density = {
        "pct_open_measurable": round(pct_meas, 3),
        "warmup_completion_rate_pct": round(warm_done, 3),
        "same_epoch_continuity_samples_median": round(statistics.median(cont), 2) if cont else 0,
        "same_epoch_continuity_samples_max": max(cont) if cont else 0,
        "first_measurable_requires_samples": 2,   # W2 warmup
    }

    anomalies = detect_anomalies(shadows)

    # recovery: observed if any measurable case's delta history strictly decreased
    # from a higher value (bad→improving relaxation) within its epoch
    recovery_observed = False
    for s in measurable:
        h = (s.get("diff") or {}).get("delta_history") or []
        if len(h) >= 2 and max(h) > 0 and h[-1] < max(h) - 1e-9:
            recovery_observed = True
            break

    # null-gate clean: every null/ineligible case has delta 0 (HOLD-NEUTRAL)
    null_gate_clean = all(
        float((s.get("diff") or {}).get("delta_bps", 0.0) or 0.0) == 0.0
        for s in shadows if not (s.get("eligible") and s.get("ineligible_reason") == "none")
    )
    # epoch integrity: every cross-epoch case reseeded (state_carried False)
    epoch_integrity_ok = all(s.get("state_carried") is False for s in cross)

    signal_density_ok = (len(measurable) >= _MIN_MEASURABLE and pct_meas >= _MIN_PCT_MEASURABLE)
    oscillation_ok = (anomalies["oscillation_flags"] == 0)
    clamp_behavior_ok = (telemetry["clamp_hit_rate"] <= _MAX_CLAMP_RATE)

    # recovery is a DEMONSTRATED CAPABILITY, sticky since the last reset — not a
    # live-state requirement. A sustained-clean cohort (delta 0) has no current
    # relaxation to show, yet recovery was proven earlier; we must not flicker the
    # readiness off just because things have been calm. Reset on fresh_start.
    _prior_ready = ((prior_audit or {}).get("readiness") or {}) if isinstance(prior_audit, dict) else {}
    _fresh_start = not isinstance(prior_audit, dict)
    recovery_ever_observed = bool(recovery_observed) if _fresh_start else (
        bool(_prior_ready.get("recovery_ever_observed")) or bool(recovery_observed))

    blocking: List[str] = []
    if not signal_density_ok:
        blocking.append(
            f"insufficient_measurable_signal (measurable={len(measurable)}, "
            f"pct={round(pct_meas,1)}%; need >= {_MIN_MEASURABLE} and >= {_MIN_PCT_MEASURABLE}%)")
    if not recovery_ever_observed:
        blocking.append("no_operational_recovery_evidence")
    if not oscillation_ok:
        blocking.append(f"oscillation_detected ({anomalies['oscillation_flags']})")
    if not clamp_behavior_ok:
        blocking.append(f"clamp_saturation (rate={telemetry['clamp_hit_rate']})")
    if not null_gate_clean:
        blocking.append("null_gate_violation")
    if not epoch_integrity_ok:
        blocking.append("epoch_integrity_violation")

    readiness = {
        "signal_density_ok": signal_density_ok,
        "oscillation_ok": oscillation_ok,
        "recovery_ok": recovery_observed,                  # current-cycle snapshot
        "recovery_ever_observed": recovery_ever_observed,  # sticky since reset
        "null_gate_clean": null_gate_clean,
        "clamp_behavior_ok": clamp_behavior_ok,
        "epoch_integrity_ok": epoch_integrity_ok,
        "activation_candidate": (signal_density_ok and oscillation_ok and recovery_ever_observed
                                 and null_gate_clean and clamp_behavior_ok and epoch_integrity_ok),
        "reasons_blocking_activation": blocking,
        "note": "AUDIT DASHBOARD ONLY — never feeds policy/governor/executor/risk",
    }

    # ── B1: plan-based vs directive open origin (INFERRED, labeled) ──
    plan_based = directive = unknown = 0
    for c in open_cases:
        f = (c.get("execution") or {}).get("forensics") or {}
        reasoning = c.get("reasoning") or {}
        ie = reasoning.get("intended_entry")
        basis = f.get("fill_quality_basis")
        match = f.get("intended_entry_epoch_match")
        if ie is not None or match is True:
            plan_based += 1
        elif basis == "held_snapshot_avg_entry" and ie is None:
            directive += 1
        else:
            unknown += 1
    pb_denom = plan_based + directive
    telemetry["open_origin"] = {
        "plan_based_count": plan_based,
        "directive_count": directive,
        "unknown_count": unknown,
        "plan_based_ratio": round(plan_based / pb_denom, 4) if pb_denom else 0.0,
        "inferred": True,   # not executor-tagged provenance; inferred from fields
    }

    # B2/B3: enrich the latest growth point + compute trends (pure)
    if telemetry["measurable_fill_growth_over_time"]:
        last = telemetry["measurable_fill_growth_over_time"][-1]
        last["pct_open_measurable"] = round(pct_meas, 3)
        last["plan_based_ratio"] = telemetry["open_origin"]["plan_based_ratio"]

    def _trend(vals):
        vals = [v for v in vals if v is not None]
        if len(vals) < 3:
            return "insufficient_data"
        half = len(vals) // 2
        early = statistics.mean(vals[:half]) if vals[:half] else 0.0
        late = statistics.mean(vals[half:]) if vals[half:] else 0.0
        if late > early + 1e-9:
            return "up"
        if late < early - 1e-9:
            return "down"
        return "flat"
    series_pts = telemetry["measurable_fill_growth_over_time"]
    trends = {
        "measurable_trend": _trend([p.get("measurable") for p in series_pts]),
        "pct_measurable_trend": _trend([p.get("pct_open_measurable") for p in series_pts]),
    }

    # ── B4: reset-continuity integrity ──
    # The growth series is read-from-prior and only grows; a real reset/wipe shows
    # up as prior_audit being ABSENT (fresh_start) — that is the honest signal. With
    # FIX-1 the case file is protected, so fresh_start should be true only on the
    # first-ever run; if it recurs later, a wipe bypassed protection.
    prior_cont = ((prior_audit or {}).get("continuity") or {}) if isinstance(prior_audit, dict) else {}
    cur_len = len(series_pts)
    cycles_since_reset = 1 if _fresh_start else int(prior_cont.get("cycles_since_reset", 0) or 0) + 1
    continuity = {
        "growth_series_len": cur_len,
        "fresh_start": _fresh_start,            # no prior history this run (first run or wipe)
        "reset_suspected": _fresh_start,        # = fresh_start; honest in-process signal
        "cycles_since_reset": cycles_since_reset,
        "last_continuity_ok": not _fresh_start,
    }

    # ── B5: activation_candidate readiness stability (AUDIT-ONLY) ──
    prior_stab = ((prior_audit or {}).get("readiness_stability") or {}) if isinstance(prior_audit, dict) else {}
    cand = bool(readiness["activation_candidate"])
    streak = (int(prior_stab.get("candidate_true_streak", 0) or 0) + 1) if cand else 0
    cand_hist = list(prior_stab.get("_candidate_history") or [])
    cand_hist.append(1 if cand else 0)
    cand_hist = cand_hist[-20:]
    WINDOW_TARGET, STREAK_REQ = 20, 10
    stable = (streak >= STREAK_REQ and signal_density_ok and recovery_ever_observed)
    readiness_stability = {
        "candidate_true_streak": streak,
        "candidate_true_rate_window": round(sum(cand_hist) / len(cand_hist), 4) if cand_hist else 0.0,
        "window_target_cycles": WINDOW_TARGET,
        "cycles_accumulated": cur_len,
        "observation_progress_pct": round(min(100.0, cur_len / WINDOW_TARGET * 100.0), 1),
        "stable_for_activation_review": stable,   # audit-only; consumed by NOTHING
        "_candidate_history": cand_hist,
    }

    observation_window = {
        "target_cycles": WINDOW_TARGET,
        "cycles_accumulated": cur_len,
        "progress_pct": readiness_stability["observation_progress_pct"],
        "activation_blocked": not cand,
        "blocking_reasons": readiness["reasons_blocking_activation"],
    }

    return {
        "doc": "P4.3/P4.4 observational dry-run audit. applied=false everywhere. "
               "No live influence. Scorecard/telemetry are dashboards, not control "
               "inputs. open_origin is INFERRED (not executor-tagged).",
        "generated_at": _now(),
        "telemetry": telemetry,
        "signal_density": signal_density,
        "trends": trends,
        "continuity": continuity,
        "anomalies": anomalies,
        "readiness": readiness,
        "readiness_stability": readiness_stability,
        "observation_window": observation_window,
    }


__all__ = ["compute_diff", "build_audit", "detect_anomalies"]
