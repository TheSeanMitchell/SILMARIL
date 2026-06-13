"""
silmaril.analytics.debut_rotation — the self-advancing DEBUT WATCH (spec B).

THE PROMISE: no human ever names the next IPO again. SPCX is the seed
target; when any target completes its debut window (priced + 5 distinct
trading sessions of live prices), the watch AUTO-ADVANCES to the next
exchange-listed entry in ipo_calendar.json (which already self-fills from
Finnhub/FMP). Completed targets are archived in-file forever — additive,
nothing deleted, the full debut lineage permanently recorded.

WHAT DOWNSTREAM GETS (debut_watch.json):
  current   {symbol, name, expected_date, phase, sessions_observed,
             price_track[]} — the symbol every debut-aware organ should
             treat as "the debut": conviction caps, wordsmith eligibility,
             EDGAR intensity, social-pulse focus, the briefing banner.
  queue     the next candidates in date order (visibility into what
             snaps in next).
  completed permanent archive of every finished watch with its final
            price track (the raw material for the IPO prediction engine,
            spec G — graded pre-debut cards score against these tracks).

PHASES: WAITING (no live prices yet) -> DEBUT_WINDOW (prices observed,
< 5 sessions) -> COMPLETE (>= 5 sessions; rotation fires next run).
SPCX seeding: its existing console price_track is imported so history
already gathered counts toward its window.

Offline-safe, reads only local JSON, judged like everything else once the
prediction engine lands. Suite step; never gated (no network).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "debut-rotation-1.0"
OUT_FILE = "debut_watch.json"
SESSIONS_TO_COMPLETE = 5
SEED_SYMBOL = "SPCX"


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


def _live_price(signals: Dict[str, Any], symbol: str) -> Optional[float]:
    for d in signals.get("debates") or []:
        if str(d.get("ticker") or "").upper() == symbol:
            try:
                return float(d.get("price") or 0) or None
            except Exception:
                return None
    return None


def _distinct_sessions(track: List[dict]) -> int:
    return len({str(h.get("t") or "")[:10] for h in track if h.get("t")})


def _next_candidates(cal: Dict[str, Any], exclude: set) -> List[dict]:
    """Upcoming exchange-listed entries, nearest date first."""
    rows = []
    for r in (cal.get("upcoming") or []):
        sym = str(r.get("symbol") or "").upper()
        if not sym or sym in exclude:
            continue
        rows.append({"symbol": sym, "name": r.get("name"),
                     "expected_date": r.get("date") or r.get("expected_date"),
                     "exchange": r.get("exchange")})
    rows.sort(key=lambda r: str(r.get("expected_date") or "9999"))
    return rows


def build_debut_rotation(out_dir) -> Dict[str, Any]:
    out = Path(out_dir)
    cal = _load(out / "ipo_calendar.json", {})
    signals = _load(out / "signals.json", {})
    prev = _load(out / OUT_FILE, {})
    now = datetime.now(timezone.utc)

    completed: List[dict] = prev.get("completed") or []
    done_syms = {str(c.get("symbol") or "").upper() for c in completed}

    current = prev.get("current")
    if not current:
        # seed with SPCX, importing any price history its console gathered
        spcx_console = _load(out / "spcx_console.json", {})
        current = {"symbol": SEED_SYMBOL, "name": "SpaceX",
                   "expected_date": None,
                   "price_track": (spcx_console.get("price_track") or [])[-500:],
                   "started_watch_at": now.isoformat(),
                   "seeded_from": "spcx_console"}

    sym = str(current.get("symbol") or "").upper()
    track: List[dict] = current.get("price_track") or []
    px = _live_price(signals, sym)
    if px:
        stamp = now.strftime("%Y-%m-%d %H:%M")
        if not track or track[-1].get("t") != stamp:
            track.append({"t": stamp, "px": px})
        track = track[-500:]
    current["price_track"] = track
    sessions = _distinct_sessions(track)
    current["sessions_observed"] = sessions
    current["phase"] = ("WAITING" if sessions == 0 else
                        "DEBUT_WINDOW" if sessions < SESSIONS_TO_COMPLETE
                        else "COMPLETE")
    # ALPHA 1.0 (June 12 directive): the canonical six-phase IPO lifecycle.
    # pre-rumor / rumor come from social-pulse + EDGAR 424B detection and
    # are recorded when those organs flag a name BEFORE it reaches the
    # calendar; from the calendar onward the mapping is deterministic:
    # in-calendar & >7d out -> announcement; <=7d -> pricing; first live
    # session -> listing; sessions 2-5 -> post_listing.
    try:
        _dte = None
        if current.get("expected_date"):
            from datetime import date as _date
            _dte = (_date.fromisoformat(str(current["expected_date"])[:10])
                    - now.date()).days
        if sessions >= 2:
            current["lifecycle_phase"] = "post_listing"
        elif sessions == 1:
            current["lifecycle_phase"] = "listing"
        elif _dte is not None and _dte <= 7:
            current["lifecycle_phase"] = "pricing"
        elif current.get("rumor_flag"):
            current["lifecycle_phase"] = "rumor"
        elif current.get("pre_rumor_flag"):
            current["lifecycle_phase"] = "pre-rumor"
        else:
            current["lifecycle_phase"] = "announcement"
    except Exception:
        current["lifecycle_phase"] = "announcement"
    # related symbols: the sympathy set every IPO drags with it — same-
    # sector peers from the live universe (top by presence), permanent on
    # the watch row so post-mortems can grade side-action predictions.
    if not current.get("related_symbols"):
        try:
            _sec = str(current.get("sector") or "")
            if _sec:
                from silmaril.universe.core import all_entries
                _peers = [t for t, _n, s in all_entries()
                          if s == _sec and t != current.get("symbol")][:6]
                current["related_symbols"] = _peers
            else:
                current["related_symbols"] = []
                current["related_note"] = ("calendar row carried no sector "
                                           "— sympathy set fills when one "
                                           "is known; never guessed")
        except Exception:
            current["related_symbols"] = []

    rotated_to = None
    if current["phase"] == "COMPLETE":
        # archive forever, then advance
        current["completed_at"] = now.isoformat()
        first = track[0]["px"] if track else None
        last = track[-1]["px"] if track else None
        current["debut_summary"] = {
            "first_seen_px": first, "last_px": last,
            "peak_px": max((h["px"] for h in track), default=None),
            "trough_px": min((h["px"] for h in track), default=None),
            "sessions": sessions,
        }
        completed.append(current)
        done_syms.add(sym)
        queue = _next_candidates(cal, done_syms)
        if queue:
            nxt = queue[0]
            rotated_to = nxt["symbol"]
            current = {**nxt, "price_track": [],
                       "started_watch_at": now.isoformat(),
                       "phase": "WAITING", "sessions_observed": 0}
        else:
            current = {"symbol": None, "phase": "IDLE",
                       "note": ("no upcoming exchange-listed IPOs in the "
                                "calendar — the watch re-arms the moment "
                                "the self-filling calendar produces one"),
                       "price_track": [], "sessions_observed": 0,
                       "started_watch_at": now.isoformat()}

    _cur_sym = str(current.get("symbol") or "").upper()
    queue = _next_candidates(cal, done_syms | ({_cur_sym} if _cur_sym else set()))

    payload = {
        "version": VERSION,
        "generated_at": now.isoformat(),
        "current": current,
        "queue": queue[:8],
        "completed": completed[-50:],
        "law": (f"a watch completes at {SESSIONS_TO_COMPLETE} distinct "
                f"trading sessions of live prices, then the next calendar "
                f"entry snaps in automatically — no human in the loop, "
                f"lineage archived forever"),
        **({"rotated_to": rotated_to} if rotated_to else {}),
    }
    _dump(out / OUT_FILE, payload)
    return {"watching": current.get("symbol"),
            "phase": current.get("phase"),
            "sessions": current.get("sessions_observed"),
            **({"rotated_to": rotated_to} if rotated_to else {})}


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(build_debut_rotation(
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")), indent=2))
