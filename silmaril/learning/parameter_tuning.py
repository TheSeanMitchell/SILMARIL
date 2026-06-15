"""silmaril.learning.parameter_tuning — Alpha 4.0 self-tuning feedback.

What changed in 4.0
───────────────────
1. Expanded threshold coverage — Alpha 4.0 ships several new tunable
   knobs that the bounded optimizer can move within safe ranges:
        conviction_engine.ROTATE_SCORE_DELTA
        conviction_engine.FORCED_ROTATE_DELTA
        conviction_engine.PRUNE_HOLDING_SCORE
        conviction_engine.IDLE_CASH_PCT          (carry-over)
        opportunity_urgency.URGENT_THRESHOLD

2. Setup expectancy attribution — instead of only tracking bleed_exit
   wins/losses, the tuner now consumes signal_validation.json's bucketed
   win-rate / expectancy data and uses it to bias adjustments. When a
   setup class (e.g. ATTACK + STRONG_BUY + strong catalyst) has a long
   positive expectancy, we LOOSEN the gates that approve it (lower
   ROTATE_SCORE_DELTA, lower URGENT_THRESHOLD). When a class has
   negative expectancy, we TIGHTEN those gates.

3. Two-API compatibility for get_tuned_value:
     • Legacy:  get_tuned_value(data_dir, key, default)  — used by 3.3 callers
     • New:     get_tuned_value(category, name, default) — used by 4.0
       callers that don't have data_dir readily threaded. The new form
       searches the conventional locations (silmaril/docs/data) on disk
       once and memoizes for the cycle.

All proposed adjustments remain bounded, capped at ±10% of the range
per cycle, and never modify code constants — they're written to
`tuning_state.json` and consumed only via `get_tuned_value`.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


TUNING_FILENAME = "tuning_state.json"

# Bounded ranges per threshold. The tuner never proposes a value outside these.
THRESHOLD_BOUNDS: Dict[str, Dict[str, float]] = {
    # ── bleed_exit (carry-over) ────────────────────────────────────────────
    "bleed_exit.LEG_DROP_PCT":                {"min": -0.008, "max": -0.003, "default": -0.005, "step": 0.0005},
    "bleed_exit.CUMULATIVE_DROP_PCT":         {"min": -0.035, "max": -0.015, "default": -0.020, "step": 0.0010},

    # ── three_month_filter (carry-over + 4.0 stays at defaults) ───────────
    "three_month_filter.DOWNTREND_THRESHOLD": {"min": -0.080, "max": -0.030, "default": -0.050, "step": 0.0050},

    # ── elite_mode (carry-over) ───────────────────────────────────────────
    "elite_mode.MIN_CONVICTION":              {"min":  0.550, "max":  0.720, "default":  0.650, "step": 0.0100},
    "elite_mode.MIN_CATALYST":                {"min":  0.450, "max":  0.650, "default":  0.550, "step": 0.0100},

    # ── conviction_engine (4.0 — expanded) ────────────────────────────────
    "conviction_engine.IDLE_CASH_PCT":        {"min":  0.030, "max":  0.080, "default":  0.050, "step": 0.0050},
    "conviction_engine.ROTATE_SCORE_DELTA":   {"min":  0.150, "max":  0.300, "default":  0.200, "step": 0.0100},
    "conviction_engine.FORCED_ROTATE_DELTA":  {"min":  0.250, "max":  0.400, "default":  0.300, "step": 0.0100},
    "conviction_engine.PRUNE_HOLDING_SCORE":  {"min":  0.200, "max":  0.350, "default":  0.250, "step": 0.0100},

    # ── opportunity_urgency (4.0 — NEW) ───────────────────────────────────
    "opportunity_urgency.URGENT_THRESHOLD":   {"min":  0.550, "max":  0.750, "default":  0.650, "step": 0.0100},
}

# Cap on per-cycle delta as a fraction of the bound width
MAX_DELTA_FRACTION = 0.10

# In-process cache for get_tuned_value, to avoid re-reading the disk on every
# call in a tight loop. Keyed by the resolved data_dir path.
_TUNING_CACHE: Dict[str, Dict[str, Any]] = {}
_TUNING_CACHE_TS: Dict[str, float] = {}
_CACHE_TTL_SECONDS = 30.0


def _safe_f(x, default: float = 0.0) -> float:
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _load_state(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / TUNING_FILENAME)
    if not isinstance(body, dict):
        body = {}
    body.setdefault("version", "4.0")
    body.setdefault("proposed", {})       # threshold_key → value
    body.setdefault("history",  [])       # list of {ts, threshold, from, to, reason}
    body.setdefault("attribution", {})    # threshold_key → {wins, losses, samples}
    body.setdefault("setup_expectancy", {})  # setup_key → expectancy summary
    return body


def _save_state(data_dir: Path, body: Dict[str, Any]) -> None:
    body["updated_at"] = datetime.now(timezone.utc).isoformat()
    body["version"] = "4.0"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / TUNING_FILENAME).write_text(
            json.dumps(body, indent=2, default=str))
    except Exception as e:
        print(f"[parameter_tuning] save failed: {e}")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ── Outcome / attribution ──────────────────────────────────────────────────
def _gather_close_outcomes(
    data_dir: Path,
    lookback_days: int = 14,
) -> List[Dict[str, Any]]:
    """Walk every alpaca_*_state.json and pull recent CLOSE orders."""
    outcomes: List[Dict[str, Any]] = []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    for p in sorted(data_dir.glob("alpaca_*_state.json")):
        try:
            body = json.loads(p.read_text())
        except Exception:
            continue
        if not isinstance(body, dict):
            continue
        aid = body.get("account_id") or p.stem
        for o in (body.get("orders") or [])[-200:]:
            if not isinstance(o, dict):
                continue
            if o.get("action") != "CLOSE":
                continue
            t = o.get("time") or ""
            if t < cutoff:
                continue
            pnl = _safe_f(o.get("realized_pnl"))
            outcomes.append({
                "ticker": (o.get("symbol") or "").upper(),
                "realized_pnl": pnl,
                "time": t,
                "trigger_reason": o.get("trigger_reason", ""),
                "entry_signal":   o.get("entry_signal", ""),
                "entry_regime":   o.get("entry_regime", ""),
                "entry_catalyst": o.get("entry_catalyst_label", ""),
                "is_elite_entry": bool(o.get("is_elite_entry", False)),
                "account": aid,
            })
    return outcomes


def _classify_trigger(reason: str) -> Optional[str]:
    """Map a close trigger_reason to its threshold key."""
    if not reason:
        return None
    r = reason.upper()
    if r.startswith("BLEED EXIT"):
        return "bleed_exit.LEG_DROP_PCT"
    if "ROTATE" in r or "FORCED_ROTATE" in r:
        return "conviction_engine.ROTATE_SCORE_DELTA"
    if "PRUNE" in r:
        return "conviction_engine.PRUNE_HOLDING_SCORE"
    if "URGENT" in r or "URGENCY" in r:
        return "opportunity_urgency.URGENT_THRESHOLD"
    return None


def attribute_outcomes(
    outcomes: List[Dict[str, Any]],
) -> Dict[str, Dict[str, int]]:
    """For each threshold, count wins/losses from closes attributed to it."""
    attribution: Dict[str, Dict[str, int]] = {
        key: {"wins": 0, "losses": 0, "samples": 0}
        for key in THRESHOLD_BOUNDS
    }
    for o in outcomes:
        key = _classify_trigger(o.get("trigger_reason", ""))
        if not key:
            continue
        pnl = _safe_f(o.get("realized_pnl"))
        # Trigger-specific win heuristics:
        if key == "bleed_exit.LEG_DROP_PCT":
            # Win if early exit prevented a deeper loss (heuristic threshold)
            if pnl > -100.0:
                attribution[key]["wins"] += 1
            else:
                attribution[key]["losses"] += 1
        elif key in ("conviction_engine.ROTATE_SCORE_DELTA",
                     "conviction_engine.PRUNE_HOLDING_SCORE",
                     "opportunity_urgency.URGENT_THRESHOLD"):
            # Win if the action that triggered the close was profitable;
            # ROTATE/PRUNE/URGENT closes are wins iff realized_pnl > 0
            if pnl > 0:
                attribution[key]["wins"] += 1
            else:
                attribution[key]["losses"] += 1
        else:
            continue
        attribution[key]["samples"] += 1
    return attribution


# ── Setup expectancy bias (4.0 — NEW) ─────────────────────────────────────
def _load_setup_expectancy(data_dir: Path) -> Dict[str, Any]:
    """Read signal_validation.json bucketed expectancy if it exists.

    Expected shape (defensive):
        {
          "buckets": {
              "STRONG_BUY|ATTACK|strong|uptrend|elite": {
                  "win_rate": 0.62, "expectancy_usd": 84.0, "n": 18, ...
              },
              ...
          }
        }
    Returns the buckets dict or {} if file is missing/unreadable.
    """
    doc = _load_json(data_dir / "signal_validation.json")
    if not isinstance(doc, dict):
        return {}
    buckets = doc.get("buckets") or doc.get("setup_expectancy") or {}
    if not isinstance(buckets, dict):
        return {}
    return buckets


def _expectancy_bias_for(
    bucket_filter: str,
    buckets: Dict[str, Any],
    min_samples: int = 5,
) -> Optional[float]:
    """Aggregate expectancy across buckets matching `bucket_filter` substring.

    Returns a bias in [-1, +1]:
        positive  = aggregate is profitable (loosen gates)
        negative  = aggregate is losing (tighten gates)
        None      = insufficient samples
    """
    total_n = 0
    weighted_exp = 0.0
    weighted_wr  = 0.0
    for key, stats in buckets.items():
        if not isinstance(key, str) or not isinstance(stats, dict):
            continue
        if bucket_filter and bucket_filter.upper() not in key.upper():
            continue
        n = int(stats.get("n") or stats.get("samples") or 0)
        if n <= 0:
            continue
        wr = _safe_f(stats.get("win_rate"), 0.5)
        exp = _safe_f(stats.get("expectancy_usd"), 0.0)
        total_n += n
        weighted_exp += exp * n
        weighted_wr  += wr * n
    if total_n < min_samples:
        return None
    avg_wr  = weighted_wr / total_n
    avg_exp = weighted_exp / total_n
    # Bias: positive when win_rate > 0.5 and expectancy > 0; negative otherwise.
    # Map to [-1, +1] saturating.
    wr_signal  = max(-1.0, min(1.0, (avg_wr - 0.5) * 4.0))  # ±0.5 → ±1.0
    exp_signal = max(-1.0, min(1.0, avg_exp / 100.0))       # ±$100 → ±1.0
    return 0.5 * wr_signal + 0.5 * exp_signal


# ── Proposal logic ─────────────────────────────────────────────────────────
def propose_adjustments(
    data_dir: Path,
    *,
    lookback_days: int = 14,
) -> Dict[str, Any]:
    """Compute new proposed threshold values, persist, and return them."""
    state = _load_state(data_dir)
    outcomes = _gather_close_outcomes(data_dir, lookback_days=lookback_days)
    attribution = attribute_outcomes(outcomes)
    setup_buckets = _load_setup_expectancy(data_dir)

    proposed: Dict[str, float] = dict(state.get("proposed", {}))
    history: List[Dict[str, Any]] = list(state.get("history", []))

    # Setup-expectancy biases used by certain threshold updates
    overall_bias    = _expectancy_bias_for("",          setup_buckets) or 0.0
    attack_bias     = _expectancy_bias_for("ATTACK",    setup_buckets) or 0.0
    elite_bias      = _expectancy_bias_for("ELITE",     setup_buckets) or 0.0
    strong_buy_bias = _expectancy_bias_for("STRONG_BUY", setup_buckets) or 0.0

    for key, bounds in THRESHOLD_BOUNDS.items():
        attr = attribution.get(key, {"wins": 0, "losses": 0, "samples": 0})
        current = float(proposed.get(key, bounds["default"]))
        samples = attr["samples"]
        delta_width = (bounds["max"] - bounds["min"]) * MAX_DELTA_FRACTION

        new_val: Optional[float] = None
        reason_bits: List[str] = []

        if key.startswith("bleed_exit"):
            # Existing 3.3 logic: bleed_exit uses its own attribution path
            if samples < 5:
                continue
            win_rate = attr["wins"] / max(1, samples)
            if win_rate >= 0.65:
                new_val = current + delta_width   # toward zero = looser
                reason_bits.append(f"loosen on {win_rate:.0%} win, n={samples}")
            elif win_rate <= 0.40:
                new_val = current - delta_width   # more negative = tighter
                reason_bits.append(f"tighten on {win_rate:.0%} win, n={samples}")
            else:
                continue

        elif key == "conviction_engine.ROTATE_SCORE_DELTA":
            # Use overall + ATTACK bias. If ATTACK setups print positive
            # expectancy, lower the rotate delta so we rotate sooner.
            bias = 0.6 * attack_bias + 0.4 * overall_bias
            if abs(bias) < 0.15:
                continue
            # bias > 0 means winning → lower the delta (loosen rotate gate)
            new_val = current - bias * delta_width
            reason_bits.append(
                f"bias {bias:+.2f} (attack {attack_bias:+.2f}, overall "
                f"{overall_bias:+.2f})"
            )

        elif key == "conviction_engine.FORCED_ROTATE_DELTA":
            # Tied to overall bias only — forced rotations need strong
            # signal regardless of regime
            bias = overall_bias
            if abs(bias) < 0.20:
                continue
            new_val = current - bias * delta_width
            reason_bits.append(f"overall bias {bias:+.2f}")

        elif key == "conviction_engine.PRUNE_HOLDING_SCORE":
            # If prune outcomes are winning, raise the score floor (we're
            # being too eager to prune); if losing, lower it.
            if samples < 5:
                continue
            win_rate = attr["wins"] / max(1, samples)
            if win_rate >= 0.65:
                new_val = current + delta_width   # higher score → less pruning
                reason_bits.append(f"prunes profitable {win_rate:.0%}, n={samples}")
            elif win_rate <= 0.40:
                new_val = current - delta_width   # lower score → more pruning
                reason_bits.append(f"prunes losing {win_rate:.0%}, n={samples}")
            else:
                continue

        elif key == "conviction_engine.IDLE_CASH_PCT":
            # If overall + strong_buy buckets are profitable, lower the
            # idle floor (we want cash deployed faster); otherwise raise.
            bias = 0.5 * overall_bias + 0.5 * strong_buy_bias
            if abs(bias) < 0.20:
                continue
            new_val = current - bias * delta_width
            reason_bits.append(
                f"bias {bias:+.2f} (overall {overall_bias:+.2f}, "
                f"strong_buy {strong_buy_bias:+.2f})"
            )

        elif key == "opportunity_urgency.URGENT_THRESHOLD":
            # Combine attribution win-rate (urgent-triggered closes) with
            # the elite/attack bias from signal_validation.
            wr_signal = 0.0
            if samples >= 5:
                win_rate = attr["wins"] / max(1, samples)
                wr_signal = (win_rate - 0.5) * 2.0     # ±0.5 → ±1.0
            bias = 0.5 * wr_signal + 0.3 * elite_bias + 0.2 * attack_bias
            if abs(bias) < 0.20:
                continue
            # Profitable urgents → lower threshold so MORE qualify
            new_val = current - bias * delta_width
            reason_bits.append(
                f"bias {bias:+.2f} (urgent-WR {wr_signal:+.2f}, "
                f"elite {elite_bias:+.2f}, attack {attack_bias:+.2f}, "
                f"n={samples})"
            )

        elif key.startswith("elite_mode") or key.startswith("three_month_filter"):
            # 4.0 doesn't auto-tune these yet (would interact too strongly
            # with hand-tuned mode logic). Hold at default.
            continue

        else:
            continue

        if new_val is None:
            continue
        new_val = _clamp(new_val, bounds["min"], bounds["max"])
        if abs(new_val - current) < bounds["step"] / 2:
            continue
        proposed[key] = round(new_val, 5)
        history.append({
            "ts":        datetime.now(timezone.utc).isoformat(),
            "threshold": key,
            "from":      round(current, 5),
            "to":        proposed[key],
            "samples":   samples,
            "reason":    "; ".join(reason_bits) if reason_bits else "tune",
        })

    state["proposed"]        = proposed
    state["history"]         = history[-200:]
    state["attribution"]     = attribution
    state["lookback_days"]   = lookback_days
    state["samples_total"]   = sum(a["samples"] for a in attribution.values())
    state["setup_expectancy"] = {
        "overall_bias":    round(overall_bias, 4),
        "attack_bias":     round(attack_bias, 4),
        "elite_bias":      round(elite_bias, 4),
        "strong_buy_bias": round(strong_buy_bias, 4),
        "bucket_count":    len(setup_buckets),
    }
    _save_state(data_dir, state)
    # Invalidate the in-process cache so callers immediately see new values
    _TUNING_CACHE.clear()
    _TUNING_CACHE_TS.clear()
    return state


# ── Reader (dual-API for back-compat + ergonomic new use) ─────────────────
def _resolve_data_dir_auto() -> Optional[Path]:
    """Look for a docs/data dir relative to the silmaril package or CWD.

    The 4.0 callers (conviction_engine, opportunity_urgency, etc.) call
    `get_tuned_value(category, name, default)` without a data_dir. We
    auto-resolve based on environment + the conventional layout.
    """
    env = os.environ.get("SILMARIL_DATA_DIR", "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    # Search up from this file's location
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        candidate = parent / "docs" / "data"
        if candidate.exists():
            return candidate
        candidate = parent / "data"
        if candidate.exists() and (candidate / TUNING_FILENAME).exists():
            return candidate
    # Last-ditch: CWD
    cwd_docs = Path.cwd() / "docs" / "data"
    if cwd_docs.exists():
        return cwd_docs
    return None


def _cached_state_for(data_dir: Path) -> Dict[str, Any]:
    import time as _time
    key = str(data_dir.resolve())
    now = _time.time()
    if (key in _TUNING_CACHE
            and (now - _TUNING_CACHE_TS.get(key, 0)) < _CACHE_TTL_SECONDS):
        return _TUNING_CACHE[key]
    state = _load_state(data_dir)
    _TUNING_CACHE[key] = state
    _TUNING_CACHE_TS[key] = now
    return state


def get_tuned_value(
    first: Union[Path, str, None],
    second: Union[str, float],
    third: Optional[float] = None,
) -> float:
    """Read a tuned value, returning the default if unset/unreadable.

    Two calling forms are supported:

    Legacy (3.3 callers):
        get_tuned_value(data_dir, key, default)
            first  = Path (or None)
            second = "category.name" string
            third  = float default
        Example:
            get_tuned_value(data_dir, "bleed_exit.LEG_DROP_PCT", -0.005)

    New (4.0 callers without data_dir threading):
        get_tuned_value(category, name, default)
            first  = "category" string (no dot)
            second = "name" string
            third  = float default
        Example:
            get_tuned_value("conviction_engine", "ROTATE_SCORE_DELTA", 0.20)
        data_dir is auto-resolved from env or the conventional layout.
    """
    # Detect calling form
    if isinstance(first, (Path,)) or (isinstance(first, str)
                                      and ("/" in first or first.endswith("data"))):
        # Legacy form
        data_dir = Path(first) if first else None
        key = str(second)
        default = float(third) if third is not None else 0.0
    elif first is None:
        # Legacy with no data_dir
        data_dir = _resolve_data_dir_auto()
        key = str(second)
        default = float(third) if third is not None else 0.0
    elif isinstance(first, str) and "." not in first and isinstance(second, str):
        # New form: (category, name, default)
        data_dir = _resolve_data_dir_auto()
        key = f"{first}.{second}"
        default = float(third) if third is not None else 0.0
    else:
        # Best-effort fallback — treat first as data_dir-like and second as key
        try:
            data_dir = Path(str(first)) if first else _resolve_data_dir_auto()
        except Exception:
            data_dir = _resolve_data_dir_auto()
        key = str(second)
        default = float(third) if third is not None else 0.0

    if not data_dir:
        return default
    try:
        state = _cached_state_for(data_dir)
        val = (state.get("proposed") or {}).get(key)
        if val is None:
            return default
        return float(val)
    except Exception:
        return default


__all__ = [
    "THRESHOLD_BOUNDS",
    "TUNING_FILENAME",
    "propose_adjustments",
    "get_tuned_value",
    "attribute_outcomes",
]
