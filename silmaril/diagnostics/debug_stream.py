"""
silmaril.diagnostics.debug_stream — One time-ordered stream of everything.

A code-debugger view of the whole system: every agent verdict, every sentiment
read, every executor block/decision, every scored outcome, every order, every
error, every harvest, and every drift invariant — merged into one chronological,
severity-tagged event log. The cockpit's debug console renders this live.

It does NOT add a parallel telemetry pipeline. It READS the artifacts the cycle
already writes (signals.json, decision_ledger.json, scoring.json, the three
alpaca state files, verified_harvest_ledger.json, drift_sentinel.json) and folds
them into a single feed. That keeps it honest — the stream can only show what the
system actually produced — and safe — it writes one file, touches nothing else.

(A true in-process tap that logs events the instant they happen, live, is the
natural next step; it requires threading a logger through cli.py and is proposed
separately as a gated change. This build gives the full picture from real data now.)

Writes docs/data/debug_stream.json. Safe to run every cycle.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

STREAM_VERSION = "debug-stream-1.0"
MAX_EVENTS = 2500
MAX_VERDICTS = 700
MAX_NEWS = 400
MAX_EXEC = 450
MAX_SCORE = 450
MAX_ORDERS_PER_ACCT = 120
MAX_HARVEST = 150

_STRONG = {"STRONG_BUY", "STRONG_SELL"}
_BLOCKY = ("blocked", "rejected", "deferred", "halt", "cap")


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _dump(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(_sanitize(obj), f, indent=2, default=str, allow_nan=False)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _ts(v: Optional[str]) -> str:
    """Normalize any timestamp/date to a sortable ISO-ish string."""
    if not v:
        return "1970-01-01T00:00:00+00:00"
    s = str(v)
    if len(s) == 10:  # date only
        return s + "T00:00:00+00:00"
    return s


def _ev(ts, level, channel, msg, ticker=None, account=None, data=None) -> Dict[str, Any]:
    return {
        "ts": _ts(ts),
        "level": level,
        "channel": channel,
        "ticker": ticker,
        "account": account,
        "msg": msg,
        "data": data or {},
    }


def _from_signals(out: Path) -> List[Dict[str, Any]]:
    sig = _load(out / "signals.json", {})
    events: List[Dict[str, Any]] = []
    run_ts = (sig.get("meta") or {}).get("generated_at")
    v_count = 0
    for d in sig.get("debates", []) or []:
        tkr = d.get("ticker")
        # NEWS / sentiment read
        s = d.get("sentiment_score")
        if s is not None and len([e for e in events if e["channel"] == "NEWS"]) < MAX_NEWS:
            arts = int(d.get("article_count") or 0)
            lvl = "INFO" if abs(float(s)) >= 0.3 else "DEBUG"
            events.append(_ev(run_ts, lvl, "NEWS",
                              f"sentiment {float(s):+.2f} on {tkr} ({arts} articles)",
                              ticker=tkr, data={"sentiment": s, "articles": arts,
                                                "sector": d.get("sector")}))
        # AGENT verdicts
        for v in d.get("verdicts", []) or []:
            if v_count >= MAX_VERDICTS:
                break
            sigv = (v.get("signal") or "?").upper()
            conv = float(v.get("conviction") or 0)
            lvl = "INFO" if sigv in _STRONG else ("DEBUG" if sigv in ("HOLD", "ABSTAIN") else "DEBUG")
            events.append(_ev(run_ts, lvl, "AGENT",
                              f"{v.get('agent')} → {sigv} {tkr} (conv {conv:.2f})",
                              ticker=tkr,
                              data={"agent": v.get("agent"), "signal": sigv, "conviction": round(conv, 3),
                                    "mult": v.get("learning_multiplier")}))
            v_count += 1
    return events


def _from_decision_ledger(out: Path) -> List[Dict[str, Any]]:
    dl = _load(out / "decision_ledger.json", {})
    rows = dl.get("rows", []) if isinstance(dl, dict) else []
    rows = sorted(rows, key=lambda r: r.get("ts") or "", reverse=True)[:MAX_EXEC]
    events = []
    for r in rows:
        cat = (r.get("category") or "").lower()
        level = "WARN" if any(b in cat for b in _BLOCKY) else "INFO"
        events.append(_ev(r.get("ts"), level, "EXEC",
                          f"{r.get('category')}: {r.get('ticker')} — {r.get('reason')}",
                          ticker=r.get("ticker"), account=r.get("account_id"),
                          data=r.get("detail") if isinstance(r.get("detail"), dict) else {"detail": r.get("detail")}))
    return events


def _from_scoring(out: Path) -> List[Dict[str, Any]]:
    sc = _load(out / "scoring.json", {})
    outs = sc.get("outcomes", []) if isinstance(sc, dict) else []
    outs = sorted(outs, key=lambda o: o.get("scored_at") or "", reverse=True)[:MAX_SCORE]
    events = []
    for o in outs:
        ok = bool(o.get("correct"))
        stale = bool(o.get("stale_price_suspected"))
        ret = o.get("return_pct")
        lvl = "DEBUG" if ok else "WARN"
        if stale:
            lvl = "DEBUG"
        rets = f"{float(ret):+.2f}%" if ret is not None else "n/a"
        tag = " [stale]" if stale else ""
        events.append(_ev(o.get("scored_at"), lvl, "SCORE",
                          f"{o.get('agent')} {o.get('signal')} {o.get('ticker')} → "
                          f"{'WIN' if ok else 'LOSS'} {rets}{tag}",
                          ticker=o.get("ticker"),
                          data={"agent": o.get("agent"), "signal": o.get("signal"),
                                "return_pct": ret, "correct": ok, "stale": stale}))
    return events


def _from_accounts(out: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    files = [("LEGACY", "alpaca_paper_state.json"),
             ("HARVEST_3", "alpaca_h3_state.json"),
             ("HARVEST_5", "alpaca_h5_state.json")]
    for acct, fname in files:
        st = _load(out / fname, {})
        if not isinstance(st, dict):
            continue
        # ERRORS
        for e in (st.get("errors") or [])[-20:]:
            if isinstance(e, dict):
                ts = e.get("ts") or e.get("time") or st.get("last_run")
                msg = e.get("message") or e.get("error") or json.dumps(e)[:160]
                tkr = e.get("ticker") or e.get("symbol")
            else:
                ts = st.get("last_run")
                msg = str(e)[:160]
                tkr = None
            events.append(_ev(ts, "ERROR", "ERROR", f"{acct}: {msg}", ticker=tkr, account=acct))
        # ORDERS
        orders = sorted((st.get("orders") or []),
                        key=lambda o: (o.get("submitted_at") or o.get("created_at") or
                                       o.get("time") or "") if isinstance(o, dict) else "",
                        reverse=True)[:MAX_ORDERS_PER_ACCT]
        for o in orders:
            if not isinstance(o, dict):
                continue
            ts = o.get("submitted_at") or o.get("created_at") or o.get("time") or st.get("last_run")
            side = (o.get("side") or o.get("action") or "?").upper()
            status = (o.get("status") or o.get("state") or "?")
            tkr = o.get("symbol") or o.get("ticker")
            qty = o.get("qty") or o.get("notional") or o.get("quantity")
            lvl = "WARN" if str(status).lower() in ("canceled", "cancelled", "rejected", "expired") else "INFO"
            events.append(_ev(ts, lvl, "ORDER",
                              f"{acct}: {side} {tkr} [{status}]",
                              ticker=tkr, account=acct,
                              data={"side": side, "status": status, "qty": qty}))
    return events


def _from_harvest(out: Path) -> List[Dict[str, Any]]:
    vh = _load(out / "verified_harvest_ledger.json", {})
    rows = vh.get("rows", []) if isinstance(vh, dict) else []
    rows = sorted(rows, key=lambda r: r.get("triggered_at") or "", reverse=True)[:MAX_HARVEST]
    events = []
    for r in rows:
        amt = r.get("amount")
        status = r.get("status")
        events.append(_ev(r.get("triggered_at"), "INFO", "HARVEST",
                          f"{r.get('account_id')}: {status} ${float(amt or 0):,.2f} "
                          f"(equity ${float(r.get('equity') or 0):,.0f})",
                          account=r.get("account_id"),
                          data={"status": status, "amount": amt, "source": r.get("source")}))
    return events


def _from_drift(out: Path) -> List[Dict[str, Any]]:
    ds = _load(out / "drift_sentinel.json", {})
    if not isinstance(ds, dict):
        return []
    ts = ds.get("generated_at")
    events = []
    for inv in ds.get("invariants", []) or []:
        status = (inv.get("status") or "ok").lower()
        lvl = {"ok": "INFO", "warn": "WARN", "fail": "ERROR"}.get(status, "INFO")
        events.append(_ev(ts, lvl, "DRIFT",
                          f"{inv.get('name')}: {status.upper()} — {inv.get('detail')}",
                          data={"status": status}))
    return events


def build_debug_stream(out_dir: Path) -> Dict[str, Any]:
    out = Path(out_dir)
    events: List[Dict[str, Any]] = []
    for fn in (_from_signals, _from_decision_ledger, _from_scoring,
               _from_accounts, _from_harvest, _from_drift):
        try:
            events.extend(fn(out))
        except Exception as e:  # never let one source break the stream
            events.append(_ev(datetime.now(timezone.utc).isoformat(), "ERROR", "ERROR",
                              f"debug_stream source {fn.__name__} failed: {e}"))

    events.sort(key=lambda e: e["ts"], reverse=True)
    events = events[:MAX_EVENTS]

    channels = dict(Counter(e["channel"] for e in events))
    levels = dict(Counter(e["level"] for e in events))

    payload = {
        "version": STREAM_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(events),
        "channels": channels,
        "levels": levels,
        "events": events,
    }
    _dump(out / "debug_stream.json", payload)
    return {"events": len(events), "channels": channels, "levels": levels}


if __name__ == "__main__":  # pragma: no cover
    import sys
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    print(json.dumps(build_debug_stream(base), indent=2))
