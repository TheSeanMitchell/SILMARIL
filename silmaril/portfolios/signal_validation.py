"""silmaril.portfolios.signal_validation — Alpha 4.0 empirical signal tracker.

What it does
────────────
Alpha 3.x's conviction scoring uses fixed weights with no outcome learning.
This module walks every realized close across the harvest accounts and
attributes the realized PnL to:

  - the entry's consensus_signal (BUY / STRONG_BUY)
  - the market regime at entry (ATTACK / BALANCED / DEFENSIVE / PRESERVATION)
  - the catalyst class at entry (strong / soft / none)
  - the three_month_signal at entry (uptrend / flat / downtrend)
  - the elite tag at entry (bool)

It produces a `setup_expectancy.json` that other modules consume to
calibrate their thresholds. The result is statistical, not synthetic:
every number is derived from historical closes, and the math is the
same as a baseball batter's slugging average.

Output (docs/data/signal_validation.json)
─────────────────────────────────────────
{
  "version": "4.0",
  "generated_at": "...",
  "lookback_days": 60,
  "n_closes": 142,
  "setups": {
     "STRONG_BUY|ATTACK|strong|uptrend|elite": {
        "n": 12, "wins": 9, "losses": 3,
        "win_rate": 0.75, "avg_pnl": 47.50, "expectancy": 31.25,
        "median_hold_days": 2.1
     },
     "BUY|BALANCED|soft|flat|normal": {...},
     ...
  },
  "catalysts": {
     "raised guidance": {"n": 18, "win_rate": 0.78, "avg_pnl": 52.30, ...},
     "blowout":          {"n": 11, "win_rate": 0.82, "avg_pnl": 71.10, ...},
     ...
  },
  "regimes": {
     "ATTACK":       {"n": 88, "win_rate": 0.61, "avg_pnl": 28.40, ...},
     "BALANCED":     {"n": 42, "win_rate": 0.52, "avg_pnl": 12.10, ...},
     ...
  },
  "top_keywords":   [{"kw": "raised guidance", "expectancy": 41.0}, ...],
  "weak_keywords":  [{"kw": "speculation", "expectancy": -8.0}, ...]
}

Modules that read it
────────────────────
  - opportunity_urgency:    multi-day narrative-persistence weighting
  - parameter_tuning:       expectancy-based bound adjustment
  - conviction_engine:      empirical lift on plans matching strong setups
  - dashboard:              render the empirical edge table

NO synthetic intelligence is involved. Every score derives from a
realized PnL that actually settled on Alpaca. The lookback window is
configurable (default 60 days). When data is thin (< 5 samples for a
bucket), expectancy is reported as `null` rather than guessed.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION = "4.0"
DEFAULT_LOOKBACK_DAYS = 60
MIN_SAMPLES_FOR_EXPECTANCY = 5

# Catalyst keyword tagging — same set used in three_month_filter.STRONG_CATALYST_KEYWORDS
# plus a few common "soft" markers so we can tag every close even if it
# wasn't a strong-catalyst rescue. Order matters: we tag with the first match.
_STRONG_KEYWORDS = (
    "blowout", "smashed estimates", "beats estimates",
    "raised guidance", "raises guidance", "guidance raised",
    "upgrade to buy", "upgraded to buy", "raised target",
    "fda approval", "fda approves", "phase 3",
    "index inclusion", "added to s&p", "added to nasdaq-100",
    "all-time high", "record revenue", "record earnings",
    "buyback", "share repurchase", "spinoff", "spin-off",
    "merger", "acquires", "to acquire", "acquisition",
    "breakout", "surge", "surges", "surging",
    "strong demand", "strong guidance", "raises outlook",
    "blowout quarter",
)
_SOFT_KEYWORDS = (
    "beat", "growth", "revenue grew", "new product",
    "analyst", "expansion", "deal", "partnership",
    "guidance", "outlook", "demand",
)


def _safe_f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _classify_catalyst(text: Optional[str]) -> str:
    """Returns 'strong' / 'soft' / 'none' for a headline or trigger_reason."""
    if not text:
        return "none"
    t = str(text).lower()
    for kw in _STRONG_KEYWORDS:
        if kw in t:
            return "strong"
    for kw in _SOFT_KEYWORDS:
        if kw in t:
            return "soft"
    return "none"


def _extract_keyword(text: Optional[str]) -> Optional[str]:
    """Return the FIRST matching strong/soft keyword in `text`, if any."""
    if not text:
        return None
    t = str(text).lower()
    for kw in _STRONG_KEYWORDS:
        if kw in t:
            return kw
    for kw in _SOFT_KEYWORDS:
        if kw in t:
            return kw
    return None


def _bucket_key(
    signal: str, regime: str, catalyst_class: str,
    three_m: str, elite: bool,
) -> str:
    """Compose the setup-bucket key. Pipe-separated for human readability."""
    return f"{signal}|{regime}|{catalyst_class}|{three_m}|{'elite' if elite else 'normal'}"


def _summarize_bucket(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute win-rate, avg_pnl, expectancy, hold-days for a bucket."""
    n = len(rows)
    if n == 0:
        return {"n": 0, "wins": 0, "losses": 0,
                "win_rate": None, "avg_pnl": 0.0,
                "expectancy": None, "median_hold_days": None}
    wins = sum(1 for r in rows if r["realized_pnl"] > 0)
    losses = n - wins
    pnls = [r["realized_pnl"] for r in rows]
    holds = [r["hold_days"] for r in rows if r.get("hold_days") is not None]
    avg_pnl = sum(pnls) / n
    # Expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
    win_pnls = [p for p in pnls if p > 0]
    loss_pnls = [-p for p in pnls if p <= 0]  # losses as positive
    if win_pnls and loss_pnls:
        avg_win = sum(win_pnls) / len(win_pnls)
        avg_loss = sum(loss_pnls) / len(loss_pnls)
        win_rate = len(win_pnls) / n
        expectancy = (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss)
    elif win_pnls:
        expectancy = sum(win_pnls) / n
    elif loss_pnls:
        expectancy = -sum(loss_pnls) / n
    else:
        expectancy = 0.0
    median_hold = statistics.median(holds) if holds else None
    enough = n >= MIN_SAMPLES_FOR_EXPECTANCY
    return {
        "n":               int(n),
        "wins":            int(wins),
        "losses":          int(losses),
        "win_rate":        round(wins / n, 4),
        "avg_pnl":         round(avg_pnl, 2),
        "expectancy":      round(expectancy, 2) if enough else None,
        "median_hold_days": round(median_hold, 2) if median_hold is not None else None,
    }


def _gather_closes(
    data_dir: Path,
    lookback_days: int,
) -> List[Dict[str, Any]]:
    """Walk every alpaca_*_state.json and pull CLOSE orders inside the window.

    Each close row is augmented with whatever entry metadata we can find.
    Currently entry metadata is sparse in state files; we use:
      - trigger_reason (close-side) for catalyst tagging
      - account_id    for regime breakdown
      - time, hold_days (from first_seen if present in position_meta history)
    """
    out: List[Dict[str, Any]] = []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days))
    for p in sorted(data_dir.glob("alpaca_*_state.json")):
        try:
            body = json.loads(p.read_text())
        except Exception:
            continue
        if not isinstance(body, dict):
            continue
        aid = body.get("account_id") or p.stem
        orders = body.get("orders") or []
        for o in orders[-500:]:
            if not isinstance(o, dict):
                continue
            if o.get("action") != "CLOSE":
                continue
            ts = _parse_iso(o.get("time") or o.get("timestamp"))
            if ts is None or ts < cutoff:
                continue
            symbol = (o.get("symbol") or "").upper()
            if not symbol or symbol in ("SGOV", "BIL", "SHY", "TFLO", "USFR"):
                continue
            pnl = _safe_f(o.get("realized_pnl"))
            trigger = o.get("trigger_reason", "") or ""
            entry_iso = o.get("entry_time") or o.get("first_seen") or o.get("opened_at")
            entry_ts = _parse_iso(entry_iso)
            hold_days = None
            if entry_ts is not None:
                hold_days = max(0.0, (ts - entry_ts).total_seconds() / 86400.0)
            out.append({
                "symbol":       symbol,
                "account":      aid,
                "time":         ts.isoformat(),
                "realized_pnl": pnl,
                "trigger":      trigger,
                "hold_days":    hold_days,
                # Best-effort entry-side classification (sparse data).
                "consensus_signal": o.get("entry_consensus_signal")
                                    or o.get("consensus_signal")
                                    or "BUY",
                "market_regime":    o.get("entry_market_mode")
                                    or o.get("market_mode")
                                    or "BALANCED",
                "three_month":      o.get("entry_three_month_signal")
                                    or "unknown",
                "elite":            bool(o.get("entry_elite")
                                          or o.get("elite_at_entry")),
                "catalyst_text":    o.get("entry_catalyst_text")
                                    or o.get("headline_at_entry")
                                    or trigger,
            })
    return out


def compute_validation(
    data_dir: Path,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute the full validation scorecard and return it."""
    closes = _gather_closes(data_dir, lookback_days)
    n = len(closes)

    # Setup-bucket aggregation.
    setups: Dict[str, List[Dict[str, Any]]] = {}
    catalysts: Dict[str, List[Dict[str, Any]]] = {}
    regimes: Dict[str, List[Dict[str, Any]]] = {}
    catalyst_classes: Dict[str, List[Dict[str, Any]]] = {}

    for c in closes:
        ccls = _classify_catalyst(c.get("catalyst_text"))
        key = _bucket_key(
            (c.get("consensus_signal") or "BUY").upper(),
            (c.get("market_regime") or "BALANCED").upper(),
            ccls,
            (c.get("three_month") or "unknown"),
            bool(c.get("elite")),
        )
        setups.setdefault(key, []).append(c)
        regimes.setdefault((c.get("market_regime") or "BALANCED").upper(),
                            []).append(c)
        catalyst_classes.setdefault(ccls, []).append(c)
        kw = _extract_keyword(c.get("catalyst_text"))
        if kw:
            catalysts.setdefault(kw, []).append(c)

    setup_summary    = {k: _summarize_bucket(v) for k, v in setups.items()}
    regime_summary   = {k: _summarize_bucket(v) for k, v in regimes.items()}
    cat_class_summary = {k: _summarize_bucket(v) for k, v in catalyst_classes.items()}
    kw_summary       = {k: _summarize_bucket(v) for k, v in catalysts.items()}

    # Top / weak keywords by expectancy (only buckets with enough samples).
    keyword_ranked: List[Tuple[str, Dict[str, Any]]] = sorted(
        ((k, v) for k, v in kw_summary.items()
         if v.get("expectancy") is not None),
        key=lambda kv: kv[1]["expectancy"], reverse=True,
    )
    top_keywords = [
        {"kw": k, "expectancy": v["expectancy"], "n": v["n"],
         "win_rate": v["win_rate"]}
        for k, v in keyword_ranked[:10]
        if v["expectancy"] > 0
    ]
    weak_keywords = [
        {"kw": k, "expectancy": v["expectancy"], "n": v["n"],
         "win_rate": v["win_rate"]}
        for k, v in reversed(keyword_ranked[-10:])
        if v["expectancy"] is not None and v["expectancy"] < 0
    ]

    n_ts = now or datetime.now(timezone.utc)
    payload = {
        "version":        VERSION,
        "generated_at":   n_ts.isoformat(),
        "lookback_days":  int(lookback_days),
        "n_closes":       int(n),
        "setups":         setup_summary,
        "regimes":        regime_summary,
        "catalyst_classes": cat_class_summary,
        "catalysts":      kw_summary,
        "top_keywords":   top_keywords,
        "weak_keywords":  weak_keywords,
    }
    return payload


def write_validation(
    data_dir: Path,
    payload: Dict[str, Any],
) -> None:
    """Persist signal_validation.json."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "signal_validation.json").write_text(
            json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[signal_validation] write failed: {e}")


def load_validation(data_dir: Path) -> Dict[str, Any]:
    """Read signal_validation.json (safe default if missing)."""
    p = data_dir / "signal_validation.json"
    if not p.exists():
        return {"version": VERSION, "setups": {}, "regimes": {},
                "catalysts": {}, "top_keywords": [], "weak_keywords": []}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"version": VERSION, "setups": {}, "regimes": {},
                "catalysts": {}, "top_keywords": [], "weak_keywords": []}


def get_catalyst_lift(
    data_dir: Optional[Path],
    catalyst_text: Optional[str],
) -> float:
    """Module helper: return an empirical lift factor for a given catalyst
    keyword, derived from historical expectancy. Returns 1.0 if there isn't
    enough data — never lies, never invents.

    Used by conviction_engine to weight a plan up/down based on whether
    the matched catalyst keyword has been a winner historically.
    """
    if not data_dir or not catalyst_text:
        return 1.0
    body = load_validation(data_dir)
    cats = body.get("catalysts") or {}
    kw = _extract_keyword(catalyst_text)
    if not kw or kw not in cats:
        return 1.0
    row = cats[kw]
    exp = row.get("expectancy")
    if exp is None:
        return 1.0
    # Map expectancy → lift. $0 expectancy = 1.0; +$50 ≈ 1.20; -$50 ≈ 0.85.
    # Bounded so a single hot keyword can't blow out sizing.
    lift = 1.0 + max(-0.15, min(0.20, float(exp) / 250.0))
    return round(lift, 4)


def get_regime_expectancy(
    data_dir: Optional[Path],
    regime: str,
) -> Optional[float]:
    """Return historical avg PnL for the given regime, or None if thin."""
    if not data_dir:
        return None
    body = load_validation(data_dir)
    row = (body.get("regimes") or {}).get((regime or "").upper())
    if not row:
        return None
    return row.get("expectancy")


__all__ = [
    "VERSION",
    "compute_validation",
    "write_validation",
    "load_validation",
    "get_catalyst_lift",
    "get_regime_expectancy",
]
