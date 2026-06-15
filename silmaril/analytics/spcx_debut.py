"""
silmaril.analytics.spcx_debut — the MASTER SPCX DEBUT CONSOLE (Alpha 0.007).

One JSON the briefing renders as mission control for the largest IPO in
history: phase + countdown, official-pricing flag (EDGAR 424B*), retail roar
(social pulse), word-engine read, the rules in force (debut conviction cap,
wordsmith eligibility, session gates) — and THE OPERATOR'S THESIS, logged as
falsifiable checkpoints the system grades forever:

    T1  prices at $135                       (gradeable at pricing)
    T2  post-open dip ~-20% from open        (their "dip to 20" read as -20%;
                                              the literal $20 — an -85% crash —
                                              is recorded too, marked
                                              IMPLAUSIBLE, and will be graded
                                              all the same)
    T3  long-term ~$400                      (SPECULATION — multi-year; logged,
                                              never traded on)

Honesty is structural: each checkpoint carries status PENDING/HIT/MISS and an
evidence price. The console never predicts; it records, gates, and grades.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ISSUE_EXPECTED = 135.0


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def build_spcx_console(out_dir: str) -> Dict[str, Any]:
    out = Path(out_dir)
    cal = _load(out / "ipo_calendar.json", {})
    edgar = _load(out / "edgar_watch.json", {})
    social = _load(out / "social_pulse.json", {})
    signals = _load(out / "signals.json", {})
    prev = _load(out / "spcx_console.json", {})
    now = datetime.now(timezone.utc)

    row = next((r for r in (cal.get("upcoming") or [])
                if r.get("symbol") == "SPCX"), {})
    spcx_ent = ((edgar.get("entities") or {}).get("SPCX")) or {}
    pulse = ((social.get("tickers") or {}).get("SPCX")) or {}

    live_px: Optional[float] = None
    for d in signals.get("debates") or []:
        if d.get("ticker") == "SPCX":
            try:
                live_px = float(d.get("price") or 0) or None
            except Exception:
                live_px = None
            break

    hist = prev.get("price_track") or []
    if live_px:
        today = now.strftime("%Y-%m-%d %H:%M")
        if not hist or hist[-1].get("t") != today:
            hist.append({"t": today, "px": live_px})
        hist = hist[-500:]
    open_px = hist[0]["px"] if hist else None
    peak_px = max((h["px"] for h in hist), default=None)

    thesis = prev.get("thesis") or [
        {"id": "T1", "claim": "prices at $135", "kind": "pricing",
         "target": ISSUE_EXPECTED, "status": "PENDING"},
        {"id": "T2", "claim": "post-open dip of ~-20% from open",
         "kind": "dip_pct", "target": -20.0, "status": "PENDING",
         "note": "operator's 'dip to 20' read as -20%"},
        {"id": "T2b", "claim": "literal dip to $20 (-85%)", "kind": "dip_abs",
         "target": 20.0, "status": "PENDING",
         "note": "recorded verbatim; IMPLAUSIBLE for a mega-cap debut, graded anyway"},
        {"id": "T3", "claim": "long-term ~$400", "kind": "long_term",
         "target": 400.0, "status": "SPECULATION",
         "note": "multi-year; logged, never traded on"},
    ]
    for t in thesis:
        if t["status"] in ("HIT", "MISS"):
            continue
        if t["kind"] == "dip_pct" and live_px and open_px:
            dd = (live_px / open_px - 1.0) * 100
            t["worst_seen_pct"] = round(min(t.get("worst_seen_pct", 0.0),
                                            dd), 2)
            if t["worst_seen_pct"] <= t["target"]:
                t["status"] = "HIT"
                t["evidence_px"] = live_px
        elif t["kind"] == "dip_abs" and live_px:
            if live_px <= t["target"]:
                t["status"] = "HIT"
                t["evidence_px"] = live_px
        elif t["kind"] == "long_term" and live_px and live_px >= t["target"]:
            t["status"] = "HIT"
            t["evidence_px"] = live_px

    payload = {
        "generated_at": now.isoformat(),
        "version": "ALPHA 0.007 — MASTER SPCX UPDATE",
        "status": {
            "phase": row.get("phase"),
            "days_to_debut": row.get("days_to_debut"),
            "date": row.get("date"),
            "priced_official": bool(spcx_ent.get("priced")),
            "latest_filing": spcx_ent.get("latest_hot"),
            "retail_mentions_24h": pulse.get("mentions_24h"),
            "retail_velocity_x": pulse.get("velocity_x"),
            "retail_word_score": pulse.get("word_score"),
        },
        "rules_in_force": [
            "debut-window conviction cap 0.60 (every agent)",
            "wordsmith book (H5) eligible only on FABLEBOY_5 BUY/STRONG_BUY",
            "session hard-gate: no orders while closed; extended = whole-share limits",
            "GIVEBACK GUARD + trailing + clock-shaped exits active",
            "all rows (news/timing/social/filings) archived permanently",
        ],
        "live": {"price": live_px, "open_seen": open_px, "peak_seen": peak_px,
                 "vs_expected_issue_pct": (round((live_px / ISSUE_EXPECTED - 1)
                                                 * 100, 2) if live_px else None)},
        "price_track": hist,
        "thesis": thesis,
    }
    (out / "spcx_console.json").write_text(json.dumps(payload, indent=2))
    return {"phase": row.get("phase") or "MISSING-FROM-CALENDAR",
            "priced": bool(spcx_ent.get("priced")),
            "mentions": pulse.get("mentions_24h"),
            "thesis_pending": sum(1 for t in thesis
                                  if t["status"] == "PENDING")}
