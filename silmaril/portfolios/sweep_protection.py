"""silmaril.portfolios.sweep_protection — Alpha 4.0 overnight/pre-market shield.

What changed in 4.0
───────────────────
1. **Big-winner shield bug fix** — 3.1 used a hard $10,000 trigger,
   which equals every harvester account's starting principal. The
   result was that the shield liquidated the book every single trading
   close, defeating the harvest philosophy. 4.0 reads the per-account
   force-sweep floor from execution_policy.json (set to principal × 1.05,
   minimum $10,500 by policy_router). If the policy file is missing,
   4.0 falls back to a 5% buffer above principal rather than the bare
   principal.

2. **ATTACK-mode danger-window carve-outs** — danger-window force
   liquidation now skips ELITE, URGENT, and fresh-strong-catalyst
   positions during ATTACK + high deployment pressure. Conservative
   liquidation still applies to ordinary positions; preservation no
   longer paralyzes the portfolio during regimes that explicitly want
   risk on.

3. **Mode-aware stale-close age** — STALE_MAX_AGE_DAYS is no longer
   hard-coded; it's read from policy.close_loop.stale_close_age_days
   (3 in DEFENSIVE, 4 in BALANCED, 5 in ATTACK). Long-horizon names
   in a strong tape get more room.

4. **SGOV redeploy hook (NEW)** — when policy.sweep.redeploy_sgov
   recommends redeployment (deployment pressure ≥ 0.70 AND ATTACK or
   BALANCED), this module sells up to 25% of the SGOV vault per cycle
   back into cash so the next executor cycle has buying power. Capped
   so vault never drops below the principal target.

5. **Principal-floor sanctity** — never sweeps cash below
   principal_target. SGOV-redeploy never reduces the SGOV vault below
   the cap given by policy. Both invariants are checked before any
   submission.

All behavior remains a non-destructive sidecar. If anything inside
fails, the rest of Silmaril's daily cycle still ships.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ─── Constants ────────────────────────────────────────────────────────────

VERSION = "4.0"

_RESERVED_VAULT_SYMBOLS = {"SGOV", "BIL", "SHY", "TFLO", "USFR"}
_VAULT_SYMBOL = "SGOV"

INSTANT_SWEEP_USD = 300.00              # unrealized $ that triggers instant sweep
INSTANT_SWEEP_PCT = 0.05                # OR 5% unrealized triggers instant sweep

# 3.1's hard $10k trigger was identical to starting principal, so the shield
# fired every close. 4.0 keeps the constant only as a DEFAULT FALLBACK floor
# when no policy file is readable. The real per-account floor comes from
# policy.sweep.force_sweep_floor (principal × 1.05, minimum $10,500).
BIG_WINNER_SHIELD_DEFAULT_FLOOR_USD = 10_500.00
SWEEP_SWITCH_FLOOR_USD              = 10_500.00

# Stale-close defaults (overridable from policy.close_loop.stale_close_age_days)
STALE_MAX_AGE_DAYS_DEFAULT = 3
STALE_MOMENTUM_FLAT_THRESHOLD = 0.005
STALE_PEAK_PROXIMITY = 0.02

# News momentum: high-signal headline keywords (case-insensitive substring match)
NEWS_BOOST_KEYWORDS = (
    "strong", "blowout", "surge", "surges", "surging",
    "upgraded to buy", "upgrade to buy", "raised target",
    "smashed estimates", "beats estimates", "record revenue",
    "all-time high", "breakout", "ramp", "explodes",
    "guidance raised", "raises guidance", "raised guidance",
)
NEWS_BOOST_MULTIPLIER     = 1.50
NEWS_BOOST_MIN_CONVICTION = 0.55

# SGOV redeploy
SGOV_REDEPLOY_FRACTION_PER_CYCLE = 0.25   # at most 25% of vault per cycle
SGOV_REDEPLOY_MIN_USD            = 50.00  # don't bother below $50

# Time windows (all UTC) — danger zones we want to be out of risk for
_DANGER_WINDOWS_UTC: List[Tuple[str, int, int, int, int, str]] = [
    ("friday_evening", 19, 30, 23, 59, "friday"),
    ("overnight_thin", 0, 30, 4, 0, "weekday"),
]

# Closing-bell window (ET → UTC). We straddle EDT and EST by accepting both.
_CLOSING_BELL_WINDOWS_UTC: List[Tuple[int, int, int, int]] = [
    (19, 30, 20, 5),   # 15:30-16:05 ET during EDT
    (20, 30, 21, 5),   # 15:30-16:05 ET during EST
]


# ─── Alpaca HTTP helpers (self-contained — no coupling to alpaca_paper) ──

_BASE_URL = "https://paper-api.alpaca.markets"
_ORDERS_ENDPOINT    = f"{_BASE_URL}/v2/orders"
_POSITIONS_ENDPOINT = f"{_BASE_URL}/v2/positions"
_ACCOUNT_ENDPOINT   = f"{_BASE_URL}/v2/account"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _headers_for(env_key_var: str, env_secret_var: str) -> Optional[Dict[str, str]]:
    """Returns Alpaca auth headers for the given env var names, or None."""
    key = os.environ.get(env_key_var, "").strip()
    sec = os.environ.get(env_secret_var, "").strip()
    if not key or not sec:
        return None
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": sec,
        "Content-Type": "application/json",
    }


def _api_get(url: str, headers: Dict[str, str]) -> Optional[Any]:
    try:
        import requests
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        print(f"[sweep] GET {url} -> {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"[sweep] GET {url} raised {type(e).__name__}: {e}")
        return None


def _api_post(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Optional[Any]:
    try:
        import requests
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        print(f"[sweep] POST {url} -> {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"[sweep] POST {url} raised {type(e).__name__}: {e}")
        return None


# ─── Extended-hours order wrapper (unchanged from 3.1 except module-level docstring) ──

def _market_session_now(now: Optional[datetime] = None) -> str:
    """Returns one of: 'regular', 'pre-market', 'after-hours', 'closed'."""
    n = now or _now_utc()
    if n.weekday() >= 5:
        return "closed"
    year = n.year
    march = datetime(year, 3, 1, tzinfo=timezone.utc)
    second_sun = [march + timedelta(days=i) for i in range(14)
                  if (march + timedelta(days=i)).weekday() == 6][1]
    nov = datetime(year, 11, 1, tzinfo=timezone.utc)
    first_sun = [nov + timedelta(days=i) for i in range(7)
                 if (nov + timedelta(days=i)).weekday() == 6][0]
    dst = (second_sun.replace(hour=7) <= n < first_sun.replace(hour=6))
    et_off = -4 if dst else -5
    pre_utc   = n.replace(hour=4,  minute=0,  second=0, microsecond=0) - timedelta(hours=et_off)
    open_utc  = n.replace(hour=9,  minute=30, second=0, microsecond=0) - timedelta(hours=et_off)
    close_utc = n.replace(hour=16, minute=0,  second=0, microsecond=0) - timedelta(hours=et_off)
    after_utc = n.replace(hour=20, minute=0,  second=0, microsecond=0) - timedelta(hours=et_off)
    if open_utc <= n < close_utc: return "regular"
    if pre_utc  <= n < open_utc:  return "pre-market"
    if close_utc <= n < after_utc: return "after-hours"
    return "closed"


def _is_extended_session(now: Optional[datetime] = None) -> bool:
    return _market_session_now(now) in ("pre-market", "after-hours")


def _submit_session_aware_order(
    headers: Dict[str, str],
    *,
    symbol: str,
    side: str,
    qty: Optional[float] = None,
    notional: Optional[float] = None,
    current_price: Optional[float] = None,
    limit_buffer_bps: int = 30,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Submit a single order, automatically using extended-hours+limit when
    the market is in pre/post session."""
    session = _market_session_now()
    is_ext = session in ("pre-market", "after-hours")

    if not is_ext:
        payload: Dict[str, Any] = {
            "symbol": symbol, "side": side,
            "type": "market", "time_in_force": "day",
        }
        if qty is not None:        payload["qty"] = str(abs(float(qty)))
        elif notional is not None: payload["notional"] = str(round(float(notional), 2))
        else: return None, "deferred"
        return _api_post(_ORDERS_ENDPOINT, headers, payload), "regular_market"

    if current_price is None or current_price <= 0:
        return None, "deferred"

    if qty is None and notional is not None:
        qty = float(notional) / float(current_price)
    if qty is None or abs(qty) < 1e-9:
        return None, "deferred"

    buf = limit_buffer_bps / 10_000.0
    limit_price = float(current_price) * (1.0 + buf) if side == "buy" \
                  else float(current_price) * (1.0 - buf)
    # Alpaca rejects sub-penny limit prices on stocks >= $1.00 (HTTP 422).
    # >= $1 must be $0.01 increments; only sub-$1 names may use $0.0001.
    # This is the protection/exit path — round(.,4) was getting exits
    # rejected in extended hours, so positions couldn't be defended.
    lp_str = f"{limit_price:.2f}" if limit_price >= 1.0 else f"{limit_price:.4f}"
    payload = {
        "symbol":         symbol,
        "qty":            str(abs(float(qty))),
        "side":           side,
        "type":           "limit",
        "limit_price":    lp_str,
        "time_in_force":  "day",
        "extended_hours": True,
    }
    return _api_post(_ORDERS_ENDPOINT, headers, payload), "extended_limit"


# ─── Time-window helpers ──────────────────────────────────────────────────

def _in_window(now: datetime, sh: int, sm: int, eh: int, em: int) -> bool:
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= now <= end


def in_closing_bell_window(now: Optional[datetime] = None) -> bool:
    n = now or _now_utc()
    if n.weekday() >= 5:
        return False
    return any(_in_window(n, sh, sm, eh, em)
               for (sh, sm, eh, em) in _CLOSING_BELL_WINDOWS_UTC)


def in_danger_window(now: Optional[datetime] = None) -> Tuple[bool, str]:
    """Returns (in_window, label)."""
    n = now or _now_utc()
    weekday = n.weekday()
    for (label, sh, sm, eh, em, wday_filter) in _DANGER_WINDOWS_UTC:
        if wday_filter == "friday" and weekday != 4:
            continue
        if wday_filter == "weekday" and weekday >= 5:
            continue
        if _in_window(n, sh, sm, eh, em):
            return True, label
    return False, ""


# ─── Position helpers ────────────────────────────────────────────────────

def _calendar_days_since(iso_ts: Optional[str], today: Optional[date] = None) -> Optional[int]:
    if not iso_ts:
        return None
    try:
        d = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00")).date()
    except Exception:
        try:
            d = date.fromisoformat(str(iso_ts)[:10])
        except Exception:
            return None
    today = today or _now_utc().date()
    return max(0, (today - d).days)


def _safe_f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def _is_vault(symbol: Optional[str]) -> bool:
    return bool(symbol) and symbol.upper() in _RESERVED_VAULT_SYMBOLS


def _position_is_strong(pos: Dict[str, Any]) -> bool:
    cur = _safe_f(pos.get("current_price"))
    entry = _safe_f(pos.get("avg_entry_price"))
    if cur <= 0 or entry <= 0:
        return False
    intraday_pct = (cur - entry) / entry
    upl_pct = _safe_f(pos.get("unrealized_plpc"))
    if intraday_pct >= STALE_MOMENTUM_FLAT_THRESHOLD:
        return True
    if upl_pct >= STALE_MOMENTUM_FLAT_THRESHOLD:
        return True
    return False


# ─── Policy / market-context loading ──────────────────────────────────────

def _load_policy(data_dir: Path) -> Dict[str, Any]:
    """Read execution_policy.json. Returns {} on any failure."""
    try:
        p = Path(data_dir) / "execution_policy.json"
        if p.exists():
            doc = json.loads(p.read_text())
            if isinstance(doc, dict):
                return doc
    except Exception:
        pass
    return {}


def _account_force_sweep_floor(
    policy: Dict[str, Any],
    account_id: str,
    principal_target: float,
) -> float:
    """Resolve the per-account big-winner shield floor.

    Precedence:
        1. policy.sweep.force_sweep_floor_by_account[account_id]
        2. policy.sweep.force_sweep_floor (global)
        3. principal_target * 1.05, minimum $10,500
        4. BIG_WINNER_SHIELD_DEFAULT_FLOOR_USD
    """
    sweep_pol = (policy.get("sweep") or {}) if isinstance(policy, dict) else {}
    by_acct = sweep_pol.get("force_sweep_floor_by_account") or {}
    if isinstance(by_acct, dict):
        v = _safe_f(by_acct.get(account_id), 0.0)
        if v > 0:
            return float(v)
    g = _safe_f(sweep_pol.get("force_sweep_floor"), 0.0)
    if g > 0:
        return float(g)
    if principal_target > 0:
        return max(BIG_WINNER_SHIELD_DEFAULT_FLOOR_USD, principal_target * 1.05)
    return BIG_WINNER_SHIELD_DEFAULT_FLOOR_USD


def _stale_close_age_days(policy: Dict[str, Any]) -> int:
    """Read policy.close_loop.stale_close_age_days; default 3."""
    cl = (policy.get("close_loop") or {}) if isinstance(policy, dict) else {}
    v = cl.get("stale_close_age_days")
    try:
        if v is not None:
            iv = int(v)
            if iv >= 1:
                return iv
    except Exception:
        pass
    return STALE_MAX_AGE_DAYS_DEFAULT


def _market_mode_from_policy(policy: Dict[str, Any]) -> str:
    """ATTACK | BALANCED | DEFENSIVE | PRESERVATION; default BALANCED."""
    mm = policy.get("market_mode") or (policy.get("market_state") or {}).get("mode")
    return str(mm or "BALANCED").upper()


def _sgov_redeploy_recommendation(policy: Dict[str, Any]) -> Dict[str, Any]:
    """Read policy.sweep.redeploy_sgov."""
    sweep_pol = (policy.get("sweep") or {}) if isinstance(policy, dict) else {}
    r = sweep_pol.get("redeploy_sgov") or {}
    return r if isinstance(r, dict) else {}


def _build_protection_carve_outs(
    policy: Dict[str, Any],
) -> Tuple[set, set, set]:
    """Returns (elite_tickers, urgent_tickers, strong_catalyst_tickers)
    pulled from execution policy. Each is a set of uppercase symbols."""
    elite = set()
    urgent = set()
    strong_cat = set()
    if not isinstance(policy, dict):
        return elite, urgent, strong_cat
    for t in (policy.get("elite_tickers") or []):
        if t:
            elite.add(str(t).upper())
    for t in (policy.get("urgency_tickers") or []):
        if t:
            urgent.add(str(t).upper())
    # urgency may also be reported as a dict {ticker: score}
    urg_by = policy.get("urgency_by_ticker") or {}
    if isinstance(urg_by, dict):
        for t, score in urg_by.items():
            if _safe_f(score) >= 0.65:
                urgent.add(str(t).upper())
    sc_list = (policy.get("strong_catalyst_tickers")
                or (policy.get("catalysts") or {}).get("strong") or [])
    for t in sc_list or []:
        if t:
            strong_cat.add(str(t).upper())
    return elite, urgent, strong_cat


def _is_protected_in_attack(
    sym: str,
    market_mode: str,
    elite: set, urgent: set, strong_cat: set,
) -> Tuple[bool, str]:
    """During ATTACK, certain positions are spared from danger-window
    force-liquidation. Returns (spared, reason)."""
    if market_mode != "ATTACK":
        return False, ""
    s = sym.upper() if sym else ""
    if s in elite:
        return True, "elite"
    if s in urgent:
        return True, "urgent"
    if s in strong_cat:
        return True, "strong_catalyst"
    return False, ""


# ─── Per-account operations ──────────────────────────────────────────────

def _instant_sweep_one_account(
    headers: Dict[str, str],
    positions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """For each position with $300 or 5% unrealized, peel off the gain into cash."""
    out: List[Dict[str, Any]] = []
    for pos in positions or []:
        sym = (pos.get("symbol") or "").upper()
        if not sym or _is_vault(sym):
            continue
        qty = _safe_f(pos.get("qty"))
        if qty <= 0:
            continue
        upl = _safe_f(pos.get("unrealized_pl"))
        upl_pct = _safe_f(pos.get("unrealized_plpc"))
        mkt = _safe_f(pos.get("market_value"))
        cur = _safe_f(pos.get("current_price"))
        if cur <= 0 or mkt <= 0:
            continue
        trigger = None
        if upl >= INSTANT_SWEEP_USD:
            trigger = f"unrealized ${upl:.2f} >= ${INSTANT_SWEEP_USD:.0f}"
        elif upl_pct >= INSTANT_SWEEP_PCT:
            trigger = f"unrealized {upl_pct*100:.2f}% >= {INSTANT_SWEEP_PCT*100:.1f}%"
        if not trigger:
            continue

        peel_usd = min(upl, INSTANT_SWEEP_USD)
        peel_usd = max(1.00, min(peel_usd, mkt - 1.00))
        if peel_usd < 1.00:
            continue
        order, mode = _submit_session_aware_order(
            headers, symbol=sym, side="sell",
            notional=peel_usd, current_price=cur,
        )
        rec = {
            "action": "INSTANT_SWEEP",
            "symbol": sym,
            "side": "sell",
            "notional": round(peel_usd, 2),
            "trigger": trigger,
            "unrealized_pl": round(upl, 2),
            "unrealized_plpc": round(upl_pct, 4),
            "order_id": (order or {}).get("id"),
            "mode": mode,
            "submitted_at": _now_iso(),
            "ok": bool(order),
        }
        out.append(rec)
        print(f"[sweep][instant] {sym} peel ${peel_usd:.2f} ({trigger})")
        time.sleep(0.25)

    total = round(sum(r["notional"] for r in out if r.get("ok")), 2)
    if total >= 5.00:
        sgov_price = None
        for p in positions:
            if (p.get("symbol") or "").upper() == _VAULT_SYMBOL:
                sgov_price = _safe_f(p.get("current_price"))
                break
        sgov, mode = _submit_session_aware_order(
            headers, symbol=_VAULT_SYMBOL, side="buy",
            notional=total, current_price=sgov_price,
        )
        out.append({
            "action": "INSTANT_SWEEP_SGOV_BUY",
            "symbol": _VAULT_SYMBOL,
            "side": "buy",
            "notional": total,
            "order_id": (sgov or {}).get("id"),
            "mode": mode,
            "submitted_at": _now_iso(),
            "ok": bool(sgov),
        })
    return out


def _close_stale_one_account(
    headers: Dict[str, str],
    positions: List[Dict[str, Any]],
    position_meta: Dict[str, Dict[str, Any]],
    *,
    max_age_days: int = STALE_MAX_AGE_DAYS_DEFAULT,
    spare_tickers: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """Force-close any position >= max_age_days calendar days old that isn't
    moving. Spares tickers in `spare_tickers` (elite/urgent/strong-catalyst).
    """
    out: List[Dict[str, Any]] = []
    today = _now_utc().date()
    spare = spare_tickers or set()
    for pos in positions or []:
        sym = (pos.get("symbol") or "").upper()
        if not sym or _is_vault(sym):
            continue
        qty = _safe_f(pos.get("qty"))
        if abs(qty) < 1e-9:
            continue
        if sym in spare:
            continue  # elite/urgent/strong-catalyst names are spared
        meta = position_meta.get(sym, {}) if isinstance(position_meta, dict) else {}
        first_seen = meta.get("first_seen") or pos.get("created_at") or pos.get("entry_date")
        age = _calendar_days_since(first_seen, today)
        if age is None or age < max_age_days:
            continue
        if _position_is_strong(pos):
            continue
        side_close = "sell" if qty > 0 else "buy"
        cur_price = _safe_f(pos.get("current_price"))
        order, mode = _submit_session_aware_order(
            headers, symbol=sym, side=side_close,
            qty=abs(qty), current_price=cur_price,
        )
        out.append({
            "action": "STALE_CLOSE",
            "symbol": sym,
            "side": side_close,
            "qty": abs(qty),
            "age_days": age,
            "trigger": (f"held {age}d >= {max_age_days}d without strong momentum"),
            "order_id": (order or {}).get("id"),
            "mode": mode,
            "submitted_at": _now_iso(),
            "ok": bool(order),
        })
        print(f"[sweep][stale] {sym} {age}d old, closing (floor {max_age_days}d)")
        time.sleep(0.25)
    return out


def _force_sweep_one_account(
    headers: Dict[str, str],
    positions: List[Dict[str, Any]],
    equity: float,
    floor_usd: float,
    reason: str,
    *,
    spare_tickers: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """Liquidate everything non-vault (except spared tickers), then park
    excess equity in SGOV. Used by manual SWEEP, big-winner shield, and
    danger-window protections."""
    out: List[Dict[str, Any]] = []
    spare = spare_tickers or set()
    spared_value = 0.0

    for pos in positions or []:
        sym = (pos.get("symbol") or "").upper()
        if not sym or _is_vault(sym):
            continue
        qty = _safe_f(pos.get("qty"))
        if abs(qty) < 1e-9:
            continue
        if sym in spare:
            spared_value += _safe_f(pos.get("market_value"))
            out.append({
                "action": "FORCE_SWEEP_SPARE",
                "symbol": sym,
                "trigger": f"{reason} — spared (ATTACK carve-out)",
                "market_value": round(_safe_f(pos.get("market_value")), 2),
                "submitted_at": _now_iso(),
                "ok": True,
            })
            continue
        side_close = "sell" if qty > 0 else "buy"
        cur_price = _safe_f(pos.get("current_price"))
        order, mode = _submit_session_aware_order(
            headers, symbol=sym, side=side_close,
            qty=abs(qty), current_price=cur_price,
        )
        out.append({
            "action": "FORCE_SWEEP_SELL",
            "symbol": sym,
            "side": side_close,
            "qty": abs(qty),
            "trigger": reason,
            "order_id": (order or {}).get("id"),
            "mode": mode,
            "submitted_at": _now_iso(),
            "ok": bool(order),
        })
        time.sleep(0.25)

    # Park excess equity in SGOV right now. Exclude spared positions from
    # equity-to-park because that capital is intentionally kept exposed.
    target_sgov = max(0.0, round((equity - spared_value) - floor_usd, 2))
    if target_sgov >= 5.00:
        sgov_price = None
        for p in positions:
            if (p.get("symbol") or "").upper() == _VAULT_SYMBOL:
                sgov_price = _safe_f(p.get("current_price"))
                break
        sgov, mode = _submit_session_aware_order(
            headers, symbol=_VAULT_SYMBOL, side="buy",
            notional=target_sgov, current_price=sgov_price,
        )
        out.append({
            "action": "FORCE_SWEEP_SGOV_BUY",
            "symbol": _VAULT_SYMBOL,
            "side": "buy",
            "notional": target_sgov,
            "trigger": (f"{reason} — park (equity ${equity:.2f}"
                        + (f" - spared ${spared_value:.2f}" if spared_value > 0 else "")
                        + f" - floor ${floor_usd:.0f})"),
            "order_id": (sgov or {}).get("id"),
            "mode": mode,
            "submitted_at": _now_iso(),
            "ok": bool(sgov),
        })
    return out


def _redeploy_sgov_one_account(
    headers: Dict[str, str],
    positions: List[Dict[str, Any]],
    cash_settled: float,
    redeploy_pol: Dict[str, Any],
    principal_target: float,
) -> List[Dict[str, Any]]:
    """Sell SGOV back to cash when policy.sweep.redeploy_sgov.recommended is True.

    Caps:
      • Never sell more than SGOV_REDEPLOY_FRACTION_PER_CYCLE (default 25%)
        of the current vault value per cycle.
      • Honor policy-provided amount_hint when present (caps the per-cycle
        sale to that dollar amount).
      • Never reduce the SGOV vault below max(0, principal_target - cash).
        (Maintains the principal-preservation invariant: principal must
        always be reachable, either in cash or in vault.)
    """
    out: List[Dict[str, Any]] = []
    if not redeploy_pol or not redeploy_pol.get("recommended"):
        return out

    # Find SGOV position
    sgov_pos = next((p for p in positions or []
                     if (p.get("symbol") or "").upper() == _VAULT_SYMBOL), None)
    if not sgov_pos:
        return out
    vault_mkt = _safe_f(sgov_pos.get("market_value"))
    vault_qty = _safe_f(sgov_pos.get("qty"))
    cur_price = _safe_f(sgov_pos.get("current_price"))
    if vault_mkt <= 0 or vault_qty <= 0 or cur_price <= 0:
        return out

    # Per-cycle cap
    per_cycle_cap = vault_mkt * SGOV_REDEPLOY_FRACTION_PER_CYCLE
    amount_hint   = _safe_f(redeploy_pol.get("amount_hint"), per_cycle_cap)
    target_sale   = min(per_cycle_cap, amount_hint)

    # Principal-preservation invariant: principal_target must remain
    # coverable by cash + remaining vault. Required vault floor after sale:
    #   remaining_vault >= max(0, principal_target - cash_settled)
    needed_vault = max(0.0, principal_target - cash_settled)
    max_redemption = max(0.0, vault_mkt - needed_vault)
    target_sale = min(target_sale, max_redemption)

    if target_sale < SGOV_REDEPLOY_MIN_USD:
        return out

    # Sell SGOV — extended-hours wrapper handles session
    order, mode = _submit_session_aware_order(
        headers, symbol=_VAULT_SYMBOL, side="sell",
        notional=target_sale, current_price=cur_price,
    )
    out.append({
        "action": "SGOV_REDEPLOY",
        "symbol": _VAULT_SYMBOL,
        "side": "sell",
        "notional": round(target_sale, 2),
        "vault_before": round(vault_mkt, 2),
        "amount_hint":  round(amount_hint, 2),
        "per_cycle_cap": round(per_cycle_cap, 2),
        "needed_vault_floor": round(needed_vault, 2),
        "trigger": (f"policy redeploy_sgov ({redeploy_pol.get('reason', 'high pressure')})"
                    if redeploy_pol.get("reason") else "policy redeploy_sgov"),
        "order_id": (order or {}).get("id"),
        "mode": mode,
        "submitted_at": _now_iso(),
        "ok": bool(order),
    })
    print(f"[sweep][redeploy_sgov] sell ${target_sale:.2f} from vault "
          f"(vault ${vault_mkt:.2f}, needed_floor ${needed_vault:.2f})")
    return out


def _news_boost_one_account(
    headers: Dict[str, str],
    positions: List[Dict[str, Any]],
    plans: List[Dict[str, Any]],
    catalysts_by_ticker: Dict[str, List[str]],
    trading_capital: float,
    max_position_pct: float,
) -> List[Dict[str, Any]]:
    """For STRONG_BUY plans whose latest headlines contain boost keywords,
    add an extra (notional × 0.5) buy order on TOP of the main cycle's open.
    """
    out: List[Dict[str, Any]] = []
    open_syms = {(p.get("symbol") or "").upper() for p in positions or []}
    for plan in plans or []:
        ticker = (plan.get("ticker") or "").upper()
        if not ticker or _is_vault(ticker):
            continue
        sig = plan.get("consensus_signal", "HOLD")
        conv = _safe_f(plan.get("consensus_conviction"))
        if sig != "STRONG_BUY":
            continue
        if conv < NEWS_BOOST_MIN_CONVICTION:
            continue
        headlines = catalysts_by_ticker.get(ticker) or []
        matched_kw: Optional[str] = None
        for hl in headlines[:5]:
            hl_lower = (hl or "").lower()
            for kw in NEWS_BOOST_KEYWORDS:
                if kw in hl_lower:
                    matched_kw = kw
                    break
            if matched_kw:
                break
        if not matched_kw:
            continue
        base_notional = trading_capital * max_position_pct
        boost_notional = round(base_notional * (NEWS_BOOST_MULTIPLIER - 1.0), 2)
        if boost_notional < 1.00:
            continue
        cur_price = None
        for pp in positions or []:
            if (pp.get("symbol") or "").upper() == ticker:
                cur_price = _safe_f(pp.get("current_price"))
                break
        if not cur_price or cur_price <= 0:
            cur_price = _safe_f(plan.get("price") or plan.get("entry_price"))
        order, mode = _submit_session_aware_order(
            headers, symbol=ticker, side="buy",
            notional=boost_notional, current_price=cur_price,
        )
        out.append({
            "action": "NEWS_BOOST",
            "symbol": ticker,
            "side": "buy",
            "notional": boost_notional,
            "trigger": f"STRONG_BUY + headline keyword '{matched_kw}' (conv {conv:.2f})",
            "had_existing_position": ticker in open_syms,
            "order_id": (order or {}).get("id"),
            "mode": mode,
            "submitted_at": _now_iso(),
            "ok": bool(order),
        })
        print(f"[sweep][news] BOOST {ticker} +${boost_notional:.2f} ({matched_kw!r})")
        time.sleep(0.25)
    return out


# ─── Sweep-switch detection ──────────────────────────────────────────────

def _sweep_switch_signal(data_dir: Path) -> Tuple[bool, str]:
    """Detect a manual SWEEP request."""
    env = os.environ.get("SILMARIL_SWEEP_SWITCH", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True, "env SILMARIL_SWEEP_SWITCH=1"
    flag = data_dir / "sweep_switch.flag"
    if flag.exists():
        try:
            body = flag.read_text().strip()[:200]
            flag.unlink(missing_ok=True)
            return True, f"flag file: {body or 'no message'}"
        except Exception:
            return True, "flag file present (unreadable, consumed)"
    return False, ""


# ─── Catalyst loader ─────────────────────────────────────────────────────

def _build_catalysts_index(data_dir: Path) -> Dict[str, List[str]]:
    p = data_dir / "catalysts.json"
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
    except Exception:
        return {}
    by_ticker: Dict[str, List[str]] = {}
    items = ((raw.get("daily") or []) + (raw.get("weekly") or [])
             or raw.get("catalysts") or raw.get("items") or [])
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        tickers = it.get("tickers") or ([it["ticker"]] if it.get("ticker") else [])
        title = it.get("title") or it.get("headline") or it.get("note") or ""
        if not title:
            continue
        for t in tickers:
            if not t:
                continue
            by_ticker.setdefault(str(t).upper(), []).append(str(title))
    return by_ticker


# ─── Public orchestrator ─────────────────────────────────────────────────

def apply_post_cycle_protections(
    data_dir: Path,
    multi_account_results: Dict[str, Dict[str, Any]],
    plans: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Run all sweep_protection steps against every configured Alpaca account.

    Same signature as 3.1 — fully drop-in. Reads execution_policy.json to
    pick up market_mode, force-sweep floor, stale-close age, and SGOV
    redeploy hint. Falls back to safe defaults when no policy is present.
    """
    plans = plans or []
    summary: Dict[str, Dict[str, Any]] = {}

    try:
        from ..execution.multi_account import HARVEST_ACCOUNTS
    except Exception as e:
        print(f"[sweep] cannot import HARVEST_ACCOUNTS: {e}")
        return summary

    sweep_triggered, sweep_reason = _sweep_switch_signal(data_dir)
    in_close = in_closing_bell_window()
    in_danger, danger_label = in_danger_window()
    catalysts_idx = _build_catalysts_index(data_dir)

    policy = _load_policy(data_dir)
    market_mode = _market_mode_from_policy(policy)
    elite_set, urgent_set, strong_cat_set = _build_protection_carve_outs(policy)
    stale_age_days = _stale_close_age_days(policy)
    sgov_redeploy_pol = _sgov_redeploy_recommendation(policy)

    for cfg in HARVEST_ACCOUNTS:
        aid = cfg.account_id
        state = (multi_account_results or {}).get(aid)
        if not isinstance(state, dict) or not state.get("enabled"):
            continue
        headers = _headers_for(cfg.env_key_var, cfg.env_secret_var)
        if not headers:
            continue
        try:
            principal_target = _safe_f(
                getattr(cfg, "principal_target", 0) or state.get("principal_target"),
                0.0,
            )
            force_floor = _account_force_sweep_floor(policy, aid, principal_target)

            sec: Dict[str, Any] = {
                "version": VERSION,
                "checked_at": _now_iso(),
                "market_mode": market_mode,
                "force_sweep_floor_resolved": round(force_floor, 2),
                "stale_close_age_days": stale_age_days,
                "instant_sweeps":  [],
                "stale_closes":    [],
                "news_boosts":     [],
                "sgov_redeploys":  [],
                "force_sweep":     {"triggered": False, "reason": ""},
                "evening_shield":  {"triggered": False, "reason": ""},
                "danger_carve_outs": {
                    "elite":           sorted(elite_set),
                    "urgent":          sorted(urgent_set),
                    "strong_catalyst": sorted(strong_cat_set),
                },
            }

            positions = _api_get(_POSITIONS_ENDPOINT, headers) or []
            if not isinstance(positions, list):
                positions = []
            account = _api_get(_ACCOUNT_ENDPOINT, headers) or {}
            equity = _safe_f((account or {}).get("equity"))
            cash_settled = _safe_f((account or {}).get("cash"))
            position_meta = state.get("position_meta") or {}

            # ────── PRESERVATION mode short-circuit ──────
            # In PRESERVATION, we never run news boosts, never redeploy SGOV.
            # Instant sweep + stale-close still run because they're capital-
            # preserving, not capital-deploying.
            is_preservation = (market_mode == "PRESERVATION")

            # 1) Manual SWEEP switch — first, short-circuits everything else
            if sweep_triggered:
                orders = _force_sweep_one_account(
                    headers, positions, equity,
                    floor_usd=SWEEP_SWITCH_FLOOR_USD,
                    reason=f"manual SWEEP switch ({sweep_reason})",
                    spare_tickers=None,  # manual sweep is intentional, no carve-outs
                )
                sec["force_sweep"] = {
                    "triggered": True,
                    "reason": sweep_reason,
                    "equity_before": round(equity, 2),
                    "floor_usd": SWEEP_SWITCH_FLOOR_USD,
                    "orders": orders,
                }
                summary[aid] = sec
                _stamp_state(data_dir, cfg, sec)
                continue

            # 2) Big-winner end-of-day shield — now uses the policy-resolved
            #    per-account floor (principal × 1.05 minimum), NOT a bare
            #    constant that equalled starting principal.
            if in_close and equity >= force_floor:
                # In ATTACK, spare elite/urgent/strong-catalyst names
                spare = (elite_set | urgent_set | strong_cat_set
                          if market_mode == "ATTACK" else None)
                orders = _force_sweep_one_account(
                    headers, positions, equity,
                    floor_usd=force_floor,
                    reason=(
                        f"big-winner shield: equity ${equity:.2f} "
                        f"≥ floor ${force_floor:.0f} ({market_mode})"
                    ),
                    spare_tickers=spare,
                )
                sec["evening_shield"] = {
                    "triggered": True,
                    "reason": f"closing_bell + equity ${equity:.2f} ≥ ${force_floor:.0f}",
                    "equity_before": round(equity, 2),
                    "floor_used": round(force_floor, 2),
                    "spared_count": len(spare or []),
                    "orders": orders,
                }
                summary[aid] = sec
                _stamp_state(data_dir, cfg, sec)
                continue

            # 3) Danger-window protective liquidation — ATTACK mode spares
            #    elite/urgent/strong-catalyst names. Only act if there's
            #    something to protect on the non-spared book.
            if in_danger:
                # Compute upl only on non-spared positions in ATTACK
                spare = (elite_set | urgent_set | strong_cat_set
                          if market_mode == "ATTACK" else set())
                upl_total = 0.0
                for p in positions:
                    sym = (p.get("symbol") or "").upper()
                    if _is_vault(sym) or sym in spare:
                        continue
                    upl_total += _safe_f(p.get("unrealized_pl"))
                if upl_total > 0:
                    orders = _force_sweep_one_account(
                        headers, positions, equity,
                        floor_usd=force_floor,
                        reason=(f"danger window: {danger_label} ({market_mode})"),
                        spare_tickers=spare or None,
                    )
                    sec["evening_shield"] = {
                        "triggered": True,
                        "reason": (
                            f"danger window {danger_label} · positive non-spared "
                            f"unrealized ${upl_total:.2f} ({market_mode})"
                        ),
                        "equity_before": round(equity, 2),
                        "floor_used": round(force_floor, 2),
                        "spared_count": len(spare),
                        "orders": orders,
                    }
                    summary[aid] = sec
                    _stamp_state(data_dir, cfg, sec)
                    continue
                else:
                    sec["evening_shield"] = {
                        "triggered": False,
                        "reason": (
                            f"danger window {danger_label} — no positive unrealized "
                            f"on non-spared book; skip"
                        ),
                    }

            # 4) Instant sweep (positions with $300 or 5% unrealized)
            sec["instant_sweeps"] = _instant_sweep_one_account(headers, positions)

            # 5) Retroactive stale-close (mode-aware age + ATTACK carve-outs)
            spare_for_stale = (elite_set | urgent_set | strong_cat_set
                                if market_mode == "ATTACK" else set())
            sec["stale_closes"] = _close_stale_one_account(
                headers, positions, position_meta,
                max_age_days=stale_age_days,
                spare_tickers=spare_for_stale,
            )

            # 6) News-momentum escalation
            #    Skip in PRESERVATION (no new exposure).
            if not is_preservation:
                trading_capital = _safe_f(state.get("trading_capital"), principal_target)
                sec["news_boosts"] = _news_boost_one_account(
                    headers, positions, plans, catalysts_idx,
                    trading_capital=trading_capital,
                    max_position_pct=cfg.max_position_pct,
                )

            # 7) NEW — SGOV redeploy (sell vault back to cash when
            #    policy says deployment pressure is high)
            #    Never runs in PRESERVATION/DEFENSIVE; policy_router
            #    only recommends in ATTACK/BALANCED + pressure ≥ 0.70.
            if not is_preservation and market_mode != "DEFENSIVE":
                redeploys = _redeploy_sgov_one_account(
                    headers, positions, cash_settled,
                    redeploy_pol=sgov_redeploy_pol,
                    principal_target=principal_target,
                )
                sec["sgov_redeploys"] = redeploys

            summary[aid] = sec
            _stamp_state(data_dir, cfg, sec)
        except Exception as e:
            import traceback as _tb
            tb = "".join(_tb.format_exception_only(type(e), e)).strip()
            summary[aid] = {"error": tb, "checked_at": _now_iso()}
            print(f"[sweep] {aid} failed: {tb}")

    # Write a global summary.
    try:
        out_path = data_dir / "sweep_protection.json"
        out_path.write_text(json.dumps({
            "version": VERSION,
            "generated_at": _now_iso(),
            "market_session": _market_session_now(),
            "market_mode": market_mode,
            "extended_hours_active": _is_extended_session(),
            "sweep_switch_triggered": sweep_triggered,
            "sweep_switch_reason": sweep_reason if sweep_triggered else "",
            "in_closing_bell": in_close,
            "in_danger_window": in_danger,
            "danger_window_label": danger_label,
            "stale_close_age_days": stale_age_days,
            "elite_carve_outs":           sorted(elite_set),
            "urgent_carve_outs":          sorted(urgent_set),
            "strong_catalyst_carve_outs": sorted(strong_cat_set),
            "sgov_redeploy_recommended": bool(sgov_redeploy_pol.get("recommended")),
            "accounts": summary,
        }, indent=2, default=str))
    except Exception as e:
        print(f"[sweep] could not write summary: {e}")

    return summary


def _stamp_state(data_dir: Path, cfg, section: Dict[str, Any]) -> None:
    """Best-effort: merge `section` into the account's state file."""
    p = data_dir / cfg.state_filename
    if not p.exists():
        return
    try:
        body = json.loads(p.read_text())
        body["sweep_protection"] = section
        p.write_text(json.dumps(body, indent=2, default=str))
    except Exception as e:
        print(f"[sweep] could not stamp {p.name}: {e}")


__all__ = [
    "VERSION",
    "apply_post_cycle_protections",
    "in_closing_bell_window",
    "in_danger_window",
    "_market_session_now",
    "_is_extended_session",
    "_is_vault",
]
