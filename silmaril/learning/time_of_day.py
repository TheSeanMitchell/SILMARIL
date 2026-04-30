"""
silmaril.learning.time_of_day

The first 30 minutes of trading behave very differently from mid-day.
At 10-minute cadence, agents should know whether it's the open, the lunch
lull, or the close. Performance is bucketed by time-of-day so we can
identify which agents have edge when.

Buckets (US Eastern):
  - PRE_MARKET     04:00–09:30
  - OPENING_30     09:30–10:00 (first 30 min — most volatile, fakeouts common)
  - MORNING        10:00–11:30
  - LUNCH_LULL     11:30–13:30 (lower volume, mean-reversion bias)
  - AFTERNOON      13:30–15:30
  - POWER_HOUR     15:30–16:00 (last 30 min — institutional positioning)
  - AFTER_HOURS    16:00–20:00

Storage: docs/data/time_of_day_performance.json (PROTECTED)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


def get_tod_bucket(dt: Optional[datetime] = None) -> str:
    """Return time-of-day bucket for current US Eastern time."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    # Convert UTC to US Eastern (UTC-4 EDT, UTC-5 EST). Approximate.
    # March-November we're in EDT (UTC-4); rest is EST (UTC-5).
    month = dt.month
    if 3 <= month <= 11:
        et = dt - timedelta(hours=4)
    else:
        et = dt - timedelta(hours=5)

    h, m = et.hour, et.minute
    # Weekday gate
    if et.weekday() >= 5:
        return "WEEKEND"

    minutes = h * 60 + m
    if minutes < 4 * 60:
        return "OVERNIGHT"
    if minutes < 9 * 60 + 30:
        return "PRE_MARKET"
    if minutes < 10 * 60:
        return "OPENING_30"
    if minutes < 11 * 60 + 30:
        return "MORNING"
    if minutes < 13 * 60 + 30:
        return "LUNCH_LULL"
    if minutes < 15 * 60 + 30:
        return "AFTERNOON"
    if minutes < 16 * 60:
        return "POWER_HOUR"
    if minutes < 20 * 60:
        return "AFTER_HOURS"
    return "OVERNIGHT"


def record_tod_outcome(
    perf_path: Path,
    agent: str,
    bucket: str,
    won: bool,
) -> None:
    data = {}
    if perf_path.exists():
        try:
            data = json.loads(perf_path.read_text())
        except Exception:
            data = {}

    agent_data = data.setdefault(agent, {})
    bucket_data = agent_data.setdefault(bucket, {"calls": 0, "wins": 0})
    bucket_data["calls"] += 1
    if won:
        bucket_data["wins"] += 1

    perf_path.parent.mkdir(parents=True, exist_ok=True)
    perf_path.write_text(json.dumps(data, indent=2))


def best_buckets_for_agent(perf_path: Path, agent: str, min_calls: int = 30) -> list:
    if not perf_path.exists():
        return []
    try:
        data = json.loads(perf_path.read_text())
    except Exception:
        return []
    agent_data = data.get(agent, {})
    rows = []
    for bucket, stats in agent_data.items():
        if stats.get("calls", 0) >= min_calls:
            rate = stats["wins"] / stats["calls"]
            rows.append((bucket, rate, stats["calls"]))
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows
