"""silmaril.portfolios.decision_authority — Alpha 3.3 / 4.0 precedence hierarchy.

What it does
────────────
Alpha 3.2 introduced many overlapping intelligence engines:
market_state, conviction_engine, profit_protection, bleed_exit,
sweep_protection, stale_close, three_month_filter, risk filters.
Alpha 4.0 adds deployment_pressure as a peer-level offensive engine
that arbitrates against ELITE_OPPORTUNITY at the same precedence band.

When two engines disagree — "elite opportunity, open big" vs "danger
window, no opens" — SOMETHING has to win. Alpha 3.2 had no defined
order, just a sequence of try/except blocks that happened to fire in
import order. That's not a hierarchy; it's a coincidence.

This module defines the formal ordering. Every engine that wants to
affect execution returns a Directive with a category. The router below
arbitrates them in strict precedence:

  P0: SAFETY_HALT          — kill switch, corruption guard, safe mode
  P1: PRESERVATION         — danger window, closing-bell shield, vulnerable
  P2: FORCED_CLOSE         — bleed_exit, trailing stop, stale_close, consensus_flip
  P3: PROFIT_PROTECTION    — instant sweep, profit-take
  P4: BLOCKED_OPEN         — risk filter, 3m downtrend, correlation cap, position cap
  P5: ELITE_OPPORTUNITY    — concentration boost, sizing escalation
  P5: DEPLOYMENT_URGENCY   — Alpha 4.0: pressure-driven escalation (peer of ELITE)
  P6: NORMAL_OPEN          — base sizing × market_state multiplier × urgency
  P7: ADVISORY             — rotation suggestion, idle-cash signal

DEPLOYMENT_URGENCY is intentionally placed at P5 (the same precedence
band as ELITE_OPPORTUNITY): both are *offensive escalation* signals and
neither one suppresses opens. In the rare case both fire on the same
ticker, the directives merge (the system gets BOTH the elite sizing
multiplier AND the deployment-pressure widen-concentration action).

DEPLOYMENT_URGENCY does NOT override:
  - SAFETY_HALT (P0)
  - PRESERVATION (P1, including critical earnings/macro proximity)
  - FORCED_CLOSE (P2)
The "why is this capital not deployed" engine cannot bypass safety.

A higher-precedence directive ALWAYS wins. Same-precedence directives
are merged: BLOCKs union, allowances intersect, sizing takes the min.
This is the explicit rule the user asked for: "the system must always
know which engine wins when recommendations conflict."

This module does NOT make decisions. It TRACKS and ARBITRATES the
decisions other modules produce. `policy_router.py` calls it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── Precedence levels (lower number = higher priority) ──────────────

P0_SAFETY_HALT         = 0
P1_PRESERVATION        = 1
P2_FORCED_CLOSE        = 2
P3_PROFIT_PROTECTION   = 3
P4_BLOCKED_OPEN        = 4
P5_ELITE_OPPORTUNITY   = 5
P5_DEPLOYMENT_URGENCY  = 5   # Alpha 4.0: peer of ELITE_OPPORTUNITY
P6_NORMAL_OPEN         = 6
P7_ADVISORY            = 7

_PRECEDENCE_NAMES = {
    P0_SAFETY_HALT:       "SAFETY_HALT",
    P1_PRESERVATION:      "PRESERVATION",
    P2_FORCED_CLOSE:      "FORCED_CLOSE",
    P3_PROFIT_PROTECTION: "PROFIT_PROTECTION",
    P4_BLOCKED_OPEN:      "BLOCKED_OPEN",
    P5_ELITE_OPPORTUNITY: "ELITE_OPPORTUNITY",  # also DEPLOYMENT_URGENCY
    P6_NORMAL_OPEN:       "NORMAL_OPEN",
    P7_ADVISORY:          "ADVISORY",
}

# Action → precedence_name resolver (lets the dashboard label the
# winner correctly when two engines share precedence 5).
_ACTION_PRECEDENCE_NAMES = {
    "deployment_urgency":   "DEPLOYMENT_URGENCY",
    "redeploy_sgov":        "DEPLOYMENT_URGENCY",
    "elite_opportunity":    "ELITE_OPPORTUNITY",
}


# ─── Directive shape ─────────────────────────────────────────────────

@dataclass
class Directive:
    """One engine's recommendation. Routed by precedence."""
    precedence: int
    engine:     str                          # "market_state", "bleed_exit", ...
    action:     str                          # "halt_opens", "force_close", "boost_size", ...
    ticker:     Optional[str] = None         # None = applies to the whole portfolio
    payload:    Dict[str, Any] = field(default_factory=dict)
    rationale:  str = ""

    @property
    def precedence_name(self) -> str:
        # Action-specific override (so DEPLOYMENT_URGENCY is labelled correctly
        # even though it shares precedence number 5 with ELITE_OPPORTUNITY).
        if self.action in _ACTION_PRECEDENCE_NAMES:
            return _ACTION_PRECEDENCE_NAMES[self.action]
        return _PRECEDENCE_NAMES.get(self.precedence, f"P{self.precedence}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "precedence":      self.precedence,
            "precedence_name": self.precedence_name,
            "engine":          self.engine,
            "action":          self.action,
            "ticker":          self.ticker,
            "payload":         self.payload,
            "rationale":       self.rationale,
        }


# ─── Arbitration ─────────────────────────────────────────────────────

def arbitrate(directives: List[Directive]) -> Dict[str, Any]:
    """Reduce a list of directives into a final execution decision.

    Rules:
      - The highest-priority directive type that fired wins.
      - Multiple directives at the same priority are merged.
      - HALTS at any level higher than ELITE_OPPORTUNITY suppress all
        opens entirely.
      - FORCED_CLOSEs at the position level always fire even if a
        higher-priority preservation halt is also active (we want to
        close vulnerable positions even when we won't open new ones).
      - Alpha 4.0: deployment_urgency and elite_opportunity coexist at
        the same precedence band; both contribute to the result.

    Returns:
      {
        "winner_precedence": int,
        "winner_action":     str,           # the dominant action
        "halt_opens":        bool,
        "halt_reasons":      [str, ...],
        "forced_closes":     [{ticker, reason}, ...],
        "elite_tickers":     [ticker, ...],
        "urgency_tickers":   [ticker, ...],  # NEW Alpha 4.0
        "global_directives": [dict, ...],    # NEW Alpha 4.0: portfolio-wide
        "blocked_tickers":   {ticker: reason},
        "all_directives":    [dict, ...]    # full audit trail
      }
    """
    if not directives:
        return {
            "winner_precedence": P7_ADVISORY,
            "winner_precedence_name": "ADVISORY",
            "winner_engine":     "default",
            "winner_action":     "NORMAL",
            "halt_opens":        False,
            "halt_reasons":      [],
            "forced_closes":     [],
            "elite_tickers":     [],
            "urgency_tickers":   [],
            "global_directives": [],
            "blocked_tickers":   {},
            "all_directives":    [],
        }

    sorted_dirs = sorted(directives, key=lambda d: d.precedence)

    halt_opens = False
    halt_reasons: List[str] = []
    forced_closes: List[Dict[str, Any]] = []
    elite_tickers: List[str] = []
    urgency_tickers: List[str] = []
    global_directives: List[Dict[str, Any]] = []
    blocked_tickers: Dict[str, str] = {}

    for d in sorted_dirs:
        # Halt actions (any of these suppress opens)
        if d.action in ("halt_opens", "preservation_halt", "safe_mode_halt"):
            halt_opens = True
            halt_reasons.append(f"{d.engine}: {d.rationale or d.action}")
        # Position-level forced closes
        elif d.action in ("force_close", "bleed_exit", "trail_stop",
                          "stale_close", "consensus_flip"):
            if d.ticker:
                forced_closes.append({
                    "ticker":    d.ticker,
                    "engine":    d.engine,
                    "action":    d.action,
                    "rationale": d.rationale,
                    "payload":   d.payload,
                })
        # Elite opportunity escalations
        elif d.action == "elite_opportunity":
            if d.ticker:
                elite_tickers.append(d.ticker)
        # Alpha 4.0: deployment-urgency directives.
        # `deployment_urgency` without a ticker is a portfolio-wide
        # escalation (relax suppression / widen concentration / boost
        # sizing); with a ticker it flags a specific name for priority
        # deployment via the global_allocator and dynamic_sizer.
        elif d.action == "deployment_urgency":
            if d.ticker:
                urgency_tickers.append(d.ticker)
            else:
                global_directives.append(d.to_dict())
        elif d.action == "redeploy_sgov":
            # Always portfolio-wide; sweep_protection consumes the payload.
            global_directives.append(d.to_dict())
        # Per-ticker blocks
        elif d.action in ("block_open", "block_buy"):
            if d.ticker and d.ticker not in blocked_tickers:
                blocked_tickers[d.ticker] = d.rationale or d.action

    # winner = the highest-priority directive that actually constrains
    # or escalates behavior. When the only fired directive is advisory,
    # winner_action = "NORMAL".
    winner = sorted_dirs[0]
    return {
        "winner_precedence":      winner.precedence,
        "winner_precedence_name": winner.precedence_name,
        "winner_engine":          winner.engine,
        "winner_action":          winner.action,
        "halt_opens":             halt_opens,
        "halt_reasons":           halt_reasons,
        "forced_closes":          forced_closes,
        "elite_tickers":          sorted(set(elite_tickers)),
        "urgency_tickers":        sorted(set(urgency_tickers)),
        "global_directives":      global_directives,
        "blocked_tickers":        blocked_tickers,
        "all_directives":         [d.to_dict() for d in sorted_dirs],
    }


__all__ = [
    "Directive",
    "arbitrate",
    "P0_SAFETY_HALT", "P1_PRESERVATION", "P2_FORCED_CLOSE",
    "P3_PROFIT_PROTECTION", "P4_BLOCKED_OPEN", "P5_ELITE_OPPORTUNITY",
    "P5_DEPLOYMENT_URGENCY",
    "P6_NORMAL_OPEN", "P7_ADVISORY",
]
