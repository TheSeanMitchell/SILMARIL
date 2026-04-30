"""
silmaril.learning.anomaly_detector

Volume spikes 5x average without news = something is happening.
Detects unusual price/volume patterns and flags them for the next debate run.

Detection types:
  - VOLUME_SPIKE: volume > 3 std above 30-day mean
  - PRICE_GAP: open gap > 2% with no news catalyst
  - ATR_SPIKE: realized range > 2x recent ATR
  - SENTIMENT_FLIP: rapid sentiment polarity reversal
  - DIVERGENCE: price up while volume drops (weakness signal)

Anomalies persist in anomaly_state.json with TTL so they don't re-fire
on every 10-min run.

Storage: docs/data/anomaly_state.json (PROTECTED)
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional


# Time-to-live for an anomaly flag (hours)
ANOMALY_TTL_HOURS = 24


def detect_volume_spike(
    current_volume: int,
    historical_volumes: List[int],
    threshold_sigma: float = 3.0,
) -> Optional[dict]:
    if len(historical_volumes) < 20 or current_volume <= 0:
        return None
    mean_v = statistics.mean(historical_volumes)
    std_v = statistics.stdev(historical_volumes) if len(historical_volumes) > 1 else 0
    if std_v == 0:
        return None
    z = (current_volume - mean_v) / std_v
    if z >= threshold_sigma:
        return {
            "type": "VOLUME_SPIKE",
            "z_score": round(z, 2),
            "current_volume": current_volume,
            "mean_volume": int(mean_v),
            "ratio": round(current_volume / mean_v, 2),
        }
    return None


def detect_price_gap(
    open_price: float,
    prev_close: float,
    threshold_pct: float = 0.02,
) -> Optional[dict]:
    if prev_close <= 0:
        return None
    gap_pct = (open_price - prev_close) / prev_close
    if abs(gap_pct) >= threshold_pct:
        return {
            "type": "PRICE_GAP",
            "gap_pct": round(gap_pct * 100, 2),
            "direction": "UP" if gap_pct > 0 else "DOWN",
            "open": open_price,
            "prev_close": prev_close,
        }
    return None


def detect_atr_spike(
    today_range: float,
    historical_ranges: List[float],
    threshold_ratio: float = 2.0,
) -> Optional[dict]:
    if len(historical_ranges) < 10 or today_range <= 0:
        return None
    median_atr = statistics.median(historical_ranges)
    if median_atr == 0:
        return None
    ratio = today_range / median_atr
    if ratio >= threshold_ratio:
        return {
            "type": "ATR_SPIKE",
            "ratio": round(ratio, 2),
            "today_range": round(today_range, 4),
            "median_recent_range": round(median_atr, 4),
        }
    return None


def detect_volume_divergence(
    price_change_pct: float,
    volume_change_pct: float,
) -> Optional[dict]:
    """
    Bull divergence: price up but volume DOWN = weak rally.
    Bear divergence: price down but volume DOWN = weak selloff.
    """
    if abs(price_change_pct) < 0.01 or abs(volume_change_pct) < 0.20:
        return None
    if price_change_pct > 0.02 and volume_change_pct < -0.20:
        return {
            "type": "DIVERGENCE",
            "subtype": "WEAK_RALLY",
            "price_change_pct": round(price_change_pct * 100, 2),
            "volume_change_pct": round(volume_change_pct * 100, 2),
        }
    if price_change_pct < -0.02 and volume_change_pct < -0.20:
        return {
            "type": "DIVERGENCE",
            "subtype": "WEAK_SELLOFF",
            "price_change_pct": round(price_change_pct * 100, 2),
            "volume_change_pct": round(volume_change_pct * 100, 2),
        }
    return None


def record_anomalies(
    state_path: Path,
    ticker: str,
    anomalies: List[dict],
) -> List[dict]:
    """
    Record anomalies for a ticker, deduplicating against existing TTL'd flags.
    Returns the freshly-flagged anomalies (excluding already-active ones).
    """
    state = {"flagged": []}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=ANOMALY_TTL_HOURS)

    # Prune expired
    state["flagged"] = [
        f for f in state.get("flagged", [])
        if datetime.fromisoformat(f.get("flagged_at", now.isoformat())) > cutoff
    ]

    existing_keys = {(f["ticker"], f["type"]) for f in state["flagged"]}
    fresh = []
    for anom in anomalies:
        key = (ticker, anom["type"])
        if key in existing_keys:
            continue
        record = {**anom, "ticker": ticker, "flagged_at": now.isoformat()}
        state["flagged"].append(record)
        fresh.append(record)

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))
    return fresh


def active_anomalies(state_path: Path) -> List[dict]:
    if not state_path.exists():
        return []
    try:
        state = json.loads(state_path.read_text())
    except Exception:
        return []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=ANOMALY_TTL_HOURS)
    return [
        f for f in state.get("flagged", [])
        if datetime.fromisoformat(f.get("flagged_at", now.isoformat())) > cutoff
    ]
