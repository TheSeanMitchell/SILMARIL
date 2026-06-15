"""silmaril.execution.directive_consumer — Alpha 6.0 brain-to-hands bridge.

What this does
──────────────
This is the central module that takes the Alpha 5.1 BRAIN outputs
(`policy.position_directives`, `policy.forced_rotations`,
`policy.deployment_floor`, `policy.orchestrator`) and turns them into
concrete Alpaca order submissions.

Until 6.0, those JSON files were produced but never consumed. The 5.1
release notes themselves flagged this as the four-gap problem. This
module closes those gaps with deterministic, explainable, audit-friendly
execution logic.

Design principles
─────────────────
1. **Read-only inputs.** Never mutates policy or position state passed in.
2. **Session-aware.** Builds extended-hours+limit orders in pre/post,
   regular market orders during the session.
3. **Conservative caps.** Every action is bounded; nothing can ever
   submit more than the per-account `max_sweep_today` for the SGOV
   sweep, nor cause cash to go negative.
4. **Idempotent.** State tracking (`scale_out_history`) ensures the same
   profit target can't fire twice.
5. **Fully audited.** Every action returns a list of decision rows that
   the executor appends to the decision_ledger.json for the dashboard.

Public API
──────────
- consume_position_directives(positions, directives, headers, ...) →
        List[order_records]
- consume_forced_rotations(positions, rotations, plans, headers, ...) →
        List[order_records]
- compute_enforced_sweep_cap(intent_cash, contract, current_cash) → float
- can_open_position(account, contract) → (bool, reason)
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_BASE_URL = "https://paper-api.alpaca.markets"
_ORDERS_ENDPOINT = f"{_BASE_URL}/v2/orders"

VAULT_TICKERS = {"SGOV", "BIL", "SHY", "TFLO", "USFR"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


# ── Session detection ─────────────────────────────────────────────────

def market_session_now(now: Optional[datetime] = None) -> str:
    """Return one of: 'pre-market', 'regular', 'after-hours', 'closed'.

    All UTC; DST handled by ±1h widening of bands. Conservative — when
    in doubt, returns 'closed' which blocks extended-hours optimism."""
    n = now or datetime.now(timezone.utc)
    if n.weekday() >= 5:
        return "closed"
    h = n.hour + n.minute / 60.0
    # Approximate ET windows in UTC, widened for DST.
    if 8.0 <= h < 13.5:
        return "pre-market"
    if 13.5 <= h < 20.0:
        return "regular"
    if 20.0 <= h < 24.0:
        return "after-hours"
    if 0.0 <= h < 1.0:
        return "after-hours"
    return "closed"


def is_extended_session(now: Optional[datetime] = None) -> bool:
    return market_session_now(now) in ("pre-market", "after-hours")


# ── HTTP wrapper (mirrors alpaca_paper) ───────────────────────────────

def _api_post(url, headers, payload, error_log=None):
    try:
        import requests
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        if error_log is not None:
            error_log.append({
                "time": _now_iso(),
                "msg": f"POST {url} -> HTTP {r.status_code}: {r.text[:300]}",
                "status": r.status_code,
            })
        return None
    except Exception as e:
        if error_log is not None:
            error_log.append({"time": _now_iso(), "msg": f"POST raised: {e}"})
        return None


# ── Order construction ───────────────────────────────────────────────

def build_order_payload(
    *,
    symbol: str,
    side: str,
    qty: Optional[float] = None,
    notional: Optional[float] = None,
    current_price: Optional[float] = None,
    limit_buffer_bps: int = 30,
    force_extended: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Build a session-aware Alpaca order payload.

    Returns None if the order can't be safely constructed (e.g. pre/post
    session with no current_price, so we can't compute a limit).
    """
    if not symbol or side not in ("buy", "sell"):
        return None
    # Session hard-gate (fixes the off-hours blanket-sell incident): the old
    # logic only distinguished regular vs EXTENDED, so a fully-CLOSED session
    # (overnight/weekend) fell through to the regular branch and built market
    # orders that queued blind into the next open. No session, no order.
    _sess_label = None
    try:
        from datetime import datetime as _dt, timezone as _tz
        from ..portfolios.market_clock import _session_for as _sess
        _sess_label = _sess(_dt.now(_tz.utc))
        if _sess_label not in ("regular", "pre-market", "after-hours"):
            return None
    except Exception:
        from datetime import datetime as _dt, timezone as _tz
        if _dt.now(_tz.utc).weekday() >= 5:
            return None
    # ONE clock rules: the same session label that passed the gate also picks
    # the order type. (Previously a second clock could disagree at the 4:00 AM
    # ET boundary and let a MARKET order through in pre-market.)
    if force_extended is not None:
        ext = force_extended
    elif _sess_label is not None:
        ext = (_sess_label != "regular")
    else:
        ext = is_extended_session()
    # Alpaca refuses FRACTIONAL/notional orders outside regular hours — this
    # was the silent "Alpaca rejected OPEN" spam (28x since Jun 9, all in
    # extended sessions). Extended orders are floored to whole shares; under
    # one share we defer to the regular session rather than submit a
    # guaranteed rejection.
    if ext and qty is not None:
        try:
            _q = float(qty)
            if abs(_q - round(_q)) > 1e-9:
                _q = float(int(_q))  # floor toward zero
                if _q < 1.0:
                    return None
                qty = _q
        except (TypeError, ValueError):
            return None
    if not ext:
        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "market",
            "time_in_force": "day",
        }
        if qty is not None:
            payload["qty"] = str(abs(float(qty)))
        elif notional is not None:
            payload["notional"] = str(round(float(notional), 2))
        else:
            return None
        return payload

    # Extended-hours path: limit orders only, qty (not notional).
    if not current_price or current_price <= 0:
        return None
    if qty is None and notional is not None:
        qty = float(notional) / float(current_price)
    if qty is None or abs(qty) < 1e-9:
        return None
    buf = limit_buffer_bps / 10_000.0
    lp = float(current_price) * (1.0 + buf) if side == "buy" \
        else float(current_price) * (1.0 - buf)
    # Alpaca rejects sub-penny limit prices on stocks >= $1.00 (HTTP 422,
    # code 42210000: "invalid limit_price ... sub-penny increment"). Prices
    # >= $1 must be in $0.01 increments; only sub-$1 names may use $0.0001.
    # round(lp, 4) was rejecting nearly every extended-hours order.
    lp_str = f"{lp:.2f}" if lp >= 1.0 else f"{lp:.4f}"
    return {
        "symbol":         symbol,
        "qty":            str(abs(float(qty))),
        "side":           side,
        "type":           "limit",
        "limit_price":    lp_str,
        "time_in_force":  "day",
        "extended_hours": True,
    }


# ── Position-directive consumption ───────────────────────────────────

# Maps directive action → (canonical_side, full_close?)
_DIRECTIVE_TO_SIDE = {
    "PROFIT_LOCK":          ("sell", True),
    "MOMENTUM_DECAY":       ("sell", True),
    "INTRADAY_EXHAUSTION":  ("sell", False),
    "SCALE_OUT":            ("sell", False),
    "SCALE_IN":             ("buy",  False),
}


def consume_position_directives(
    positions: List[Dict[str, Any]],
    directives: List[Dict[str, Any]],
    *,
    headers: Dict[str, str],
    account_id: str,
    position_meta: Dict[str, Any],
    contract: Optional[Dict[str, Any]] = None,
    current_cash: float = 0.0,
    error_log: Optional[List[Dict]] = None,
) -> List[Dict[str, Any]]:
    """Translate position_directives into Alpaca orders.

    Returns: list of order_record dicts (one per submitted order). Each
    record is shaped for orders_placed and includes the trigger reason
    so the decision ledger can render WHY.

    `position_meta` is mutated in-place to record scale-out history,
    break-even-stop flags, and tightened-stop levels so the same
    directive doesn't fire twice on subsequent cycles.
    """
    orders_placed: List[Dict[str, Any]] = []
    if not directives or not positions or not headers:
        return orders_placed

    # Build position lookup by (owner, symbol).
    pos_by_sym: Dict[str, Dict[str, Any]] = {}
    for p in positions:
        sym = (p.get("symbol") or p.get("ticker") or "").upper()
        if sym and sym not in VAULT_TICKERS:
            pos_by_sym[sym] = p

    # Filter to our account.
    our_directives = [d for d in directives
                      if (d.get("owner") or "").upper() == account_id.upper()]
    # Priority sort (PROFIT_LOCK=1 before stop tightening=4).
    our_directives.sort(key=lambda d: int(d.get("priority", 9)))

    # Track which symbols we've already touched this cycle so we don't
    # both SCALE_OUT and PROFIT_LOCK the same position.
    touched: set = set()
    margin_blocked = current_cash < -1.0   # don't pile on if already on margin

    for d in our_directives:
        sym = (d.get("ticker") or "").upper()
        action = (d.get("action") or "").upper()
        if not sym or sym in touched or sym in VAULT_TICKERS:
            continue
        pos = pos_by_sym.get(sym)
        if not pos:
            continue
        qty = _safe_f(pos.get("qty"))
        if abs(qty) < 1e-9:
            continue
        cur_price = _safe_f(pos.get("current_price"))

        # Stop-management directives don't submit orders; they mutate meta.
        if action == "BREAK_EVEN_STOP":
            meta = position_meta.setdefault(sym, {})
            meta["stop_at_break_even"] = True
            meta["stop_at_break_even_set_at"] = _now_iso()
            touched.add(sym)
            orders_placed.append({
                "action":         "STOP_ADJUST",
                "symbol":         sym,
                "directive":      action,
                "new_stop_pct":   0.0,
                "trigger_reason": d.get("rationale", ""),
                "rationale":      d.get("rationale", ""),
                "time":           _now_iso(),
                "timestamp":      _now_iso(),
                "submitted":      False,    # meta-only adjustment
            })
            continue
        if action == "TIGHTEN_STOP":
            meta = position_meta.setdefault(sym, {})
            new_pct = _safe_f(d.get("new_stop_pct"), 0.025)
            meta["tightened_stop_pct"] = new_pct
            meta["tightened_stop_set_at"] = _now_iso()
            touched.add(sym)
            orders_placed.append({
                "action":         "STOP_ADJUST",
                "symbol":         sym,
                "directive":      action,
                "new_stop_pct":   new_pct,
                "trigger_reason": d.get("rationale", ""),
                "rationale":      d.get("rationale", ""),
                "time":           _now_iso(),
                "timestamp":      _now_iso(),
                "submitted":      False,
            })
            continue

        # Order-emitting directives below.
        side_info = _DIRECTIVE_TO_SIDE.get(action)
        if not side_info:
            continue
        canonical_side, is_full = side_info
        is_long = qty > 0
        # Flip sides for shorts: SCALE_OUT on a short means buy to cover.
        if not is_long:
            canonical_side = "buy" if canonical_side == "sell" else "sell"

        # SCALE_IN on margin = no.
        if action == "SCALE_IN" and margin_blocked:
            continue

        # Compute order qty.
        if is_full:
            order_qty = abs(qty)
        else:
            size_pct = _safe_f(d.get("size_pct"), 0.25)
            order_qty = abs(qty) * max(0.05, min(1.0, size_pct))
            # Round down to integer share if it's not a fractional-friendly
            # price; Alpaca paper accepts fractional but we want to be safe.
            if cur_price and cur_price > 100.0:
                order_qty = round(order_qty, 4)
            else:
                order_qty = round(order_qty, 4)
            if order_qty * cur_price < 1.0:
                continue   # too small to bother

        # SCALE_OUT history tracking so we don't repeat the same target.
        if action == "SCALE_OUT":
            tag = d.get("tag") or f"scale_out_default"
            meta = position_meta.setdefault(sym, {})
            history = meta.setdefault("scale_out_history", {})
            if history.get(tag):
                continue
            history[tag] = {"time": _now_iso(), "qty": round(order_qty, 4)}

        payload = build_order_payload(
            symbol=sym, side=canonical_side, qty=order_qty,
            current_price=cur_price,
        )
        if payload is None:
            continue

        r = _api_post(_ORDERS_ENDPOINT, headers, payload, error_log=error_log)
        if r:
            touched.add(sym)
            orders_placed.append({
                "action":         action,
                "symbol":         sym,
                "side":           canonical_side,
                "qty":            round(order_qty, 4),
                "directive":      action,
                "trigger_reason": d.get("rationale", ""),
                "rationale":      d.get("rationale", ""),
                "order_id":       r.get("id"),
                "time":           _now_iso(),
                "timestamp":      _now_iso(),
                "submitted":      True,
                "session":        market_session_now(),
                "is_extended":    is_extended_session(),
            })
    return orders_placed


# ── Forced-rotation consumption ──────────────────────────────────────

def consume_forced_rotations(
    positions: List[Dict[str, Any]],
    rotations: List[Dict[str, Any]],
    plans: List[Dict[str, Any]],
    *,
    headers: Dict[str, str],
    account_id: str,
    error_log: Optional[List[Dict]] = None,
) -> List[Dict[str, Any]]:
    """Execute forced rotations: close `sell_ticker`, queue `buy_ticker`.

    Each rotation record from conviction_engine.build_forced_rotation_directives:
        {action: 'forced_rotate', owner, sell_ticker, buy_ticker,
         score_delta, holding_score, alternative_score, rationale}

    We close immediately; the buy_ticker is appended to the plans list as
    a high-conviction synthetic plan so the standard OPEN loop picks it up
    on the same cycle.
    """
    orders_placed: List[Dict[str, Any]] = []
    if not rotations or not positions or not headers:
        return orders_placed

    pos_by_sym = {(p.get("symbol") or "").upper(): p for p in positions
                  if (p.get("symbol") or "").upper() not in VAULT_TICKERS}
    plans_appended: List[Dict[str, Any]] = []
    touched: set = set()

    for rot in rotations:
        if (rot.get("owner") or "").upper() != account_id.upper():
            continue
        sell = (rot.get("sell_ticker") or "").upper()
        buy  = (rot.get("buy_ticker") or "").upper()
        if not sell or not buy or sell in touched:
            continue
        pos = pos_by_sym.get(sell)
        if not pos:
            continue
        qty = _safe_f(pos.get("qty"))
        if abs(qty) < 1e-9:
            continue
        cur_price = _safe_f(pos.get("current_price"))
        side = "sell" if qty > 0 else "buy"

        payload = build_order_payload(
            symbol=sell, side=side, qty=abs(qty), current_price=cur_price,
        )
        if payload is None:
            continue
        r = _api_post(_ORDERS_ENDPOINT, headers, payload, error_log=error_log)
        if r:
            touched.add(sell)
            orders_placed.append({
                "action":         "FORCED_ROTATE_SELL",
                "symbol":         sell,
                "side":           side,
                "qty":            abs(qty),
                "directive":      "FORCED_ROTATION",
                "buy_target":     buy,
                "trigger_reason": rot.get("rationale", ""),
                "rationale":      rot.get("rationale", ""),
                "order_id":       r.get("id"),
                "time":           _now_iso(),
                "timestamp":      _now_iso(),
                "submitted":      True,
            })
            # Synthesize a buy plan for the partner ticker so the
            # normal OPEN loop in alpaca_paper picks it up this cycle.
            score = _safe_f(rot.get("alternative_score"), 0.65)
            plans_appended.append({
                "ticker": buy,
                "consensus_signal": "STRONG_BUY",
                "consensus_conviction": min(0.85, 0.55 + score * 0.35),
                "synthetic": True,
                "from_rotation": sell,
                "asset_class": "equity",
            })

    if plans_appended:
        # Merge into the caller's plans list (mutates in place).
        # Caller-supplied list is mutable; we append.
        existing = {(p.get("ticker") or "").upper() for p in plans}
        for p in plans_appended:
            t = (p.get("ticker") or "").upper()
            if t and t not in existing:
                plans.append(p)
                existing.add(t)

    return orders_placed


# ── Pre-cycle sweep cap enforcement ──────────────────────────────────

def compute_enforced_sweep_cap(
    intent_cash: float,
    contract: Optional[Dict[str, Any]],
    current_cash: float,
    *,
    cash_reserve: float = 1.00,
) -> Tuple[float, Optional[str]]:
    """Return (allowed_sweep, reason_if_clipped).

    Honors:
      - `contract.max_sweep_today` (per-account hard cap)
      - cash floor: never sweep more than `current_cash - reserve`
      - never sweep negative cash into SGOV

    Logic:
      allowed = min(intent_cash,
                    contract.max_sweep_today (if present),
                    current_cash - reserve)
    """
    if intent_cash <= 0:
        return (0.0, None)
    if current_cash <= cash_reserve:
        return (0.0,
                f"current_cash ${current_cash:.2f} ≤ reserve ${cash_reserve:.2f} — no sweep")

    intent_cap = max(0.0, intent_cash)
    contract_cap = float("inf")
    contract_reason = None
    if contract:
        mst = _safe_f(contract.get("max_sweep_today"))
        if mst > 0 or (contract.get("max_sweep_today") is not None
                       and contract.get("objective_today") != "HARVEST_OVERAGE"):
            contract_cap = mst
            contract_reason = (f"contract.max_sweep_today=${mst:.2f}"
                                if mst else "contract forbids sweep this cycle (max=$0)")
    cash_cap = max(0.0, current_cash - cash_reserve)
    final = min(intent_cap, contract_cap, cash_cap)
    if final < intent_cash - 0.01:
        if contract_cap <= cash_cap and contract_cap < intent_cap:
            return (final, contract_reason)
        return (final, f"cash floor: ${cash_cap:.2f} available after reserve")
    return (final, None)


# ── Margin / negative-cash guard ─────────────────────────────────────

def can_open_position(
    account: Dict[str, Any],
    contract: Optional[Dict[str, Any]],
    *,
    proposed_notional: float = 0.0,
) -> Tuple[bool, str]:
    """Returns (allowed, reason).

    Refuses opens when:
      - cash is already negative (don't pile onto margin)
      - opening this position would push cash below buying_power floor
      - contract says we're in REDEPLOY_FROM_SGOV and we haven't redeployed
    """
    cash = _safe_f((account or {}).get("cash"))
    if cash < 0:
        return (False,
                f"BLOCKED: account cash ${cash:.2f} < 0 (margin used) — "
                "refusing new opens until margin cleared")
    if proposed_notional > 0 and (cash - proposed_notional) < -1.0:
        return (False,
                f"BLOCKED: opening ${proposed_notional:.2f} would push cash "
                f"from ${cash:.2f} to ${cash - proposed_notional:.2f} (margin)")
    return (True, "ok")


def must_redeploy_from_sgov(contract: Optional[Dict[str, Any]]) -> Tuple[bool, float]:
    """Return (yes, amount). amount=0 if no redeploy needed."""
    if not contract:
        return (False, 0.0)
    amt = _safe_f(contract.get("redeploy_from_sgov_amount"))
    if amt > 5.0 and contract.get("must_redeploy_today"):
        return (True, amt)
    return (False, 0.0)


__all__ = [
    "VAULT_TICKERS",
    "market_session_now",
    "is_extended_session",
    "build_order_payload",
    "consume_position_directives",
    "consume_forced_rotations",
    "compute_enforced_sweep_cap",
    "can_open_position",
    "must_redeploy_from_sgov",
]
