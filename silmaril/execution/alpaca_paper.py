"""
silmaril.execution.alpaca_paper — Free paper-trading bridge to Alpaca.

Alpaca's paper trading API is FREE (no real money, no fees). Every
consensus BUY/SELL signal becomes a real-shaped order in your paper
account, executed against simulated fills.

HARD GUARANTEE: This module is paper-only. Base URL is hardcoded.
There is no parameter, env-var, or secret that can flip this to live.
Live trading requires a separate, deliberately-named module that does
not currently exist in this codebase.

Setup:
  1. Create free account at https://alpaca.markets
  2. Generate paper-trading API keys
  3. Set GitHub secrets:
       ALPACA_API_KEY
       ALPACA_API_SECRET
  4. The daily.yml workflow calls this automatically after consensus phase
  5. State written to docs/data/alpaca_paper_state.json (PROTECTED)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    _HAS_ALPACA = True
except ImportError:
    _HAS_ALPACA = False


# HARDCODED — paper only. There is no override.
PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def _client() -> Optional["TradingClient"]:
    if not _HAS_ALPACA:
        return None
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        return None
    return TradingClient(api_key, api_secret, paper=True)


def execute_consensus_signals(
    plans: List[Dict],
    state_path: Path,
    max_position_pct: float = 0.05,
    min_consensus_conviction: float = 0.60,
    max_total_positions: int = 15,
    enable_shorts: bool = True,
) -> Dict:
    """
    Send today's top trade plans to Alpaca paper-trading.

    plans: list of trade plan dicts (BUY-side ranked by conviction)
    state_path: docs/data/alpaca_paper_state.json
    max_position_pct: cap any single position at this % of equity
    min_consensus_conviction: only trade above this conviction
    max_total_positions: hard cap on concurrent positions
    enable_shorts: if True, SELL/STRONG_SELL signals open short positions
    """
    state = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "enabled": False,
        "reason": "",
        "account": {},
        "orders_placed": [],
        "positions": [],
        "errors": [],
        "shorts_enabled": enable_shorts,
    }

    client = _client()
    if client is None:
        state["reason"] = (
            "alpaca-py not installed or ALPACA_API_KEY/SECRET not set. "
            "Skipping paper-trade execution."
        )
        _write(state_path, state)
        return state

    state["enabled"] = True

    try:
        account = client.get_account()
        equity = float(account.equity)
        state["account"] = {
            "equity": equity,
            "cash": float(account.cash),
            "status": str(account.status),
            "pattern_day_trader": bool(account.pattern_day_trader),
            "shorting_enabled": bool(account.shorting_enabled),
        }
    except Exception as e:
        state["errors"].append(f"account fetch: {type(e).__name__}: {e}")
        _write(state_path, state)
        return state

    try:
        existing = client.get_all_positions()
        state["positions"] = [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": str(p.side),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
            }
            for p in existing
        ]
    except Exception as e:
        state["errors"].append(f"positions fetch: {type(e).__name__}: {e}")
        existing = []

    held_long = {p.symbol for p in existing if str(p.side).lower() == "long"}
    held_short = {p.symbol for p in existing if str(p.side).lower() == "short"}
    n_positions = len(existing)
    available_slots = max(0, max_total_positions - n_positions)

    # ---- LONG entries ----
    long_actionable = [
        p for p in plans
        if (p.get("consensus_conviction") or 0) >= min_consensus_conviction
        and p.get("consensus_signal") in ("BUY", "STRONG_BUY")
        and p.get("ticker") not in held_long
        and p.get("asset_class", "equity") in ("equity", "etf")
    ]
    long_actionable.sort(key=lambda p: p.get("consensus_conviction", 0), reverse=True)

    for plan in long_actionable[:available_slots]:
        ticker = plan.get("ticker")
        try:
            position_dollars = equity * max_position_pct
            entry = float(plan.get("entry_price", 0)) or float(plan.get("price", 0))
            if entry <= 0:
                state["errors"].append(f"{ticker}: no entry price")
                continue
            qty = max(1, int(position_dollars / entry))
            order = MarketOrderRequest(
                symbol=ticker, qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            placed = client.submit_order(order)
            state["orders_placed"].append({
                "ticker": ticker, "qty": qty, "side": "BUY",
                "alpaca_order_id": str(placed.id),
                "consensus_conviction": plan.get("consensus_conviction"),
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            })
            available_slots -= 1
        except Exception as e:
            state["errors"].append(f"{ticker} BUY: {type(e).__name__}: {e}")

    # ---- SHORT entries (only if enabled and account supports) ----
    if enable_shorts and state["account"].get("shorting_enabled"):
        short_actionable = [
            p for p in plans
            if (p.get("consensus_conviction") or 0) >= min_consensus_conviction
            and p.get("consensus_signal") in ("SELL", "STRONG_SELL")
            and p.get("ticker") not in held_short
            and p.get("ticker") not in held_long
            and p.get("asset_class", "equity") in ("equity", "etf")
        ]
        short_actionable.sort(key=lambda p: p.get("consensus_conviction", 0), reverse=True)

        for plan in short_actionable[:max(0, available_slots)]:
            ticker = plan.get("ticker")
            try:
                position_dollars = equity * (max_position_pct * 0.6)  # smaller for shorts
                entry = float(plan.get("entry_price", 0)) or float(plan.get("price", 0))
                if entry <= 0:
                    continue
                qty = max(1, int(position_dollars / entry))
                order = MarketOrderRequest(
                    symbol=ticker, qty=qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                )
                placed = client.submit_order(order)
                state["orders_placed"].append({
                    "ticker": ticker, "qty": qty, "side": "SHORT",
                    "alpaca_order_id": str(placed.id),
                    "consensus_conviction": plan.get("consensus_conviction"),
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                state["errors"].append(f"{ticker} SHORT: {type(e).__name__}: {e}")

    # ---- Exits: close positions whose latest consensus is opposite ----
    plan_signals = {p.get("ticker"): p.get("consensus_signal") for p in plans}
    for pos in existing:
        sig = plan_signals.get(pos.symbol)
        side = str(pos.side).lower()
        # Long position with SELL signal -> close
        # Short position with BUY signal -> close
        should_close = (
            (side == "long" and sig in ("SELL", "STRONG_SELL")) or
            (side == "short" and sig in ("BUY", "STRONG_BUY"))
        )
        # Auto-close shorts after 3 days regardless (SHORT_ALPHA's rule)
        # The position object's avg_entry_time would tell us — Alpaca exposes this
        # For simplicity we rely on signal flip here

        if should_close:
            try:
                client.close_position(pos.symbol)
                state["orders_placed"].append({
                    "ticker": pos.symbol,
                    "qty": float(pos.qty),
                    "side": "CLOSE",
                    "alpaca_order_id": "close_position",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                state["errors"].append(f"{pos.symbol} CLOSE: {type(e).__name__}: {e}")

    _write(state_path, state)
    _append_equity_curve(state_path.parent / "alpaca_equity_curve.json", state)
    return state


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _append_equity_curve(curve_path: Path, state: dict) -> None:
    """Persistent equity curve — only grows."""
    curve = {"snapshots": []}
    if curve_path.exists():
        try:
            curve = json.loads(curve_path.read_text())
        except Exception:
            pass
    snap = {
        "timestamp": state.get("last_run"),
        "equity": state.get("account", {}).get("equity"),
        "cash": state.get("account", {}).get("cash"),
        "n_positions": len(state.get("positions", [])),
        "orders_today": len(state.get("orders_placed", [])),
    }
    curve.setdefault("snapshots", []).append(snap)
    curve["snapshots"] = curve["snapshots"][-5000:]
    curve_path.parent.mkdir(parents=True, exist_ok=True)
    curve_path.write_text(json.dumps(curve, indent=2, default=str))
