"""
silmaril.agents.fee_aware_rotation — Should we rotate or HODL?

Every $1 compounder uses this. Compares the expected edge of rotating
into a new ticker against the round-trip fee cost. Rotates only when
edge meaningfully exceeds friction.

The learning rule:
  expected_edge_pct >= round_trip_fees_pct * MULTIPLIER

  MULTIPLIER varies by archetype:
    - 1.5×  fast traders (CryptoBro, JRR Token)
    - 2.0×  patient traders (SCROOGE, MIDAS)

Edge is approximated from the consensus delta between current holding
and target. A larger consensus_score gap implies more expected return.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..execution.detail import build_execution


# Map consensus signal → expected pct return (rough heuristic)
SIGNAL_EXPECTED_RETURN = {
    "STRONG_BUY":  3.0,
    "BUY":         1.5,
    "HOLD":        0.0,
    "SELL":       -1.5,
    "STRONG_SELL": -3.0,
}


def estimate_edge_pct(consensus_signal: str, consensus_score: float) -> float:
    """Estimate the expected % return from a position based on consensus."""
    base = SIGNAL_EXPECTED_RETURN.get(consensus_signal, 0.0)
    # Consensus score adds nuance. Score is roughly -2 to +2.
    score_lift = consensus_score * 0.6
    return base + score_lift


def estimate_round_trip_fee_pct(
    ticker: str,
    asset_class: str,
    price: float,
    notional: float,
) -> float:
    """
    Round-trip = sell current + buy target. Returns fees as % of notional.
    """
    if notional <= 0:
        return 0.0
    shares = notional / price if price > 0 else 0
    sell_exec = build_execution(
        ticker=ticker, asset_class=asset_class, side="SELL",
        shares=shares, price=price, available_before=0.0,
    )
    buy_exec = build_execution(
        ticker=ticker, asset_class=asset_class, side="BUY",
        shares=shares, price=price, available_before=notional,
    )
    total_fees = sell_exec["fees"]["total"] + buy_exec["fees"]["total"]
    return (total_fees / notional) * 100 if notional > 0 else 0.0


def should_rotate(
    current_consensus_signal: Optional[str],
    current_consensus_score: float,
    target_consensus_signal: str,
    target_consensus_score: float,
    asset_class: str,
    price: float,
    notional: float,
    multiplier: float = 2.0,
) -> Tuple[bool, str]:
    """
    Returns (rotate, explanation).

    Rotate when:
      (target_edge - current_edge) >= round_trip_fee × multiplier

    Always returns (True, "...") when current_consensus is None (we're flat
    and need to deploy capital).
    """
    target_edge = estimate_edge_pct(target_consensus_signal, target_consensus_score)
    fee_pct = estimate_round_trip_fee_pct("PROXY", asset_class, max(1.0, price), notional)

    if current_consensus_signal is None:
        return True, f"Initial entry — no current position. Target edge {target_edge:+.2f}%."

    current_edge = estimate_edge_pct(current_consensus_signal, current_consensus_score)
    edge_gain = target_edge - current_edge
    threshold = fee_pct * multiplier

    if edge_gain >= threshold:
        return (True, (
            f"Rotate: edge gain {edge_gain:+.2f}% ≥ "
            f"{multiplier}× round-trip fees ({fee_pct:.3f}% × {multiplier} = {threshold:.3f}%)."
        ))
    return (False, (
        f"HODL: edge gain {edge_gain:+.2f}% < {threshold:.3f}% (fee threshold). "
        f"Not worth the round-trip cost."
    ))
