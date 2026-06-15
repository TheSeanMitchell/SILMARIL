"""
silmaril.learning.slippage — Realistic fill modeling.

Real-world fills slip. Mid-price assumptions overstate strategy returns.
This module applies a context-aware slippage cost to every BUY/SELL action
so equity curves are realistic.

Slippage scales with:
  - Liquidity (large-cap = small slippage; small-cap = large)
  - Volatility (high IV = wider spreads)
  - Asset class (crypto > equities > FX > index ETF)
  - Order size relative to volume
"""
from __future__ import annotations

from typing import Optional


# Base slippage in basis points by asset class
BASE_SLIPPAGE_BPS = {
    "equity": 8,        # large-cap default
    "etf": 3,           # tight spreads
    "crypto": 25,       # wider, varies by venue
    "fx": 5,
    "commodity_etf": 6,
    "bond_etf": 4,
    "small_cap": 25,
    "memecoin": 75,
    "prediction_market": 50,
}


def estimate_slippage_bps(
    asset_class: str,
    realized_vol: Optional[float] = None,
    is_small_cap: bool = False,
    order_size_usd: Optional[float] = None,
    daily_volume_usd: Optional[float] = None,
) -> float:
    """Return slippage in basis points (1bp = 0.01%)."""
    if is_small_cap:
        base = BASE_SLIPPAGE_BPS["small_cap"]
    else:
        base = BASE_SLIPPAGE_BPS.get(asset_class, 10)

    # Volatility adjustment
    if realized_vol is not None:
        if realized_vol > 0.40:
            base *= 1.8
        elif realized_vol > 0.25:
            base *= 1.3
        elif realized_vol < 0.10:
            base *= 0.8

    # Size impact: if order > 0.5% of daily volume, add price-impact slippage
    if order_size_usd and daily_volume_usd and daily_volume_usd > 0:
        participation = order_size_usd / daily_volume_usd
        if participation > 0.005:
            # Linear price impact above 0.5% participation
            extra = (participation - 0.005) * 5000  # 5000 bps per 100% participation
            base += min(extra, 100)  # cap at 100bps

    return base


def apply_slippage_to_price(price: float, side: str, bps: float) -> float:
    """
    Adjust fill price by slippage. BUY pays more, SELL receives less.
    """
    factor = bps / 10000.0
    if side.upper() in ("BUY", "STRONG_BUY", "COVER"):
        return price * (1 + factor)
    elif side.upper() in ("SELL", "STRONG_SELL", "SHORT"):
        return price * (1 - factor)
    return price


def apply_slippage_to_pnl(
    entry_price: float,
    exit_price: float,
    side: str,
    asset_class: str,
    realized_vol: Optional[float] = None,
    is_small_cap: bool = False,
) -> dict:
    """
    Compute round-trip slippage cost and slipped P&L for any closed trade.
    Returns: {gross_pnl, slippage_cost, net_pnl, slippage_bps}
    """
    bps = estimate_slippage_bps(asset_class, realized_vol, is_small_cap)
    # Round-trip: pay slippage on entry AND exit
    slipped_entry = apply_slippage_to_price(entry_price, side, bps)
    slipped_exit = apply_slippage_to_price(
        exit_price, "SELL" if side in ("BUY", "STRONG_BUY") else "BUY", bps
    )
    if side in ("BUY", "STRONG_BUY"):
        gross = exit_price - entry_price
        net = slipped_exit - slipped_entry
    else:  # SHORT
        gross = entry_price - exit_price
        net = slipped_entry - slipped_exit

    return {
        "gross_pnl": gross,
        "net_pnl": net,
        "slippage_cost": gross - net,
        "slippage_bps": bps,
    }
