"""silmaril.portfolios.preservation_intelligence — Alpha 3.3 / 4.0 smart preservation.

What it does
────────────
Alpha 3.2's preservation mode was time-window only — Friday evening,
overnight thin, closing bell. That misses cases where the calendar
says "regular hours" but the actual risk profile is screaming.

This module produces a per-position vulnerability bump beyond the
generic profit_at_risk score, looking specifically at:

  - earnings_proximity      — earnings reported in < 24 hours
  - macro_event_proximity   — FOMC, CPI, NFP in < 24 hours
  - after_hours_anomaly     — price gap last cycle vs prior close
  - sentiment_deterioration — sentiment dropped > 0.30 in last 24h
  - liquidity_collapse      — current bar volume < 0.40 × 30d avg

Each fires a separate Directive at P1_PRESERVATION for the affected
ticker so the executor force-closes (or refuses to open) regardless of
the market_state mode. The point is: "today, THIS specific position is
unusually dangerous — close it even if everything else looks fine."

Alpha 4.0 contextual coordination
─────────────────────────────────
The 3.3 implementation fired the same `warning`/`critical` severities
regardless of market mode. In an ATTACK regime where breadth is wide
and elite opportunities exist, a `liquidity_collapse` warning fired on
a healthy position is over-preservation — it kills the very setup we
want to deploy on.

Alpha 4.0 changes:
  - `critical` severities (earnings_proximity within 24h) are NEVER
    discounted. Earnings risk is real regardless of regime.
  - `warning` severities (macro, sentiment, liquidity, after_hours_gap)
    are downgraded to `info` in ATTACK mode UNLESS:
      - the position is NOT tagged elite and not high-urgency, AND
      - the ticker has no fresh strong catalyst.
  - `info` severities never trigger force_close (3.3 behaviour preserved).

This is the explicit "rebalance preservation dominance" the mandate asks
for: preservation still fires the same triggers, but they're prioritised
by context instead of recursively suppressing offensive deployment.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple


# Trigger thresholds
EARNINGS_HOURS_WINDOW         = 24       # earnings within 24h → vulnerable
MACRO_HOURS_WINDOW            = 24       # FOMC/CPI/NFP within 24h → vulnerable
SENTIMENT_DETERIORATION_DROP  = 0.30     # sentiment fell ≥ 0.30 in last cycle
LIQUIDITY_COLLAPSE_RATIO      = 0.40     # volume / avg_30d < 0.40
AFTER_HOURS_GAP_PCT           = 0.025    # 2.5% overnight gap = anomaly

# Alpha 4.0: triggers that may be discounted in ATTACK mode (warnings only).
_DISCOUNTABLE_TRIGGERS = {
    "macro_event_proximity",
    "sentiment_deterioration",
    "liquidity_collapse",
    "after_hours_anomaly",
}
# Critical triggers — NEVER discounted regardless of mode.
_NEVER_DISCOUNT_TRIGGERS = {
    "earnings_proximity",
}

_MACRO_EVENT_KEYWORDS = (
    "fomc", "fed decision", "rate decision",
    "cpi", "ppi", "nfp", "non-farm payroll", "nonfarm payrolls",
    "jobless claims", "gdp release", "pce inflation",
)


def _safe_f(x, default=0.0) -> float:
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _check_earnings_proximity(
    ticker: str,
    days_to_earnings: Optional[int],
) -> Optional[Dict[str, Any]]:
    """If earnings are within EARNINGS_HOURS_WINDOW, fire a directive."""
    if days_to_earnings is None:
        return None
    if int(days_to_earnings) <= 1 and int(days_to_earnings) >= 0:
        return {
            "trigger": "earnings_proximity",
            "rationale": (f"{ticker} reports earnings in "
                           f"{int(days_to_earnings)} day(s); historical "
                           f"earnings vol > 2× normal — preserve before print"),
            "severity": "critical",
        }
    return None


def _check_macro_proximity(
    catalysts: Optional[List[Dict[str, Any]]],
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Scan upcoming catalysts for FOMC/CPI/NFP/etc within MACRO_HOURS_WINDOW."""
    if not catalysts:
        return None
    n = now or datetime.now(timezone.utc)
    for item in catalysts:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or item.get("headline") or "").lower()
        when = _parse_iso(item.get("when") or item.get("date") or item.get("ts"))
        if not when:
            continue
        diff_h = (when - n).total_seconds() / 3600.0
        if diff_h < 0 or diff_h > MACRO_HOURS_WINDOW:
            continue
        if any(kw in title for kw in _MACRO_EVENT_KEYWORDS):
            return {
                "trigger": "macro_event_proximity",
                "rationale": (f"Major macro event in {diff_h:.1f}h: "
                               f"{item.get('title') or item.get('headline')}"),
                "severity": "warning",
            }
    return None


def _check_sentiment_deterioration(
    current_sentiment: Optional[float],
    prior_sentiment: Optional[float],
    ticker: str,
) -> Optional[Dict[str, Any]]:
    if current_sentiment is None or prior_sentiment is None:
        return None
    drop = float(prior_sentiment) - float(current_sentiment)
    if drop >= SENTIMENT_DETERIORATION_DROP:
        return {
            "trigger": "sentiment_deterioration",
            "rationale": (f"{ticker} sentiment dropped {drop:+.2f} since "
                           f"prior cycle ({prior_sentiment:.2f} → "
                           f"{current_sentiment:.2f})"),
            "severity": "warning",
        }
    return None


def _check_liquidity_collapse(
    current_volume: Optional[float],
    avg_volume_30d: Optional[float],
    ticker: str,
) -> Optional[Dict[str, Any]]:
    if not current_volume or not avg_volume_30d or avg_volume_30d <= 0:
        return None
    ratio = float(current_volume) / float(avg_volume_30d)
    if ratio < LIQUIDITY_COLLAPSE_RATIO:
        return {
            "trigger": "liquidity_collapse",
            "rationale": (f"{ticker} current volume {current_volume:,.0f} = "
                           f"{ratio*100:.0f}% of 30d avg "
                           f"{avg_volume_30d:,.0f} — thin tape"),
            "severity": "warning",
        }
    return None


def _check_after_hours_anomaly(
    overnight_gap_pct: Optional[float],
    ticker: str,
) -> Optional[Dict[str, Any]]:
    if overnight_gap_pct is None:
        return None
    gap = float(overnight_gap_pct)
    if abs(gap) >= AFTER_HOURS_GAP_PCT:
        direction = "down" if gap < 0 else "up"
        return {
            "trigger": "after_hours_anomaly",
            "rationale": (f"{ticker} gapped {gap*100:+.2f}% overnight "
                           f"({direction}); preserve until session stabilizes"),
            "severity": "warning",
        }
    return None


def _apply_attack_discount(
    triggers: List[Dict[str, Any]],
    ticker: str,
    market_mode: str,
    is_elite: bool,
    is_urgent: bool,
    has_fresh_strong_catalyst: bool,
) -> List[Dict[str, Any]]:
    """Alpha 4.0: in ATTACK mode, downgrade discountable warnings for
    elite/urgent/strong-catalyst names. Pure transformation, no side effects.
    """
    if (market_mode or "BALANCED").upper() != "ATTACK":
        return triggers
    if not (is_elite or is_urgent or has_fresh_strong_catalyst):
        return triggers
    out = []
    for t in triggers:
        if t.get("trigger") in _NEVER_DISCOUNT_TRIGGERS:
            out.append(t)
            continue
        if (t.get("severity") == "warning"
            and t.get("trigger") in _DISCOUNTABLE_TRIGGERS):
            new_t = dict(t)
            new_t["severity"] = "info"
            new_t["rationale"] = (
                f"[ATTACK-DISCOUNTED] {t['rationale']} "
                f"({ticker} elite={is_elite} urgent={is_urgent} "
                f"strong_catalyst={has_fresh_strong_catalyst})")
            out.append(new_t)
        else:
            out.append(t)
    return out


def assess_position_preservation(
    ticker: str,
    position: Dict[str, Any],
    *,
    ctx: Optional[Any] = None,
    catalysts: Optional[List[Dict[str, Any]]] = None,
    prior_sentiment: Optional[float] = None,
    overnight_gap_pct: Optional[float] = None,
    now: Optional[datetime] = None,
    # Alpha 4.0 context (all default to safe no-discount values)
    market_mode: str = "BALANCED",
    is_elite: bool = False,
    is_urgent: bool = False,
    has_fresh_strong_catalyst: bool = False,
) -> Dict[str, Any]:
    """Produce the preservation scorecard for one position.

    Alpha 4.0 args:
      - market_mode: "ATTACK"/"BALANCED"/"DEFENSIVE"/"PRESERVATION"
      - is_elite / is_urgent: tags from policy_router
      - has_fresh_strong_catalyst: True if the ticker has a catalyst
        score ≥ 0.55 from three_month_filter or signal_validation.

    Returns:
      {
        "ticker":            "AAPL",
        "vulnerable":        bool,
        "triggers":          [{"trigger": "earnings_proximity", ...}, ...],
        "max_severity":      "critical" | "warning" | "info" | "none",
        "should_force_close": bool   (True only when max_severity == "critical")
      }
    """
    triggers: List[Dict[str, Any]] = []

    # Pull context fields defensively
    days_to_earn = None
    current_sent = None
    vol = None
    avg_vol = None
    if ctx is not None:
        days_to_earn = (getattr(ctx, "days_to_earnings", None)
                        if not isinstance(ctx, dict)
                        else ctx.get("days_to_earnings"))
        current_sent = (getattr(ctx, "sentiment_score", None)
                        if not isinstance(ctx, dict)
                        else ctx.get("sentiment_score"))
        vol = (getattr(ctx, "volume", None)
                if not isinstance(ctx, dict) else ctx.get("volume"))
        avg_vol = (getattr(ctx, "avg_volume_30d", None)
                    if not isinstance(ctx, dict)
                    else ctx.get("avg_volume_30d"))

    # 1. Earnings (NEVER discounted)
    earn = _check_earnings_proximity(ticker, days_to_earn)
    if earn:
        triggers.append(earn)

    # 2. Macro events
    macro = _check_macro_proximity(catalysts, now)
    if macro:
        triggers.append(macro)

    # 3. Sentiment deterioration
    sent = _check_sentiment_deterioration(current_sent, prior_sentiment, ticker)
    if sent:
        triggers.append(sent)

    # 4. Liquidity collapse
    liq = _check_liquidity_collapse(vol, avg_vol, ticker)
    if liq:
        triggers.append(liq)

    # 5. After-hours anomaly
    ah = _check_after_hours_anomaly(overnight_gap_pct, ticker)
    if ah:
        triggers.append(ah)

    # Alpha 4.0: context-aware discount
    triggers = _apply_attack_discount(
        triggers, ticker, market_mode,
        is_elite=is_elite, is_urgent=is_urgent,
        has_fresh_strong_catalyst=has_fresh_strong_catalyst,
    )

    severity_rank = {"critical": 3, "warning": 2, "info": 1, "none": 0}
    max_sev = "none"
    for t in triggers:
        s = t.get("severity", "info")
        if severity_rank.get(s, 0) > severity_rank.get(max_sev, 0):
            max_sev = s
    # Vulnerable means at least one trigger fired AND severity is ≥ warning
    # (in 3.3 it was "any trigger". This change is intentional: an "info"-
    # only triggers list is not really vulnerable.)
    vulnerable = bool(
        triggers and severity_rank.get(max_sev, 0) >= severity_rank["warning"])
    should_force_close = (max_sev == "critical")

    return {
        "ticker":             (ticker or "").upper(),
        "vulnerable":         vulnerable,
        "triggers":           triggers,
        "max_severity":       max_sev,
        "should_force_close": should_force_close,
    }


def build_preservation_directives(
    positions_by_owner: Dict[str, List[Dict[str, Any]]],
    *,
    contexts_by_ticker: Optional[Dict[str, Any]] = None,
    catalysts: Optional[List[Dict[str, Any]]] = None,
    prior_sentiment_by_ticker: Optional[Dict[str, float]] = None,
    overnight_gap_by_ticker: Optional[Dict[str, float]] = None,
    now: Optional[datetime] = None,
    # Alpha 4.0 inputs
    market_mode: str = "BALANCED",
    urgency_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
    elite_tickers: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Produce a list of preservation directives (ticker + reason + severity).

    Caller converts them into `decision_authority.Directive` rows.

    Alpha 4.0: pass market_mode / urgency_by_ticker / elite_tickers so the
    discount logic can identify which positions deserve the context-aware
    downgrade. Back-compat: omitting these args yields 3.3 behaviour.
    """
    contexts_by_ticker = contexts_by_ticker or {}
    prior_sentiment_by_ticker = prior_sentiment_by_ticker or {}
    overnight_gap_by_ticker = overnight_gap_by_ticker or {}
    urgency_by_ticker = urgency_by_ticker or {}
    elite_tickers = elite_tickers or set()

    out: List[Dict[str, Any]] = []
    for owner, positions in (positions_by_owner or {}).items():
        for pos in (positions or []):
            sym = (pos.get("symbol") or pos.get("ticker") or "").upper()
            if not sym or sym in ("SGOV", "BIL", "SHY", "TFLO", "USFR"):
                continue
            ctx = contexts_by_ticker.get(sym)
            is_elite  = sym in elite_tickers
            urg = urgency_by_ticker.get(sym, {}) or {}
            is_urgent = bool(urg.get("urgent")
                              or urg.get("score", 0.0) >= 0.65)
            # Inspect ctx for a recent strong-catalyst marker.
            has_strong_cat = False
            if ctx is not None:
                cs = (getattr(ctx, "catalyst_strength", None)
                       if not isinstance(ctx, dict)
                       else ctx.get("catalyst_strength"))
                if cs is not None:
                    try:
                        has_strong_cat = float(cs) >= 0.55
                    except Exception:
                        has_strong_cat = False
            scorecard = assess_position_preservation(
                sym, pos, ctx=ctx, catalysts=catalysts,
                prior_sentiment=prior_sentiment_by_ticker.get(sym),
                overnight_gap_pct=overnight_gap_by_ticker.get(sym),
                now=now,
                market_mode=market_mode,
                is_elite=is_elite, is_urgent=is_urgent,
                has_fresh_strong_catalyst=has_strong_cat,
            )
            if scorecard["triggers"]:
                scorecard["owner"] = owner
                out.append(scorecard)
    return out


__all__ = [
    "assess_position_preservation",
    "build_preservation_directives",
]
