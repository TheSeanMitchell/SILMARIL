"""
silmaril.learning.correlation_matrix

When SCROOGE, MIDAS, and STEADFAST all pile into NVDA, you've got
concentrated risk masquerading as diversification. This module computes
a nightly correlation matrix and warns when 3+ portfolios hold positions
with > 0.7 correlation.

Storage: docs/data/correlation_history.json (PROTECTED)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def compute_position_correlations(
    portfolios: Dict[str, dict],
    price_history: Dict[str, List[float]],
    lookback_days: int = 60,
) -> dict:
    """
    portfolios: {agent_name: {current_position: {ticker, ...}}}
    price_history: {ticker: [last N daily closes]}
    Returns: {pairs: [(ticker_a, ticker_b, corr)], concentration_alerts: [...]}
    """
    held_tickers = set()
    holders_by_ticker: Dict[str, List[str]] = {}
    for agent, p in portfolios.items():
        pos = (p or {}).get("current_position")
        if pos and pos.get("ticker"):
            t = pos["ticker"]
            held_tickers.add(t)
            holders_by_ticker.setdefault(t, []).append(agent)

    # Compute pairwise correlations
    tickers = sorted(held_tickers)
    pairs = []
    for i, ta in enumerate(tickers):
        for tb in tickers[i+1:]:
            corr = _pearson(
                price_history.get(ta, [])[-lookback_days:],
                price_history.get(tb, [])[-lookback_days:],
            )
            if corr is not None:
                pairs.append((ta, tb, round(corr, 3)))

    # Identify concentration alerts: pairs with corr > 0.7 where 3+ agents collectively hold
    concentration_alerts = []
    for ta, tb, corr in pairs:
        if corr > 0.70:
            agents_a = holders_by_ticker.get(ta, [])
            agents_b = holders_by_ticker.get(tb, [])
            unique = set(agents_a) | set(agents_b)
            if len(unique) >= 3:
                concentration_alerts.append({
                    "ticker_a": ta,
                    "ticker_b": tb,
                    "correlation": corr,
                    "holders_a": agents_a,
                    "holders_b": agents_b,
                    "total_agents_exposed": sorted(unique),
                })

    # Single-name concentration: any ticker held by 5+ agents
    for t, agents in holders_by_ticker.items():
        if len(agents) >= 5:
            concentration_alerts.append({
                "ticker": t,
                "single_name_concentration": True,
                "holders": agents,
            })

    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "tickers_held": tickers,
        "pairs": pairs,
        "concentration_alerts": concentration_alerts,
    }


def _pearson(a: list, b: list) -> float:
    """Hand-rolled Pearson correlation, no numpy required."""
    if not a or not b:
        return None
    n = min(len(a), len(b))
    if n < 10:
        return None
    a, b = a[-n:], b[-n:]
    # Convert to log-returns
    ra = [(a[i] - a[i-1]) / a[i-1] if a[i-1] else 0 for i in range(1, n)]
    rb = [(b[i] - b[i-1]) / b[i-1] if b[i-1] else 0 for i in range(1, n)]
    if not ra or not rb:
        return None
    mean_a = sum(ra) / len(ra)
    mean_b = sum(rb) / len(rb)
    num = sum((ra[i] - mean_a) * (rb[i] - mean_b) for i in range(len(ra)))
    den_a = (sum((x - mean_a) ** 2 for x in ra)) ** 0.5
    den_b = (sum((x - mean_b) ** 2 for x in rb)) ** 0.5
    if den_a == 0 or den_b == 0:
        return None
    return num / (den_a * den_b)


def append_to_history(history_path: Path, snapshot: dict) -> None:
    history = {"snapshots": []}
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text())
        except Exception:
            pass
    history.setdefault("snapshots", []).append(snapshot)
    history["snapshots"] = history["snapshots"][-90:]  # 90-day rolling
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=2))
