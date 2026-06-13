"""
SILMARIL — Deal Journal (read-only, append-only, REAL data only)
================================================================

The recurring ask: every trade should carry a note of WHEN and WHY it was made —
the news that informed it — and connect to how it turned out. This builds exactly
that, the SAFE way: it OBSERVES the orders the system already placed and journals
the surrounding context. It does NOT touch the live trade path (that wiring is the
gated Track-B step); this is its read-only sibling, so it's safe before Monday.

It connects the three things the operator wants linked:
  WORDS   — the headlines + catalyst class + regime around the trade
  ACTIONS — the order itself (side, size, conviction, signal)
  NUMBERS — the realized outcome (return, win/loss) once it scores

Per the EC checklist this covers: EC-02 (catalyst classification), EC-06 (why a
trade succeeded — attribution context), EC-07 (failed theses preserved with equal
fidelity), EC-09 (timestamp / sector / catalyst / regime / conviction completeness).

Honesty rules:
  - Rich news/regime/benchmark context is attached ONLY to orders journaled near
    their execution (context_basis="live"). Older orders are backfilled with the
    fields that are historically valid (ticker, side, size, conviction, sector,
    IPO-complex membership) and marked context_basis="backfill" — we do NOT attach
    current headlines to an old trade and pretend they were the cause.
  - Outcome links are recomputed each run from real scored outcomes; losses are kept
    exactly like wins.
  - No LLM, no external calls. Append-only: docs/data/deal_journal.json.
"""

from __future__ import annotations

import json
import logging
import statistics as _stats
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

VERSION = "deal-journal-1.0"

_ACCOUNTS = {"LEGACY": "alpaca_paper_state.json",
             "HARVEST_3": "alpaca_h3_state.json",
             "HARVEST_5": "alpaca_h5_state.json"}

_LIVE_WINDOW_DAYS = 2          # order journaled within N days of execution => full context
_LINK_LOOKBACK_DAYS = 5        # outcome.predicted_at within N days of the order
_SIG_MOVE_PCT = 1.0

# catalyst-type -> EC-02 class
_TYPE_CLASS = {
    "earnings": "earnings",
    "cpi": "macro", "fomc": "macro", "bls_empl": "macro", "ppi": "macro",
    "pce": "macro", "gdp": "macro", "jobs": "macro",
    "opex": "structural", "opex_quarterly": "structural", "index_rebalance": "structural",
    "ex_div": "dividend", "crypto_unlock": "crypto",
}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return None


def _d(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:  # noqa: BLE001
        return None


def _headline_titles(debate: Dict[str, Any], n: int = 3) -> List[str]:
    out = []
    for h in (debate.get("recent_headlines") or [])[:n]:
        if isinstance(h, dict):
            t = h.get("title") or h.get("headline") or ""
        else:
            t = str(h)
        if t:
            out.append(t[:140])
    return out


def _active_ipo_complex() -> Optional[Dict[str, Any]]:
    """Authoritative full complex for the active IPO (group -> [tickers]), from the
    registry — not the truncated display snapshot. market_rotation excluded."""
    try:
        from .ipo_calendar import active_ipo
        a = active_ipo()
    except Exception:  # noqa: BLE001
        return None
    if not a:
        return None
    groups = {g: [t.upper() for t in tk] for g, tk in (a.get("complex") or {}).items()
              if g != "market_rotation"}
    return {"company": a.get("company"), "groups": groups}


def _ipo_group_of(ticker: str, ipo_complex: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Is this ticker a DIRECT part of the active IPO complex? Return {company, group}.
    Broad-market exposure (market_rotation) is excluded upstream."""
    if not ipo_complex:
        return None
    for grp, tickers in (ipo_complex.get("groups") or {}).items():
        if ticker in tickers:
            return {"company": ipo_complex.get("company"), "group": grp}
    return None


def _classify_catalyst(ticker: str, order_dt: Optional[date], debate: Dict[str, Any],
                       cat_events: List[Dict[str, Any]], ipo_group: Optional[Dict[str, str]],
                       live: bool) -> str:
    if ipo_group:
        return "ipo_related"
    if live and order_dt:
        # a dated catalyst on this ticker within +/-3 days of the order
        for e in cat_events:
            if (e.get("ticker") or "").upper() != ticker:
                continue
            ed = _d(e.get("date"))
            if ed and abs((ed - order_dt).days) <= 3:
                return _TYPE_CLASS.get((e.get("type") or "").lower(), "macro")
    if live:
        ns = (debate.get("tags") or {}).get("news_state", "NORMAL")
        if ns in ("HOT", "ELEVATED") or (debate.get("recent_headlines")):
            return "narrative_social"
    return "unknown"


def _benchmark_snapshot(benchmarking: Any) -> Dict[str, Any]:
    if not isinstance(benchmarking, dict):
        return {}
    obs = benchmarking.get("observations") or []
    if not obs:
        return {}
    last = obs[-1]
    return {k: last.get(k) for k in ("SPY", "QQQ", "XLK", "XLE") if last.get(k) is not None}


def _collect_orders(data_dir: Path) -> List[Dict[str, Any]]:
    rows = []
    for acct, fname in _ACCOUNTS.items():
        st = _load(data_dir / fname)
        if not isinstance(st, dict):
            continue
        for o in (st.get("orders") or []):
            oid = o.get("order_id")
            if not oid or not o.get("symbol"):
                continue
            rows.append({"account": acct, "order_id": oid, "ticker": (o.get("symbol") or "").upper(),
                         "side": o.get("side") or o.get("action"), "notional": o.get("notional"),
                         "conviction": o.get("conviction"), "signal": o.get("signal"),
                         "time": o.get("time") or o.get("timestamp")})
    return rows


def _link_outcome(deal: Dict[str, Any], outcomes_by_ticker: Dict[str, List[Dict[str, Any]]]) -> None:
    odt = _d(deal.get("time"))
    cands = outcomes_by_ticker.get(deal["ticker"]) or []
    best = None
    for o in cands:
        pa = _d(o.get("predicted_at"))
        if pa and odt and abs((pa - odt).days) <= _LINK_LOOKBACK_DAYS:
            best = o
            break
    if best:
        deal["outcome"] = {
            "return_pct": best.get("return_pct"),
            "correct": best.get("correct"),
            "scored_at": best.get("scored_at"),
            "result": "win" if best.get("correct") else "loss",
        }
    elif "outcome" not in deal:
        deal["outcome"] = None


def build_deal_journal(data_dir: Path) -> Dict[str, Any]:
    data_dir = Path(data_dir)
    today = datetime.now(timezone.utc).date()
    now_iso = datetime.now(timezone.utc).isoformat()

    sig = _load(data_dir / "signals.json") or {}
    debates = {(d.get("ticker") or "").upper(): d for d in sig.get("debates", []) if d.get("ticker")}
    cat_doc = _load(data_dir / "catalysts.json") or {}
    cat_events = (cat_doc.get("daily") or []) + (cat_doc.get("weekly") or [])
    benchmarking = _load(data_dir / "benchmarking.json")
    ipo_complex = _active_ipo_complex()
    bench_now = _benchmark_snapshot(benchmarking)
    try:
        from ..universe.core import asset_class_of  # noqa: F401
    except Exception:  # noqa: BLE001
        pass

    # existing journal (append-only)
    store = _load(data_dir / "deal_journal.json")
    deals: List[Dict[str, Any]] = (store.get("deals") if isinstance(store, dict) else None) or []
    seen = {d.get("order_id") for d in deals}

    # journal NEW orders
    for o in _collect_orders(data_dir):
        if o["order_id"] in seen:
            continue
        seen.add(o["order_id"])
        odt = _d(o.get("time"))
        live = bool(odt and (today - odt).days <= _LIVE_WINDOW_DAYS)
        deb = debates.get(o["ticker"], {})
        sector = deb.get("sector")
        ipo_group = _ipo_group_of(o["ticker"], ipo_complex)
        deal = {
            "order_id": o["order_id"], "account": o["account"], "ticker": o["ticker"],
            "side": o["side"], "notional": o["notional"], "conviction": o["conviction"],
            "signal": o["signal"], "time": o["time"], "sector": sector,
            "context_basis": "live" if live else "backfill",
            "catalyst_class": _classify_catalyst(o["ticker"], odt, deb, cat_events, ipo_group, live),
            "ipo_complex": ipo_group,
        }
        if live:
            deal["headlines"] = _headline_titles(deb)
            deal["headline_count"] = len(deb.get("recent_headlines") or [])
            deal["regime"] = {k: (deb.get("tags") or {}).get(k) for k in
                              ("market_regime", "trend_state", "vol_state", "news_state", "liquidity_state")
                              if (deb.get("tags") or {}).get(k)}
            deal["benchmark_at_journal"] = bench_now
        deals.append(deal)

    # outcome linkage — recomputed each run (wins AND losses)
    outcomes = (_load(data_dir / "scoring.json") or {}).get("outcomes", []) if isinstance(_load(data_dir / "scoring.json"), dict) else []
    obt: Dict[str, List[Dict[str, Any]]] = {}
    for oc in outcomes:
        if not oc.get("stale_price_suspected"):
            obt.setdefault((oc.get("ticker") or "").upper(), []).append(oc)
    for d in deals:
        _link_outcome(d, obt)

    # ── aggregates for the cockpit ──
    live_deals = [d for d in deals if d.get("context_basis") == "live"]
    linked = [d for d in deals if d.get("outcome")]

    def _agg(rows):
        rets = [float(d["outcome"]["return_pct"]) for d in rows
                if d.get("outcome") and isinstance(d["outcome"].get("return_pct"), (int, float))]
        wins = sum(1 for d in rows if d.get("outcome") and d["outcome"].get("correct"))
        n_out = sum(1 for d in rows if d.get("outcome"))
        return {
            "n": len(rows),
            "linked": n_out,
            "avg_return": round(_stats.mean(rets), 3) if rets else None,
            "win_rate": round(wins / n_out, 3) if n_out else None,
        }

    by_class: Dict[str, List[Dict[str, Any]]] = {}
    for d in deals:
        by_class.setdefault(d.get("catalyst_class", "unknown"), []).append(d)
    class_rows = [dict(catalyst_class=c, **_agg(v)) for c, v in by_class.items()]
    class_rows.sort(key=lambda r: -r["n"])

    # news-vs-silence (forward-accumulating; uses live+linked deals only)
    with_news = [d for d in live_deals if d.get("headline_count")]
    no_news = [d for d in live_deals if not d.get("headline_count")]
    news_vs_silence = {"news_backed": _agg(with_news), "silent": _agg(no_news)}

    recent = sorted(deals, key=lambda d: str(d.get("time") or ""), reverse=True)[:24]

    out = {
        "version": VERSION,
        "generated_at": now_iso,
        "deals_count": len(deals),
        "live_count": len(live_deals),
        "linked_count": len(linked),
        "by_catalyst_class": class_rows,
        "news_vs_silence": news_vs_silence,
        "recent": recent,
        "note": ("Read-only journal of real orders with the news/catalyst/regime context "
                 "around them, linked to realized outcomes (wins and losses kept equally). "
                 "Rich context attaches to trades journaled live; older trades are structural. "
                 "The news-edge view fills forward."),
        "deals": deals,
    }
    try:
        (data_dir / "deal_journal.json").write_text(json.dumps(out, indent=2))
        log.info("  Deal journal: %d deals (%d live, %d linked to outcomes)",
                 len(deals), len(live_deals), len(linked))
    except Exception as e:  # noqa: BLE001
        log.warning("  Deal journal write failed — %s", e)
    return out


if __name__ == "__main__":
    import sys
    o = build_deal_journal(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data"))
    print(f"deals={o['deals_count']} live={o['live_count']} linked={o['linked_count']}")
    print("by class:", [(r["catalyst_class"], r["n"], "win%=" + str(r["win_rate"])) for r in o["by_catalyst_class"]])
    nv = o["news_vs_silence"]
    print("news-backed:", nv["news_backed"], "| silent:", nv["silent"])
    print("most recent deal:", {k: o["recent"][0].get(k) for k in ("ticker", "side", "catalyst_class", "context_basis", "outcome")} if o["recent"] else None)
