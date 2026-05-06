"""
silmaril.execution.attribution — Alpaca order tagging and reconciliation.

Every order placed through the Alpaca bridge is tagged with the agent(s)
whose consensus call drove it. This creates a chain of custody:

  Gold    — order exists in Alpaca AND in our state (reconciled)
  Orphan  — order exists in Alpaca but we have NO record of placing it
  Phantom — we have a record of placing it but Alpaca has NO matching fill

The attribution map writes to docs/data/alpaca_attribution.json each
cycle so the dashboard can show which agent is responsible for each
Alpaca position and whether the books are balanced.

Used by: cli.py (after execute_consensus_signals returns), dashboard.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def tag_orders(
    orders_placed: List[Dict[str, Any]],
    debate_dicts: List[Dict[str, Any]],
    alpaca_positions: Optional[List[Dict[str, Any]]] = None,
    attribution_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Build the attribution map for this cycle.

    orders_placed   — list of orders from alpaca_paper_state["orders_placed"]
    debate_dicts    — the full debate output (used to trace which agents called each ticker)
    alpaca_positions — live open positions from Alpaca (optional, for reconciliation)
    attribution_path — where to write the attribution JSON (optional)

    Returns a dict with:
      "tagged_orders"  — orders annotated with driving agents
      "gold"           — tickers reconciled between our state and Alpaca
      "orphans"        — tickers in Alpaca but not in our records
      "phantoms"       — tickers we ordered but Alpaca has no record of
      "generated_at"   — timestamp
    """
    # Build a lookup: ticker → agents who voted BUY/STRONG_BUY
    ticker_agents: Dict[str, List[str]] = {}
    for d in debate_dicts:
        ticker = d.get("ticker", "")
        if not ticker:
            continue
        driving = []
        for v in d.get("verdicts", []):
            if v.get("signal") in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"):
                driving.append(v.get("agent", "UNKNOWN"))
        if driving:
            ticker_agents[ticker] = driving

    # Annotate each placed order with its driving agents
    tagged: List[Dict] = []
    our_tickers = set()
    for order in orders_placed:
        sym = order.get("symbol") or order.get("ticker", "")
        agents = ticker_agents.get(sym, ["CONSENSUS"])
        tagged.append({
            **order,
            "driving_agents": agents,
            "attributed_at": _now(),
        })
        our_tickers.add(sym)

    # Reconcile against live Alpaca positions
    alpaca_tickers = set()
    if alpaca_positions:
        for pos in alpaca_positions:
            sym = pos.get("symbol", "")
            if sym:
                alpaca_tickers.add(sym)

    gold = sorted(our_tickers & alpaca_tickers)
    orphans = sorted(alpaca_tickers - our_tickers)
    phantoms = sorted(our_tickers - alpaca_tickers)

    result = {
        "tagged_orders": tagged,
        "gold": gold,
        "orphans": orphans,
        "phantoms": phantoms,
        "order_count": len(tagged),
        "generated_at": _now(),
    }

    if orphans:
        print(f"[attribution] ⚠ {len(orphans)} ORPHAN position(s) in Alpaca not in our records: {orphans}")
    if phantoms:
        print(f"[attribution] ⚠ {len(phantoms)} PHANTOM order(s) we placed but Alpaca has no record: {phantoms}")
    if gold:
        print(f"[attribution] ✓ {len(gold)} GOLD position(s) reconciled: {gold}")

    if attribution_path:
        # Merge with existing attribution history
        existing = _load(attribution_path)
        history = existing.get("history", [])
        history.append(result)
        history = history[-90:]  # keep 90 cycles of history
        _save(attribution_path, {
            "latest": result,
            "history": history,
            "updated_at": _now(),
        })

    return result


def build_agent_position_map(
    debate_dicts: List[Dict[str, Any]],
    alpaca_positions: List[Dict[str, Any]],
) -> Dict[str, Dict]:
    """
    For each open Alpaca position, identify which agents called it.
    Returns a map: symbol → {agents, signal, conviction, side, unrealized_pnl}
    Used by the dashboard to display "FORGE's pick" etc.
    """
    ticker_to_consensus: Dict[str, Dict] = {
        d["ticker"]: d.get("consensus", {}) for d in debate_dicts if d.get("ticker")
    }
    ticker_to_agents: Dict[str, List[str]] = {}
    for d in debate_dicts:
        ticker = d.get("ticker", "")
        if not ticker:
            continue
        agents = [
            v["agent"] for v in d.get("verdicts", [])
            if v.get("signal") in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL")
            and v.get("agent")
        ]
        if agents:
            ticker_to_agents[ticker] = agents

    result: Dict[str, Dict] = {}
    for pos in alpaca_positions:
        sym = pos.get("symbol", "")
        if not sym:
            continue
        cons = ticker_to_consensus.get(sym, {})
        result[sym] = {
            "symbol": sym,
            "driving_agents": ticker_to_agents.get(sym, ["UNKNOWN"]),
            "consensus_signal": cons.get("signal", "UNKNOWN"),
            "consensus_conviction": cons.get("avg_conviction"),
            "side": "long" if float(pos.get("qty", 0)) > 0 else "short",
            "qty": pos.get("qty"),
            "avg_entry_price": pos.get("avg_entry_price"),
            "current_price": pos.get("current_price"),
            "unrealized_pl": pos.get("unrealized_pl"),
            "unrealized_plpc": pos.get("unrealized_plpc"),
        }
    return result
