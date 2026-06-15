"""
silmaril.learning.counterfactual

Logs what *would* have happened if a dissenting agent had been listened to.
After 90+ days, we can ask: "Of the times agent X was overruled, how often
was it correct?"

Storage: docs/data/counterfactuals.json (PROTECTED — never reset)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


def log_counterfactual(
    cf_path: Path,
    date_str: str,
    ticker: str,
    consensus_signal: str,
    dissenting_agent: str,
    dissent_signal: str,
    next_day_return: float,
) -> None:
    cf = {"records": []}
    if cf_path.exists():
        try:
            cf = json.loads(cf_path.read_text())
        except Exception:
            pass

    if dissent_signal in ("BUY", "STRONG_BUY"):
        dissent_correct = next_day_return > 0
    elif dissent_signal in ("SELL", "STRONG_SELL"):
        dissent_correct = next_day_return < 0
    else:
        dissent_correct = abs(next_day_return) < 0.005

    if consensus_signal in ("BUY", "STRONG_BUY"):
        consensus_correct = next_day_return > 0
    elif consensus_signal in ("SELL", "STRONG_SELL"):
        consensus_correct = next_day_return < 0
    else:
        consensus_correct = abs(next_day_return) < 0.005

    cf.setdefault("records", []).append({
        "date": date_str,
        "ticker": ticker,
        "consensus_signal": consensus_signal,
        "dissenting_agent": dissenting_agent,
        "dissent_signal": dissent_signal,
        "next_day_return": next_day_return,
        "consensus_correct": consensus_correct,
        "dissent_correct": dissent_correct,
        "dissent_was_better": dissent_correct and not consensus_correct,
    })

    cf["records"] = cf["records"][-20000:]
    cf_path.parent.mkdir(parents=True, exist_ok=True)
    cf_path.write_text(json.dumps(cf, indent=2))


def score_counterfactuals(cf_path: Path) -> Dict[str, Dict]:
    if not cf_path.exists():
        return {}
    try:
        cf = json.loads(cf_path.read_text())
    except Exception:
        return {}

    by_agent = {}
    for r in cf.get("records", []):
        agent = r.get("dissenting_agent")
        if not agent:
            continue
        d = by_agent.setdefault(agent, {"n_dissents": 0, "n_better": 0})
        d["n_dissents"] += 1
        if r.get("dissent_was_better"):
            d["n_better"] += 1

    return {
        agent: {**stats, "rate": stats["n_better"] / max(1, stats["n_dissents"])}
        for agent, stats in by_agent.items()
    }
