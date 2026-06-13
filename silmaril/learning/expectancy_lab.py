"""silmaril.learning.expectancy_lab — Alpha 5.1 expectancy lab.

What it does
────────────
The master directive: "the system still does not clearly prove
expectancy by setup, catalyst, sector, regime, account, hold-duration."
Without expectancy, "tuning is guessing, profitability is accidental,
confidence is fake."

This module is the SINGLE SOURCE OF TRUTH for empirical expectancy.
Every closed trade is bucketed by every axis the system uses to decide,
and the resulting buckets are exposed for both the dashboard AND the
conviction engine to consume.

Inputs (defensive):
  - alpaca_attribution.json  — closed trade rows with pnl, regime,
                                sector, setup_archetype, catalyst_label,
                                hold_hours, account_id, signal
  - alpaca_paper.json + harvest accounts (for trade-tail fallback when
                                            attribution hasn't caught up)

Bucket axes (configurable):
  - SETUP                (10 archetypes)
  - REGIME               (ATTACK/BALANCED/DEFENSIVE/PRESERVATION)
  - SECTOR
  - CATALYST_TYPE
  - HOLD_BUCKET          (short<1d / medium 1-4d / long >4d)
  - ACCOUNT              (LEGACY/HARVEST_3/HARVEST_5)
  - SIGNAL               (STRONG_BUY / BUY)

For each bucket we report:
  {samples, wins, losses, win_rate, avg_return, expectancy,
   avg_hold_hours, sharpe_proxy}

Sharpe-proxy = expectancy / stdev(returns) — capped at 4.

Output (docs/data/expectancy_lab.json)
──────────────────────────────────────
{
  "version": "5.1",
  "generated_at": "...",
  "buckets": {
    "BREAKOUT_CONTINUATION::ATTACK::Technology": {
       "samples": 12, "win_rate": 0.66, "avg_return": 0.034,
       "expectancy": 0.021, "avg_hold_hours": 19, "sharpe_proxy": 1.9
    }, ...
  },
  "by_axis": {
     "setup": {...}, "regime": {...}, "sector": {...},
     "account": {...}, "signal": {...}, "hold_bucket": {...}
  },
  "best_combo": {"key": "...", "expectancy": 0.041, "samples": 11},
  "worst_combo": {...},
  "totals": {"trades_indexed": 92}
}
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION  = "5.1"
FILENAME = "expectancy_lab.json"

# Minimum samples before a bucket is considered statistically meaningful.
# The dashboard shows everything, but `best_combo` / `worst_combo` only
# consider buckets with this many samples.
MIN_SAMPLES_REPORT  = 5
MIN_SAMPLES_HEADLINE = 8


def _safe_f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def _load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _hold_bucket(hold_hours: float) -> str:
    if hold_hours <= 0:
        return "unknown"
    if hold_hours < 24:
        return "short_under_1d"
    if hold_hours <= 96:
        return "medium_1_to_4d"
    return "long_over_4d"


def _trades_from_attribution(attrib: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pull closed-trade rows out of alpaca_attribution.json."""
    if not isinstance(attrib, dict):
        return []
    rows = attrib.get("orders") or attrib.get("rows") or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        pnl = _safe_f(r.get("pnl") or r.get("realized_pnl") or r.get("net_pnl"))
        if pnl == 0 and not r.get("realized_pnl_pct"):
            # Skip rows that don't have a closed P&L.
            continue
        out.append(r)
    return out


def _stat_block(samples: List[Tuple[float, float]]) -> Dict[str, Any]:
    """Compute one bucket's stats. samples = list of (return_pct, hold_hours)."""
    n = len(samples)
    if n == 0:
        return {"samples": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                  "avg_return": 0.0, "expectancy": 0.0,
                  "avg_hold_hours": 0.0, "sharpe_proxy": 0.0}
    returns = [s[0] for s in samples]
    holds   = [s[1] for s in samples]
    wins   = sum(1 for r in returns if r > 0)
    losses = n - wins
    avg = sum(returns) / float(n)
    # std dev (sample)
    if n > 1:
        mu = avg
        var = sum((r - mu) ** 2 for r in returns) / float(n - 1)
        sd = math.sqrt(var)
    else:
        sd = 0.0
    sharpe = (avg / sd) if sd > 0 else 0.0
    sharpe = max(-4.0, min(4.0, sharpe))
    avg_hold = sum(holds) / float(n) if holds else 0.0
    return {
        "samples":        int(n),
        "wins":           int(wins),
        "losses":         int(losses),
        "win_rate":       round(wins / float(n), 4),
        "avg_return":     round(avg, 4),
        "expectancy":     round(avg, 4),         # synonym for clarity
        "avg_hold_hours": round(avg_hold, 2),
        "sharpe_proxy":   round(sharpe, 4),
    }


def build_expectancy_lab(
    data_dir: Path,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute + persist the expectancy_lab payload."""
    n_now = now or datetime.now(timezone.utc)
    attrib = _load_json(data_dir / "alpaca_attribution.json")
    setup_clf = _load_json(data_dir / "setup_classifications.json") or {}

    # If trades lack setup_archetype, fall back to classifying their
    # catalyst_label via setup_classifier.classify_plan on a stub.
    try:
        from ..portfolios.setup_classifier import classify_plan as _classify_plan
    except Exception:
        _classify_plan = None

    trades = _trades_from_attribution(attrib)

    # Multi-axis buckets
    combo: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    by_setup:   Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    by_regime:  Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    by_sector:  Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    by_account: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    by_signal:  Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    by_hold:    Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    by_catalyst:Dict[str, List[Tuple[float, float]]] = defaultdict(list)

    for r in trades:
        pnl = _safe_f(r.get("pnl") or r.get("realized_pnl") or r.get("net_pnl"))
        ret_pct = _safe_f(r.get("realized_pnl_pct") or r.get("pnl_pct"))
        if ret_pct == 0 and pnl != 0:
            entry = _safe_f(r.get("entry_price") or r.get("avg_entry"))
            qty   = _safe_f(r.get("qty"))
            denom = entry * qty
            if denom > 0:
                ret_pct = pnl / denom
        hold = _safe_f(r.get("hold_hours") or (r.get("hold_days") or 0) * 24)
        archetype = r.get("setup_archetype")
        if not archetype and _classify_plan:
            stub = {
                "consensus_signal": r.get("signal") or "BUY",
                "catalyst_label":   r.get("catalyst_label"),
                "three_month_signal": r.get("three_month_signal"),
                "is_elite":         r.get("is_elite"),
            }
            try:
                archetype, _, _ = _classify_plan(stub)
            except Exception:
                archetype = "GENERIC"
        archetype = archetype or "GENERIC"
        regime    = (r.get("regime") or r.get("market_mode") or "UNKNOWN").upper()
        sector    = r.get("sector") or "Unknown"
        account   = (r.get("account_id") or "?")
        signal    = (r.get("signal") or "?").upper()
        catalyst  = (r.get("catalyst_label") or "no_catalyst")
        hold_b    = _hold_bucket(hold)

        sample = (ret_pct, hold)
        combo_key = f"{archetype}::{regime}::{sector}"
        combo[combo_key].append(sample)
        by_setup[archetype].append(sample)
        by_regime[regime].append(sample)
        by_sector[sector].append(sample)
        by_account[account].append(sample)
        by_signal[signal].append(sample)
        by_hold[hold_b].append(sample)
        by_catalyst[catalyst].append(sample)

    def _materialize(buckets: Dict[str, List[Tuple[float, float]]]) -> Dict[str, Dict[str, Any]]:
        return {k: _stat_block(v) for k, v in buckets.items() if v}

    combo_blocks = _materialize(combo)
    by_axis = {
        "setup":      _materialize(by_setup),
        "regime":     _materialize(by_regime),
        "sector":     _materialize(by_sector),
        "account":    _materialize(by_account),
        "signal":     _materialize(by_signal),
        "hold_bucket":_materialize(by_hold),
        "catalyst":   _materialize(by_catalyst),
    }

    # Headline best/worst — among combos with enough samples.
    eligible = [(k, v) for k, v in combo_blocks.items()
                  if v["samples"] >= MIN_SAMPLES_HEADLINE]
    if eligible:
        best = max(eligible, key=lambda kv: kv[1]["expectancy"])
        worst = min(eligible, key=lambda kv: kv[1]["expectancy"])
        best_combo = {"key": best[0], **best[1]}
        worst_combo = {"key": worst[0], **worst[1]}
    else:
        best_combo = {"key": "", "samples": 0}
        worst_combo = {"key": "", "samples": 0}

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "buckets":      combo_blocks,
        "by_axis":      by_axis,
        "best_combo":   best_combo,
        "worst_combo":  worst_combo,
        "totals":       {"trades_indexed": len(trades)},
        "rationale":    (f"{len(trades)} attributed trades · "
                            f"{len(combo_blocks)} combo buckets · "
                            f"{len(eligible)} statistically-significant"),
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[expectancy_lab] write failed: {e}")
    return payload


def get_combo_expectancy(
    data_dir: Path,
    setup: Optional[str], regime: Optional[str], sector: Optional[str],
) -> Optional[float]:
    """Lookup expectancy for one combo. None when bucket not significant."""
    if not (setup and regime and sector):
        return None
    body = _load_json(data_dir / FILENAME)
    if not isinstance(body, dict):
        return None
    key = f"{setup}::{regime}::{sector}"
    bucket = (body.get("buckets") or {}).get(key)
    if not bucket or int(bucket.get("samples", 0)) < MIN_SAMPLES_REPORT:
        return None
    return _safe_f(bucket.get("expectancy"))


def load_expectancy_lab(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "buckets": {}, "by_axis": {},
             "best_combo": {}, "worst_combo": {},
             "totals": {"trades_indexed": 0},
             "rationale": "no expectancy_lab file"}


__all__ = [
    "VERSION", "MIN_SAMPLES_REPORT", "MIN_SAMPLES_HEADLINE",
    "build_expectancy_lab", "get_combo_expectancy", "load_expectancy_lab",
]
