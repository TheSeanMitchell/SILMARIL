"""silmaril.portfolios.bleed_exit — Alpha 3.2 narrow-window hold pruning.

What it does
────────────
The operator's brief: "Every 30 minutes there should be an assessment.
If for four 30-minute sessions in a row the value keeps dropping more
than half a percent, for a total of more than 2 percent over two hours,
sell it off."

This module gives the existing close-decision loop in alpaca_paper.py a
fourth exit branch (alongside profit-take, trailing-stop, consensus-flip)
that fires when a held position has been quietly bleeding intraday.

How the 30-minute window is enforced
────────────────────────────────────
Daily.yml fires the main cycle every 5–10 minutes during market hours.
We do NOT take a snapshot on every cycle — that would let the bleed
test trip on noise. Instead, each position in `position_meta` carries a
`snapshots_30m` list of `{"ts": iso, "price": float}` entries; a new
entry is appended ONLY when the most recent one is at least
`MIN_INTERVAL_MIN = 28` minutes old. A grace gap of 2 minutes absorbs
cron jitter so we don't miss a window when GitHub Actions runs 12:01
instead of 11:59.

The trigger
───────────
Bleed-exit fires when BOTH of these are true:
  (a) the most recent FOUR interval returns (i.e. snapshots[-5:-1] vs
      [-4:]) are each ≤ -0.5%, AND
  (b) the cumulative drop from snapshots[-5] to snapshots[-1] is ≤ -2.0%.

Why both? A single -0.6% blip should NOT fire it; nor should a slow
-2.1% drift that didn't lose ground in every window. The operator's
sentence requires both: "four 30-minute sessions in a row dropping
more than half a percent, for a total of more than 2 percent."

Tunables — top-level constants. Senate breeder may eventually mutate
these per agent in the same way it does staleness aggression, but for
3.2 they're fixed.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Sampling cadence: append a new 30m snapshot once this many minutes
# have passed since the last one. 28-minute floor leaves a 2-minute
# grace window for cron jitter so a 10:30 cycle that fires at 10:32
# still produces a clean half-hour sample.
MIN_INTERVAL_MIN: int = 28

# How many half-hour intervals to keep. Five snapshots = four intervals
# = two hours of history. Trim aggressively so position_meta stays small.
MAX_SNAPSHOTS: int = 8

# Trigger thresholds (negative numbers = drops).
LEG_DROP_PCT: float = -0.005   # each 30m leg must be ≤ -0.5%
CUMULATIVE_DROP_PCT: float = -0.02   # 2-hour total must be ≤ -2.0%
REQUIRED_CONSECUTIVE_LEGS: int = 4   # four legs in a row


def _parse_ts(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def update_30min_snapshots(
    meta: Dict[str, Any],
    current_price: Optional[float],
    now: Optional[datetime] = None,
    min_interval_min: int = MIN_INTERVAL_MIN,
    max_snapshots: int = MAX_SNAPSHOTS,
) -> Dict[str, Any]:
    """Append a new snapshot to `meta["snapshots_30m"]` if the last entry
    is old enough. Returns the (possibly-updated) meta dict.

    Always mutates `meta` in place AND returns it so callers can chain.
    Side-effect free if `current_price` is missing or non-positive.

    Snapshot shape: {"ts": ISO-UTC-string, "price": float}.
    """
    if not current_price or current_price <= 0:
        return meta
    snaps: List[Dict[str, Any]] = list(meta.get("snapshots_30m") or [])
    n = now or _now_utc()
    # Decide whether to append a new snapshot
    do_append = True
    if snaps:
        last_ts = _parse_ts(snaps[-1].get("ts"))
        if last_ts is not None:
            elapsed = (n - last_ts).total_seconds() / 60.0
            if elapsed < float(min_interval_min):
                do_append = False
    if do_append:
        snaps.append({"ts": n.isoformat(), "price": float(current_price)})
        # Trim
        if len(snaps) > max_snapshots:
            snaps = snaps[-max_snapshots:]
        meta["snapshots_30m"] = snaps
    return meta


def evaluate_bleed(
    snapshots: List[Dict[str, Any]],
    leg_drop_pct: float = LEG_DROP_PCT,
    cumulative_drop_pct: float = CUMULATIVE_DROP_PCT,
    required_legs: int = REQUIRED_CONSECUTIVE_LEGS,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Decide whether the bleed-exit rule has tripped.

    Returns: (fired, reason, components)
      fired:      True when both conditions hold and the position should sell.
      reason:     human-readable close_reason for the orders log.
      components: structured detail for the advisory ledger / dashboard.

    Components dict shape:
      {
        "legs_required":   4,
        "legs_observed":   3,
        "leg_returns":     [-0.0061, -0.0042, ...],
        "cumulative_pct":  -0.0231,
        "window_minutes":  120,
        "fired":           bool,
      }
    """
    components: Dict[str, Any] = {
        "legs_required":   required_legs,
        "legs_observed":   0,
        "leg_returns":     [],
        "cumulative_pct":  0.0,
        "window_minutes":  0,
        "fired":           False,
    }
    if not snapshots or len(snapshots) < required_legs + 1:
        return False, "", components

    # We need the LAST required_legs+1 snapshots to evaluate required_legs legs.
    window = snapshots[-(required_legs + 1):]
    prices = [float(s.get("price") or 0) for s in window]
    if any(p <= 0 for p in prices):
        return False, "", components

    # Build the per-leg returns
    legs: List[float] = []
    for i in range(1, len(prices)):
        prev = prices[i - 1]
        cur = prices[i]
        if prev <= 0:
            return False, "", components
        legs.append((cur - prev) / prev)
    components["leg_returns"] = [round(l, 5) for l in legs]
    components["legs_observed"] = len(legs)

    # Cumulative drop across the whole window
    cumulative = (prices[-1] - prices[0]) / prices[0]
    components["cumulative_pct"] = round(cumulative, 5)
    # Window minutes (best effort — ts may be missing)
    t_first = _parse_ts(window[0].get("ts"))
    t_last = _parse_ts(window[-1].get("ts"))
    if t_first and t_last:
        components["window_minutes"] = int((t_last - t_first).total_seconds() / 60.0)

    all_legs_bad = all(l <= leg_drop_pct for l in legs)
    cumulative_bad = cumulative <= cumulative_drop_pct
    components["fired"] = bool(all_legs_bad and cumulative_bad)

    if not components["fired"]:
        return False, "", components

    reason = (
        f"BLEED EXIT: {len(legs)}× 30m down "
        f"(cum {cumulative*100:+.2f}% over {components['window_minutes']}min, "
        f"legs " + ", ".join(f"{l*100:+.2f}%" for l in legs) + ")"
    )
    return True, reason, components


def check_position_for_bleed(
    position_meta: Dict[str, Any],
    symbol: str,
    current_price: Optional[float],
    now: Optional[datetime] = None,
    data_dir: Optional[Path] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """One-shot helper used by the close loop in alpaca_paper.py.

    Updates the symbol's snapshot list (mutates `position_meta` in place)
    and then evaluates the bleed rule on the updated list.

    Alpha 3.3: when `data_dir` is provided, the leg/cumulative thresholds
    are looked up from tuning_state.json (set by parameter_tuning) and
    fall back to the module-level defaults if unset or out of bounds.

    Returns (fired, reason, components) — same shape as `evaluate_bleed`.
    """
    if not position_meta or not symbol:
        return False, "", {}
    meta = position_meta.get(symbol) or {}
    if not isinstance(meta, dict):
        return False, "", {}
    meta = update_30min_snapshots(meta, current_price, now=now)
    position_meta[symbol] = meta
    snaps = meta.get("snapshots_30m") or []
    # Pull tuned thresholds if available
    leg = LEG_DROP_PCT
    cum = CUMULATIVE_DROP_PCT
    if data_dir is not None:
        try:
            from ..learning.parameter_tuning import get_tuned_value as _gt
            leg = _gt(data_dir, "bleed_exit.LEG_DROP_PCT", LEG_DROP_PCT)
            cum = _gt(data_dir, "bleed_exit.CUMULATIVE_DROP_PCT", CUMULATIVE_DROP_PCT)
        except Exception:
            pass
    return evaluate_bleed(snaps, leg_drop_pct=leg, cumulative_drop_pct=cum)


__all__ = [
    "MIN_INTERVAL_MIN",
    "MAX_SNAPSHOTS",
    "LEG_DROP_PCT",
    "CUMULATIVE_DROP_PCT",
    "REQUIRED_CONSECUTIVE_LEGS",
    "update_30min_snapshots",
    "evaluate_bleed",
    "check_position_for_bleed",
]
