"""silmaril.portfolios.correlation_control — Alpha 3.3 concentration caps.

What it does
────────────
The Alpaca executor in 3.2 had a `max_total_positions` count cap but
no awareness of WHAT was being held. If consensus picks 5 semiconductor
names in one cycle, the legacy path opens all 5 — a single sector
correction would crater the account.

This module enforces concentration limits across two axes:
  - by sector (Tech, Health Care, Financials, ...)
  - by asset_class (equity, etf, crypto, ...)

It also provides a pre-trade `can_open(ticker)` check the executor
calls before submitting an OPEN.

Caps are policy-driven via the dict in `policy.correlation_limits` so
market_state can tighten them in DEFENSIVE/PRESERVATION modes and
loosen them in ATTACK. Defaults below.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# Defaults — overridable by ExecutionPolicy
DEFAULT_LIMITS: Dict[str, Any] = {
    "max_per_sector":      3,    # at most 3 positions in any one sector
    "max_per_asset_class": 8,    # at most 8 ETFs, 8 equities, etc.
    "max_sector_book_pct": 0.30, # at most 30% of book in one sector
}


def _safe_f(x, default=0.0) -> float:
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _lookup_sector(ticker: str,
                    sector_lookup: Optional[Dict[str, str]] = None) -> str:
    """Return the sector name for a ticker, falling back to 'Unknown'."""
    if sector_lookup and ticker.upper() in sector_lookup:
        return sector_lookup[ticker.upper()] or "Unknown"
    return "Unknown"


def _lookup_asset_class(ticker: str,
                         asset_class_lookup: Optional[Dict[str, str]] = None) -> str:
    if asset_class_lookup and ticker.upper() in asset_class_lookup:
        return asset_class_lookup[ticker.upper()] or "equity"
    # Defensive fallback via universe helper if available
    try:
        from ..universe.core import asset_class_of
        return asset_class_of(ticker) or "equity"
    except Exception:
        return "equity"


def build_concentration_snapshot(
    positions: List[Dict[str, Any]],
    *,
    sector_lookup: Optional[Dict[str, str]] = None,
    asset_class_lookup: Optional[Dict[str, str]] = None,
    trading_capital: float = 10_000.0,
) -> Dict[str, Any]:
    """Summarize current concentration across sector and asset class.

    Returns:
      {
        "sectors":      {"Technology": {"count": 3, "market_value": 1500, "pct": 0.15}, ...},
        "asset_classes": {"equity": {"count": 5, "market_value": 4200, "pct": 0.42}, ...},
        "tickers_by_sector": {"Technology": ["NVDA", "AMD", "MSFT"], ...},
        "total_market_value": 7800,
        "trading_capital":    10000,
      }
    """
    sectors: Dict[str, Dict[str, Any]] = {}
    asset_classes: Dict[str, Dict[str, Any]] = {}
    tickers_by_sector: Dict[str, List[str]] = {}
    total_mv = 0.0

    for pos in positions or []:
        sym = (pos.get("symbol") or pos.get("ticker") or "").upper()
        if not sym:
            continue
        # Skip vault tickers entirely — they aren't risk capital
        if sym in ("SGOV", "BIL", "SHY", "TFLO", "USFR"):
            continue
        mv = _safe_f(pos.get("market_value"))
        total_mv += mv
        sec = _lookup_sector(sym, sector_lookup)
        ac = _lookup_asset_class(sym, asset_class_lookup)
        sectors.setdefault(sec, {"count": 0, "market_value": 0.0, "pct": 0.0})
        asset_classes.setdefault(ac, {"count": 0, "market_value": 0.0, "pct": 0.0})
        sectors[sec]["count"] += 1
        sectors[sec]["market_value"] += mv
        asset_classes[ac]["count"] += 1
        asset_classes[ac]["market_value"] += mv
        tickers_by_sector.setdefault(sec, []).append(sym)

    cap = trading_capital if trading_capital > 0 else 1.0
    for s in sectors.values():
        s["pct"] = round(s["market_value"] / cap, 4)
        s["market_value"] = round(s["market_value"], 2)
    for a in asset_classes.values():
        a["pct"] = round(a["market_value"] / cap, 4)
        a["market_value"] = round(a["market_value"], 2)

    return {
        "sectors":            sectors,
        "asset_classes":      asset_classes,
        "tickers_by_sector":  tickers_by_sector,
        "total_market_value": round(total_mv, 2),
        "trading_capital":    round(cap, 2),
    }


def can_open(
    ticker: str,
    *,
    concentration: Dict[str, Any],
    proposed_notional: float,
    sector_lookup: Optional[Dict[str, str]] = None,
    asset_class_lookup: Optional[Dict[str, str]] = None,
    limits: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Pre-trade concentration check.

    Returns (ok, reason, detail).
      ok=True if the open is allowed.
      reason="" if ok, otherwise human-readable.
      detail carries the relevant counts/percentages so the rejection
      log can show "Technology already 3/3 at 0.32 of book".
    """
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    sym = (ticker or "").upper()
    sec = _lookup_sector(sym, sector_lookup)
    ac = _lookup_asset_class(sym, asset_class_lookup)
    sectors = concentration.get("sectors") or {}
    asset_classes = concentration.get("asset_classes") or {}
    trading_capital = _safe_f(concentration.get("trading_capital"), 10_000.0)
    proposed = _safe_f(proposed_notional)

    sec_info = sectors.get(sec) or {"count": 0, "market_value": 0.0, "pct": 0.0}
    ac_info = asset_classes.get(ac) or {"count": 0, "market_value": 0.0, "pct": 0.0}

    # Sector count cap
    if sec_info["count"] >= int(limits["max_per_sector"]):
        return False, (
            f"Sector '{sec}' already at {sec_info['count']} positions "
            f"(cap {limits['max_per_sector']})"
        ), {"sector": sec, "info": sec_info, "limits": limits}

    # Asset class count cap
    if ac_info["count"] >= int(limits["max_per_asset_class"]):
        return False, (
            f"Asset class '{ac}' already at {ac_info['count']} positions "
            f"(cap {limits['max_per_asset_class']})"
        ), {"asset_class": ac, "info": ac_info, "limits": limits}

    # Sector book-percentage cap (post-trade)
    if trading_capital > 0:
        new_sector_pct = (sec_info["market_value"] + proposed) / trading_capital
        if new_sector_pct > float(limits["max_sector_book_pct"]):
            return False, (
                f"Sector '{sec}' would be {new_sector_pct*100:.1f}% of book "
                f"after open (cap {limits['max_sector_book_pct']*100:.0f}%)"
            ), {
                "sector": sec, "proposed_pct": round(new_sector_pct, 4),
                "limits": limits,
            }

    return True, "", {"sector": sec, "asset_class": ac}


__all__ = [
    "DEFAULT_LIMITS",
    "build_concentration_snapshot",
    "can_open",
]
