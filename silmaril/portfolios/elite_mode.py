"""silmaril.portfolios.elite_mode — Alpha 3.3 elite opportunity escalation.

What it does
────────────
When consensus is extreme, catalysts are strong, the 3-month trend is
already healthy, urgency is high, AND the macro mode allows it, the
system should treat this as an "elite" setup and ESCALATE — larger
notional, looser stops, faster fill.

This is the operator's "AAA edge" mandate: most plans are average and
should be sized average; the rare plan where everything aligns should
be sized up.

Detection rules
───────────────
A plan qualifies as ELITE when ALL of:
  - consensus_signal == "STRONG_BUY"
  - consensus_conviction ≥ 0.65
  - three_month_signal in ("uptrend",) (not "flat", not "downtrend")
  - catalyst_strength ≥ 0.55  (strong, not soft)
  - urgency_score ≥ 0.65       (recent breakout, fresh catalyst)
  - market_state.mode in ("ATTACK", "BALANCED")  (never in DEFENSIVE/PRESERVATION)
  - backer count ≥ 4           (multi-agent unanimous-ish)

When elite fires, the policy router:
  - applies an ELITE_SIZING_MULTIPLIER (default 1.5×) to the
    `position_sizing_multiplier` knob from market_state
  - raises the per-position concentration cap from 8-12% to up to 20%
  - lowers the min conviction floor for related opens (more aggressive)
  - flags the ticker in `policy.elite_tickers` so the executor logs
    "OPEN ELITE NVDA" instead of "OPEN STRONG_BUY NVDA"

Defensive bounds
────────────────
Elite mode caps:
  - At most TWO elite tickers per cycle per account.
  - Total elite-sized notional ≤ 40% of trading_capital.
  - If portfolio_at_risk vulnerability count > 1, elite is suppressed
    (already exposed; don't double-up).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# Tunables
MIN_CONVICTION   = 0.65
MIN_CATALYST     = 0.55
MIN_URGENCY      = 0.65
MIN_BACKERS      = 4

MAX_ELITE_PER_CYCLE = 2
MAX_ELITE_BOOK_PCT  = 0.40
ELITE_SIZING_MULTIPLIER = 1.50
ELITE_CONCENTRATION_CAP = 0.20


def _safe_f(x, default=0.0) -> float:
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


def plan_qualifies(
    plan: Dict[str, Any],
    *,
    urgency_score: Optional[float] = None,
    market_state_mode: str = "BALANCED",
) -> Dict[str, Any]:
    """Score one plan for elite eligibility. Returns:
      {
        "ticker":    "NVDA",
        "qualifies": bool,
        "score":     0.0..1.0,
        "rationale": "STRONG_BUY conv 0.71, uptrend +12%, strong catalyst, urgency 0.78",
        "blockers":  ["mode DEFENSIVE", ...]   (empty list if qualifies=True)
      }
    """
    ticker = (plan.get("ticker") or "").upper()
    sig = (plan.get("consensus_signal") or "").upper()
    conv = _safe_f(plan.get("consensus_conviction")
                    or plan.get("avg_conviction"))
    cat = _safe_f(plan.get("catalyst_strength"))
    three_m = plan.get("three_month_signal", "unknown")
    backers = plan.get("backers") or []
    urgency = _safe_f(urgency_score)

    blockers: List[str] = []
    if sig != "STRONG_BUY":
        blockers.append(f"signal={sig or 'HOLD'} (need STRONG_BUY)")
    if conv < MIN_CONVICTION:
        blockers.append(f"conviction {conv:.2f} < {MIN_CONVICTION}")
    if three_m != "uptrend":
        blockers.append(f"3m={three_m} (need uptrend)")
    if cat < MIN_CATALYST:
        blockers.append(f"catalyst {cat:.2f} < {MIN_CATALYST}")
    if urgency < MIN_URGENCY:
        blockers.append(f"urgency {urgency:.2f} < {MIN_URGENCY}")
    if len(backers) < MIN_BACKERS:
        blockers.append(f"backers {len(backers)} < {MIN_BACKERS}")
    if market_state_mode in ("DEFENSIVE", "PRESERVATION"):
        blockers.append(f"market_state={market_state_mode}")

    qualifies = not blockers
    # Composite score for ranking among elite candidates
    score = (conv * 0.30 + cat * 0.25 + urgency * 0.25
             + min(1.0, len(backers) / 6.0) * 0.10
             + (1.0 if three_m == "uptrend" else 0.0) * 0.10)
    score = round(max(0.0, min(1.0, score)), 4)

    if qualifies:
        rationale = (
            f"STRONG_BUY conv {conv:.2f}, 3m uptrend, "
            f"catalyst {cat:.2f}, urgency {urgency:.2f}, "
            f"{len(backers)} backers, mode {market_state_mode}"
        )
    else:
        rationale = "; ".join(blockers)

    return {
        "ticker":    ticker,
        "qualifies": qualifies,
        "score":     score,
        "rationale": rationale,
        "blockers":  blockers,
    }


def select_elite_plans(
    plans: List[Dict[str, Any]],
    urgency_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    market_state_mode: str = "BALANCED",
    profit_at_risk_vulnerable_count: int = 0,
    max_elite: int = MAX_ELITE_PER_CYCLE,
) -> Dict[str, Any]:
    """Pick the top elite candidates across all plans.

    Suppresses entirely if vulnerable_count > 1 — we're already exposed.
    Returns:
      {
        "elite_tickers":  ["NVDA", "AMD"],
        "candidates":     [scorecard, ...]  (all qualifying scorecards)
        "rejected":       [scorecard, ...]  (non-qualifying with blockers)
        "suppressed":     bool,
        "suppression_reason": "..."
      }
    """
    urgency_by_ticker = urgency_by_ticker or {}
    suppressed = False
    suppression_reason = ""

    if profit_at_risk_vulnerable_count > 1:
        suppressed = True
        suppression_reason = (
            f"Elite mode suppressed: {profit_at_risk_vulnerable_count} "
            f"open positions already flagged vulnerable; do not double-up."
        )

    if market_state_mode in ("DEFENSIVE", "PRESERVATION"):
        suppressed = True
        suppression_reason = (
            f"Elite mode suppressed: market_state={market_state_mode} "
            f"is not compatible with concentration escalation."
        )

    candidates: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for plan in plans or []:
        ticker = (plan.get("ticker") or "").upper()
        u = urgency_by_ticker.get(ticker, {})
        score_u = u.get("score") if isinstance(u, dict) else None
        result = plan_qualifies(
            plan,
            urgency_score=score_u,
            market_state_mode=market_state_mode,
        )
        if result["qualifies"]:
            candidates.append(result)
        else:
            rejected.append(result)

    if suppressed:
        elite_tickers: List[str] = []
    else:
        candidates.sort(key=lambda c: c["score"], reverse=True)
        elite_tickers = [c["ticker"] for c in candidates[:max_elite]]

    return {
        "elite_tickers":     elite_tickers,
        "candidates":        candidates,
        "rejected":          rejected,
        "suppressed":        suppressed,
        "suppression_reason": suppression_reason,
        "max_per_cycle":     max_elite,
    }


__all__ = [
    "MIN_CONVICTION", "MIN_CATALYST", "MIN_URGENCY", "MIN_BACKERS",
    "MAX_ELITE_PER_CYCLE", "MAX_ELITE_BOOK_PCT",
    "ELITE_SIZING_MULTIPLIER", "ELITE_CONCENTRATION_CAP",
    "plan_qualifies", "select_elite_plans",
]
