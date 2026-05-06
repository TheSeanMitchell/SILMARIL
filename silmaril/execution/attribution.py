"""
silmaril.execution.attribution — Every Alpaca order tagged with its
source chain.

When you look at the Alpaca dashboard or the Trade Attribution Lab tab,
every order should answer: "Who decided this trade and why?"

The mechanism:
  1. Each order gets a client_order_id encoding source + agents + signals
     + cycle. Alpaca preserves it on the order record.
  2. A parallel record goes to docs/data/trade_attribution.json with the
     full breakdown (agents, signals, regime, conviction).
  3. After fills land, resolve_attribution_outcomes() back-fills realized
     P&L on the attribution records.

Source kinds (extensible):
  consensus              — main 15-voter consensus
  candidate-{NAME}       — a Senate candidate agent's tagged trade
  conclave-{NAME}        — a Conclave-born descendant's tagged trade

Storage: docs/data/trade_attribution.json (PROTECTED)
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Alpaca client_order_id has a 48-character limit. We compress aggressively.
_MAX_CLIENT_ORDER_ID = 48

# Pattern: SIL_{src}_{agentH}_{signalH}_{cyc}
# - src: 4 chars   (e.g. "cons", "cand", "conc")
# - agentH: 8 chars MD5 of comma-joined agent codenames
# - signalH: 8 chars MD5 of comma-joined signal types
# - cyc: 14 chars YYYYMMDDTHHMMSS
# Total with separators: 4 + 4 + 8 + 1 + 8 + 1 + 14 = 40 + SIL_ prefix = 44
_SRC_MAP = {
    "consensus": "cons",
    "candidate": "cand",
    "conclave": "conc",
}


def _short_hash(items: List[str]) -> str:
    """Stable 8-char hash of a sorted list — for compressed encoding."""
    if not items:
        return "00000000"
    joined = ",".join(sorted(items))
    return hashlib.md5(joined.encode("utf-8")).hexdigest()[:8]


def build_client_order_id(
    *,
    source: str,
    agent_codenames: List[str],
    signal_types: List[str],
    cycle_ts: Optional[datetime] = None,
) -> str:
    """
    Build a compact, Alpaca-safe client_order_id encoding the trade source.

    source: "consensus", "candidate-NIGHTSHADE_V2", "conclave-OSPREY", etc.
    agent_codenames: list of contributing agents (e.g. ["AEGIS", "FORGE"]).
    signal_types: list of contributing signal type names (may be empty).
    cycle_ts: cycle timestamp, defaults to now.

    Returns a string ≤ 48 chars. Lookup the full record in
    trade_attribution.json by this client_order_id.
    """
    when = cycle_ts if cycle_ts is not None else datetime.now(timezone.utc)
    cyc = when.strftime("%Y%m%dT%H%M%S")

    # Source kind: take the prefix before any "-" suffix
    kind = source.split("-", 1)[0].lower()
    src = _SRC_MAP.get(kind, "othr")

    aH = _short_hash(agent_codenames)
    sH = _short_hash(signal_types)

    cid = f"SIL_{src}_{aH}_{sH}_{cyc}"
    if len(cid) > _MAX_CLIENT_ORDER_ID:
        cid = cid[:_MAX_CLIENT_ORDER_ID]
    return cid


def record_attribution(
    *,
    attribution_path: Path,
    client_order_id: str,
    source: str,
    ticker: str,
    side: str,                     # "buy" | "sell" | "buy_to_cover" etc.
    notional: float,
    consensus_signal: str,
    consensus_conviction: float,
    contributing_agents: List[Dict[str, Any]],   # [{codename, signal, conviction}]
    contributing_signals: List[Dict[str, Any]],  # [{type, value, weight}]
    regime: Optional[str] = None,
    cycle_ts: Optional[datetime] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Append a full attribution record. Outcome fields (fill_price, slippage,
    realized_pnl) are filled in later by resolve_attribution_outcomes().

    Returns the record written.
    """
    when = cycle_ts if cycle_ts is not None else datetime.now(timezone.utc)

    record: Dict[str, Any] = {
        "client_order_id": client_order_id,
        "source": source,
        "ticker": ticker,
        "side": side,
        "notional": round(notional, 4),
        "consensus_signal": consensus_signal,
        "consensus_conviction": round(consensus_conviction, 4),
        "regime": regime or "UNKNOWN",
        "contributing_agents": contributing_agents,
        "contributing_signals": contributing_signals,
        "placed_at": when.isoformat(),
        # Outcome fields — populated by resolve_attribution_outcomes()
        "alpaca_order_id": None,
        "fill_price": None,
        "slippage_bps": None,
        "realized_pnl": None,
        "unrealized_pnl": None,
        "closed_at": None,
        "status": "OPEN",
    }
    if extras:
        record["extras"] = extras

    if attribution_path.exists():
        data = json.loads(attribution_path.read_text())
    else:
        data = {"records": []}

    data.setdefault("records", []).append(record)
    data["last_updated"] = when.isoformat()
    attribution_path.write_text(json.dumps(data, indent=2))
    return record


def find_record(attribution_path: Path, client_order_id: str) -> Optional[Dict[str, Any]]:
    """Lookup a record by client_order_id. Returns None if not found."""
    if not attribution_path.exists():
        return None
    data = json.loads(attribution_path.read_text())
    for rec in data.get("records", []):
        if rec.get("client_order_id") == client_order_id:
            return rec
    return None


def update_record_outcome(
    *,
    attribution_path: Path,
    client_order_id: str,
    alpaca_order_id: Optional[str] = None,
    fill_price: Optional[float] = None,
    slippage_bps: Optional[float] = None,
    realized_pnl: Optional[float] = None,
    unrealized_pnl: Optional[float] = None,
    closed_at: Optional[datetime] = None,
    status: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Update outcome fields on an existing record. Returns the updated record
    or None if not found.
    """
    if not attribution_path.exists():
        return None
    data = json.loads(attribution_path.read_text())

    for rec in data.get("records", []):
        if rec.get("client_order_id") != client_order_id:
            continue
        if alpaca_order_id is not None:
            rec["alpaca_order_id"] = alpaca_order_id
        if fill_price is not None:
            rec["fill_price"] = round(float(fill_price), 4)
        if slippage_bps is not None:
            rec["slippage_bps"] = round(float(slippage_bps), 2)
        if realized_pnl is not None:
            rec["realized_pnl"] = round(float(realized_pnl), 4)
        if unrealized_pnl is not None:
            rec["unrealized_pnl"] = round(float(unrealized_pnl), 4)
        if closed_at is not None:
            rec["closed_at"] = closed_at.isoformat()
        if status is not None:
            rec["status"] = status

        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        attribution_path.write_text(json.dumps(data, indent=2))
        return rec

    return None


def reconcile(
    attribution_path: Path,
    alpaca_orders: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Cross-reference SILMARIL records against Alpaca's actual orders.
    Returns three buckets:
      gold   — present in both (the happy path)
      orphan — present in Alpaca but not in attribution.json
      phantom — present in attribution.json but not in Alpaca

    alpaca_orders: list of dicts with at least 'client_order_id'.
    """
    if attribution_path.exists():
        data = json.loads(attribution_path.read_text())
        sil_records = data.get("records", [])
    else:
        sil_records = []

    sil_by_cid = {r.get("client_order_id"): r for r in sil_records if r.get("client_order_id")}
    alp_by_cid = {o.get("client_order_id"): o for o in alpaca_orders if o.get("client_order_id")}

    gold_cids = set(sil_by_cid.keys()) & set(alp_by_cid.keys())
    orphan_cids = set(alp_by_cid.keys()) - set(sil_by_cid.keys())
    phantom_cids = set(sil_by_cid.keys()) - set(alp_by_cid.keys())

    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "gold":    [{"client_order_id": cid, "sil": sil_by_cid[cid], "alpaca": alp_by_cid[cid]} for cid in gold_cids],
        "orphan":  [{"client_order_id": cid, "alpaca": alp_by_cid[cid]} for cid in orphan_cids],
        "phantom": [{"client_order_id": cid, "sil": sil_by_cid[cid]} for cid in phantom_cids],
        "summary": {
            "gold":    len(gold_cids),
            "orphan":  len(orphan_cids),
            "phantom": len(phantom_cids),
        },
    }
