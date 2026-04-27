"""
silmaril.scoring.regime_tags — Market-condition labels attached to every
decision so we can later answer questions like:

  "Does FORGE only work in trending markets?"
  "Does HEX make money in ranging markets but lose in trends?"
  "Does VEIL fire well only when there's news?"

Without these labels, performance numbers are noise. With them, you can
detect regime-specific edge and downweight agents outside their comfort zone.

Tags applied at decision time (snapshot of the world):
  market_regime:       RISK_ON | NEUTRAL | RISK_OFF        (from VIX + breadth)
  trend_state:         TRENDING | RANGING | UNCLEAR        (from SMA stack + slope)
  vol_state:           HIGH_VOL | NORMAL | LOW_VOL          (from ATR/price ratio)
  news_state:          NEWS_DRIVEN | NORMAL                 (from article_count)
  liquidity_state:     LIQUID | THIN                        (from volume)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def tag_context(ctx_dict: Dict[str, Any]) -> Dict[str, str]:
    """
    Build the regime tag set for a single asset's debate context.
    `ctx_dict` is what you'd see in a debate dict — has price, sma_50,
    sma_200, atr_14, volume, avg_volume_30d, article_count, vix, etc.
    """
    return {
        "market_regime": ctx_dict.get("market_regime", "NEUTRAL"),
        "trend_state":   _trend_state(ctx_dict),
        "vol_state":     _vol_state(ctx_dict),
        "news_state":    _news_state(ctx_dict),
        "liquidity_state": _liquidity_state(ctx_dict),
    }


def _trend_state(d: Dict[str, Any]) -> str:
    price = d.get("price")
    sma20 = d.get("sma_20")
    sma50 = d.get("sma_50")
    sma200 = d.get("sma_200")
    if not price or not sma50 or not sma200:
        return "UNCLEAR"
    above_50 = price > sma50
    above_200 = price > sma200
    stacked_up = (sma20 or sma50) > sma50 > sma200
    stacked_dn = (sma20 or sma50) < sma50 < sma200
    if above_50 and above_200 and stacked_up:
        return "TRENDING"
    if not above_50 and not above_200 and stacked_dn:
        return "TRENDING"  # downtrend is still a trend
    spread = abs(sma50 - sma200) / sma200 if sma200 else 0
    if spread < 0.02:
        return "RANGING"
    return "UNCLEAR"


def _vol_state(d: Dict[str, Any]) -> str:
    atr = d.get("atr_14")
    price = d.get("price")
    vix = d.get("vix")
    if atr and price:
        atr_pct = atr / price
        if atr_pct > 0.04:
            return "HIGH_VOL"
        if atr_pct < 0.01:
            return "LOW_VOL"
    if vix:
        if vix > 25:
            return "HIGH_VOL"
        if vix < 14:
            return "LOW_VOL"
    return "NORMAL"


def _news_state(d: Dict[str, Any]) -> str:
    n = d.get("article_count", 0) or 0
    return "NEWS_DRIVEN" if n >= 8 else "NORMAL"


def _liquidity_state(d: Dict[str, Any]) -> str:
    vol = d.get("volume") or 0
    avg = d.get("avg_volume_30d") or 0
    if not avg:
        return "LIQUID"  # crypto / forex have no avg_volume meaning
    if vol > avg * 1.5:
        return "LIQUID"   # high turnover
    if vol < avg * 0.4:
        return "THIN"
    return "LIQUID"
