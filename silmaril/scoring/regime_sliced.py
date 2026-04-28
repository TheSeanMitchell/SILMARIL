"""Regime-sliced performance scoring for SILMARIL v2.

Why this exists
---------------
A single win-rate number across all market conditions hides the truth.
A trend-follower can be brilliant in a strong bull and useless in chop;
a mean-reverter is the opposite. If we score every agent against one
average, we punish specialists.

This module slices the prediction log by regime so the dashboard can
answer questions like:
- "Which agent has the best win rate when VIX > 25?"
- "Who actually picks tops in chop, vs. just lucky in bulls?"
- "Is BARNACLE only useful in bear markets?"

Regime classification
---------------------
We use a lightweight three-state classifier driven by VIX level and
SPY 20-day momentum, the same one the backtest engine uses. That
keeps live and backtest scoring directly comparable.

  BULL : VIX < 20 and SPY 20d momentum > +2%
  BEAR : VIX > 25 or SPY 20d momentum < -3%
  CHOP : everything else

This module does NOT recompute next-day returns; it expects the
prediction log to already carry an `outcome_return` field (filled in
by the live feedback loop after the next session closes).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

# Match SILMARIL_BACKTEST signal sign convention exactly.
SIGNAL_SIGN: dict[str, int] = {
    "STRONG_BUY": 1,
    "BUY": 1,
    "HOLD": 0,
    "ABSTAIN": 0,
    "SELL": -1,
    "STRONG_SELL": -1,
}

# Don't grade trades smaller than this — noise dominates.
PUSH_THRESHOLD = 0.005  # 0.5%

# Minimum number of calls required before we publish a regime stat.
# Smaller samples give absurd win rates that mislead the dashboard.
MIN_CALLS_FOR_RANKING = 10


def classify_live_regime(vix: float | None, spy_mom_20d: float | None) -> str:
    """Classify the current market regime.

    Mirrors silmaril.backtest.replay.classify_regime so live and
    backtest leaderboards line up.
    """
    if vix is None or spy_mom_20d is None:
        return "UNKNOWN"
    if vix < 20 and spy_mom_20d > 0.02:
        return "BULL"
    if vix > 25 or spy_mom_20d < -0.03:
        return "BEAR"
    return "CHOP"


@dataclass
class RegimeStats:
    """Summary for one (agent, regime) cell."""

    agent: str
    regime: str
    n_calls: int
    n_active: int  # excludes HOLD/ABSTAIN
    n_wins: int
    win_rate: float
    expectancy: float
    cum_return: float

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "regime": self.regime,
            "n_calls": self.n_calls,
            "n_active": self.n_active,
            "n_wins": self.n_wins,
            "win_rate": round(self.win_rate, 4),
            "expectancy": round(self.expectancy, 5),
            "cum_return": round(self.cum_return, 4),
        }


def _grade_one(prediction: dict) -> tuple[int, float]:
    """Return (sign, signed_return) for a graded prediction.

    A prediction is graded only if it has a numeric `outcome_return`
    attached AND the signal is directional. HOLD/ABSTAIN return (0, 0).
    """
    sig = prediction.get("signal", "HOLD")
    sign = SIGNAL_SIGN.get(sig, 0)
    if sign == 0:
        return 0, 0.0
    ret = prediction.get("outcome_return")
    if ret is None or not isinstance(ret, (int, float)) or math.isnan(ret):
        return 0, 0.0
    if abs(ret) < PUSH_THRESHOLD:
        # Push: too small to score. Counts as active but not a win/loss.
        return sign, 0.0
    return sign, sign * float(ret)


def slice_by_regime(predictions: Iterable[dict]) -> dict[str, dict[str, RegimeStats]]:
    """Bucket predictions by (agent, regime) and compute stats.

    Input: iterable of prediction dicts with at minimum:
        agent, signal, regime, outcome_return (may be missing/None)

    Output: { agent: { regime: RegimeStats } }
    """
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for p in predictions:
        agent = p.get("agent", "?")
        regime = p.get("regime", "UNKNOWN")
        buckets[(agent, regime)].append(p)

    out: dict[str, dict[str, RegimeStats]] = defaultdict(dict)
    for (agent, regime), preds in buckets.items():
        n_calls = len(preds)
        n_active = 0
        n_wins = 0
        signed_returns: list[float] = []
        for pr in preds:
            sign, signed = _grade_one(pr)
            if sign == 0:
                continue
            n_active += 1
            signed_returns.append(signed)
            if signed > 0:
                n_wins += 1

        win_rate = (n_wins / n_active) if n_active else 0.0
        expectancy = (sum(signed_returns) / n_active) if n_active else 0.0
        cum = 1.0
        for r in signed_returns:
            # 1% sizing per active call — same convention as backtest.
            cum *= 1.0 + 0.01 * r
        cum_return = cum - 1.0

        out[agent][regime] = RegimeStats(
            agent=agent,
            regime=regime,
            n_calls=n_calls,
            n_active=n_active,
            n_wins=n_wins,
            win_rate=win_rate,
            expectancy=expectancy,
            cum_return=cum_return,
        )

    return dict(out)


def rank_agents_by_regime(
    predictions: Iterable[dict],
    regime: str,
    metric: str = "expectancy",
    min_calls: int = MIN_CALLS_FOR_RANKING,
) -> list[RegimeStats]:
    """Return agents ranked best-to-worst within a single regime.

    Filters out agents with too few graded calls in that regime.
    """
    if metric not in {"win_rate", "expectancy", "cum_return"}:
        raise ValueError(f"unknown metric: {metric}")

    sliced = slice_by_regime(predictions)
    rows: list[RegimeStats] = []
    for agent, by_regime in sliced.items():
        stat = by_regime.get(regime)
        if stat is None:
            continue
        if stat.n_active < min_calls:
            continue
        rows.append(stat)

    rows.sort(key=lambda s: getattr(s, metric), reverse=True)
    return rows


def build_regime_leaderboard(
    predictions: Iterable[dict],
    metric: str = "expectancy",
    min_calls: int = MIN_CALLS_FOR_RANKING,
) -> dict:
    """Build a full regime-sliced leaderboard payload for the dashboard.

    Output shape:
    {
      "metric": "expectancy",
      "min_calls": 10,
      "regimes": {
        "BULL":  [ {agent, n_calls, n_active, win_rate, expectancy, cum_return}, ... ],
        "BEAR":  [ ... ],
        "CHOP":  [ ... ],
        "UNKNOWN": [ ... ]
      },
      "specialists": [
        {"agent": "KESTREL+", "best_regime": "CHOP", "edge_vs_avg": 0.0042},
        ...
      ]
    }

    The `specialists` list highlights agents whose performance in their
    best regime is meaningfully better than their average across all
    regimes. That's the actual interesting question.
    """
    preds = list(predictions)
    sliced = slice_by_regime(preds)

    regimes_payload: dict[str, list[dict]] = {}
    for regime in ("BULL", "BEAR", "CHOP", "UNKNOWN"):
        rows = rank_agents_by_regime(preds, regime, metric=metric, min_calls=min_calls)
        regimes_payload[regime] = [r.to_dict() for r in rows]

    # Specialist detection: for each agent, find the regime where they
    # most outperform their own cross-regime average.
    specialists: list[dict] = []
    for agent, by_regime in sliced.items():
        # Need at least 2 regimes with enough calls to compare.
        viable = {r: s for r, s in by_regime.items() if s.n_active >= min_calls}
        if len(viable) < 2:
            continue
        avg_metric = sum(getattr(s, metric) for s in viable.values()) / len(viable)
        best_regime, best_stat = max(
            viable.items(), key=lambda kv: getattr(kv[1], metric)
        )
        edge = getattr(best_stat, metric) - avg_metric
        if edge <= 0:
            continue
        specialists.append(
            {
                "agent": agent,
                "best_regime": best_regime,
                "edge_vs_avg": round(edge, 5),
                "n_active": best_stat.n_active,
            }
        )
    specialists.sort(key=lambda d: d["edge_vs_avg"], reverse=True)

    return {
        "metric": metric,
        "min_calls": min_calls,
        "regimes": regimes_payload,
        "specialists": specialists,
    }


# ---------------------------------------------------------------------------
# Self-check: run me directly to verify the math on synthetic predictions.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    import random

    random.seed(7)
    fake: list[dict] = []
    # TREND: 60% wins in BULL, 40% in CHOP, 35% in BEAR
    win_rates = {
        "TREND": {"BULL": 0.60, "CHOP": 0.40, "BEAR": 0.35},
        "MEANREV": {"BULL": 0.45, "CHOP": 0.58, "BEAR": 0.50},
    }
    for agent, by_regime in win_rates.items():
        for regime, p_win in by_regime.items():
            for _ in range(80):
                signal = "BUY" if random.random() < 0.5 else "SELL"
                # if it 'wins', return is positive in the signal direction
                magnitude = abs(random.gauss(0, 0.015)) + 0.006
                if random.random() < p_win:
                    ret = magnitude if signal == "BUY" else -magnitude
                else:
                    ret = -magnitude if signal == "BUY" else magnitude
                fake.append(
                    {
                        "agent": agent,
                        "signal": signal,
                        "regime": regime,
                        "outcome_return": ret,
                    }
                )

    board = build_regime_leaderboard(fake, metric="win_rate", min_calls=20)
    print(json.dumps(board, indent=2))
