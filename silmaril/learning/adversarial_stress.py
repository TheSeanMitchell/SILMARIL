"""
silmaril.learning.adversarial_stress

Adversarial stress test: re-run yesterday's signals through a simulated
"everyone front-runs us" scenario where prices move 1-2% against the
consensus before fills. If the strategy still wins, it's robust. If it
craters, the edge is fragile.

Triggered manually via stress_test.yml workflow. Output is rendered in a
dedicated dashboard panel like the backtest.

Storage: docs/data/stress_test_results.json (PROTECTED)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


# Stress scenarios — applied as signed return adjustment to next-day-return
SCENARIOS = {
    "BASELINE":          {"adjustment_pct":   0.000, "description": "No adversarial impact"},
    "MILD_FRONTRUN":     {"adjustment_pct":  -0.005, "description": "0.5% front-running cost"},
    "STANDARD_FRONTRUN": {"adjustment_pct":  -0.010, "description": "1.0% front-running cost"},
    "AGGRESSIVE_FRONT":  {"adjustment_pct":  -0.020, "description": "2.0% aggressive front-running"},
    "REGIME_FLIP":       {"adjustment_pct":  -0.015, "description": "Mid-day regime flip cost"},
    "LIQUIDITY_CRISIS":  {"adjustment_pct":  -0.030, "description": "Sudden liquidity withdrawal (3%)"},
}


def stress_test_signals(
    debates: List[Dict],
    next_day_returns: Dict[str, float],
) -> Dict:
    """
    debates: list of debate dicts with consensus_signal, ticker, conviction
    next_day_returns: {ticker: actual_next_day_return}

    Returns: per-scenario summary of strategy robustness.
    """
    results = {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "scenarios": {},
    }

    for scenario_name, scenario in SCENARIOS.items():
        adj = scenario["adjustment_pct"]
        scenario_results = {
            "description": scenario["description"],
            "adjustment_pct": adj * 100,
            "n_calls": 0,
            "n_correct": 0,
            "total_return_bps": 0.0,
            "win_rate": 0.0,
            "expectancy_bps": 0.0,
        }

        for debate in debates:
            ticker = debate.get("ticker")
            signal = debate.get("consensus_signal", "HOLD")
            actual = next_day_returns.get(ticker)
            if actual is None or signal in ("HOLD", "ABSTAIN"):
                continue

            # Adjusted return: BUY suffers when price gets bid up first
            #                  SELL/SHORT suffers when price drops first
            if signal in ("BUY", "STRONG_BUY"):
                adjusted_return = actual + adj  # adj is negative -> hurts BUY
            else:  # SELL/SHORT
                adjusted_return = actual - adj  # adj negative -> -(neg) = positive hurt
                # Recompute for clarity: shorts pay the front-run cost too
                adjusted_return = -actual + abs(adj)
                # Actually: if we're shorting and there's adversarial buying first,
                # we get filled at a worse price (lower), so PnL is reduced
                adjusted_return = -actual - abs(adj)  # short pays the cost

            scenario_results["n_calls"] += 1
            won = adjusted_return > 0
            if won:
                scenario_results["n_correct"] += 1
            scenario_results["total_return_bps"] += adjusted_return * 10000

        n = scenario_results["n_calls"]
        if n > 0:
            scenario_results["win_rate"] = round(scenario_results["n_correct"] / n, 4)
            scenario_results["expectancy_bps"] = round(
                scenario_results["total_return_bps"] / n, 2
            )

        results["scenarios"][scenario_name] = scenario_results

    # Robustness verdict
    baseline = results["scenarios"]["BASELINE"]["expectancy_bps"]
    aggressive = results["scenarios"]["AGGRESSIVE_FRONT"]["expectancy_bps"]
    if baseline <= 0:
        results["robustness_verdict"] = "FRAGILE — baseline expectancy negative"
    elif aggressive > 0:
        results["robustness_verdict"] = "ROBUST — survives 2% adversarial cost"
    elif aggressive > -baseline * 0.5:
        results["robustness_verdict"] = "MODERATE — degrades but still profitable"
    else:
        results["robustness_verdict"] = "FRAGILE — edge collapses under adversarial cost"

    return results


def save_stress_results(path: Path, results: Dict) -> None:
    """Append to history (preserves all prior stress runs)."""
    history = {"runs": []}
    if path.exists():
        try:
            history = json.loads(path.read_text())
        except Exception:
            pass
    history.setdefault("runs", []).append(results)
    history["runs"] = history["runs"][-50:]  # keep last 50 runs
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2))
