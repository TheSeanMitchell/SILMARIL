"""silmaril.portfolios.dynamic_sizer — Alpha 3.3 / 4.0 adaptive sizing.

What it does
────────────
Replaces the hard `notional = trading_capital * max_position_pct` in
the OPEN branches of alpaca_paper.py with a function that consumes:

  - the plan (conviction, three_month_signal, catalyst_strength)
  - the urgency scorecard
  - the elite-tickers list
  - the urgency-tickers list (Alpha 4.0 — pressure-driven)
  - the market_state knobs (position_sizing_multiplier, etc.)
  - the deployment_pressure score (Alpha 4.0)
  - the per-account base sizing config (max_position_pct, principal)
  - the current concentration snapshot (to scale down if a sector is
    getting heavy)
  - the empirical catalyst-lift from signal_validation (Alpha 4.0)

…and returns ONE final notional plus a structured rationale. Every
sizing decision is auditable.

Sizing formula (all multipliers stack)
──────────────────────────────────────
    base       = trading_capital * max_position_pct
    × conviction_scaler      (0.7 at 0.40 conviction → 1.4 at 0.85)
    × urgency_scaler         (0.85 at 0.0 urgency → 1.30 at 1.0 urgency)
    × market_state_mult      (from market_state.knobs)
    × elite_mult             (ELITE_SIZING_MULTIPLIER if ticker in elite_tickers)
    × deployment_pressure    (Alpha 4.0: 1.0 at 0 pressure → 1.20 at 1.0 pressure)
    × volatility_scaler      (smaller positions on high-ATR names — elite-aware)
    × concentration_scaler   (1.0 if sector is light, 0.5 if sector is heavy)
    × empirical_catalyst_lift (Alpha 4.0: from signal_validation, bounded ±20%)
    × urgency_ticker_boost   (Alpha 4.0: +10% for pressure-tagged urgency_tickers)

Then capped at:
    - elite ceiling 20% of book (or normal 12%, whichever applies)
    - what's actually still deployable after open_positions costs

The function is pure — no I/O, no side effects beyond returning the
result dict (signal_validation lift is read lazily via the data_dir arg,
which itself just reads a small JSON file).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


# Bounds — even a perfect signal can't size beyond these without operator override.
HARD_MIN_NOTIONAL = 1.00
NORMAL_CONCENTRATION_CAP = 0.12   # 12% of book per position by default
ELITE_CONCENTRATION_CAP  = 0.20   # 20% allowed only for elite-tagged tickers

# Alpha 4.0 tunables
DEPLOYMENT_PRESSURE_MAX_BOOST = 0.20   # +20% notional at pressure = 1.0
URGENCY_TICKER_BOOST          = 0.10   # +10% for pressure-tagged urgency tickers
ATTACK_PRESSURE_FLOOR         = 0.70   # base × this in ATTACK + high pressure

# Volatility-scaler tiers (split between normal and elite)
_VOL_TIERS_NORMAL = (
    (0.01, 1.15),
    (0.02, 1.05),
    (0.03, 1.00),
    (0.04, 0.90),
    (0.06, 0.75),
    (1.00, 0.65),
)
# Elite breakouts ARE high-ATR; we still want to size them up.
_VOL_TIERS_ELITE = (
    (0.01, 1.15),
    (0.02, 1.10),
    (0.03, 1.05),
    (0.04, 1.00),   # 4% vol stays at 1.00 for elite (was 0.90 normal)
    (0.06, 0.90),   # 6% vol = 0.90 for elite (was 0.75 normal)
    (1.00, 0.80),
)


def _safe_f(x, default=0.0) -> float:
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _conviction_scaler(conv: float) -> float:
    """0.7× at conv=0.40, 1.0× at conv=0.55, 1.4× at conv=0.85."""
    c = max(0.40, min(0.85, conv))
    return 0.70 + (c - 0.40) * (1.40 - 0.70) / (0.85 - 0.40)


def _urgency_scaler(urgency: float) -> float:
    """0.85× at urgency=0.0, 1.30× at urgency=1.0."""
    u = max(0.0, min(1.0, urgency))
    return 0.85 + u * (1.30 - 0.85)


def _deployment_pressure_scaler(pressure: float) -> float:
    """1.0× at pressure=0, up to (1.0 + MAX_BOOST)× at pressure=1.0."""
    p = max(0.0, min(1.0, pressure))
    return 1.0 + p * DEPLOYMENT_PRESSURE_MAX_BOOST


def _volatility_scaler(
    atr_14: Optional[float], price: Optional[float], is_elite: bool = False,
) -> float:
    """Higher ATR/price → smaller size, but with an elite-aware tier table.

    Alpha 4.0: elite-tagged tickers use a gentler tier so breakouts aren't
    structurally undersized.
    """
    p = _safe_f(price)
    a = _safe_f(atr_14)
    if p <= 0 or a <= 0:
        return 1.0
    pct = a / p
    tiers = _VOL_TIERS_ELITE if is_elite else _VOL_TIERS_NORMAL
    for cutoff, mult in tiers:
        if pct <= cutoff:
            return mult
    return tiers[-1][1]


def _concentration_scaler(sector_pct: float, max_sector_pct: float) -> float:
    """1.0× when the sector is well under cap, falling linearly to 0.3×
    as the sector approaches the policy cap."""
    if max_sector_pct <= 0:
        return 1.0
    headroom = max(0.0, max_sector_pct - sector_pct)
    pct_of_room = headroom / max_sector_pct
    return max(0.30, min(1.0, 0.30 + pct_of_room * 0.70))


def _empirical_catalyst_lift(
    data_dir: Optional[Path],
    plan: Dict[str, Any],
) -> float:
    """Read signal_validation.json (if present) and return a bounded lift
    factor (0.85..1.20) based on the historical expectancy of the matched
    catalyst keyword. Defaults to 1.0 when the file is missing or
    inconclusive.
    """
    if data_dir is None:
        return 1.0
    try:
        from . import signal_validation as sv
        # Use the matched keyword if the three_month filter already tagged one,
        # else fall back to a soft scan of recent_headlines.
        kw = plan.get("catalyst_matched_keyword")
        if kw:
            return sv.get_catalyst_lift(data_dir, kw)
        # Try first recent headline string
        for h in (plan.get("recent_headlines") or [])[:3]:
            text = h if isinstance(h, str) else (
                isinstance(h, dict) and (h.get("title") or h.get("headline")))
            if text:
                lift = sv.get_catalyst_lift(data_dir, text)
                if lift != 1.0:
                    return lift
        return 1.0
    except Exception:
        return 1.0


def size_position(
    *,
    ticker: str,
    plan: Dict[str, Any],
    trading_capital: float,
    base_max_position_pct: float,
    market_state_knobs: Optional[Dict[str, Any]] = None,
    urgency: Optional[Dict[str, Any]] = None,
    elite_tickers: Optional[List[str]] = None,
    urgency_tickers: Optional[List[str]] = None,
    deployment_pressure: float = 0.0,
    market_mode: str = "BALANCED",
    sector_pct: float = 0.0,
    max_sector_pct: float = 0.30,
    atr_14: Optional[float] = None,
    current_price: Optional[float] = None,
    available_cash: Optional[float] = None,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compute the final notional for one plan and return audit detail.

    Returns:
      {
        "notional":             123.45,
        "elite":                False,
        "urgency_priority":     bool,
        "ok":                   True,
        "concentration_cap":    1500.00,
        "components": {
          "base":                 800.00,
          "conviction_scaler":    1.15,
          "urgency_scaler":       1.04,
          "market_state_mult":    1.00,
          "elite_mult":           1.00,
          "deployment_pressure":  1.12,
          "volatility_scaler":    0.90,
          "concentration_scaler": 0.85,
          "catalyst_lift":        1.05,
          "urgency_boost":        1.10,
        },
        "rationale":            "base $800 × conv 1.15 × urg 1.04 × ..."
      }
    """
    knobs = market_state_knobs or {}
    elite_tickers   = elite_tickers or []
    urgency_tickers = urgency_tickers or []
    ticker_u = (ticker or "").upper()

    # Read inputs
    conv = _safe_f(plan.get("consensus_conviction")
                    or plan.get("avg_conviction"))
    urgency_score = (urgency or {}).get("score", 0.0)
    is_elite   = ticker_u in elite_tickers
    is_urgent  = ticker_u in urgency_tickers
    mode       = (market_mode or "BALANCED").upper()
    pressure   = max(0.0, min(1.0, float(deployment_pressure or 0.0)))

    # Multipliers
    mult_conv = _conviction_scaler(conv)
    mult_urg = _urgency_scaler(_safe_f(urgency_score))
    mult_mkt = _safe_f(knobs.get("position_sizing_multiplier"), 1.0)
    mult_eli = 1.0
    try:
        from .elite_mode import ELITE_SIZING_MULTIPLIER as _ESM
    except Exception:
        _ESM = 1.50
    if is_elite:
        mult_eli = float(_ESM)
    mult_pressure = _deployment_pressure_scaler(pressure)
    mult_vol = _volatility_scaler(atr_14, current_price, is_elite=is_elite)
    mult_con = _concentration_scaler(sector_pct, max_sector_pct)
    mult_cat = _empirical_catalyst_lift(data_dir, plan)
    mult_urg_boost = 1.0 + URGENCY_TICKER_BOOST if is_urgent else 1.0

    base = max(0.0, _safe_f(trading_capital) * _safe_f(base_max_position_pct))
    notional = (
        base
        * mult_conv
        * mult_urg
        * mult_mkt
        * mult_eli
        * mult_pressure
        * mult_vol
        * mult_con
        * mult_cat
        * mult_urg_boost
    )

    # Alpha 4.0: floor in ATTACK + high pressure. Prevents over-conservative
    # scalers from killing a perfectly good trade. Never above the cap below.
    floored = False
    if mode == "ATTACK" and pressure >= 0.60:
        floor_notional = base * ATTACK_PRESSURE_FLOOR
        if notional < floor_notional:
            notional = floor_notional
            floored = True

    # Concentration cap
    cap_pct = ELITE_CONCENTRATION_CAP if is_elite else NORMAL_CONCENTRATION_CAP
    cap_dollars = _safe_f(trading_capital) * cap_pct
    capped = False
    if notional > cap_dollars:
        notional = cap_dollars
        capped = True

    # Cash sanity
    if available_cash is not None and notional > float(available_cash):
        notional = max(0.0, float(available_cash))

    notional = round(notional, 2)
    ok = notional >= HARD_MIN_NOTIONAL

    rationale = (
        f"base ${base:.2f} × conv {mult_conv:.2f} × urg {mult_urg:.2f} "
        f"× mkt {mult_mkt:.2f} × elite {mult_eli:.2f} "
        f"× pressure {mult_pressure:.2f} × vol {mult_vol:.2f} "
        f"× concentration {mult_con:.2f} × catalyst {mult_cat:.2f} "
        f"× urgency_boost {mult_urg_boost:.2f} → ${notional:.2f}"
    )
    if floored:
        rationale += " [PRESSURE_FLOOR]"
    if capped:
        rationale += " [CONCENTRATION_CAP]"

    return {
        "ticker":            ticker_u,
        "notional":          notional,
        "elite":             is_elite,
        "urgency_priority":  is_urgent,
        "ok":                ok,
        "concentration_cap": round(cap_dollars, 2),
        "components": {
            "base":                 round(base, 2),
            "conviction_scaler":    round(mult_conv, 4),
            "urgency_scaler":       round(mult_urg, 4),
            "market_state_mult":    round(mult_mkt, 4),
            "elite_mult":           round(mult_eli, 4),
            "deployment_pressure":  round(mult_pressure, 4),
            "volatility_scaler":    round(mult_vol, 4),
            "concentration_scaler": round(mult_con, 4),
            "catalyst_lift":        round(mult_cat, 4),
            "urgency_boost":        round(mult_urg_boost, 4),
        },
        "rationale":         rationale,
    }


__all__ = [
    "HARD_MIN_NOTIONAL",
    "NORMAL_CONCENTRATION_CAP",
    "ELITE_CONCENTRATION_CAP",
    "DEPLOYMENT_PRESSURE_MAX_BOOST",
    "size_position",
]
