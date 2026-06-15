"""Trailing stop + momentum stall exit logic for all agent portfolios."""
from __future__ import annotations
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_TRAILING_STOP_PCT: float = 0.06
DEFAULT_MAX_HOLD_DAYS: int = 3
DEFAULT_MOMENTUM_STALL_THRESHOLD: float = -0.005
ABSOLUTE_MAX_HOLD_DAYS: int = 7

AGENT_EXIT_CONFIG: Dict[str, Dict[str, Any]] = {
    "THUNDERHEAD":  {"trailing_stop_pct": 0.04, "max_hold_days": 2},
    "FORGE":        {"trailing_stop_pct": 0.06, "max_hold_days": 3},
    "JADE":         {"trailing_stop_pct": 0.07, "max_hold_days": 4},
    "KESTREL":      {"trailing_stop_pct": 0.04, "max_hold_days": 2},
    "KESTREL+":     {"trailing_stop_pct": 0.04, "max_hold_days": 2},
    "ZENITH":       {"trailing_stop_pct": 0.08, "max_hold_days": 5},
    "WEAVER":       {"trailing_stop_pct": 0.03, "max_hold_days": 1},
    "SPECK":        {"trailing_stop_pct": 0.07, "max_hold_days": 3},
    "VESPA":        {"trailing_stop_pct": 0.05, "max_hold_days": 2},
    "HEX":          {"trailing_stop_pct": 0.05, "max_hold_days": 3},
    "SYNTH":        {"trailing_stop_pct": 0.06, "max_hold_days": 4},
    "VEIL":         {"trailing_stop_pct": 0.06, "max_hold_days": 3},
    "OBSIDIAN":     {"trailing_stop_pct": 0.07, "max_hold_days": 5},
    "MAGUS":        {"trailing_stop_pct": 0.05, "max_hold_days": 3},
    "TALON":        {"trailing_stop_pct": 0.06, "max_hold_days": 3},
    "AEGIS":        {"trailing_stop_pct": 0.03, "max_hold_days": 5},
    "BARON":        {"trailing_stop_pct": 0.07, "max_hold_days": 4},
    "STEADFAST":    {"trailing_stop_pct": 0.10, "max_hold_days": 30},
    "CONTRARIAN":   {"trailing_stop_pct": 0.05, "max_hold_days": 3},
    "SHORT_ALPHA":  {"trailing_stop_pct": 0.04, "max_hold_days": 2},
    "NOMAD":        {"trailing_stop_pct": 0.06, "max_hold_days": 4},
    "BARNACLE":     {"trailing_stop_pct": 0.06, "max_hold_days": 5},
    "ATLAS":        {"trailing_stop_pct": 0.05, "max_hold_days": 3},
    "NIGHTSHADE":   {"trailing_stop_pct": 0.05, "max_hold_days": 2},
    "CICADA":       {"trailing_stop_pct": 0.05, "max_hold_days": 2},
    "SHEPHERD":     {"trailing_stop_pct": 0.06, "max_hold_days": 4},
    "BIOS":         {"trailing_stop_pct": 0.05, "max_hold_days": 3},
}

def get_agent_config(agent_codename: str) -> Dict[str, Any]:
    o = AGENT_EXIT_CONFIG.get(agent_codename, {})
    return {
        "trailing_stop_pct": o.get("trailing_stop_pct", DEFAULT_TRAILING_STOP_PCT),
        "max_hold_days": o.get("max_hold_days", DEFAULT_MAX_HOLD_DAYS),
        "momentum_stall_threshold": o.get(
            "momentum_stall_threshold", DEFAULT_MOMENTUM_STALL_THRESHOLD),
    }

def update_peak_price(position: Dict[str, Any], current_price: float) -> Dict[str, Any]:
    if current_price and current_price > 0:
        current_peak = position.get("peak_price") or position.get("entry_price") or current_price
        if current_price > current_peak:
            position["peak_price"] = current_price
    return position

def record_price_snapshot(position: Dict[str, Any], current_price: float) -> Dict[str, Any]:
    if current_price and current_price > 0:
        snapshots = position.get("price_snapshots", [])
        snapshots.append(current_price)
        position["price_snapshots"] = snapshots[-10:]
    return position

def _days_held(position: Dict[str, Any], today: str) -> int:
    entry_date = position.get("entry_date", today)
    try:
        return max(0, (date.fromisoformat(today) - date.fromisoformat(entry_date)).days)
    except Exception:
        return 0

def check_exit_conditions(
    position: Dict[str, Any],
    current_price: Optional[float],
    today: str,
    trailing_stop_pct: float = DEFAULT_TRAILING_STOP_PCT,
    max_hold_days: int = DEFAULT_MAX_HOLD_DAYS,
    momentum_stall_threshold: float = DEFAULT_MOMENTUM_STALL_THRESHOLD,
) -> Tuple[bool, str]:
    if not current_price or current_price <= 0:
        return False, ""
    ticker = position.get("ticker", "?")
    entry_price = position.get("entry_price") or current_price
    peak_price = position.get("peak_price") or entry_price
    if peak_price > 0:
        if current_price < peak_price * (1.0 - trailing_stop_pct):
            drop = (current_price / peak_price - 1.0) * 100
            return True, (f"TRAILING STOP: {ticker} fell {drop:.1f}% "
                          f"from peak {peak_price:.4f} to {current_price:.4f}")
    days = _days_held(position, today)
    if days >= ABSOLUTE_MAX_HOLD_DAYS:
        return True, f"HARD CAP: {ticker} held {days}d >= {ABSOLUTE_MAX_HOLD_DAYS}d"
    if days >= max_hold_days:
        snapshots: List[float] = position.get("price_snapshots", [])
        if len(snapshots) >= 2:
            last_return = (snapshots[-1] - snapshots[-2]) / snapshots[-2]
            if last_return < momentum_stall_threshold:
                return True, (f"MOMENTUM STALL: {ticker} held {days}d, "
                              f"last session {last_return*100:+.2f}%")
        else:
            return True, f"MAX HOLD: {ticker} held {days}d without snapshot data"
    return False, ""
