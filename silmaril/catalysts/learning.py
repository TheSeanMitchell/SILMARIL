"""
SILMARIL — Catalyst Learning & Predictiveness (deterministic, REAL data only)
=============================================================================

The catalyst pipeline already INGESTS real events (earnings, macro, opex,
ex-div, crypto unlocks, index rebalances) and CONSUMES them forward (earnings
proximity -> protection, magnitude -> conviction/sizing). What was missing is
the part that LEARNS and TEACHES. This module adds it:

  1. FORWARD INTELLIGENCE — the upcoming gauntlet ranked by impact + proximity,
     split into market-wide macro and universe-ticker events, deduped.
  2. CLUSTERING -> VOLATILITY — when several high-impact catalysts cluster in a
     short window, volatility is structurally more likely. We compute the daily
     catalyst "load" and flag elevated windows. This is a real, computable
     expectation (not a guess): more high-impact events in a span = more risk.
  3. IPO PROXIMITY — catalysts within +/-10 days of the active IPO (from
     ipo_calendar), so the macro backdrop of the launch is explicit.
  4. PREDICTIVENESS LOOP (forward-accumulating) — an append-only ledger of
     catalysts that FIRED on our universe, linked to the realized price moves we
     already measure in scored outcomes, aggregated by catalyst type x magnitude.
     This is how the system learns which catalysts actually move stocks. It is
     EMPTY until catalysts fire and outcomes score from here forward — we do not
     fabricate a track record.
  5. BASELINE — the real distribution of realized moves by volatility state, so
     catalyst moves can be judged against the normal floor.

No LLM, no external calls. Writes docs/data/catalyst_learning.json for the
cockpit's Catalysts tab. Ledger persists in docs/data/catalyst_ledger.json.
"""

from __future__ import annotations

import json
import logging
import statistics as _stats
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

VERSION = "catalyst-learning-1.0"

_MAG_WEIGHT = {"very_high": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}
_MACRO_TYPES = {"fomc", "cpi", "ppi", "pce", "bls_empl", "jobs", "gdp",
                "opex", "opex_quarterly", "eia_crude", "ism", "retail_sales"}
_SIG_MOVE_PCT = 1.0          # |move| above this counts as a "hit"
_LINK_LOOKBACK_DAYS = 5      # catalyst may precede the prediction by up to N days
_LEDGER_FIRE_WINDOW = 1      # a catalyst is "fired" if its date is within [today-N, today]


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


def _mag_weight(m: Optional[str]) -> float:
    return _MAG_WEIGHT.get((m or "").lower(), 1.0)


def _events(catalysts_doc: Any) -> List[Dict[str, Any]]:
    if not isinstance(catalysts_doc, dict):
        return []
    return list(catalysts_doc.get("daily") or []) + list(catalysts_doc.get("weekly") or [])


def _market_relevant(events: List[Dict[str, Any]], universe: set) -> List[Dict[str, Any]]:
    """Events that can move the market or our universe: market-wide macro (no
    ticker), our universe tickers, or anything tagged very_high. Micro-cap
    earnings are excluded — they don't drive market-wide volatility."""
    out = []
    for e in events:
        tkr = (e.get("ticker") or "").strip().upper()
        if (not tkr) or (tkr in universe) or ((e.get("magnitude") or "") == "very_high"):
            out.append(e)
    return out


def _dedup_macro(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse same-type macro events within 3 days (e.g. FOMC spanning 2 days)."""
    out: List[Dict[str, Any]] = []
    kept: List[Tuple[str, date]] = []
    for e in sorted(events, key=lambda x: str(x.get("date") or "")):
        dt = _d(e.get("date"))
        typ = (e.get("type") or "").lower()
        if dt and any(t == typ and abs((dt - kd).days) <= 3 for t, kd in kept):
            continue
        out.append(e)
        if dt:
            kept.append((typ, dt))
    return out


def _held_tickers(data_dir: Path) -> set:
    held = set()
    for f in ("alpaca_paper_state.json", "alpaca_h3_state.json", "alpaca_h5_state.json"):
        st = _load(data_dir / f)
        if isinstance(st, dict):
            for p in (st.get("positions") or []):
                sym = (p.get("symbol") or "").upper()
                if sym:
                    held.add(sym)
    return held


def _forward_intelligence(events, universe, held, today) -> Dict[str, Any]:
    macro_raw = [e for e in events if not (e.get("ticker") or "").strip()]
    macro = _dedup_macro(macro_raw)
    # universe-ticker events, excluding macro-type events that happen to carry an
    # index ticker (e.g. SPY-tagged FOMC) — those belong with the macro list.
    uni = [e for e in events if (e.get("ticker") or "").upper() in universe
           and (e.get("type") or "").lower() not in _MACRO_TYPES]

    def shape(e, is_macro):
        dt = _d(e.get("date"))
        row = {
            "date": e.get("date"),
            "type": e.get("type"),
            "magnitude": e.get("magnitude"),
            "note": e.get("note", ""),
            "days_until": (dt - today).days if dt else None,
        }
        if not is_macro:
            row["ticker"] = (e.get("ticker") or "").upper()
            row["held"] = row["ticker"] in held
        return row

    macro_rows = sorted([shape(e, True) for e in macro if _d(e.get("date")) and _d(e.get("date")) >= today],
                        key=lambda r: (r["days_until"], -_mag_weight(r["magnitude"])))
    uni_rows = sorted([shape(e, False) for e in uni if _d(e.get("date")) and _d(e.get("date")) >= today],
                      key=lambda r: (r["days_until"], -_mag_weight(r["magnitude"])))
    vh = sum(1 for e in events if (e.get("magnitude") or "") == "very_high")
    hi = sum(1 for e in events if (e.get("magnitude") or "") == "high")
    return {
        "macro": macro_rows,
        "universe": uni_rows,
        "counts": {"total": len(events), "macro": len(macro_rows),
                   "universe": len(uni_rows), "very_high": vh, "high": hi},
    }


def _clustering(events, today, horizon_days=21) -> Dict[str, Any]:
    by_day: Dict[str, Dict[str, Any]] = {}
    for e in events:
        dt = _d(e.get("date"))
        if not dt or not (today <= dt <= today + timedelta(days=horizon_days)):
            continue
        key = dt.isoformat()
        slot = by_day.setdefault(key, {"date": key, "load": 0.0, "events": 0, "high_impact": 0})
        slot["load"] = round(slot["load"] + _mag_weight(e.get("magnitude")), 1)
        slot["events"] += 1
        if (e.get("magnitude") or "") in ("very_high", "high"):
            slot["high_impact"] += 1
    daily_load = [by_day[k] for k in sorted(by_day)]

    # rolling 7-day window: find the heaviest stretch
    peak = None
    elevated_ahead = False
    for i in range(0, horizon_days + 1):
        ws = today + timedelta(days=i)
        we = ws + timedelta(days=6)
        win = [s for s in daily_load if ws <= _d(s["date"]) <= we]
        load = round(sum(s["load"] for s in win), 1)
        hi = sum(s["high_impact"] for s in win)
        if peak is None or load > peak["load"]:
            peak = {"start": ws.isoformat(), "end": we.isoformat(), "load": load,
                    "events": sum(s["events"] for s in win), "high_impact": hi}
        if i <= 14 and hi >= 3:
            elevated_ahead = True
    note = ("Multiple high-impact catalysts cluster ahead — volatility is structurally more "
            "likely in the heaviest window." if elevated_ahead else
            "No unusual catalyst clustering in the next two weeks.")
    return {"daily_load": daily_load, "peak_window": peak,
            "elevated_ahead": elevated_ahead, "note": note}


def _ipo_proximity(events, data_dir, today, span_days=10) -> Optional[Dict[str, Any]]:
    ipo = _load(data_dir / "ipo_intelligence.json")
    active = (ipo or {}).get("active") if isinstance(ipo, dict) else None
    if not active or not active.get("date"):
        return None
    ipo_d = _d(active.get("date"))
    if not ipo_d:
        return None
    gauntlet = []
    macro_kept: List[Tuple[str, date]] = []   # (type, date) of macro events already added
    for e in events:
        dt = _d(e.get("date"))
        if not dt or abs((dt - ipo_d).days) > span_days:
            continue
        typ = (e.get("type") or "").lower()
        if typ in _MACRO_TYPES:
            if any(t == typ and abs((dt - kd).days) <= 3 for t, kd in macro_kept):
                continue
            macro_kept.append((typ, dt))
        rel = (dt - ipo_d).days
        label = (e.get("ticker") or "MARKET") + " " + (e.get("type") or "")
        gauntlet.append({"date": e.get("date"), "label": label.strip(),
                         "magnitude": e.get("magnitude"), "rel_to_ipo": rel,
                         "note": e.get("note", "")})
    gauntlet.sort(key=lambda r: r["date"])
    return {"ipo": {"company": active.get("company"), "ticker": active.get("ticker"),
                    "date": active.get("date"), "days_until": active.get("days_until")},
            "span_days": span_days, "gauntlet": gauntlet}


def _update_ledger(data_dir, events, universe, today) -> List[Dict[str, Any]]:
    """Append catalysts that FIRED on universe tickers (date within [today-N, today])."""
    path = data_dir / "catalyst_ledger.json"
    doc = _load(path)
    entries = doc.get("entries") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        entries = []
    seen = {(e.get("ticker"), e.get("date"), e.get("type")) for e in entries}
    for e in events:
        tkr = (e.get("ticker") or "").upper()
        dt = _d(e.get("date"))
        if not tkr or tkr not in universe or not dt:
            continue
        if not (today - timedelta(days=_LEDGER_FIRE_WINDOW) <= dt <= today):
            continue
        key = (tkr, e.get("date"), e.get("type"))
        if key in seen:
            continue
        seen.add(key)
        entries.append({"ticker": tkr, "date": e.get("date"), "type": e.get("type"),
                        "magnitude": e.get("magnitude"), "recorded_at": today.isoformat()})
    try:
        path.write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(),
                                    "entries": entries}, indent=2))
    except Exception as ex:  # noqa: BLE001
        log.warning("  Catalyst ledger write failed — %s", ex)
    return entries


def _predictiveness(ledger, outcomes) -> Dict[str, Any]:
    """Link FIRED catalysts (ledger) to realized moves (clean outcomes), aggregate
    by type x magnitude. Recomputed each run (idempotent)."""
    clean = [o for o in outcomes if not o.get("stale_price_suspected")
             and isinstance(o.get("return_pct"), (int, float))]
    # index ledger by ticker -> list of (catalyst_date, type, magnitude)
    by_ticker: Dict[str, List[Tuple[date, str, str]]] = {}
    for e in ledger:
        dt = _d(e.get("date"))
        if dt:
            by_ticker.setdefault(e.get("ticker"), []).append((dt, e.get("type"), e.get("magnitude")))

    tm: Dict[Tuple[str, str], List[float]] = {}
    per_type: Dict[str, List[float]] = {}
    linked = 0
    for o in clean:
        tkr = (o.get("ticker") or "").upper()
        pa = _d(o.get("predicted_at"))
        sa = _d(o.get("scored_at")) or pa
        if not pa or tkr not in by_ticker:
            continue
        hit_cat = None
        for cdt, ctyp, cmag in by_ticker[tkr]:
            if pa - timedelta(days=_LINK_LOOKBACK_DAYS) <= cdt <= (sa or pa):
                hit_cat = (ctyp, cmag)
                break
        if not hit_cat:
            continue
        linked += 1
        r = float(o["return_pct"])
        tm.setdefault((hit_cat[0], hit_cat[1]), []).append(r)
        per_type.setdefault(hit_cat[0], []).append(r)

    def agg(vals):
        return {
            "n": len(vals),
            "avg_abs_move": round(_stats.mean(abs(v) for v in vals), 3),
            "avg_signed_move": round(_stats.mean(vals), 3),
            "hit_rate": round(sum(1 for v in vals if abs(v) > _SIG_MOVE_PCT) / len(vals), 3),
        }

    by_tm = [dict(type=t, magnitude=m, **agg(v)) for (t, m), v in tm.items() if v]
    by_tm.sort(key=lambda r: (-r["avg_abs_move"], -r["n"]))
    by_t = [dict(type=t, **agg(v)) for t, v in per_type.items() if v]
    by_t.sort(key=lambda r: -r["avg_abs_move"])
    note = ("Learning accrues as catalysts fire and outcomes score from here forward; "
            "no track record is fabricated." if linked == 0 else
            f"{linked} scored outcomes linked to fired catalysts so far.")
    return {"by_type_magnitude": by_tm, "by_type": by_t,
            "linked_outcomes": linked, "ledger_size": len(ledger), "note": note}


def _baseline(outcomes) -> Dict[str, Any]:
    clean = [o for o in outcomes if not o.get("stale_price_suspected")
             and isinstance(o.get("return_pct"), (int, float))]
    by_vol: Dict[str, List[float]] = {}
    for o in clean:
        vs = (o.get("tags") or {}).get("vol_state", "?")
        by_vol.setdefault(vs, []).append(float(o["return_pct"]))
    rows = [{"vol_state": vs, "n": len(v),
             "avg_abs_move": round(_stats.mean(abs(x) for x in v), 3)}
            for vs, v in by_vol.items() if v]
    rows.sort(key=lambda r: -r["n"])
    allv = [float(o["return_pct"]) for o in clean]
    return {
        "by_vol_state": rows,
        "overall_avg_abs_move": round(_stats.mean(abs(x) for x in allv), 3) if allv else None,
        "overall_hit_rate": round(sum(1 for x in allv if abs(x) > _SIG_MOVE_PCT) / len(allv), 3) if allv else None,
        "n": len(allv),
    }


def build_catalyst_learning(data_dir: Path) -> Dict[str, Any]:
    data_dir = Path(data_dir)
    today = datetime.now(timezone.utc).date()
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        from ..universe.core import all_tickers
        universe = set(all_tickers())
    except Exception:  # noqa: BLE001
        universe = set()

    events = _events(_load(data_dir / "catalysts.json"))
    relevant = _market_relevant(events, universe)
    held = _held_tickers(data_dir)
    outcomes = (_load(data_dir / "scoring.json") or {}).get("outcomes", []) if isinstance(_load(data_dir / "scoring.json"), dict) else []

    ledger = _update_ledger(data_dir, events, universe, today)

    out = {
        "version": VERSION,
        "generated_at": now_iso,
        "upcoming": _forward_intelligence(events, universe, held, today),
        "clustering": _clustering(relevant, today),
        "ipo_proximity": _ipo_proximity(relevant, data_dir, today),
        "learning": _predictiveness(ledger, outcomes),
        "baseline": _baseline(outcomes),
        "note": ("Forward gauntlet + clustering are immediately actionable; the predictiveness "
                 "loop fills forward from real fired-catalyst -> realized-move links. All real data."),
    }
    try:
        (data_dir / "catalyst_learning.json").write_text(json.dumps(out, indent=2))
        cl = out["clustering"]
        log.info("  Catalyst learning: %d upcoming (%d macro, %d universe); elevated_ahead=%s; "
                 "ledger=%d linked=%d",
                 out["upcoming"]["counts"]["total"], out["upcoming"]["counts"]["macro"],
                 out["upcoming"]["counts"]["universe"], cl["elevated_ahead"],
                 out["learning"]["ledger_size"], out["learning"]["linked_outcomes"])
    except Exception as e:  # noqa: BLE001
        log.warning("  Catalyst learning write failed — %s", e)
    return out


if __name__ == "__main__":
    import sys
    o = build_catalyst_learning(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data"))
    u, c = o["upcoming"], o["clustering"]
    print(f"upcoming: {u['counts']} | elevated_ahead={c['elevated_ahead']}")
    if c["peak_window"]:
        pw = c["peak_window"]
        print(f"peak window: {pw['start']}..{pw['end']} load={pw['load']} high_impact={pw['high_impact']}")
    if o["ipo_proximity"]:
        print("IPO gauntlet:", [g["label"] + " " + str(g["rel_to_ipo"]) + "d" for g in o["ipo_proximity"]["gauntlet"]])
    print("learning:", o["learning"]["note"])
    print("baseline by vol:", [(b["vol_state"], b["avg_abs_move"]) for b in o["baseline"]["by_vol_state"]])
