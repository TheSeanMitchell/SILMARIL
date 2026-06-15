"""silmaril.portfolios.market_state — Alpha 3.2 adaptive mode classifier.

What it does
────────────
Right now SILMARIL reacts to a schedule. This module gives the rest of
the system a single source of truth about WHAT KIND of moment we're in,
so every downstream module (sizing, sweep aggressiveness, conviction
threshold, news-boost gating) can adapt instead of running a fixed
formula every cycle.

Modes
─────
Exactly one of:
  - "ATTACK"       — strong tailwind regime + low VIX → press the bet
  - "BALANCED"     — neutral / no clear signal (default)
  - "DEFENSIVE"    — elevated VIX or RISK_OFF regime → tighten stops
  - "PRESERVATION" — danger window (Friday eve, overnight) → favor cash/SGOV

The mode is a recommendation; downstream modules use the knobs returned
alongside it. We never let market_state directly change a position —
the close-decision loop reads its hints, applies them, and moves on.

Output (dict — written to docs/data/market_state.json)
──────────────────────────────────────────────────────
{
  "version": "3.2",
  "generated_at": "...",
  "mode":               "ATTACK" | "BALANCED" | "DEFENSIVE" | "PRESERVATION",
  "session":            "regular" | "pre-market" | "after-hours" | "closed",
  "regime":             "RISK_ON" | "RISK_OFF" | "NEUTRAL",
  "vix":                float | None,
  "in_closing_bell":    bool,
  "in_danger_window":   bool,
  "danger_window_label":"" | "friday_evening" | "overnight_thin",
  "knobs": {
    "position_sizing_multiplier":   1.0,
    "trailing_stop_tightness":      1.0,   # multiplier on the trail %
    "sweep_aggression":             1.0,   # >1 = peel sooner / smaller
    "new_opens_allowed":            true,
    "min_conviction_floor":         0.40,
    "news_boost_multiplier":        1.0,   # multiplier on news_boost size
  },
  "rationale": "..."
}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


# ─── Knob defaults per mode ───────────────────────────────────────────

_MODE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "ATTACK": {
        "position_sizing_multiplier": 1.20,   # +20% notional during alignment
        "trailing_stop_tightness":    0.85,   # looser stops, let it run
        "sweep_aggression":           0.80,   # peel later
        "new_opens_allowed":          True,
        "min_conviction_floor":       0.35,   # lower bar
        "news_boost_multiplier":      1.20,
    },
    "BALANCED": {
        "position_sizing_multiplier": 1.00,
        "trailing_stop_tightness":    1.00,
        "sweep_aggression":           1.00,
        "new_opens_allowed":          True,
        "min_conviction_floor":       0.40,
        "news_boost_multiplier":      1.00,
    },
    "DEFENSIVE": {
        "position_sizing_multiplier": 0.70,   # smaller positions
        "trailing_stop_tightness":    1.25,   # tighter stops
        "sweep_aggression":           1.30,   # peel sooner
        "new_opens_allowed":          True,
        "min_conviction_floor":       0.55,   # higher bar
        "news_boost_multiplier":      0.80,
    },
    "PRESERVATION": {
        "position_sizing_multiplier": 0.0,    # no new exposure
        "trailing_stop_tightness":    1.50,
        "sweep_aggression":           1.75,
        "new_opens_allowed":          False,  # close-only mode
        "min_conviction_floor":       0.75,
        "news_boost_multiplier":      0.0,
    },
}


def _safe_float(x, default=None):
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _market_session(now: Optional[datetime] = None) -> str:
    """Wrap sweep_protection's session detector with a defensive import.
    Returns 'regular' | 'pre-market' | 'after-hours' | 'closed'.
    """
    try:
        from .sweep_protection import _market_session_now as _ms
        return _ms(now)
    except Exception:
        n = now or datetime.now(timezone.utc)
        if n.weekday() >= 5:
            return "closed"
        return "regular"  # safe default


def _danger_window(now: Optional[datetime] = None):
    try:
        from .sweep_protection import in_danger_window as _idw, in_closing_bell_window as _cbw
        in_dw, label = _idw(now)
        in_cb = _cbw(now)
        return in_dw, label, in_cb
    except Exception:
        return False, "", False


def classify_market_state(
    *,
    vix: Optional[float] = None,
    regime: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute a market-state dict from current signals.

    `regime` is the existing classify_regime() output ("RISK_ON" / "RISK_OFF"
    / "NEUTRAL"). VIX is an optional float. `now` is for testing; defaults
    to wall clock.
    """
    in_danger, danger_label, in_close = _danger_window(now)
    session = _market_session(now)
    vix_val = _safe_float(vix)
    regime_norm = (regime or "NEUTRAL").upper()

    # Decide mode by priority:
    # 1) Preservation if we're in a danger window OR in the closing-bell
    #    window with extended-hours about to open up gap risk.
    # 2) Defensive on elevated VIX (>= 25) or explicit RISK_OFF.
    # 3) Attack on RISK_ON with low VIX (< 17).
    # 4) Otherwise Balanced.
    rationale_bits = []
    if in_danger:
        mode = "PRESERVATION"
        rationale_bits.append(f"in danger window ({danger_label})")
    elif in_close:
        mode = "PRESERVATION"
        rationale_bits.append("inside closing-bell window")
    elif (vix_val is not None and vix_val >= 25) or regime_norm == "RISK_OFF":
        mode = "DEFENSIVE"
        if vix_val is not None and vix_val >= 25:
            rationale_bits.append(f"VIX elevated {vix_val:.1f}")
        if regime_norm == "RISK_OFF":
            rationale_bits.append("regime RISK_OFF")
    elif regime_norm == "RISK_ON" and (vix_val is None or vix_val < 17):
        mode = "ATTACK"
        rationale_bits.append("regime RISK_ON")
        if vix_val is not None:
            rationale_bits.append(f"VIX low {vix_val:.1f}")
    else:
        mode = "BALANCED"
        rationale_bits.append("no overriding signal")

    knobs = dict(_MODE_DEFAULTS[mode])

    out = {
        "version": "3.2",
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "mode": mode,
        "session": session,
        "regime": regime_norm,
        "vix": vix_val,
        "in_closing_bell": bool(in_close),
        "in_danger_window": bool(in_danger),
        "danger_window_label": danger_label,
        "knobs": knobs,
        "rationale": "; ".join(rationale_bits) if rationale_bits else "",
    }
    return out


def write_market_state(
    data_dir: Path,
    *,
    vix: Optional[float] = None,
    regime: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute + persist to docs/data/market_state.json. Returns the dict."""
    state = classify_market_state(vix=vix, regime=regime, now=now)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "market_state.json").write_text(
            json.dumps(state, indent=2, default=str))
    except Exception as e:
        print(f"[market_state] write failed: {e}")
    return state


def get_knob(state: Dict[str, Any], key: str, default: float = 1.0) -> float:
    """Read a knob with a default. Safe no-op when state is missing."""
    knobs = (state or {}).get("knobs") or {}
    v = knobs.get(key, default)
    try:
        return float(v)
    except Exception:
        return float(default)


__all__ = [
    "classify_market_state",
    "write_market_state",
    "get_knob",
]
