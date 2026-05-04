"""silmaril.execution.alpaca_paper — v2 with HOLD-exit + all_debate_signals."""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_BASE_URL = "https://paper-api.alpaca.markets"  # PAPER ONLY — hardcoded
_ORDERS_ENDPOINT = f"{_BASE_URL}/v2/orders"
_POSITIONS_ENDPOINT = f"{_BASE_URL}/v2/positions"
_ACCOUNT_ENDPOINT = f"{_BASE_URL}/v2/account"
_MAX_RETRIES = 3
_RETRY_DELAY_S = 2.0
_SKIP_ASSET_CLASSES = {"crypto", "token"}

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
    return {"orders": [], "orders_placed": [], "last_run": None,
            "account": {}, "errors": [], "enabled": False}

def _save_state(state, path):
    state["orders"] = state.get("orders", [])[-500:]
    state["last_run"] = _now_iso()
    try: path.write_text(json.dumps(state, indent=2, default=str))
    except Exception as e: print(f"[alpaca] save failed: {e}")

def execute_consensus_signals(
    plans: List[Dict[str, Any]],
    state_path: Path,
    max_position_pct: float = 0.08,
    min_consensus_conviction: float = 0.40,
    max_total_positions: int = 15,
    enable_shorts: bool = True,
    all_debate_signals: Optional[Dict[str, str]] = None,
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
    state["enabled"] = True
    state["account"] = {"equity": round(equity, 2),
                        "cash": round(float(account.get("cash", 0)), 2)}
    print(f"[alpaca] equity ${equity:,.2f}")
    if equity < 1.0:
        _save_state(state, state_path)
        return state
    plan_signals, plan_conv, plan_class = {}, {}, {}
    for p in plans:
        t = p.get("ticker", "")
        if not t: continue
        plan_signals[t] = p.get("consensus_signal", "HOLD")
        plan_conv[t] = float(p.get("consensus_conviction") or p.get("avg_conviction") or 0)
        plan_class[t] = p.get("asset_class", "equity")
    exit_signals = dict(all_debate_signals or {})
    exit_signals.update(plan_signals)
    existing = _api_get(_POSITIONS_ENDPOINT, headers) or []
    if not isinstance(existing, list): existing = []
    print(f"[alpaca] open positions: {len(existing)}")
    orders_placed = []
    closed = 0
    for pos in existing:
        symbol = pos.get("symbol", "")
        try: qty = float(pos.get("qty", "0"))
        except Exception: qty = 0
        if not symbol or qty == 0: continue
        side = "long" if qty > 0 else "short"
        sig = exit_signals.get(symbol, "HOLD")
        should_close = ((side == "long" and sig in ("SELL","STRONG_SELL","HOLD")) or
                        (side == "short" and sig in ("BUY","STRONG_BUY","HOLD")))
        if should_close:
            print(f"[alpaca] CLOSE {side} {symbol} ({sig})")
            close_side = "sell" if side == "long" else "buy"
            r = _api_post(_ORDERS_ENDPOINT, headers, {
                "symbol": symbol, "qty": str(abs(qty)),
                "side": close_side, "type": "market", "time_in_force": "day"})
            if r:
                closed += 1
                orders_placed.append({"action": "CLOSE", "symbol": symbol,
                                      "side": close_side, "qty": abs(qty),
                                      "trigger_signal": sig, "order_id": r.get("id")})
    if closed > 0:
        time.sleep(1.5)
        existing = _api_get(_POSITIONS_ENDPOINT, headers) or []
        if not isinstance(existing, list): existing = []
    open_symbols = {p.get("symbol") for p in existing}
    open_count = len(existing)
    opened = 0
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
            orders_placed.append({"action": "OPEN", "symbol": ticker, "side": "buy",
                                  "notional": notional, "conviction": conviction,
                                  "signal": signal, "order_id": r.get("id")})
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
                orders_placed.append({"action": "SHORT", "symbol": ticker, "side": "sell",
                                      "notional": notional, "conviction": conviction,
                                      "signal": signal, "order_id": r.get("id")})
    state["orders_placed"] = orders_placed
    state["orders"] = state.get("orders", []) + [
        {**o, "time": _now_iso()} for o in orders_placed]
    state["last_cycle_summary"] = {"time": _now_iso(), "closed": closed,
                                    "opened": opened, "open_after": open_count,
                                    "equity": equity}
    _save_state(state, state_path)
    print(f"[alpaca] cycle: closed={closed} opened={opened} total={open_count}")
    return state
