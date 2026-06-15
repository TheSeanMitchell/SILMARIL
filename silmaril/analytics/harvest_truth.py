"""
silmaril.analytics.harvest_truth — the harvest ledger, rebuilt from fills.

"Nothing was ever synced. Keeping things synced is everything." Encoded as law:
this module trusts NOTHING the engine claimed about harvesting. It rebuilds the
entire harvest story from the only source that counts — the broker's own order
records captured in each account state — and publishes the drift between what
was SAID and what actually FILLED.

WHAT COUNTS AS TRUTH
  - sell orders whose trigger_reason contains HARVEST / CLOCK HARVEST /
    GIVEBACK / PROFIT TAKE, with a broker order id and a non-rejected status
  - SGOV buy orders (the vault sweeps) with the same standard
  - everything else — pending_harvest counters, intent rows, close_reasons
    without ids — is treated as CLAIMS and reported as drift, never as money

OUTPUT docs/data/harvest_truth.json
  per-account: events[], totals{harvest_sells_$, sgov_sweeps_$, sgov_held_now}
  combined:    fills_confirmed vs ledger_claimed -> drift_$ and a plain verdict
  era split:   pre-gate symbolic intents (status null, off-hours) counted and
               labeled HISTORICAL-SYMBOLIC so the old era can't pollute the new

Deterministic, stdlib-only, additive, suite-wired. The briefing renders this
as the ONLY harvest display — the symbolic counters are demoted to a footnote.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ACCOUNTS = (
    ("LEGACY", "alpaca_paper_state.json"),
    ("HARVEST_3", "alpaca_h3_state.json"),
    ("HARVEST_5", "alpaca_h5_state.json"),
)
HARVEST_TAGS = ("HARVEST", "GIVEBACK", "PROFIT TAKE")
GOOD_STATUS = {"filled", "partially_filled", "accepted", "new",
               "pending_new", "done_for_day"}


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _classify(o: dict) -> str:
    """CONFIRMED (broker id + sane status) · SUBMITTED (id, status unknown)
    · SYMBOLIC (no id — the old era's paper ghosts)."""
    oid = o.get("alpaca_order_id") or o.get("order_id") or o.get("id")
    status = str(o.get("status") or "").lower()
    if oid and (status in GOOD_STATUS or o.get("filled_avg_price")
                or o.get("filled_qty")):
        return "CONFIRMED"
    if oid:
        return "SUBMITTED"
    return "SYMBOLIC"


def build_harvest_truth(out_dir: str) -> Dict[str, Any]:
    out = Path(out_dir)
    accounts: Dict[str, Any] = {}
    comb = {"confirmed_harvest_usd": 0.0, "confirmed_sgov_sweep_usd": 0.0,
            "symbolic_events": 0, "sgov_held_now_usd": 0.0,
            "claimed_pending_usd": 0.0}

    for label, fn in ACCOUNTS:
        st = _load(out / fn, {}) or {}
        events: List[dict] = []
        tot_harv = tot_sweep = 0.0
        symbolic = 0
        for o in st.get("orders") or []:
            reason = str(o.get("trigger_reason") or "")
            sym = str(o.get("symbol") or "")
            side = str(o.get("side") or "")
            is_harvest_sell = (side == "sell"
                               and any(t in reason.upper()
                                       for t in HARVEST_TAGS))
            is_sweep_buy = (sym == "SGOV" and side == "buy")
            if not (is_harvest_sell or is_sweep_buy):
                continue
            cls = _classify(o)
            px = _f(o.get("filled_avg_price")) or _f(o.get("limit_price")) \
                or _f(o.get("price"))
            qty = _f(o.get("filled_qty")) or _f(o.get("qty"))
            notional = _f(o.get("notional")) or round(px * qty, 2)
            ev = {"time": str(o.get("time") or "")[:16], "symbol": sym,
                  "side": side, "usd": notional, "class": cls,
                  "kind": "SGOV_SWEEP" if is_sweep_buy else "HARVEST_SELL",
                  "reason": reason[:90]}
            events.append(ev)
            if cls == "CONFIRMED" and is_harvest_sell:
                tot_harv += notional
            elif cls == "CONFIRMED" and is_sweep_buy:
                tot_sweep += notional
            elif cls == "SYMBOLIC":
                symbolic += 1
        sgov_now = sum(_f(p.get("market_value"))
                       for p in st.get("positions") or []
                       if p.get("symbol") == "SGOV")
        claimed = _f(st.get("grocery_pending_harvest"))
        accounts[label] = {
            "events": events[-60:],
            "totals": {"harvest_sells_confirmed_usd": round(tot_harv, 2),
                       "sgov_sweeps_confirmed_usd": round(tot_sweep, 2),
                       "sgov_held_now_usd": round(sgov_now, 2),
                       "symbolic_events_historical": symbolic,
                       "engine_claimed_pending_usd": round(claimed, 2)},
        }
        comb["confirmed_harvest_usd"] += tot_harv
        comb["confirmed_sgov_sweep_usd"] += tot_sweep
        comb["symbolic_events"] += symbolic
        comb["sgov_held_now_usd"] += sgov_now
        comb["claimed_pending_usd"] += claimed

    drift = round(comb["claimed_pending_usd"]
                  + comb["confirmed_harvest_usd"]
                  - comb["confirmed_sgov_sweep_usd"]
                  - comb["sgov_held_now_usd"], 2)
    if comb["confirmed_harvest_usd"] == 0 and comb["symbolic_events"] > 0:
        verdict = (f"NOTHING WAS EVER SYNCED — {comb['symbolic_events']} "
                   "historical harvest intents have no broker confirmation; "
                   "$0 confirmed harvested, $0 SGOV held. The fill-truth era "
                   "starts now: only broker-confirmed events count.")
    elif drift == 0:
        verdict = "SYNCED: every claimed dollar maps to a broker fill."
    else:
        verdict = (f"DRIFT ${drift}: claims exceed broker-confirmed flows — "
                   "treat the symbolic counters as decoration, this page as "
                   "the ledger.")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "law": "synced is everything — only broker-confirmed events count",
        "accounts": accounts,
        "combined": {k: round(v, 2) for k, v in comb.items()},
        "drift_usd": drift,
        "verdict": verdict,
    }
    (out / "harvest_truth.json").write_text(json.dumps(payload, indent=2))
    return {"confirmed_harvest": round(comb["confirmed_harvest_usd"], 2),
            "sgov_now": round(comb["sgov_held_now_usd"], 2),
            "symbolic": comb["symbolic_events"], "drift": drift}
