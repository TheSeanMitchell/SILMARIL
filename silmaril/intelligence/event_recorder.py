"""
SILMARIL — Event Recorder (append-only, deterministic, REAL data only)
======================================================================

Captures the market's movement AROUND the ACTIVE IPO (chosen by ipo_calendar)
so the full arc — run-up, debut, hype decay — can be analyzed later. Tracking
rotates automatically as IPOs complete; this module just records whatever
ipo_calendar.active_ipo() returns.

Every value in a snapshot is REAL, pulled from data SILMARIL already produces:
  - index levels + 1d/1w/1mo moves <- benchmarking.json
  - per-name price/signal/headlines <- signals.json (debates)
  - sector rotation (money proxy)   <- news_intelligence.json (regime baskets)
  - our own order activity          <- alpaca_*_state.json (orders)

NOTHING is fabricated. "Money flow" is an explicit DERIVED proxy from real
sector signals — never invented dollar figures. Missing source -> empty field.

Storage is APPEND-ONLY: docs/data/event_tracking/<id>.json accumulates one
compact snapshot per run and is NEVER overwritten (the operator wants every bit).
ipo_analysis.py turns that time series into the learning layer for the cockpit.

Display-only; touches no trade logic. No LLM, no tokens, no external calls.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ipo_calendar import active_ipo, pipeline_status

log = logging.getLogger(__name__)

VERSION = "event-rec-2.0"

_ACCOUNT_FILES = {
    "LEGACY":    "alpaca_paper_state.json",
    "HARVEST_3": "alpaca_h3_state.json",
    "HARVEST_5": "alpaca_h5_state.json",
}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return None


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _flatten_complex(complex_groups: Dict[str, List[str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for group, tickers in (complex_groups or {}).items():
        for t in tickers:
            out[t.upper()] = group
    return out


def _market_block(benchmarking: Any, debates: List[Dict[str, Any]]) -> Dict[str, Any]:
    block: Dict[str, Any] = {}
    for d in debates:
        mr = (d.get("tags") or {}).get("market_regime")
        if mr:
            block["regime"] = mr
            break
    if isinstance(benchmarking, dict):
        obs = benchmarking.get("observations") or []
        if obs:
            last = obs[-1]
            block["silmaril_equity"] = last.get("silmaril_equity")
            for k in ("SPY", "QQQ", "XLK", "XLE"):
                if k in last:
                    block[k.lower() + "_level"] = last[k]
        windows = benchmarking.get("windows") or {}
        # multi-horizon moves so the drawdown INTO the event is visible
        for horizon, suffix in (("1d", "1d"), ("1w", "1w"), ("1mo", "1mo")):
            w = windows.get(horizon) or {}
            for src, base in (("spy_return", "spy"), ("qqq_return", "qqq"),
                              ("xlk_return", "xlk"), ("xle_return", "xle")):
                if src in w:
                    block[f"{base}_{suffix}"] = round(float(w[src]) * 100, 2)
    return block


def _complex_block(complex_map: Dict[str, str], by_ticker: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for tkr, group in complex_map.items():
        d = by_ticker.get(tkr)
        if not d:
            rows.append({"ticker": tkr, "group": group, "in_universe": False})
            continue
        cons = d.get("consensus") or {}
        rows.append({
            "ticker": tkr,
            "group": group,
            "in_universe": True,
            "price": d.get("price"),
            "signal": (cons.get("signal") or "HOLD").upper(),
            "score": round(float(cons.get("score") or 0.0), 3),
            "headlines": len(d.get("recent_headlines") or []),
            "sector": d.get("sector", ""),
            "news_state": (d.get("tags") or {}).get("news_state", "NORMAL"),
        })
    rows.sort(key=lambda r: (-int(r.get("headlines", 0) or 0), -abs(r.get("score", 0) or 0)))
    return rows


def _money_flow_block(intel: Any) -> List[Dict[str, Any]]:
    if not isinstance(intel, dict):
        return []
    baskets = (intel.get("stocks") or {}).get("baskets") or []
    out = []
    for b in baskets[:14]:
        out.append({
            "basket": b.get("basket"),
            "etf": b.get("etf"),
            "net_score": b.get("net_score"),
            "stance": b.get("stance"),
            "headline_count": b.get("headline_count"),
        })
    return out


def _hot_stocks_block(intel: Any) -> List[Dict[str, Any]]:
    if not isinstance(intel, dict):
        return []
    out = []
    for m in ((intel.get("stocks") or {}).get("momentum") or [])[:8]:
        out.append({"ticker": m.get("ticker"), "side": "stock", "headlines": m.get("headlines"),
                    "signal": m.get("signal"), "momentum": m.get("momentum"), "news_state": m.get("news_state")})
    for m in ((intel.get("other") or {}).get("momentum") or [])[:3]:
        out.append({"ticker": m.get("ticker"), "side": "other", "headlines": m.get("headlines"),
                    "signal": m.get("signal"), "momentum": m.get("momentum"), "news_state": m.get("news_state")})
    return out


def _our_activity_block(data_dir: Path, complex_map: Dict[str, str], limit: int = 15) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for acct, fname in _ACCOUNT_FILES.items():
        st = _load(data_dir / fname)
        if not isinstance(st, dict):
            continue
        for o in (st.get("orders") or []):
            sym = (o.get("symbol") or "").upper()
            if sym in complex_map:
                rows.append({
                    "account": acct,
                    "symbol": sym,
                    "group": complex_map[sym],
                    "side": o.get("side") or o.get("action"),
                    "notional": o.get("notional"),
                    "signal": o.get("signal"),
                    "time": o.get("time") or o.get("timestamp"),
                })
    rows.sort(key=lambda r: str(r.get("time") or ""), reverse=True)
    return rows[:limit]


def record_event_snapshots(data_dir: Path) -> Dict[str, Any]:
    """Append one REAL snapshot for the ACTIVE IPO; write a light summary."""
    data_dir = Path(data_dir)
    today = _today()
    now_iso = datetime.now(timezone.utc).isoformat()

    signals = _load(data_dir / "signals.json") or {}
    debates: List[Dict[str, Any]] = signals.get("debates", []) if isinstance(signals, dict) else []
    by_ticker = {(d.get("ticker") or "").upper(): d for d in debates if d.get("ticker")}
    intel = _load(data_dir / "news_intelligence.json")
    benchmarking = _load(data_dir / "benchmarking.json")

    track_dir = data_dir / "event_tracking"
    try:
        track_dir.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass

    active = active_ipo(today)
    summary: Dict[str, Any] = {
        "version": VERSION,
        "generated_at": now_iso,
        "active_id": active["id"] if active else None,
        "pipeline": pipeline_status(today),
        "events": [],
    }

    if active is None:
        try:
            (data_dir / "event_tracking_summary.json").write_text(json.dumps(summary, indent=2))
        except Exception:  # noqa: BLE001
            pass
        log.info("  Event recorder: no IPO currently in window — pipeline only")
        return summary

    du = (datetime.strptime(active["date"][:10], "%Y-%m-%d").date() - today).days
    complex_map = _flatten_complex(active.get("complex", {}))

    snap = {
        "ts": now_iso,
        "days_until": du,
        "market": _market_block(benchmarking, debates),
        "complex": _complex_block(complex_map, by_ticker),
        "money_flow_proxy": _money_flow_block(intel),
        "hot_stocks": _hot_stocks_block(intel),
        "our_activity": _our_activity_block(data_dir, complex_map),
    }

    ev_path = track_dir / f"{active['id']}.json"
    store = _load(ev_path)
    if not isinstance(store, dict) or "snapshots" not in store:
        store = {"first_snapshot": now_iso, "snapshots": []}
    # always refresh meta from the registry (preserves accumulated snapshots)
    store["event"] = {k: active.get(k) for k in
                      ("id", "company", "ticker", "date", "pricing_date", "exchange",
                       "valuation_usd", "raise_usd", "underwriters", "sector", "note")}
    store["complex_definition"] = active.get("complex", {})
    store["snapshots"].append(snap)
    store["last_snapshot"] = now_iso
    store["snapshot_count"] = len(store["snapshots"])
    try:
        ev_path.write_text(json.dumps(store, indent=2))
        log.info("  Event recorder [%s]: snapshot #%d appended (T%+dd)",
                 active["id"], store["snapshot_count"], du)
    except Exception as e:  # noqa: BLE001
        log.warning("  Event recorder [%s]: write failed — %s", active["id"], e)

    summary["events"].append({
        "id": active["id"],
        "company": active["company"],
        "ticker": active.get("ticker"),
        "date": active.get("date"),
        "days_until": du,
        "recording": True,
        "snapshot_count": store.get("snapshot_count"),
    })
    try:
        (data_dir / "event_tracking_summary.json").write_text(json.dumps(summary, indent=2))
    except Exception:  # noqa: BLE001
        pass
    return summary


if __name__ == "__main__":
    import sys
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    s = record_event_snapshots(d)
    print("active:", s.get("active_id"), "| events:", len(s.get("events", [])))
