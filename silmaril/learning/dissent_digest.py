"""
silmaril.learning.dissent_digest

Builds a structured "lessons from yesterday" digest that gets injected
into today's agent context. This is how agents learn from each other.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


def build_dissent_digest(
    scoring_path: Path,
    history_path: Path,
    counterfactuals_path: Path = None,
    lookback_days: int = 7,
) -> str:
    if not scoring_path.exists() or not history_path.exists():
        return ""
    try:
        scoring = json.loads(scoring_path.read_text())
        history = json.loads(history_path.read_text())
    except Exception:
        return ""

    lines = ["=== LEARNING CONTEXT — last 7 days ==="]

    by_agent = scoring.get("by_agent", {})
    sorted_agents = sorted(
        by_agent.items(),
        key=lambda kv: kv[1].get("rolling_30d_win_rate", 0.5),
        reverse=True,
    )
    if sorted_agents:
        top3 = sorted_agents[:3]
        bot3 = sorted_agents[-3:]
        lines.append("Hot streaks (rolling 30d):")
        for name, stats in top3:
            wr = stats.get("rolling_30d_win_rate", 0.5)
            lines.append(f"  {name}: {wr*100:.1f}% win rate")
        lines.append("Cold streaks (rolling 30d):")
        for name, stats in bot3:
            wr = stats.get("rolling_30d_win_rate", 0.5)
            lines.append(f"  {name}: {wr*100:.1f}% win rate")

    runs = history.get("runs", [])
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    recent = [r for r in runs if r.get("date", "0000-00-00") >= cutoff]

    overruled_wins = []
    for run in recent[-30:]:
        for debate in run.get("debates", []):
            consensus = debate.get("consensus_signal")
            outcome = debate.get("outcome_correct_consensus")
            if outcome is False:
                ticker = debate.get("ticker")
                date_str = debate.get("date")
                for v in debate.get("verdicts", []):
                    if v.get("signal") != consensus and v.get("was_correct"):
                        overruled_wins.append(
                            f"  {date_str} {ticker}: {v['agent']} dissented "
                            f"with {v['signal']} (was correct)"
                        )
    if overruled_wins:
        lines.append("Recent overruled-minority wins:")
        lines.extend(overruled_wins[:5])

    # Add counterfactual high-performers if available
    if counterfactuals_path and counterfactuals_path.exists():
        try:
            cf = json.loads(counterfactuals_path.read_text())
            from collections import defaultdict
            by_agent_cf = defaultdict(lambda: [0, 0])
            for r in cf.get("records", [])[-2000:]:
                a = r.get("dissenting_agent")
                if a:
                    by_agent_cf[a][0] += 1
                    if r.get("dissent_was_better"):
                        by_agent_cf[a][1] += 1
            best = sorted(
                [(a, w/max(1,n)) for a, (n, w) in by_agent_cf.items() if n >= 20],
                key=lambda x: -x[1],
            )[:3]
            if best:
                lines.append("Best dissent track-record (when overruled):")
                for a, rate in best:
                    lines.append(f"  {a}: {rate*100:.1f}% of overruled calls were correct")
        except Exception:
            pass

    return "\n".join(lines)


def attach_digest_to_contexts(contexts: list, digest: str) -> None:
    for ctx in contexts:
        if hasattr(ctx, "__dict__"):
            ctx.learning_context = digest
        elif isinstance(ctx, dict):
            ctx["learning_context"] = digest
