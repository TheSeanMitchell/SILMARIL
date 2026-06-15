"""
silmaril.analytics.regime — Market regime classifier.

Classifies today's market into one of three regimes:
  RISK_ON   — trend up + calm volatility
  NEUTRAL   — mixed signals or consolidation
  RISK_OFF  — broken trend + elevated volatility

Inputs are SPY's price relative to its 200-day SMA and the VIX level.
Every agent sees the regime and adjusts accordingly. AEGIS uses it
directly in its veto logic.
"""

from __future__ import annotations

from typing import Optional


def classify_regime(
    spy_price: Optional[float],
    spy_sma_50: Optional[float],
    spy_sma_200: Optional[float],
    vix: Optional[float],
) -> str:
    """Return 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF'."""
    if not spy_price or not spy_sma_200:
        # Insufficient data — default to NEUTRAL
        return "NEUTRAL"

    spy_above_200 = spy_price > spy_sma_200
    spy_above_50 = spy_sma_50 and spy_price > spy_sma_50

    # Without VIX, degrade to trend-only
    if vix is None:
        return "RISK_ON" if (spy_above_200 and spy_above_50) else (
            "RISK_OFF" if not spy_above_200 else "NEUTRAL"
        )

    # RISK_OFF conditions — any one triggers it
    if vix >= 28:
        return "RISK_OFF"
    if not spy_above_200:
        return "RISK_OFF"

    # RISK_ON conditions — all must be true
    if spy_above_200 and spy_above_50 and vix < 18:
        return "RISK_ON"

    return "NEUTRAL"


def spy_trend_label(spy_price: Optional[float], spy_sma_50: Optional[float]) -> str:
    """Return 'UP' | 'DOWN' | 'FLAT'."""
    if not spy_price or not spy_sma_50:
        return "FLAT"
    pct = (spy_price - spy_sma_50) / spy_sma_50
    if pct > 0.02:
        return "UP"
    if pct < -0.02:
        return "DOWN"
    return "FLAT"


# ═══════════════════════════════════════════════════════════════════
# REGIME v2 — multi-axis (ALPHA 1.0, operator directive June 12).
# The v1 single axis pinned RISK_ON through this whole tape: 3,025
# learning rows, one label, zero conditioning power. WHEN an agent works
# is the question, and WHEN needs axes that VARY inside a bull market.
# v1 stays untouched above (AEGIS veto + every existing consumer keeps
# working); v2 ADDS orthogonal axes. All pure functions, all explainable.
# ═══════════════════════════════════════════════════════════════════

def classify_market_regime_v2(spy_price, spy_sma_50, spy_sma_200, vix,
                              spy_ret_1d=None) -> str:
    """RISK_ON / NEUTRAL / SIDEWAYS / RISK_OFF / BEAR / PANIC."""
    # PANIC: volatility event or crash day overrides everything
    if (vix is not None and vix >= 36) or \
       (spy_ret_1d is not None and spy_ret_1d <= -0.03):
        return "PANIC"
    if spy_price and spy_sma_200:
        below_200 = spy_price < spy_sma_200
        dead_cross = bool(spy_sma_50 and spy_sma_200
                          and spy_sma_50 < spy_sma_200)
        if below_200 and dead_cross:
            return "BEAR"
        if below_200 or (vix is not None and vix >= 28):
            return "RISK_OFF"
    elif vix is not None and vix >= 28:
        return "RISK_OFF"
    # SIDEWAYS: hugging the 50d with calm vol — chop, not trend
    if (spy_price and spy_sma_50
            and abs(spy_price / spy_sma_50 - 1.0) < 0.01
            and (vix is None or vix < 20)):
        return "SIDEWAYS"
    if (spy_price and spy_sma_200 and spy_sma_50
            and spy_price > spy_sma_200 and spy_price > spy_sma_50
            and (vix is None or vix < 18)):
        return "RISK_ON"
    return "NEUTRAL"


def classify_volatility_regime(vix, prev_vix=None) -> dict:
    """level: COMPRESSED/CALM/NORMAL/EXPANSION/SPIKE; direction when a
    prior reading exists: EXPANDING/CONTRACTING/STABLE (±5% band)."""
    if vix is None:
        return {"level": "UNKNOWN", "direction": "UNKNOWN"}
    level = ("SPIKE" if vix >= 30 else "EXPANSION" if vix >= 24 else
             "NORMAL" if vix >= 18 else "CALM" if vix >= 14 else
             "COMPRESSED")
    if prev_vix:
        chg = vix / prev_vix - 1.0
        direction = ("EXPANDING" if chg > 0.05 else
                     "CONTRACTING" if chg < -0.05 else "STABLE")
    else:
        direction = "UNKNOWN"
    return {"level": level, "direction": direction}


def classify_breadth_regime(advancers_pct, leaders_share=None) -> str:
    """STRONG >=65% advancers / MIXED 35-65 / WEAK <35; NARROW when a
    thin leadership cohort carries a 'strong' tape (rally on few backs)."""
    if advancers_pct is None:
        return "UNKNOWN"
    if advancers_pct >= 0.65:
        if leaders_share is not None and leaders_share >= 0.5:
            return "NARROW"
        return "STRONG"
    if advancers_pct < 0.35:
        return "WEAK"
    return "MIXED"


def classify_liquidity_regime(vix, breadth_regime) -> dict:
    """HONEST PROXY: true depth/spread data isn't wired yet. Stress shows
    up first as vol expansion + breadth failure together — that combo is
    when fills get worse and exits crowd. AMPLE / TIGHT / CRUNCH."""
    if vix is None:
        return {"level": "UNKNOWN", "proxy": True}
    if vix >= 30 and breadth_regime in ("WEAK", "UNKNOWN"):
        level = "CRUNCH"
    elif vix >= 24:
        level = "TIGHT"
    else:
        level = "AMPLE"
    return {"level": level, "proxy": True,
            "note": "VIX x breadth proxy until real depth/spread data lands"}


def detect_defensive_rotation(sector_returns_1d: dict) -> dict:
    """True when the defense trio (XLP/XLU/XLV) outruns the offense trio
    (XLK/XLY/XLC) on the day by >50bps — the classic risk-off tell that
    fires long before an index breaks its 200d."""
    try:
        def_ = [sector_returns_1d[s] for s in ("XLP", "XLU", "XLV")
                if sector_returns_1d.get(s) is not None]
        off = [sector_returns_1d[s] for s in ("XLK", "XLY", "XLC")
               if sector_returns_1d.get(s) is not None]
        if len(def_) < 2 or len(off) < 2:
            return {"active": None, "spread_bps": None}
        spread = (sum(def_) / len(def_)) - (sum(off) / len(off))
        return {"active": spread > 0.005,
                "spread_bps": round(spread * 10000, 1)}
    except Exception:
        return {"active": None, "spread_bps": None}


def classify_regime_axes(spy_price=None, spy_sma_50=None, spy_sma_200=None,
                         vix=None, prev_vix=None, spy_ret_1d=None,
                         advancers_pct=None, leaders_share=None,
                         sector_returns_1d=None) -> dict:
    """The full v2 read: four axes + rotation flag + composite headline.
    Missing inputs degrade to UNKNOWN per-axis — never a fake label."""
    market = classify_market_regime_v2(spy_price, spy_sma_50, spy_sma_200,
                                       vix, spy_ret_1d)
    vol = classify_volatility_regime(vix, prev_vix)
    breadth = classify_breadth_regime(advancers_pct, leaders_share)
    liq = classify_liquidity_regime(vix, breadth)
    rot = detect_defensive_rotation(sector_returns_1d or {})
    # composite headline: worst-axis-wins for the one-glance read
    if market == "PANIC" or vol["level"] == "SPIKE" or liq["level"] == "CRUNCH":
        composite = "STRESS"
    elif market in ("BEAR", "RISK_OFF") or rot.get("active"):
        composite = "DEFENSIVE"
    elif market == "SIDEWAYS" or breadth in ("MIXED", "NARROW"):
        composite = "CHOP"
    elif market == "RISK_ON" and breadth == "STRONG":
        composite = "FULL_RISK_ON"
    else:
        composite = "CONSTRUCTIVE"
    return {"market_regime": market, "volatility_regime": vol,
            "breadth_regime": breadth, "liquidity_regime": liq,
            "defensive_rotation": rot, "composite": composite,
            "version": "regime-2.0"}
