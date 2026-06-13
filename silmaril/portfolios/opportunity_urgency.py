"""silmaril.portfolios.opportunity_urgency — Alpha 4.0 urgency scoring.

What's new in 4.0
─────────────────
1. Narrative persistence — multi-day repeat-coverage scoring. A catalyst
   that appears across 3 consecutive days from independent sources is
   more durable than a single-day burst. Reads signal_validation.json to
   weight catalyst classes that have historically converted to wins.

2. Catalyst decay — a fresh catalyst that has already moved the stock
   substantially before our entry gets a decay penalty (we're chasing).
   Fresh + un-extended = full credit; fresh + +12% already today = decay
   discount.

3. Tuned URGENT_THRESHOLD — read through parameter_tuning when available.

4. Slope window widened from 5 vs 5 → 10 vs 10 bars for cleaner signal
   on noisy small caps. Drops the W_INTRADAY weight from 0.15 → 0.10 and
   reallocates to a new W_NARRATIVE = 0.10 component.

5. Accepts an optional `data_dir` kwarg so the empirical-lift lookup can
   read signal_validation.json. policy_router calls with data_dir + a
   TypeError fallback for back-compat against 3.3 sidecars.

Anything ≥ tuned URGENT_THRESHOLD is flagged as `urgent`. Urgent + ELITE
plans get preferred allocation and sizing escalation; urgent + advisory
plans get prioritized for the next open slot.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


URGENT_THRESHOLD = 0.65

# Weights — sum to 1.0
W_MOMENTUM_ACCEL = 0.30
W_BREAKOUT       = 0.25
W_FRESH_CATALYST = 0.20
W_INTRADAY       = 0.10   # reduced from 0.15
W_SOURCE_CRED    = 0.05   # reduced from 0.10
W_NARRATIVE      = 0.10   # NEW — persistence + empirical-lift

# Slope windows widened for stability
SLOPE_WINDOW = 10  # was 5

# Catalyst decay: if a fresh catalyst has already moved the name >= this
# pct intraday before our entry, dampen its freshness contribution.
CHASE_INTRADAY_THRESHOLD = 0.08    # 8% in a single bar already extended
CHASE_DECAY_FACTOR       = 0.60    # multiply fresh score by 0.60 when chasing


def _safe_f(x, default: float = 0.0) -> float:
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _tuned(name: str, default: float) -> float:
    try:
        from ..learning.parameter_tuning import get_tuned_value  # type: ignore
        val = get_tuned_value("opportunity_urgency", name, default)
        if isinstance(val, (int, float)) and val == val:
            return float(val)
    except Exception:
        pass
    return float(default)


# ── Component scorers ───────────────────────────────────────────────────────
def _momentum_acceleration_score(closes: Optional[List[float]]) -> float:
    """Compare recent N-bar slope to prior N-bar slope (N = SLOPE_WINDOW)."""
    if not closes or len(closes) < 2 * SLOPE_WINDOW:
        return 0.0
    try:
        recent_window = closes[-SLOPE_WINDOW:]
        prior_window  = closes[-2 * SLOPE_WINDOW:-SLOPE_WINDOW]
        recent = (recent_window[-1] - recent_window[0]) / max(1e-9, recent_window[0])
        prior  = (prior_window[-1]  - prior_window[0])  / max(1e-9, prior_window[0])
    except Exception:
        return 0.0
    # Acceleration = recent - prior. Map 0%→0, +4%→0.5, +10%→1.0
    accel = recent - prior
    return max(0.0, min(1.0, accel / 0.10))


def _breakout_velocity_score(closes: Optional[List[float]],
                              current_price: Optional[float],
                              lookback: int = 20) -> float:
    """How far is current price above the N-bar high?"""
    if not closes or len(closes) < lookback:
        return 0.0
    cp = _safe_f(current_price) or _safe_f(closes[-1])
    if cp <= 0:
        return 0.0
    try:
        prior_high = max(closes[-lookback:-1])  # exclude today
    except ValueError:
        return 0.0
    if prior_high <= 0:
        return 0.0
    above = (cp - prior_high) / prior_high
    if above <= 0:
        return 0.0
    return max(0.0, min(1.0, above / 0.05))


def _fresh_catalyst_score(recent_headlines: Optional[List[Dict[str, Any]]],
                           now: Optional[datetime] = None) -> float:
    """Time-decay over the most recent strong headline."""
    if not recent_headlines:
        return 0.0
    n = now or datetime.now(timezone.utc)
    best_age_hours: Optional[float] = None
    for h in recent_headlines[:8]:
        if not isinstance(h, dict):
            continue
        pub = h.get("published") or h.get("ts") or h.get("published_iso")
        if not pub:
            continue
        try:
            d = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
            age = (n - d).total_seconds() / 3600.0
        except Exception:
            continue
        if age < 0:
            continue
        if best_age_hours is None or age < best_age_hours:
            best_age_hours = age
    if best_age_hours is None:
        return 0.0
    # 0h→1.0, 4h→0.85, 24h→0.5, 48h→0.25, 72h→0
    if best_age_hours <= 4:
        return 1.0 - (best_age_hours / 4.0) * 0.15
    if best_age_hours <= 24:
        return 0.85 - ((best_age_hours - 4) / 20.0) * 0.35
    if best_age_hours <= 72:
        return max(0.0, 0.50 - ((best_age_hours - 24) / 48.0) * 0.50)
    return 0.0


def _intraday_thrust_score(change_pct: Optional[float],
                            atr_14: Optional[float],
                            price: Optional[float]) -> float:
    """Current-bar return measured in ATR units."""
    cp = _safe_f(price)
    chg = _safe_f(change_pct)
    atr = _safe_f(atr_14)
    if cp <= 0 or atr <= 0 or chg <= 0:
        return 0.0
    move_in_atr = (chg * cp) / atr
    return max(0.0, min(1.0, move_in_atr / 1.5))


def _source_credibility_score(article_count: int, source_count: int) -> float:
    s1 = min(1.0, source_count / 5.0) if source_count else 0.0
    s2 = min(1.0, article_count / 10.0) if article_count else 0.0
    return max(s1, s2)


def _narrative_persistence_score(
    recent_headlines: Optional[List[Dict[str, Any]]],
    now: Optional[datetime] = None,
) -> float:
    """How many distinct calendar days in the last 5 days have at least one
    strong headline from a distinct source?

    1 day → 0.20
    2 days → 0.55
    3 days → 0.85
    4+ days → 1.0
    """
    if not recent_headlines:
        return 0.0
    n = now or datetime.now(timezone.utc)
    days_with_news: Dict[str, set] = {}
    for h in recent_headlines[:24]:
        if not isinstance(h, dict):
            continue
        pub = h.get("published") or h.get("ts") or h.get("published_iso")
        src = (h.get("source") or h.get("publisher") or "").lower()
        if not pub:
            continue
        try:
            d = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
            age_days = (n - d).total_seconds() / 86400.0
        except Exception:
            continue
        if age_days < 0 or age_days > 5:
            continue
        day_key = d.strftime("%Y-%m-%d")
        days_with_news.setdefault(day_key, set()).add(src or "_unknown")

    # Count days with at least one source
    days = sum(1 for srcs in days_with_news.values() if len(srcs) >= 1)
    if days <= 0:
        return 0.0
    if days == 1:
        return 0.20
    if days == 2:
        return 0.55
    if days == 3:
        return 0.85
    return 1.0


def _empirical_narrative_lift(
    data_dir: Optional[Path],
    plan_or_ticker: Any,
    catalyst_label: Optional[str],
) -> float:
    """Bounded 0.85..1.20 multiplier on the narrative score, based on the
    historical win-rate of this catalyst class. 1.0 = no info."""
    if data_dir is None:
        return 1.0
    try:
        from . import signal_validation  # type: ignore
        lift = signal_validation.get_catalyst_lift(
            data_dir,
            signal       = None,
            regime       = None,
            catalyst_lab = catalyst_label,
            elite        = False,
        )
        if isinstance(lift, (int, float)) and lift == lift:
            return max(0.85, min(1.20, float(lift)))
    except Exception:
        pass
    return 1.0


def _catalyst_decay_factor(
    fresh_score: float,
    change_pct: Optional[float],
) -> float:
    """If a fresh catalyst has already extended >= CHASE_INTRADAY_THRESHOLD
    intraday, multiply the fresh component by CHASE_DECAY_FACTOR so urgent
    becomes 'urgent but late'. Pure freshness retains full credit."""
    chg = _safe_f(change_pct)
    if fresh_score < 0.5 or chg < CHASE_INTRADAY_THRESHOLD:
        return 1.0
    return CHASE_DECAY_FACTOR


# ── Public API ──────────────────────────────────────────────────────────────
def score_urgency(
    ticker: str,
    *,
    closes: Optional[List[float]] = None,
    current_price: Optional[float] = None,
    change_pct: Optional[float] = None,
    atr_14: Optional[float] = None,
    recent_headlines: Optional[List[Dict[str, Any]]] = None,
    article_count: int = 0,
    source_count: int = 0,
    catalyst_label: Optional[str] = None,
    now: Optional[datetime] = None,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Returns a structured urgency scorecard with all six components."""
    s_mom = _momentum_acceleration_score(closes)
    s_brk = _breakout_velocity_score(closes, current_price)
    s_fre = _fresh_catalyst_score(recent_headlines, now)
    s_int = _intraday_thrust_score(change_pct, atr_14, current_price)
    s_cre = _source_credibility_score(article_count, source_count)

    # Catalyst decay penalty when chasing an already-extended fresh print
    decay = _catalyst_decay_factor(s_fre, change_pct)
    s_fre_adj = s_fre * decay

    # Narrative persistence + empirical lift
    s_nar_raw = _narrative_persistence_score(recent_headlines, now)
    lift = _empirical_narrative_lift(data_dir, ticker, catalyst_label)
    s_nar = max(0.0, min(1.0, s_nar_raw * lift))

    composite = (
        W_MOMENTUM_ACCEL * s_mom
        + W_BREAKOUT       * s_brk
        + W_FRESH_CATALYST * s_fre_adj
        + W_INTRADAY       * s_int
        + W_SOURCE_CRED    * s_cre
        + W_NARRATIVE      * s_nar
    )
    composite = round(max(0.0, min(1.0, composite)), 4)
    urgent_threshold = _tuned("URGENT_THRESHOLD", URGENT_THRESHOLD)
    urgent = composite >= urgent_threshold

    bits = []
    if s_brk >= 0.5:
        bits.append(f"breakout {s_brk:.2f}")
    if s_mom >= 0.5:
        bits.append(f"acceleration {s_mom:.2f}")
    if s_fre_adj >= 0.7:
        bits.append("fresh catalyst")
    elif s_fre >= 0.7 and decay < 1.0:
        bits.append("fresh-but-extended")
    if s_int >= 0.5:
        bits.append(f"intraday thrust {s_int:.2f}")
    if s_cre >= 0.5 and source_count:
        bits.append(f"{source_count} sources")
    if s_nar >= 0.55:
        bits.append(f"narrative persistence {s_nar:.2f}")
    rationale = "; ".join(bits) or "no urgency signals"

    return {
        "ticker":    (ticker or "").upper(),
        "score":     composite,
        "urgent":    urgent,
        "threshold": round(urgent_threshold, 4),
        "components": {
            "momentum_acceleration":  round(s_mom, 4),
            "breakout_velocity":      round(s_brk, 4),
            "fresh_catalyst":         round(s_fre_adj, 4),
            "fresh_catalyst_raw":     round(s_fre, 4),
            "intraday_thrust":        round(s_int, 4),
            "source_credibility":     round(s_cre, 4),
            "narrative_persistence":  round(s_nar, 4),
        },
        "decay_factor":     round(decay, 4),
        "empirical_lift":   round(lift, 4),
        "rationale":        rationale,
    }


def score_plans(
    plans: List[Dict[str, Any]],
    contexts_by_ticker: Dict[str, Any],
    now: Optional[datetime] = None,
    data_dir: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """Score every plan and return a {ticker: scorecard} dict.

    Tolerates AssetContext objects OR plain dicts in contexts_by_ticker.
    `data_dir` is optional; when provided, the narrative-persistence
    component gets an empirical-lift multiplier from signal_validation.json.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for plan in plans:
        ticker = (plan.get("ticker") or "").upper()
        if not ticker:
            continue
        ctx = contexts_by_ticker.get(ticker)
        closes = price = chg = atr = arts = src = headlines = None
        if ctx is not None:
            closes   = getattr(ctx, "price_history", None) or (
                ctx.get("price_history") if isinstance(ctx, dict) else None)
            price    = getattr(ctx, "price", None) or (
                ctx.get("price") if isinstance(ctx, dict) else None)
            chg      = getattr(ctx, "change_pct", None) or (
                ctx.get("change_pct") if isinstance(ctx, dict) else None)
            atr      = getattr(ctx, "atr_14", None) or (
                ctx.get("atr_14") if isinstance(ctx, dict) else None)
            arts     = getattr(ctx, "article_count", 0) or (
                ctx.get("article_count") if isinstance(ctx, dict) else 0)
            src      = getattr(ctx, "source_count", 0) or (
                ctx.get("source_count") if isinstance(ctx, dict) else 0)
            headlines = getattr(ctx, "recent_headlines", None) or (
                ctx.get("recent_headlines") if isinstance(ctx, dict) else None)
        catalyst_label = (plan.get("catalyst_strength_label") or
                           plan.get("catalyst_class") or None)
        sc = score_urgency(
            ticker,
            closes=closes, current_price=price, change_pct=chg,
            atr_14=atr, recent_headlines=headlines,
            article_count=int(arts or 0), source_count=int(src or 0),
            catalyst_label=catalyst_label, now=now, data_dir=data_dir,
        )
        out[ticker] = sc
    return out


__all__ = [
    "URGENT_THRESHOLD",
    "score_urgency",
    "score_plans",
]
