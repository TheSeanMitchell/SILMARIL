"""
silmaril.backtest.metrics

The truth-telling layer. Once a backtest produces a list of predictions, this
module turns them into honest performance numbers:

  - per-agent win rate (and sample size, the part most retail tools hide)
  - per-agent expectancy (average next-day return signed by signal direction)
  - per-agent Sharpe-ish ratio (mean / stdev of signed returns)
  - per-agent max drawdown of a hypothetical $1-per-signal strategy
  - REGIME-SLICED win rates (BULL / BEAR / CHOP) — this is the killer feature
  - asset-class slices (equity / crypto / token / fx / commodities / energy)

All metrics ignore HOLD and ABSTAIN — those don't take a position. STRONG_BUY
and BUY are scored as long; STRONG_SELL and SELL as short.

Why Sharpe-ish: a real Sharpe needs a multi-day return series. Next-day-only
underestimates compound performance and ignores transaction cost. Our number
is a relative agent-vs-agent ranking, not a backtested portfolio Sharpe. We
note this in the report.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, is_dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _as_dict(p: Any) -> Dict[str, Any]:
    """Normalize a prediction (dict or dataclass) to a dict.

    Defensive helper. Some callers pass Prediction dataclass instances,
    others pass already-converted dicts. Both must work.
    """
    if isinstance(p, dict):
        return p
    if is_dataclass(p):
        return asdict(p)
    if hasattr(p, "to_dict"):
        return p.to_dict()
    # last resort: dict() of the object's attributes
    return dict(getattr(p, "__dict__", {}))


# Signal sign: +1 long, -1 short, 0 no-position
SIGNAL_SIGN: Dict[str, int] = {
    "STRONG_BUY": +1,
    "BUY": +1,
    "STRONG_SELL": -1,
    "SELL": -1,
    "HOLD": 0,
    "ABSTAIN": 0,
}


@dataclass
class AgentScore:
    agent: str
    n_predictions: int = 0
    n_active: int = 0          # excludes HOLD/ABSTAIN
    wins: int = 0
    losses: int = 0
    pushes: int = 0            # active but |return| < 0.5%
    win_rate: float = 0.0      # wins / (wins + losses)
    expectancy: float = 0.0    # mean signed return on active predictions
    stdev: float = 0.0
    sharpe_ish: float = 0.0    # expectancy / stdev * sqrt(252)
    max_drawdown: float = 0.0
    final_equity: float = 1.0  # equity curve from $1 with +/- expectancy per signal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "n_predictions": self.n_predictions,
            "n_active": self.n_active,
            "wins": self.wins,
            "losses": self.losses,
            "pushes": self.pushes,
            "win_rate": round(self.win_rate, 4),
            "expectancy_pct": round(self.expectancy * 100, 4),
            "stdev_pct": round(self.stdev * 100, 4),
            "sharpe_ish": round(self.sharpe_ish, 3),
            "max_drawdown_pct": round(self.max_drawdown * 100, 3),
            "final_equity_from_1": round(self.final_equity, 4),
        }


def _signed_returns(predictions: Iterable[Any]) -> List[float]:
    """Convert active predictions into signed return series (long: +ret, short: -ret)."""
    out: List[float] = []
    for raw in predictions:
        p = _as_dict(raw)
        sig = p.get("signal", "ABSTAIN")
        sign = SIGNAL_SIGN.get(sig, 0)
        if sign == 0:
            continue
        ndr = p.get("next_day_return")
        if ndr is None:
            continue
        out.append(sign * float(ndr))
    return out


def _stdev(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)


def _max_drawdown(equity_curve: List[float]) -> float:
    """Returns max drawdown as a positive fraction (0.15 = 15% drawdown)."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for e in equity_curve:
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def score_agent(
    agent_name: str,
    predictions: List[Any],
    *,
    push_threshold: float = 0.005,
) -> AgentScore:
    score = AgentScore(agent=agent_name, n_predictions=len(predictions))
    active = []
    for raw in predictions:
        p = _as_dict(raw)
        sig = p.get("signal", "ABSTAIN")
        sign = SIGNAL_SIGN.get(sig, 0)
        if sign == 0:
            continue
        ndr = p.get("next_day_return")
        if ndr is None:
            continue
        # v2.0: clip extreme single-bar returns. yfinance occasionally has
        # bad bars (split adjustments, low-liquidity moves) that show as
        # 500%+ daily returns. These corrupt the equity curve. Real position
        # sizing has stops anyway, so clipping at ±50% is realistic.
        try:
            ndr_f = float(ndr)
        except (ValueError, TypeError):
            continue
        if ndr_f != ndr_f:  # NaN check
            continue
        ndr_f = max(-0.5, min(0.5, ndr_f))
        active.append((sign, ndr_f))

    score.n_active = len(active)
    if score.n_active == 0:
        return score

    signed = []
    for sign, ndr in active:
        signed_ret = sign * ndr
        signed.append(signed_ret)
        if abs(ndr) < push_threshold:
            score.pushes += 1
        elif signed_ret > 0:
            score.wins += 1
        else:
            score.losses += 1

    decided = score.wins + score.losses
    score.win_rate = score.wins / decided if decided > 0 else 0.0
    score.expectancy = sum(signed) / len(signed)
    score.stdev = _stdev(signed)
    score.sharpe_ish = (score.expectancy / score.stdev * math.sqrt(252)) if score.stdev > 0 else 0.0

    # Equity curve from $1, sized 1 unit per active call (equally-weighted)
    eq = 1.0
    curve = [eq]
    for r in signed:
        eq *= (1 + r * 0.01)  # treat each signal as 1% sizing — gentle leverage cap
        curve.append(eq)
    score.final_equity = eq
    score.max_drawdown = _max_drawdown(curve)
    return score


def score_backtest(
    predictions: List[Any],
) -> Dict[str, AgentScore]:
    """Score every agent. Returns {agent_name: AgentScore}."""
    by_agent: Dict[str, List[Any]] = defaultdict(list)
    for raw in predictions:
        p = _as_dict(raw)
        by_agent[p["agent"]].append(raw)  # keep original shape for downstream
    return {name: score_agent(name, preds) for name, preds in by_agent.items()}


def regime_sliced_metrics(
    predictions: List[Any],
) -> Dict[str, Dict[str, AgentScore]]:
    """Score every agent within each regime separately. Returns {regime: {agent: AgentScore}}."""
    by_regime: Dict[str, List[Any]] = defaultdict(list)
    for raw in predictions:
        p = _as_dict(raw)
        by_regime[p.get("regime", "UNKNOWN")].append(raw)
    return {regime: score_backtest(preds) for regime, preds in by_regime.items()}


def asset_class_sliced_metrics(
    predictions: List[Any],
) -> Dict[str, Dict[str, AgentScore]]:
    """Score every agent within each asset class separately."""
    by_class: Dict[str, List[Any]] = defaultdict(list)
    for raw in predictions:
        p = _as_dict(raw)
        by_class[p.get("asset_class", "unknown")].append(raw)
    return {ac: score_backtest(preds) for ac, preds in by_class.items()}


def render_leaderboard(
    scores: Dict[str, AgentScore],
    *,
    min_n: int = 30,
    sort_by: str = "sharpe_ish",
) -> str:
    """Pretty-print a leaderboard. min_n hides agents with too-thin data."""
    rows = [s for s in scores.values() if s.n_active >= min_n]
    rows.sort(key=lambda s: getattr(s, sort_by), reverse=True)

    lines = [
        "",
        f"{'AGENT':<14} {'N':>5} {'WIN%':>7} {'EV%':>8} {'SHARPE-ish':>11} {'MAXDD%':>9} {'EQUITY':>9}",
        "-" * 70,
    ]
    for s in rows:
        lines.append(
            f"{s.agent:<14} {s.n_active:>5} "
            f"{s.win_rate*100:>6.1f}% "
            f"{s.expectancy*100:>+7.3f}% "
            f"{s.sharpe_ish:>+11.2f} "
            f"{s.max_drawdown*100:>+8.2f}% "
            f"{s.final_equity:>9.3f}"
        )
    skipped = len(scores) - len(rows)
    if skipped > 0:
        lines.append(f"  ({skipped} agents hidden, n < {min_n})")
    lines.append("")
    return "\n".join(lines)


def write_report_json(
    predictions: List[Dict[str, Any]],
    output_path: str,
    *,
    min_n: int = 30,
) -> Dict[str, Any]:
    """Build a complete JSON report (overall + regime + asset-class slices)."""
    overall = score_backtest(predictions)
    regime_slices = regime_sliced_metrics(predictions)
    class_slices = asset_class_sliced_metrics(predictions)

    report = {
        "overall": {name: s.to_dict() for name, s in overall.items()},
        "by_regime": {
            regime: {name: s.to_dict() for name, s in scores.items()}
            for regime, scores in regime_slices.items()
        },
        "by_asset_class": {
            ac: {name: s.to_dict() for name, s in scores.items()}
            for ac, scores in class_slices.items()
        },
        "min_sample_for_inclusion": min_n,
        "notes": [
            "Sharpe-ish uses next-day signed returns × sqrt(252); not a portfolio Sharpe.",
            "Win rate excludes HOLD/ABSTAIN. Pushes are active calls with |ret|<0.5%.",
            "Equity curve is $1 with 1% sizing per active call. Adjust sizing in your own runs.",
            "Sentiment-dependent agents (VEIL, SPECK) are crippled in backtest mode.",
        ],
    }

    import json
    from pathlib import Path
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"[backtest] wrote report to {out}")
    return report
