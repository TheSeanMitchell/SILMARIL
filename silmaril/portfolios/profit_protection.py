"""silmaril.portfolios.profit_protection — Alpha 3.2 profit-at-risk.

What it does
────────────
The recurring loss pattern that triggered Alpha 3.1: a position runs to
~$360 unrealized profit, then gives half back to an after-hours selloff.
sweep_protection.py addresses the symptom (instant peel at $300 / 5%,
overnight shield, danger windows). This module addresses the diagnosis
side: it scores every position on how MUCH PROFIT IS AT RISK and
publishes the result so the dashboard can show a per-position
vulnerability bar and so the sweep escalator can boost aggression on
the most-exposed names.

Components of the profit-at-risk score (0..1, higher = more at risk)
────────────────────────────────────────────────────────────────────
  - unrealized_at_risk_score  — how much $ is actually being protected
  - exhaustion_score          — distance from peak normalized by recent ATR
  - overnight_proximity_score — minutes until next market close / gap risk
  - sentiment_decay_score     — fading article volume / negative drift
  - vol_regime_score          — VIX / Bollinger-band-width contribution

Score combines linearly (weights are tunable). Anything above 0.65 is
flagged as VULNERABLE and the dashboard renders it accordingly.

This module is advisory. It does not place orders. The sweep_protection
sidecar can read its output and decide to be more aggressive on
high-PaR holdings in a future patch.

Output: docs/data/profit_at_risk.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


WEIGHT_UNREALIZED = 0.30
WEIGHT_EXHAUSTION = 0.30
WEIGHT_OVERNIGHT = 0.20
WEIGHT_SENTIMENT = 0.10
WEIGHT_VOL_REGIME = 0.10

VULNERABLE_THRESHOLD = 0.65


def _safe_f(x, default=0.0) -> float:
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _minutes_until_next_close(now: Optional[datetime] = None) -> int:
    """Crude estimate of minutes until 16:00 ET. 0 if outside regular hours."""
    n = now or datetime.now(timezone.utc)
    if n.weekday() >= 5:
        return 0
    # 16:00 ET ≈ 20:00 UTC EDT / 21:00 UTC EST. Use 20:00 as conservative.
    close_today = n.replace(hour=20, minute=0, second=0, microsecond=0)
    if n >= close_today:
        return 0
    return max(0, int((close_today - n).total_seconds() / 60.0))


def _score_unrealized(upl: float, mkt: float) -> float:
    """Higher when there's a real dollar amount of gain to protect."""
    if upl <= 0 or mkt <= 0:
        return 0.0
    # $50 = 0.25, $200 = 0.65, $500 = 0.95
    s = max(0.0, min(1.0, upl / 500.0))
    return round(s, 4)


def _score_exhaustion(current: float, peak: float, atr: Optional[float]) -> float:
    """Higher when current is well below peak relative to recent ATR.

    If we know ATR, we use it. Without ATR we fall back to a flat
    -3%-from-peak ≈ 0.5 scoring."""
    if current <= 0 or peak <= 0:
        return 0.0
    drop_pct = (peak - current) / peak  # positive when below peak
    if drop_pct <= 0:
        return 0.0
    if atr and atr > 0 and peak > 0:
        atr_pct = atr / peak
        # drop in ATR units: 1 ATR = 0.45, 3 ATR = 0.9
        units = drop_pct / atr_pct
        return round(max(0.0, min(1.0, units / 3.5)), 4)
    return round(max(0.0, min(1.0, drop_pct / 0.06)), 4)


def _score_overnight(now: Optional[datetime] = None) -> float:
    """Higher when we're close to a market close / gap-risk window."""
    mins = _minutes_until_next_close(now)
    if mins == 0:
        # After hours or weekend — we're already past close, exposure is max.
        try:
            from .sweep_protection import _market_session_now, in_danger_window
            sess = _market_session_now(now)
            in_dw, _ = in_danger_window(now)
            if in_dw:
                return 1.0
            if sess in ("after-hours", "pre-market", "closed"):
                return 0.85
        except Exception:
            return 0.6
        return 0.5
    # Decay linearly: 6.5 hours pre-close → 0.0; 30 min pre-close → 0.85
    score = max(0.0, 1.0 - (mins / 390.0))
    return round(score, 4)


def _score_sentiment(article_count: int,
                     source_count: int,
                     sentiment: Optional[float]) -> float:
    """Higher when sentiment is fading or going negative."""
    s = 0.0
    if sentiment is not None and sentiment < 0:
        s += min(0.5, abs(sentiment))
    if article_count <= 0 and source_count <= 0:
        s += 0.3   # no eyes on it = uncomfortable to ride
    elif article_count >= 5 and (sentiment or 0) >= 0:
        s -= 0.1   # active positive coverage = comfortable
    return round(max(0.0, min(1.0, s)), 4)


def _score_vol_regime(vix: Optional[float], bb_width: Optional[float]) -> float:
    """Higher when implied + realized vol are elevated."""
    s = 0.0
    if vix is not None:
        # VIX 14 → 0.0, VIX 22 → 0.4, VIX 30 → 0.9
        s += max(0.0, min(1.0, (vix - 14) / 17.0))
    if bb_width is not None:
        # bb_width > 0.10 is wide
        s += max(0.0, min(0.3, (bb_width - 0.05) * 3.0))
    return round(min(1.0, s), 4)


def score_position_par(
    position: Dict[str, Any],
    *,
    ctx: Optional[Dict[str, Any]] = None,
    vix: Optional[float] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Returns the full PaR scorecard for one position.

    `position` is the Alpaca position dict (symbol, qty, current_price,
    avg_entry_price, peak_price, market_value, unrealized_pl, unrealized_plpc).
    `ctx` is optional dict with atr_14, bb_width, sentiment_score,
    article_count, source_count. Missing fields are tolerated.
    """
    ctx = ctx or {}
    sym = (position.get("symbol") or position.get("ticker") or "").upper()
    upl = _safe_f(position.get("unrealized_pl"))
    mkt = _safe_f(position.get("market_value"))
    cur = _safe_f(position.get("current_price"))
    peak = _safe_f(position.get("peak_price") or cur)
    atr = ctx.get("atr_14")
    bb = ctx.get("bb_width")

    s_unreal = _score_unrealized(upl, mkt)
    s_exh = _score_exhaustion(cur, peak, atr)
    s_over = _score_overnight(now)
    s_sent = _score_sentiment(
        int(ctx.get("article_count") or 0),
        int(ctx.get("source_count") or 0),
        ctx.get("sentiment_score"),
    )
    s_vol = _score_vol_regime(vix, bb)

    composite = (
        WEIGHT_UNREALIZED * s_unreal
        + WEIGHT_EXHAUSTION * s_exh
        + WEIGHT_OVERNIGHT * s_over
        + WEIGHT_SENTIMENT * s_sent
        + WEIGHT_VOL_REGIME * s_vol
    )
    composite = round(max(0.0, min(1.0, composite)), 4)
    vulnerable = composite >= VULNERABLE_THRESHOLD

    return {
        "ticker":     sym,
        "score":      composite,
        "vulnerable": vulnerable,
        "components": {
            "unrealized":     s_unreal,
            "exhaustion":     s_exh,
            "overnight":      s_over,
            "sentiment":      s_sent,
            "vol_regime":     s_vol,
        },
        "unrealized_pl":  round(upl, 2),
        "unrealized_plpc": _safe_f(position.get("unrealized_plpc")),
        "current_price":  cur,
        "peak_price":     peak,
    }


def write_profit_at_risk(
    data_dir: Path,
    positions_by_owner: Dict[str, List[Dict[str, Any]]],
    contexts_by_ticker: Optional[Dict[str, Any]] = None,
    vix: Optional[float] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Score every open position across every account, write the JSON,
    return the payload."""
    contexts_by_ticker = contexts_by_ticker or {}
    rows: List[Dict[str, Any]] = []
    for owner, positions in positions_by_owner.items():
        for pos in (positions or []):
            sym = (pos.get("symbol") or pos.get("ticker") or "").upper()
            if not sym:
                continue
            # Skip SGOV vault — protection isn't applicable
            if sym in ("SGOV", "BIL", "SHY", "TFLO", "USFR"):
                continue
            # Build a small ctx dict from the AssetContext if we have one
            c = contexts_by_ticker.get(sym)
            cd: Dict[str, Any] = {}
            if c is not None:
                if hasattr(c, "atr_14"):
                    cd = {
                        "atr_14":         getattr(c, "atr_14", None),
                        "bb_width":       getattr(c, "bb_width", None),
                        "sentiment_score": getattr(c, "sentiment_score", None),
                        "article_count":  getattr(c, "article_count", 0),
                        "source_count":   getattr(c, "source_count", 0),
                    }
                elif isinstance(c, dict):
                    cd = {
                        "atr_14":         c.get("atr_14"),
                        "bb_width":       c.get("bb_width"),
                        "sentiment_score": c.get("sentiment_score"),
                        "article_count":  c.get("article_count", 0),
                        "source_count":   c.get("source_count", 0),
                    }
            row = score_position_par(pos, ctx=cd, vix=vix, now=now)
            row["owner"] = owner
            rows.append(row)
    rows.sort(key=lambda r: r["score"], reverse=True)
    payload = {
        "version": "3.2",
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "positions": rows,
        "vulnerable_count": sum(1 for r in rows if r["vulnerable"]),
        "advisory_only": True,
        "weights": {
            "unrealized": WEIGHT_UNREALIZED,
            "exhaustion": WEIGHT_EXHAUSTION,
            "overnight":  WEIGHT_OVERNIGHT,
            "sentiment":  WEIGHT_SENTIMENT,
            "vol_regime": WEIGHT_VOL_REGIME,
        },
        "threshold": VULNERABLE_THRESHOLD,
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "profit_at_risk.json").write_text(
            json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[profit_at_risk] write failed: {e}")
    return payload


__all__ = [
    "score_position_par",
    "write_profit_at_risk",
]
