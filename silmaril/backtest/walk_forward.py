"""
silmaril.backtest.walk_forward

Out-of-sample validation, explained simply:

The danger we are guarding against is called OVERFITTING. It works like this:
if you tune an agent's thresholds (say, "BUY when RSI < 35") by looking at all
4 years of historical data and picking the rule that worked best, that rule
will look amazing in the backtest. But it succeeded by memorizing noise — by
fitting the past, not by capturing a true edge. When you deploy it to NEW data
it has never seen, performance collapses.

The fix is walk-forward (or "out-of-sample") validation. You divide the
timeline into sequential chunks. For each chunk:
  - Treat the EARLIER history as "training" data — the agent gets tuned on it.
  - Test the SAME RULES on a HELD-OUT chunk the agent has never seen.

If the agent's win rate in the held-out chunk is roughly equal to its win rate
in the training chunk, that's evidence of REAL edge.
If the held-out win rate is much worse, that's evidence of overfitting.

For SILMARIL specifically: our agents aren't ML-trained, they're rule-based.
The rules are fixed in code. So "training" doesn't tune the rules — instead,
walk-forward tells us whether the rules HOLD UP across regimes. An agent that
only worked in the 2022 bear market and fails in 2024 should be retired.

The output is per-window win rate. Big variance across windows = brittle agent.
Stable across windows = trustworthy agent.
"""
from __future__ import annotations

from dataclasses import dataclass, is_dataclass, asdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .metrics import AgentScore, score_backtest


def _as_dict(p: Any) -> Dict[str, Any]:
    """Normalize a prediction (dict or dataclass) to a dict."""
    if isinstance(p, dict):
        return p
    if is_dataclass(p):
        return asdict(p)
    if hasattr(p, "to_dict"):
        return p.to_dict()
    return dict(getattr(p, "__dict__", {}))


@dataclass
class WindowResult:
    window_start: str
    window_end: str
    n_trading_days: int
    agent_scores: Dict[str, AgentScore]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "n_trading_days": self.n_trading_days,
            "agent_scores": {name: s.to_dict() for name, s in self.agent_scores.items()},
        }


def split_by_windows(
    predictions: List[Any],
    *,
    n_splits: int = 4,
) -> List[List[Any]]:
    """Divides predictions into n equal-time windows by date."""
    if not predictions:
        return [[] for _ in range(n_splits)]

    sorted_preds = sorted(predictions, key=lambda p: _as_dict(p)["date"])
    first = date.fromisoformat(_as_dict(sorted_preds[0])["date"])
    last = date.fromisoformat(_as_dict(sorted_preds[-1])["date"])
    span_days = (last - first).days
    chunk_days = max(1, span_days // n_splits)

    windows: List[List[Any]] = [[] for _ in range(n_splits)]
    for raw in sorted_preds:
        p = _as_dict(raw)
        d = date.fromisoformat(p["date"])
        idx = min(n_splits - 1, (d - first).days // chunk_days)
        windows[idx].append(raw)
    return windows


def walk_forward_validation(
    predictions: List[Any],
    *,
    n_splits: int = 4,
) -> Dict[str, Any]:
    """Score each window independently. Returns full report."""
    windows = split_by_windows(predictions, n_splits=n_splits)
    results: List[WindowResult] = []

    for i, window_preds in enumerate(windows):
        if not window_preds:
            continue
        dates = [_as_dict(p)["date"] for p in window_preds]
        scores = score_backtest(window_preds)
        results.append(WindowResult(
            window_start=min(dates),
            window_end=max(dates),
            n_trading_days=len(set(dates)),
            agent_scores=scores,
        ))

    return {
        "n_splits": n_splits,
        "windows": [r.to_dict() for r in results],
        "stability_summary": _stability_summary(results),
    }


def _stability_summary(results: List[WindowResult]) -> Dict[str, Dict[str, Any]]:
    """For each agent, compute win-rate stability across windows."""
    if not results:
        return {}
    agent_names = set()
    for r in results:
        agent_names.update(r.agent_scores.keys())

    summary: Dict[str, Dict[str, Any]] = {}
    for name in agent_names:
        win_rates = []
        n_active_per_window = []
        for r in results:
            s = r.agent_scores.get(name)
            if s is None or s.n_active < 5:
                continue
            win_rates.append(s.win_rate)
            n_active_per_window.append(s.n_active)
        if len(win_rates) < 2:
            summary[name] = {
                "stability": "INSUFFICIENT_DATA",
                "windows_with_data": len(win_rates),
            }
            continue

        mean_wr = sum(win_rates) / len(win_rates)
        spread = max(win_rates) - min(win_rates)
        # rough heuristic
        if spread > 0.20:
            verdict = "BRITTLE"
        elif spread > 0.10:
            verdict = "VARIABLE"
        else:
            verdict = "STABLE"

        summary[name] = {
            "stability": verdict,
            "windows_with_data": len(win_rates),
            "mean_win_rate": round(mean_wr, 4),
            "win_rate_spread": round(spread, 4),
            "win_rates_per_window": [round(w, 4) for w in win_rates],
            "n_active_per_window": n_active_per_window,
        }
    return summary
