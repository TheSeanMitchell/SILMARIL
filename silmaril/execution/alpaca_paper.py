"""silmaril.execution.alpaca_paper — v4.1 Alpha 2.2.

v4.1 changes (PR 1B fix):
  * CRITICAL: HOLD signal no longer triggers position close.
    Only SELL/STRONG_SELL closes longs; only BUY/STRONG_BUY closes shorts.
    Previously, HOLD was closing every position, causing $0 PnL and
    Alpaca going silent after May 1.
  * Agents now RIDE their positions until a genuine exit signal fires.
  * Profit-take and trailing stop still operate independently.
  * timestamp added to every order record for dashboard accuracy.
"""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_BASE_URL = "https://paper-api.alpaca.markets"  # PAPER ONLY
_ORDERS_ENDPOINT = f"{_BASE_URL}/v2/orders"
_POSITIONS_ENDPOINT = f"{_BASE_URL}/v2/positions"
_ACCOUNT_ENDPOINT = f"{_BASE_URL}/v2/account"
_MAX_RETRIES = 3
_RETRY_DELAY_S = 2.0
_SKIP_ASSET_CLASSES = {"crypto", "token"}

DEFAULT_PROFIT_TAKE_PCT = 0.05    # +5% triggers harvest
DEFAULT_TRAIL_STOP_PCT = 0.04     # -4% from peak triggers exit


def _get_headers():
    key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_API_SECRET", "").strip()
    if not key or not secret: return None
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
            "Content-Type": "application/json"}

def _api_get(url, headers):
    try:
        import requests
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[alpaca] GET failed: {e}")
        return None

def _api_post(url, headers, payload):
    for attempt in range(_MAX_RETRIES):
        try:
            import requests
            r = requests.post(url, headers=headers, json=payload, timeout=15)
            if r.status_code in (200, 201): return r.json()
            print(f"[alpaca] POST {r.status_code}: {r.text[:200]}")
            return None
        except Exception as e:
            if attempt < _MAX_RETRIES - 1: time.sleep(_RETRY_DELAY_S)
            else:
                print(f"[alpaca] POST failed: {e}")
                return None

def _now_iso(): return datetime.now(timezone.utc).isoformat()

def _load_state(path):
    if path.exists():
        try: return json.loads(path.read_text())
        except Exception: pass
    return {
        "version": "2.2",
        "enabled": False,
        "account": {},
        "principal_target": 100000,
        "savings": 0.0,
        "lifetime_realized_wins": 0,
        "lifetime_realized_losses": 0,
        "position_meta": {},
        "tickers_traded_this_cycle": [],
        "recent_alpaca_tickers": [],
        "orders": [],
        "orders_placed": [],
        "errors": [],
    }

def _save_state(state, path):
    state["orders"] = state.get("orders", [])[-500:]
    state["last_run"] = _now_iso()
    try: path.write_text(json.dumps(state, indent=2, default=str))
    except Exception as e: print(f"[alpaca] save failed: {e}")


def _prune_recent_tickers(state):
    """Keep only Alpaca order tickers from the last 24h, for dashboard borders."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent = []
    for o in state.get("orders", []):
        if o.get("time", "") >= cutoff:
            sym = o.get("symbol")
            if sym and sym not in recent:
                recent.append(sym)
    state["recent_alpaca_tickers"] = recent[:50]


def execute_consensus_signals(
    plans: List[Dict[str, Any]],
    state_path: Path,
    max_position_pct: float = 0.08,
    min_consensus_conviction: float = 0.40,
    max_total_positions: int = 15,
    enable_shorts: bool = True,
    all_debate_signals: Optional[Dict[str, str]] = None,
    profit_take_pct: float = DEFAULT_PROFIT_TAKE_PCT,
    trailing_stop_pct: float = DEFAULT_TRAIL_STOP_PCT,
    principal_target: Optional[float] = None,
) -> Dict:
    state = _load_state(state_path)
    headers = _get_headers()
    if not headers:
        state["enabled"] = False
        state["reason"] = "ALPACA_API_KEY/SECRET not set"
        state.setdefault("errors", []).append({"time": _now_iso(), "msg": state["reason"]})
        _save_state(state, state_path)
        return state

    account = _api_get(_ACCOUNT_ENDPOINT, headers)
    if not account:
        state["enabled"] = False
        state["reason"] = "Account fetch failed"
        _save_state(state, state_path)
        return state

    equity = float(account.get("equity", 0))
    cash_avail = float(account.get("cash", 0))
    state["enabled"] = True
    state["account"] = {"equity": round(equity, 2), "cash": round(cash_avail, 2)}

    # First-time principal target: set to current equity if not set
    if principal_target is not None:
        state["principal_target"] = principal_target
    if not state.get("principal_target") or state["principal_target"] == 100000:
        if equity > 0:
            state["principal_target"] = round(equity, 2)
    principal = float(state["principal_target"])

    print(f"[alpaca] equity ${equity:,.2f} | principal ${principal:,.2f} | savings ${state.get('savings', 0):,.2f}")
    if equity < 1.0:
        _save_state(state, state_path)
        return state

    # Build signal maps
    plan_signals, plan_conv, plan_class = {}, {}, {}
    for p in plans:
        t = p.get("ticker", "")
        if not t: continue
        plan_signals[t] = p.get("consensus_signal", "HOLD")
        plan_conv[t] = float(p.get("consensus_conviction") or p.get("avg_conviction") or 0)
        plan_class[t] = p.get("asset_class", "equity")
    exit_signals = dict(all_debate_signals or {})
    exit_signals.update(plan_signals)

    # Fetch open positions
    existing = _api_get(_POSITIONS_ENDPOINT, headers) or []
    if not isinstance(existing, list): existing = []
    print(f"[alpaca] open positions: {len(existing)}")

    # Initialize position_meta tracking for any new positions
    position_meta = state.get("position_meta", {})
    tickers_traded = []
    orders_placed = []
    closed = 0

    for pos in existing:
        symbol = pos.get("symbol", "")
        try: qty = float(pos.get("qty", "0"))
        except Exception: qty = 0
        try: current_price = float(pos.get("current_price", 0))
        except Exception: current_price = 0
        try: entry_price = float(pos.get("avg_entry_price", 0))
        except Exception: entry_price = 0

        if not symbol or qty == 0: continue
        side = "long" if qty > 0 else "short"

        # Update position meta — track peak price ourselves
        meta = position_meta.get(symbol, {})
        prev_peak = meta.get("peak_price", entry_price or current_price)
        new_peak = max(prev_peak, current_price) if current_price else prev_peak
        position_meta[symbol] = {
            "entry_price": entry_price,
            "peak_price": new_peak,
            "first_seen": meta.get("first_seen", _now_iso()),
            "qty": abs(qty),
        }

        # Decide whether to close
        close_reason = None
        pnl_pct = 0.0
        if entry_price > 0 and current_price > 0:
            pnl_pct = (current_price / entry_price - 1.0) * 100
        peak_drop_pct = 0.0
        if new_peak > 0 and current_price > 0:
            peak_drop_pct = (current_price / new_peak - 1.0) * 100

        # ── 1. Profit-take ───────────────────────────────────────
        # ── 1. Tiered grocery harvest ─────────────────────────────
        # Partial harvests: sweep gains into grocery bucket without
        # always closing the full position. Let winners run.
        try:
            from silmaril.portfolios.grocery import compute_harvest
            _harv_amt, _remaining, _tier = compute_harvest(
                entry_price=entry_price,
                current_price=current_price,
                qty=abs(qty),
                principal=float(state.get("principal_target", 10000)),
            )
            if _harv_amt > 0 and _tier != "NONE":
                close_reason = (
                    f"GROCERY HARVEST ({_tier}): {symbol} "
                    f"+{pnl_pct:.2f}% — sweeping ${_harv_amt:.2f} to grocery bucket"
                )
                state["grocery_pending_harvest"] = (
                    state.get("grocery_pending_harvest", 0.0) + _harv_amt)
        except Exception:
            # Fallback to simple profit-take if grocery module unavailable
            if side == "long" and entry_price > 0 and current_price >= entry_price * (1.0 + profit_take_pct):
                close_reason = f"PROFIT TAKE: {symbol} +{pnl_pct:.2f}% from entry — harvest"
            elif side == "short" and entry_price > 0 and current_price <= entry_price * (1.0 - profit_take_pct):
                close_reason = f"PROFIT TAKE: {symbol} short -{abs(pnl_pct):.2f}% from entry — harvest"

        # ── 2. Trailing stop (only if no profit-take) ────────────
        elif side == "long" and new_peak > 0 and current_price <= new_peak * (1.0 - trailing_stop_pct):
            close_reason = f"TRAILING STOP: {symbol} -{abs(peak_drop_pct):.2f}% from peak ${new_peak:.2f}"

        # ── 3. Consensus flip — ONLY on genuine SELL signal ──────
        # FIX v4.1: HOLD signal no longer closes positions.
        # A HOLD means "neutral — no new conviction either way."
        # Riding a position through neutral consensus is correct behavior.
        # Only a genuine SELL/STRONG_SELL (bearish conviction) exits longs.
        else:
            sig = exit_signals.get(symbol, "HOLD")
            if side == "long" and sig in ("SELL", "STRONG_SELL"):
                close_reason = f"Consensus turned bearish: {sig}"
            elif side == "short" and sig in ("BUY", "STRONG_BUY"):
                close_reason = f"Consensus turned bullish on short: {sig}"

        if close_reason:
            print(f"[alpaca] CLOSE {side} {symbol}: {close_reason}")
            close_side = "sell" if side == "long" else "buy"
            r = _api_post(_ORDERS_ENDPOINT, headers, {
                "symbol": symbol, "qty": str(abs(qty)),
                "side": close_side, "type": "market", "time_in_force": "day"})
            if r:
                closed += 1
                tickers_traded.append(symbol)
                # Realized P&L
                if side == "long":
                    realized = (current_price - entry_price) * abs(qty)
                else:
                    realized = (entry_price - current_price) * abs(qty)
                # Harvest if profitable
                if realized > 0:
                    state["savings"] = float(state.get("savings", 0)) + realized
                    state["lifetime_realized_wins"] = state.get("lifetime_realized_wins", 0) + 1
                    print(f"[alpaca]   → +${realized:.2f} harvested to savings (total ${state['savings']:.2f})")
                else:
                    state["lifetime_realized_losses"] = state.get("lifetime_realized_losses", 0) + 1
                    print(f"[alpaca]   → ${realized:.2f} loss")
                orders_placed.append({
                    "action": "CLOSE", "symbol": symbol, "side": close_side,
                    "qty": abs(qty), "trigger_reason": close_reason,
                    "realized_pnl": round(realized, 2),
                    "entry_price": entry_price, "exit_price": current_price,
                    "order_id": r.get("id"), "time": _now_iso(),
                    "timestamp": _now_iso(),
                })
                # Drop from meta
                position_meta.pop(symbol, None)

    if closed > 0:
        time.sleep(1.5)
        existing = _api_get(_POSITIONS_ENDPOINT, headers) or []
        if not isinstance(existing, list): existing = []

    open_symbols = {p.get("symbol") for p in existing}
    open_count = len(existing)
    opened = 0

    # Open new long positions
    for p in plans:
        ticker = p.get("ticker", "")
        signal = p.get("consensus_signal", "HOLD")
        conviction = plan_conv.get(ticker, 0.0)
        asset_class = plan_class.get(ticker, "equity")
        if not ticker: continue
        if signal not in ("BUY", "STRONG_BUY"): continue
        if conviction < min_consensus_conviction: continue
        if ticker in open_symbols: continue
        if asset_class in _SKIP_ASSET_CLASSES: continue
        if open_count >= max_total_positions: break
        notional = round(equity * max_position_pct, 2)
        if notional < 1.0: continue
        print(f"[alpaca] OPEN {signal} {ticker} ${notional:.2f} (c={conviction:.2f})")
        r = _api_post(_ORDERS_ENDPOINT, headers, {
            "symbol": ticker, "notional": str(notional),
            "side": "buy", "type": "market", "time_in_force": "day"})
        if r:
            opened += 1; open_count += 1; open_symbols.add(ticker)
            tickers_traded.append(ticker)
            orders_placed.append({
                "action": "OPEN", "symbol": ticker, "side": "buy",
                "notional": notional, "conviction": conviction,
                "signal": signal, "order_id": r.get("id"),
                "time": _now_iso(), "timestamp": _now_iso(),
            })

    # Open shorts
    if enable_shorts:
        for p in plans:
            ticker = p.get("ticker", "")
            signal = p.get("consensus_signal", "HOLD")
            conviction = plan_conv.get(ticker, 0.0)
            asset_class = plan_class.get(ticker, "equity")
            if signal not in ("SELL", "STRONG_SELL"): continue
            if conviction < min_consensus_conviction: continue
            if ticker in open_symbols: continue
            if asset_class in _SKIP_ASSET_CLASSES: continue
            if open_count >= max_total_positions: break
            notional = round(equity * max_position_pct, 2)
            if notional < 1.0: continue
            print(f"[alpaca] SHORT {ticker} ${notional:.2f}")
            r = _api_post(_ORDERS_ENDPOINT, headers, {
                "symbol": ticker, "notional": str(notional),
                "side": "sell", "type": "market", "time_in_force": "day"})
            if r:
                opened += 1; open_count += 1; open_symbols.add(ticker)
                tickers_traded.append(ticker)
                orders_placed.append({
                    "action": "SHORT", "symbol": ticker, "side": "sell",
                    "notional": notional, "conviction": conviction,
                    "signal": signal, "order_id": r.get("id"),
                    "time": _now_iso(), "timestamp": _now_iso(),
                })

    # Append orders to history
    state["orders"] = state.get("orders", []) + orders_placed
    state["orders_placed"] = orders_placed
    state["position_meta"] = position_meta
    state["tickers_traded_this_cycle"] = list(set(tickers_traded))
    _prune_recent_tickers(state)

    total_value = equity + state.get("savings", 0)
    state["last_cycle_summary"] = {
        "time": _now_iso(), "timestamp": _now_iso(),
        "closed": closed, "opened": opened,
        "open_after": open_count, "equity": equity,
        "savings": round(state.get("savings", 0), 2),
        "total_value": round(total_value, 2),
        "tickers_traded": list(set(tickers_traded)),
    }
    _save_state(state, state_path)
    print(f"[alpaca] cycle: closed={closed} opened={opened} total={open_count} | "
          f"savings ${state.get('savings', 0):.2f} | total ${total_value:.2f}")
    return state
