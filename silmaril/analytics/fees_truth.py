"""
silmaril.analytics.fees_truth — the real-world cost layer (ALPHA 1.0).

WHY: Alpaca PAPER fills charge nothing. Real US-equity trading is
"commission-free" but NOT free: sells pay the SEC transaction fee and
FINRA's Trading Activity Fee (TAF), and every market order pays the
spread. A book graded without these is structurally flattered — and a
$100/day harvest target that ignores ~basis-points-per-round-trip drag
is a lie at scale. This organ retro-estimates real-world costs across
EVERY recorded order (all three accounts, full history) and publishes a
net-of-fees view, so every agent, harvest, and expectation can be judged
against what a REAL account would have kept.

FEE MODEL (US equities; rates are config constants — they change, so a
networked pass should verify quarterly; the model is labeled ESTIMATE):
  SEC fee   sells only: SEC_FEE_PER_DOLLAR x sell notional
  TAF       sells only: TAF_PER_SHARE x shares, capped TAF_CAP per order
  Slippage  both sides, market orders: SLIPPAGE_BPS of notional — the
            half-spread cost of demanding liquidity in liquid large-caps.
            Limit orders are assigned zero slippage (they MAKE liquidity).
  (Crypto's notorious taker fees are why the valuables zone gets its own
   fee table when that book opens — constant included now, unused.)

COVERAGE HONESTY: old sell rows often carry qty but no notional/price.
TAF is exact from qty; SEC/slippage need dollars. Rows missing dollars
are counted and reported as estimation gaps — never silently guessed.

OUTPUT docs/data/fees_truth.json: per-account totals, per-side breakdown,
round-trip cost estimate per $1K traded, net-of-fees equity view, and the
headline: lifetime estimated drag vs lifetime realized P&L.
Read-only over order history; touches nothing else. Suite step.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

VERSION = "fees-truth-1.0"

# ── fee constants (verify quarterly on a networked pass) ───────────────
SEC_FEE_PER_DOLLAR = 27.80 / 1_000_000   # SEC Section 31, sells
TAF_PER_SHARE = 0.000166                 # FINRA TAF, sells (equities)
TAF_CAP_PER_ORDER = 8.30
SLIPPAGE_BPS_MARKET = 2.0                # half-spread est., liquid names
CRYPTO_TAKER_BPS = 25.0                  # future valuables zone (unused)

ACCOUNT_FILES = (
    ("LEGACY", "alpaca_paper_state.json"),
    ("HARVEST_3", "alpaca_h3_state.json"),
    ("HARVEST_5", "alpaca_h5_state.json"),
)

_BUY_ACTIONS = ("OPEN", "OPEN_ELITE", "SCALE_IN", "REDEPLOY_FROM_SGOV")
_SELL_ACTIONS = ("CLOSE", "SCALE_OUT", "HARVEST", "SHORT", "SGOV_SWEEP",
                 "INTRADAY_EXHAUSTION", "EXIT", "BLEED")
_NONTRADE_ACTIONS = ("STOP_ADJUST",)


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _dump(path: Path, obj: Any) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, allow_nan=False)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _f(x, default=0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def estimate_order_costs(row: Dict[str, Any]) -> Dict[str, Any]:
    """Estimated real-world cost of one recorded order row.
    Returns {sec, taf, slippage, total, side, notional_known}."""
    action = str(row.get("action") or "")
    side = str(row.get("side") or "").lower()
    if action in _NONTRADE_ACTIONS:
        return {"sec": 0.0, "taf": 0.0, "slippage": 0.0, "total": 0.0,
                "side": "none", "notional_known": True}
    is_sell = (side == "sell") or (action in _SELL_ACTIONS and side != "buy")
    qty = _f(row.get("qty") or row.get("submitted_qty") or
             row.get("filled_qty"))
    notional = _f(row.get("notional"))
    if not notional:
        px = _f(row.get("exit_price") if is_sell else row.get("entry_price"))
        if not px:
            px = _f(row.get("filled_avg_price") or row.get("limit_price"))
        if qty and px:
            notional = qty * px
    notional_known = notional > 0
    is_limit = bool(row.get("use_limit")) or (
        str(row.get("order_type") or "").lower() == "limit")
    slippage = (0.0 if is_limit else
                notional * SLIPPAGE_BPS_MARKET / 10_000.0)
    sec = notional * SEC_FEE_PER_DOLLAR if is_sell else 0.0
    taf = min(qty * TAF_PER_SHARE, TAF_CAP_PER_ORDER) if (is_sell and qty) else 0.0
    return {"sec": round(sec, 4), "taf": round(taf, 4),
            "slippage": round(slippage, 4),
            "total": round(sec + taf + slippage, 4),
            "side": ("sell" if is_sell else "buy"),
            "notional_known": notional_known}


def round_trip_cost_per_1k(limit_orders: bool = False) -> float:
    """Estimated cost of buying then selling $1,000 of a liquid equity at
    ~typical share counts (assume $100/share => 10 shares). The honest
    number every harvest floor must clear."""
    slip = 0.0 if limit_orders else 2 * (1000 * SLIPPAGE_BPS_MARKET / 10_000.0)
    sec = 1000 * SEC_FEE_PER_DOLLAR
    taf = min(10 * TAF_PER_SHARE, TAF_CAP_PER_ORDER)
    return round(slip + sec + taf, 4)


def build_fees_truth(out_dir) -> Dict[str, Any]:
    out = Path(out_dir)
    accounts: Dict[str, Any] = {}
    for account_id, fn in ACCOUNT_FILES:
        st = _load(out / fn, {})
        orders: List[dict] = st.get("orders") or []
        tot = {"sec": 0.0, "taf": 0.0, "slippage": 0.0, "total": 0.0}
        n_buy = n_sell = n_gap = 0
        traded_notional = 0.0
        for row in orders:
            c = estimate_order_costs(row)
            if c["side"] == "none":
                continue
            for k in ("sec", "taf", "slippage", "total"):
                tot[k] += c[k]
            if c["side"] == "sell":
                n_sell += 1
            else:
                n_buy += 1
            if not c["notional_known"]:
                n_gap += 1
            else:
                traded_notional += _f(row.get("notional")) or 0.0
        equity = _f((st.get("account") or {}).get("equity"))
        realized = (_f(st.get("lifetime_realized_wins"))
                    - abs(_f(st.get("lifetime_realized_losses"))))
        tot = {k: round(v, 2) for k, v in tot.items()}
        accounts[account_id] = {
            "orders_seen": len(orders),
            "buys": n_buy, "sells": n_sell,
            "estimation_gaps": n_gap,
            "gap_note": (f"{n_gap} sell row(s) lack price/notional — TAF "
                         f"exact from qty; SEC/slippage under-counted there"
                         if n_gap else "full coverage"),
            "est_lifetime_fees": tot,
            "paper_equity": round(equity, 2),
            "net_of_fees_equity_view": round(equity - tot["total"], 2),
            "lifetime_realized_pnl": round(realized, 2),
            "fees_vs_realized_pct": (round(tot["total"] / abs(realized) * 100.0, 1)
                                     if realized else None),
        }
    payload = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "sec_fee_per_million_sold": round(SEC_FEE_PER_DOLLAR * 1e6, 2),
            "taf_per_share_sold": TAF_PER_SHARE,
            "taf_cap_per_order": TAF_CAP_PER_ORDER,
            "slippage_bps_market_orders": SLIPPAGE_BPS_MARKET,
            "crypto_taker_bps_future_zone": CRYPTO_TAKER_BPS,
            "note": ("ESTIMATES of real-account drag paper trading never "
                     "charges; rates are config — verify quarterly"),
        },
        "round_trip_cost_per_1k": {
            "market_orders": round_trip_cost_per_1k(False),
            "limit_orders": round_trip_cost_per_1k(True),
            "law": ("every harvest floor must clear this number — a 'win' "
                    "smaller than the round trip is a real-world loss"),
        },
        "accounts": accounts,
    }
    _dump(out / "fees_truth.json", payload)
    return {a: f"${accounts[a]['est_lifetime_fees']['total']:.2f} est drag"
            for a, _ in ACCOUNT_FILES if a in accounts}


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(build_fees_truth(
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")), indent=2))
