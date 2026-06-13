"""
SILMARIL — IPO Analysis & Learning (deterministic, REAL data only)
==================================================================

Turns the Event Recorder's append-only time series into understanding. For the
active IPO it computes the observed ARC — coverage build-up/decay, the market
drawdown/recovery, sector rotation, which hot names persisted vs faded, and our
own engagement. When an IPO completes, that arc is frozen into a PLAYBOOK entry.

The playbook is the foundation for "predicting" future IPOs: each completed IPO
becomes a real, measured template that the next one can be compared against. We
do NOT fabricate a predictive model — with zero completed IPOs there is nothing
to predict yet; the value accrues honestly as the playbook fills. Everything
here is computed from recorded real data. No LLM, no external calls.

Writes docs/data/ipo_intelligence.json for the cockpit's IPO Watch tab.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ipo_calendar import active_ipo, pipeline_status, completed_ipos, phase_of

log = logging.getLogger(__name__)

VERSION = "ipo-analysis-1.0"


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return None


def _phase_from_du(du: Optional[int], wb: int = 30, wa: int = 120) -> str:
    if du is None:
        return "unknown"
    if du > wb:
        return "upcoming"
    if du > 1:
        return "pre_event"
    if -1 <= du <= 1:
        return "event_window"
    if du >= -wa:
        return "post_event_decay"
    return "completed"


def _day(ts: str) -> str:
    return str(ts or "")[:10]


def _complex_headlines(snap: Dict[str, Any]) -> int:
    return sum(int(c.get("headlines") or 0) for c in (snap.get("complex") or []) if c.get("in_universe"))


def _market_headlines(snap: Dict[str, Any]) -> int:
    return sum(int(b.get("headline_count") or 0) for b in (snap.get("money_flow_proxy") or []))


def _coverage_arc(snaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not snaps:
        return {}
    # daily series: last snapshot of each day
    by_day: Dict[str, Dict[str, Any]] = {}
    for s in snaps:
        by_day[_day(s.get("ts"))] = s
    series = [{"date": d, "complex_headlines": _complex_headlines(by_day[d]),
               "market_headlines": _market_headlines(by_day[d])}
              for d in sorted(by_day)]
    # by-phase averages
    phase_acc: Dict[str, List[int]] = {}
    for s in snaps:
        ph = _phase_from_du(s.get("days_until"))
        phase_acc.setdefault(ph, []).append(_complex_headlines(s))
    by_phase = {ph: round(sum(v) / len(v), 1) for ph, v in phase_acc.items() if v}
    peak = max(series, key=lambda r: r["complex_headlines"]) if series else None
    first_v = series[0]["complex_headlines"] if series else 0
    last_v = series[-1]["complex_headlines"] if series else 0
    trend = "rising" if last_v > first_v else "falling" if last_v < first_v else "flat"
    return {"series": series, "by_phase": by_phase, "peak": peak,
            "first": first_v, "latest": last_v, "trend": trend,
            "days_recorded": len(series)}


def _market_arc(snaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not snaps:
        return {}
    first_m = snaps[0].get("market") or {}
    last_m = snaps[-1].get("market") or {}
    idx = ["spy", "qqq", "xlk", "xle"]
    start_levels = {k: first_m.get(k + "_level") for k in idx if first_m.get(k + "_level") is not None}
    cur_levels = {k: last_m.get(k + "_level") for k in idx if last_m.get(k + "_level") is not None}
    drawdown = {}
    for k in idx:
        a, b = start_levels.get(k), cur_levels.get(k)
        if a and b:
            drawdown[k] = round((b - a) / a * 100, 2)
    # daily index series
    by_day: Dict[str, Dict[str, Any]] = {}
    for s in snaps:
        by_day[_day(s.get("ts"))] = (s.get("market") or {})
    series = []
    for d in sorted(by_day):
        m = by_day[d]
        series.append({"date": d, "spy": m.get("spy_level"), "qqq": m.get("qqq_level"),
                       "xlk": m.get("xlk_level"), "regime": m.get("regime")})
    # debut-day capture (days_until == 0), if present
    debut = next((s for s in snaps if s.get("days_until") == 0), None)
    debut_market = (debut.get("market") if debut else None)
    return {"window_start_levels": start_levels, "current_levels": cur_levels,
            "change_since_window_start_pct": drawdown,
            "latest_1d": {k: last_m.get(k + "_1d") for k in idx if last_m.get(k + "_1d") is not None},
            "latest_1w": {k: last_m.get(k + "_1w") for k in idx if last_m.get(k + "_1w") is not None},
            "latest_1mo": {k: last_m.get(k + "_1mo") for k in idx if last_m.get(k + "_1mo") is not None},
            "series": series, "debut_market": debut_market}


def _rotation_arc(snaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not snaps:
        return {}
    def flows(s):
        return {b.get("basket"): b.get("net_score") for b in (s.get("money_flow_proxy") or [])
                if b.get("net_score") is not None}
    first_f, last_f = flows(snaps[0]), flows(snaps[-1])
    deltas = []
    for basket, last_v in last_f.items():
        first_v = first_f.get(basket)
        if first_v is not None:
            deltas.append({"basket": basket, "delta_net": round(last_v - first_v, 3),
                           "from": first_v, "to": last_v})
    deltas.sort(key=lambda r: r["delta_net"], reverse=True)
    winners = [d for d in deltas if d["delta_net"] > 0][:5]
    losers = [d for d in deltas if d["delta_net"] < 0][-5:]
    # current stance snapshot
    current = [{"basket": b.get("basket"), "etf": b.get("etf"), "net_score": b.get("net_score"),
                "stance": b.get("stance"), "headline_count": b.get("headline_count")}
               for b in (snaps[-1].get("money_flow_proxy") or [])][:8]
    return {"winners": winners, "losers": losers, "current": current}


def _hot_persistence(snaps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not snaps:
        return []
    counts: Dict[str, int] = {}
    last_signal: Dict[str, str] = {}
    for s in snaps:
        for h in (s.get("hot_stocks") or []):
            t = h.get("ticker")
            if not t:
                continue
            counts[t] = counts.get(t, 0) + 1
            last_signal[t] = h.get("signal")
    latest_set = {h.get("ticker") for h in (snaps[-1].get("hot_stocks") or [])}
    rows = [{"ticker": t, "appearances": c, "still_hot": t in latest_set, "last_signal": last_signal.get(t)}
            for t, c in counts.items()]
    rows.sort(key=lambda r: (-r["appearances"], not r["still_hot"]))
    return rows[:12]


def _our_engagement(snaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not snaps:
        return {}
    latest = snaps[-1].get("our_activity") or []
    by_acct: Dict[str, int] = {}
    for o in latest:
        by_acct[o.get("account", "?")] = by_acct.get(o.get("account", "?"), 0) + 1
    return {"complex_orders_recent": len(latest), "by_account": by_acct,
            "latest": latest[:8]}


def _latest_view(snaps: List[Dict[str, Any]], ticker: Optional[str]) -> Dict[str, Any]:
    if not snaps:
        return {}
    s = snaps[-1]
    cx = s.get("complex") or []
    cx_sorted = sorted(cx, key=lambda c: (0 if c.get("ticker") == ticker else 1, -(c.get("headlines", 0) or 0)))
    return {
        "market": s.get("market") or {},
        "complex": cx_sorted[:12],
        "money_flow_proxy": (s.get("money_flow_proxy") or [])[:8],
        "hot_stocks": s.get("hot_stocks") or [],
        "our_activity": (s.get("our_activity") or [])[:6],
        "our_activity_count": len(s.get("our_activity") or []),
    }


def _arc(snaps: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "coverage": _coverage_arc(snaps),
        "market": _market_arc(snaps),
        "sector_rotation": _rotation_arc(snaps),
        "hot_persistence": _hot_persistence(snaps),
        "our_engagement": _our_engagement(snaps),
    }


def build_ipo_intelligence(data_dir: Path) -> Dict[str, Any]:
    data_dir = Path(data_dir)
    today = datetime.now(timezone.utc).date()
    now_iso = datetime.now(timezone.utc).isoformat()
    track_dir = data_dir / "event_tracking"

    active = active_ipo(today)
    active_block: Optional[Dict[str, Any]] = None
    if active:
        store = _load(track_dir / f"{active['id']}.json") or {}
        snaps = store.get("snapshots") or []
        du = (datetime.strptime(active["date"][:10], "%Y-%m-%d").date() - today).days
        active_block = {
            "id": active["id"], "company": active["company"], "ticker": active.get("ticker"),
            "date": active.get("date"), "pricing_date": active.get("pricing_date"),
            "exchange": active.get("exchange"), "valuation_usd": active.get("valuation_usd"),
            "raise_usd": active.get("raise_usd"), "underwriters": active.get("underwriters", []),
            "sector": active.get("sector"), "note": active.get("note", ""),
            "days_until": du, "phase": phase_of(active, today), "recording": True,
            "snapshot_count": store.get("snapshot_count", len(snaps)),
            "first_snapshot": store.get("first_snapshot"), "last_snapshot": store.get("last_snapshot"),
            "latest": _latest_view(snaps, active.get("ticker")),
            "arc": _arc(snaps),
        }

    # playbook: completed IPOs with a frozen arc (empty until one completes)
    playbook = []
    for ipo in completed_ipos(today):
        store = _load(track_dir / f"{ipo['id']}.json") or {}
        snaps = store.get("snapshots") or []
        if snaps:
            playbook.append({
                "id": ipo["id"], "company": ipo["company"], "ticker": ipo.get("ticker"),
                "date": ipo.get("date"), "valuation_usd": ipo.get("valuation_usd"),
                "snapshot_count": len(snaps),
                "arc": _arc(snaps),
            })

    out = {
        "version": VERSION,
        "generated_at": now_iso,
        "active": active_block,
        "pipeline": pipeline_status(today),
        "playbook": playbook,
        "learning_note": ("Each completed IPO becomes a measured template in the playbook. "
                          "Prediction emerges by comparison as the playbook fills — not from any "
                          "fabricated model. All arcs computed from recorded real data."),
    }
    try:
        (data_dir / "ipo_intelligence.json").write_text(json.dumps(out, indent=2))
        log.info("  IPO analysis: active=%s phase=%s playbook=%d",
                 active_block["company"] if active_block else None,
                 active_block["phase"] if active_block else "-", len(playbook))
    except Exception as e:  # noqa: BLE001
        log.warning("  IPO analysis: write failed — %s", e)
    return out


if __name__ == "__main__":
    import sys
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    o = build_ipo_intelligence(d)
    a = o.get("active")
    if a:
        cov = a["arc"]["coverage"]
        print(f"active={a['company']} T{a['days_until']:+d}d phase={a['phase']} "
              f"snapshots={a['snapshot_count']} coverage_trend={cov.get('trend')} "
              f"days_recorded={cov.get('days_recorded')}")
    print("pipeline:", [r["company"] + ("*" if r["is_active"] else "") for r in o["pipeline"]])
    print("playbook entries:", len(o["playbook"]))
