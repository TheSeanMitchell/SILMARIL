"""
silmaril.analytics.realized_attribution — where the BANKED dollars came from.

Scoring tracks the quality of the *call*; this module tracks the *money*. From
the deal journal's actual order flow it pairs buys with subsequent sells per
(account, ticker) FIFO-style on notional, producing realized round-trips, then
rolls realized P&L up by account, ticker, and entry catalyst class. Finally it
distributes each round-trip's realized dollars across the agents whose scored
calls match that (ticker, entry-window, direction) — conviction-weighted — to
give an APPROXIMATE per-agent realized-dollar table (clearly labeled approx:
verdict-level fill attribution isn't stored historically, so this is the
closest deterministic reconstruction; it becomes exact for trades entered after
the deal journal began carrying conviction/signal).

No LLM. Read-only inputs (deal_journal.json, scoring.json). Writes
docs/data/realized_attribution.json.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

VERSION = "realized-attribution-1.0"
ENTRY_WINDOW_DAYS = 4  # scored call must sit within this many days of the entry


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


def _day(iso: str) -> str:
    return str(iso)[:10]


def _days_between(a: str, b: str) -> int:
    try:
        da = datetime.fromisoformat(a[:10]).date()
        db = datetime.fromisoformat(b[:10]).date()
        return abs((db - da).days)
    except Exception:
        return 9999


def build_realized_attribution(data_dir: Path) -> Dict[str, Any]:
    data_dir = Path(data_dir)
    dj = _load(data_dir / "deal_journal.json", {})
    cat_by_oid = {str(r.get("order_id")): r.get("catalyst_class")
                  for r in (dj.get("deals") or []) if r.get("order_id")}
    sc = _load(data_dir / "scoring.json", {})
    outcomes = sc.get("outcomes") or []

    # --- pair buys with later sells per (account, ticker), FIFO on qty ---
    # Source of truth for fills: the broker order logs in the three account
    # state files (status=filled with filled_avg_price/filled_qty). History
    # covers whatever the logs retain — labeled "since tracking began".
    flows: Dict[tuple, List[dict]] = defaultdict(list)
    for acct, fn in (("LEGACY", "alpaca_paper_state.json"),
                     ("HARVEST_3", "alpaca_h3_state.json"),
                     ("HARVEST_5", "alpaca_h5_state.json")):
        st = _load(data_dir / fn, {})
        for o in (st.get("orders") or []):
            if str(o.get("status") or "").lower() != "filled":
                continue
            tkr = str(o.get("symbol") or o.get("ticker") or "").upper()
            side = str(o.get("side") or "").lower()
            try:
                px = float(o.get("filled_avg_price") or 0)
                qty = float(o.get("filled_qty") or 0)
            except (TypeError, ValueError):
                continue
            if not tkr or px <= 0 or qty <= 0 or side not in ("buy", "sell"):
                continue
            flows[(acct, tkr)].append({
                "side": side, "px": px, "qty": qty,
                "time": o.get("filled_at") or o.get("submitted_at") or "",
                "cat": cat_by_oid.get(str(o.get("id") or o.get("order_id") or "")),
                "conv": None, "sig": None})
    for k in flows:
        flows[k].sort(key=lambda e: str(e.get("time", "")))

    trips: List[dict] = []
    for (acct, tkr), evs in flows.items():
        open_lots: List[dict] = []
        for e in evs:
            if e["side"] == "buy":
                open_lots.append(dict(e))
                continue
            sell_q = e["qty"]
            while sell_q > 1e-9 and open_lots:
                lot = open_lots[0]
                q = min(lot["qty"], sell_q)
                pnl = (e["px"] - lot["px"]) * q
                trips.append({"account": acct, "ticker": tkr,
                              "entry_time": lot["time"], "exit_time": e["time"],
                              "qty": round(q, 6), "entry_px": lot["px"], "exit_px": e["px"],
                              "realized": round(pnl, 4),
                              "catalyst_class": lot.get("cat"),
                              "hold_days": _days_between(str(lot["time"]), str(e["time"]))})
                lot["qty"] -= q
                sell_q -= q
                if lot["qty"] <= 1e-9:
                    open_lots.pop(0)

    # --- rollups ---
    def _roll(key):
        agg = defaultdict(lambda: {"realized": 0.0, "trips": 0, "wins": 0})
        for t in trips:
            k = t.get(key) or "unknown"
            a = agg[k]
            a["realized"] += t["realized"]; a["trips"] += 1
            a["wins"] += 1 if t["realized"] > 0 else 0
        return {k: {"realized": round(v["realized"], 2), "trips": v["trips"],
                    "wins": v["wins"]} for k, v in
                sorted(agg.items(), key=lambda kv: -kv[1]["realized"])}

    # --- approximate per-agent split via scored calls near the entry ---
    by_tkr_day: Dict[str, List[dict]] = defaultdict(list)
    for o in outcomes:
        t = str(o.get("ticker") or "").upper()
        if t:
            by_tkr_day[t].append(o)
    agent_real = defaultdict(lambda: {"realized": 0.0, "trips": 0})
    attributed = 0
    for t in trips:
        cands = [o for o in by_tkr_day.get(t["ticker"], [])
                 if str(o.get("signal", "")).upper().find("BUY") >= 0
                 and _days_between(str(o.get("entry_time") or o.get("date") or ""),
                                   str(t["entry_time"])) <= ENTRY_WINDOW_DAYS]
        if not cands:
            continue
        attributed += 1
        wsum = sum(max(0.05, float(o.get("conviction") or 0.3)) for o in cands)
        for o in cands:
            w = max(0.05, float(o.get("conviction") or 0.3)) / wsum
            a = agent_real[o.get("agent") or "unknown"]
            a["realized"] += t["realized"] * w
            a["trips"] += 1
    by_agent = {k: {"realized_approx": round(v["realized"], 2), "trips_touched": v["trips"]}
                for k, v in sorted(agent_real.items(), key=lambda kv: -kv[1]["realized"])}

    total = round(sum(t["realized"] for t in trips), 2)
    payload = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "round_trips": len(trips),
        "total_realized": total,
        "by_account": _roll("account"),
        "by_ticker": dict(list(_roll("ticker").items())[:25]),
        "by_catalyst_class": _roll("catalyst_class"),
        "by_agent_approx": by_agent,
        "agent_attribution_note": (
            "Per-agent split is APPROXIMATE: realized dollars are distributed "
            "conviction-weighted across agents whose scored BUY calls sat within "
            f"{ENTRY_WINDOW_DAYS} days of the entry. Account/ticker/catalyst rollups "
            "are exact from fill pairs."),
        "trips_attributed_to_agents": attributed,
        "recent_trips": sorted(trips, key=lambda x: str(x.get("exit_time", "")))[-20:],
    }
    _dump(data_dir / "realized_attribution.json", payload)
    return {"trips": len(trips), "total_realized": total, "agents": len(by_agent)}


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(build_realized_attribution(
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")), indent=2))
