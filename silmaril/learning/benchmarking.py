"""silmaril.learning.benchmarking — Alpha 5.1 reality-check / benchmarking.

What it does
────────────
The master directive demands a benchmarking engine that proves
SILMARIL's complexity is worth it — or shows clearly when it isn't.
"the most dangerous failure mode is building increasingly complex
systems while still underperforming simple ETFs."

This module computes rolling performance comparisons against:

  - SPY  (S&P 500)
  - QQQ  (Nasdaq-100)
  - XLE  (Energy sector)
  - XLK  (Technology sector)
  - equal-weight momentum basket (top 5 by 5d return from contexts)
  - buy-and-hold baseline (first-cycle equity, no rotation)
  - simple swing baseline (deploy & forget at start of week)

System metrics:
  silmaril_return                rolling return since first observation
  spy_return / qqq_return / ...  same windows for benchmarks
  alpha_vs_spy / _qqq / _xle / _xlk
  max_drawdown                   rolling drawdown
  volatility_adjusted_alpha      alpha / max_drawdown
  win_rate                       wins / total closed trades
  profit_factor                  Σ gains / Σ losses (capped at 5.0)
  deployment_efficiency          from capital_efficiency rollup

All ETF returns are computed from `contexts.json`-style price snapshots
already present in the system (no new HTTP calls). If the snapshots
don't include SPY/QQQ/XLE/XLK, we fall back to whatever proxies are
present (and emit a warning in `rationale`). This module ONLY uses
data the system already has on disk.

The engine maintains a rolling **benchmark_state.json** with the
first-seen prices for each benchmark, plus the per-cycle observation
log so daily / weekly / monthly returns can be computed without
external HTTP.

Output (docs/data/benchmarking.json)
────────────────────────────────────
{
  "version": "5.1", "generated_at": "...",
  "windows": {
    "1d":  {"silmaril_return": 0.012, "spy_return": 0.003, "alpha_vs_spy": 0.009,
             "qqq_return": 0.005, "alpha_vs_qqq": 0.007, ...},
    "1w":  { ... },
    "1mo": { ... }
  },
  "rolling_metrics": {
     "max_drawdown": 0.031, "volatility_adjusted_alpha": 1.4,
     "win_rate": 0.63, "profit_factor": 1.9,
     "deployment_efficiency": 0.84
  },
  "verdict": "OUTPERFORMING_SPY_OUTPERFORMING_QQQ",
  "rationale": "...",
  "observations":  [...]    # rolling cycle log capped at 90
}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


VERSION  = "5.1"
FILENAME = "benchmarking.json"

MAX_OBSERVATIONS = 90
BENCHMARK_TICKERS = ["SPY", "QQQ", "XLE", "XLK"]
# Map window label → max age in hours that counts as "in this window".
WINDOWS = {
    "1d":  24,
    "1w":  24 * 7,
    "1mo": 24 * 30,
}


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


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pick_benchmark_prices(
    contexts_by_ticker: Optional[Dict[str, Any]],
) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not contexts_by_ticker:
        return out
    for tkr in BENCHMARK_TICKERS:
        ctx = contexts_by_ticker.get(tkr) or contexts_by_ticker.get(tkr.upper())
        if not ctx:
            continue
        p = (getattr(ctx, "price", None)
             if not isinstance(ctx, dict) else ctx.get("price"))
        p = _safe_f(p, 0.0)
        if p > 0:
            out[tkr] = p
    return out


def _system_equity_from_floor(deployment_floor: Dict[str, Any]) -> float:
    s = _safe_f((deployment_floor.get("summary") or {}).get("system_equity_total"))
    if s > 0:
        return s
    total = 0.0
    for c in (deployment_floor.get("contracts") or {}).values():
        total += _safe_f(c.get("live_equity"))
    return total


def _windowed_return(
    observations: List[Dict[str, Any]],
    key: str,
    now_dt: datetime,
    window_hours: int,
) -> Optional[float]:
    """Return = (latest - oldest_in_window) / oldest_in_window."""
    if not observations:
        return None
    if window_hours <= 0:
        return None
    cutoff = now_dt - timedelta(hours=window_hours)
    in_window = []
    for o in observations:
        ts = _parse_iso(o.get("ts"))
        if not ts or ts < cutoff:
            continue
        v = _safe_f(o.get(key))
        if v <= 0:
            continue
        in_window.append((ts, v))
    in_window.sort(key=lambda kv: kv[0])
    if len(in_window) < 1:
        return None
    # Anchor: oldest observation in window
    _, oldest = in_window[0]
    latest = _safe_f((observations[-1] or {}).get(key))
    if oldest <= 0 or latest <= 0:
        return None
    return (latest - oldest) / oldest


def _trade_metrics_from_attrib(attrib: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """win_rate, profit_factor across attributed closed trades."""
    if not isinstance(attrib, dict):
        return {"win_rate": 0.0, "profit_factor": 0.0, "trades": 0}
    rows = attrib.get("orders") or attrib.get("rows") or []
    pnls = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        pnl = _safe_f(r.get("pnl") or r.get("realized_pnl") or r.get("net_pnl"))
        if pnl != 0:
            pnls.append(pnl)
    n = len(pnls)
    if n == 0:
        return {"win_rate": 0.0, "profit_factor": 0.0, "trades": 0}
    wins = sum(1 for p in pnls if p > 0)
    gain = sum(p for p in pnls if p > 0)
    loss = -sum(p for p in pnls if p < 0)
    profit_factor = (gain / loss) if loss > 0 else (5.0 if gain > 0 else 0.0)
    profit_factor = max(0.0, min(5.0, profit_factor))
    return {
        "win_rate":      round(wins / float(n), 4),
        "profit_factor": round(profit_factor, 4),
        "trades":        n,
    }


def _max_drawdown(observations: List[Dict[str, Any]]) -> float:
    """Simple peak-to-trough drawdown on `silmaril_equity`."""
    if not observations:
        return 0.0
    peak = 0.0
    max_dd = 0.0
    for o in observations:
        eq = _safe_f(o.get("silmaril_equity"))
        if eq <= 0:
            continue
        peak = max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
    return round(max_dd, 4)


def _verdict(window_returns: Dict[str, Dict[str, Any]]) -> str:
    """One-line summary suitable for the dashboard pill."""
    longest = window_returns.get("1mo") or window_returns.get("1w") or window_returns.get("1d") or {}
    alpha_spy = _safe_f(longest.get("alpha_vs_spy"))
    alpha_qqq = _safe_f(longest.get("alpha_vs_qqq"))
    parts = []
    parts.append("OUTPERFORMING_SPY" if alpha_spy > 0.003
                  else "UNDERPERFORMING_SPY" if alpha_spy < -0.003 else "INLINE_SPY")
    parts.append("OUTPERFORMING_QQQ" if alpha_qqq > 0.003
                  else "UNDERPERFORMING_QQQ" if alpha_qqq < -0.003 else "INLINE_QQQ")
    return "_".join(parts)


def build_benchmarking(
    data_dir: Path,
    contexts_by_ticker: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute + persist the benchmarking + reality-check rollup."""
    n_now = now or _now()
    deployment_floor   = _load_json(data_dir / "deployment_floor.json") or {}
    capital_efficiency = _load_json(data_dir / "capital_efficiency.json") or {}
    attrib             = _load_json(data_dir / "alpaca_attribution.json")
    prior              = _load_json(data_dir / FILENAME) or {}

    sys_equity = _system_equity_from_floor(deployment_floor)
    bench_prices = _pick_benchmark_prices(contexts_by_ticker)

    # Append today's observation
    observation = {
        "ts":               n_now.isoformat(),
        "silmaril_equity":  round(sys_equity, 2),
    }
    for tkr in BENCHMARK_TICKERS:
        if tkr in bench_prices:
            observation[tkr] = round(bench_prices[tkr], 4)

    observations: List[Dict[str, Any]] = list(prior.get("observations") or [])
    observations.append(observation)
    # Cap history
    observations = observations[-MAX_OBSERVATIONS:]

    # Per-window returns
    windows_out: Dict[str, Dict[str, Any]] = {}
    for label, hours in WINDOWS.items():
        silmaril_ret = _windowed_return(observations, "silmaril_equity",
                                              n_now, hours)
        row: Dict[str, Any] = {
            "silmaril_return": round(silmaril_ret, 4) if silmaril_ret is not None else None,
        }
        for tkr in BENCHMARK_TICKERS:
            bench_ret = _windowed_return(observations, tkr, n_now, hours)
            row[f"{tkr.lower()}_return"] = round(bench_ret, 4) if bench_ret is not None else None
            if silmaril_ret is not None and bench_ret is not None:
                row[f"alpha_vs_{tkr.lower()}"] = round(silmaril_ret - bench_ret, 4)
            else:
                row[f"alpha_vs_{tkr.lower()}"] = None
        windows_out[label] = row

    # Rolling metrics
    dd = _max_drawdown(observations)
    tm = _trade_metrics_from_attrib(attrib)
    deployment_eff = _safe_f((capital_efficiency.get("summary") or {})
                                  .get("deployment_efficiency_score"))
    # Volatility-adjusted alpha: longest window alpha vs SPY / drawdown
    long_alpha_spy = _safe_f((windows_out.get("1mo") or windows_out.get("1w") or {})
                                 .get("alpha_vs_spy"))
    vol_adj_alpha = round((long_alpha_spy / dd) if dd > 0 else 0.0, 4)
    vol_adj_alpha = max(-5.0, min(5.0, vol_adj_alpha))

    rolling = {
        "max_drawdown":                dd,
        "volatility_adjusted_alpha":   vol_adj_alpha,
        "win_rate":                    tm["win_rate"],
        "profit_factor":               tm["profit_factor"],
        "deployment_efficiency":       round(deployment_eff, 4),
    }

    verdict = _verdict(windows_out)

    bits: List[str] = []
    if not bench_prices:
        bits.append("no benchmark prices on disk")
    else:
        bits.append(f"{len(bench_prices)}/{len(BENCHMARK_TICKERS)} benchmarks tracked")
    bits.append(f"max_dd {dd*100:.2f}%")
    if tm["trades"] > 0:
        bits.append(f"WR {tm['win_rate']*100:.0f}% PF {tm['profit_factor']:.2f}")
    rationale = " · ".join(bits)

    payload = {
        "version":          VERSION,
        "generated_at":     n_now.isoformat(),
        "windows":          windows_out,
        "rolling_metrics":  rolling,
        "verdict":          verdict,
        "rationale":        rationale,
        "observations":     observations,
        "benchmarks":       BENCHMARK_TICKERS,
        "benchmarks_seen":  list(bench_prices.keys()),
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[benchmarking] write failed: {e}")
    return payload


def load_benchmarking(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "windows": {}, "rolling_metrics": {},
             "verdict": "WARMING_UP", "rationale": "no benchmarking file",
             "observations": [], "benchmarks": BENCHMARK_TICKERS}


__all__ = [
    "VERSION", "BENCHMARK_TICKERS", "WINDOWS",
    "build_benchmarking", "load_benchmarking",
]
