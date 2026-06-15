"""
silmaril.analytics.ipo_calendar — every IPO launch date, tracked.

Generalizes the SpaceX capture into a standing capability: each cycle we pull
the upcoming IPO calendar (FMP's ipo-calendar endpoint, key already in repo
secrets), normalize it, compute days-to-debut, and flag overlap with the
trading universe and the news flow. The debut-window phrase layer in
sentiment.py ("prices above range", "oversubscribed", "delays IPO") then has a
ROSTER of names to listen for — so capital-flow learning around debuts is a
process, not a one-off.

Offline-safe: in sandboxes without network the fetch is skipped and the seed
list (SPCX) plus any previously-fetched calendar persists. Deterministic; no
LLM. Writes docs/data/ipo_calendar.json.
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "ipo-calendar-1.0"
LOOKAHEAD_DAYS = 120

# Names we always track regardless of feed (symbol, name, expected_date, exchange)
SEED: List[Dict[str, Any]] = [
    {"symbol": "SPCX", "company": "SpaceX", "date": "2026-06-12",
     "exchange": "NASDAQ", "seeded": True,
     "note": "largest IPO in history (~$1.9T); high-impact debut window"},
]


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


def _fetch_fmp_calendar() -> Optional[List[Dict[str, Any]]]:
    """Upcoming IPOs from FMP. None on any failure (offline/quota) — callers
    fall back to the last stored calendar + seeds."""
    key = os.environ.get("FMP_API_KEY")
    if not key:
        return None
    today = date.today()
    frm = today.isoformat()
    to = date.fromordinal(today.toordinal() + LOOKAHEAD_DAYS).isoformat()
    url = (f"https://financialmodelingprep.com/api/v3/ipo_calendar"
           f"?from={frm}&to={to}&apikey={key}")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not isinstance(data, list):
            return None
        out = []
        for row in data:
            sym = str(row.get("symbol") or "").upper()
            d = str(row.get("date") or "")[:10]
            if not sym or not d:
                continue
            out.append({"symbol": sym,
                        "company": row.get("company") or row.get("name") or sym,
                        "date": d,
                        "exchange": row.get("exchange"),
                        "price_range": row.get("priceRange") or row.get("price"),
                        "shares": row.get("shares"),
                        "seeded": False})
        return out
    except Exception:
        return None


def _fetch_finnhub_calendar() -> Optional[List[Dict[str, Any]]]:
    """Fallback IPO calendar via Finnhub. None on any failure."""
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return None
    today = date.today()
    frm = today.isoformat()
    to = date.fromordinal(today.toordinal() + LOOKAHEAD_DAYS).isoformat()
    url = (f"https://finnhub.io/api/v1/calendar/ipo?from={frm}&to={to}&token={key}")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        rows = data.get("ipoCalendar") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return None
        out = []
        for row in rows:
            sym = str(row.get("symbol") or "").upper()
            d = str(row.get("date") or "")[:10]
            if not sym or not d:
                continue
            out.append({"symbol": sym, "company": row.get("name") or sym,
                        "date": d, "exchange": row.get("exchange"),
                        "price_range": row.get("price"),
                        "shares": row.get("numberOfShares"), "seeded": False})
        return out
    except Exception:
        return None


def _days_to(d: str, today: date) -> Optional[int]:
    try:
        return (date.fromisoformat(d[:10]) - today).days
    except Exception:
        return None


def build_ipo_calendar(data_dir: Path) -> Dict[str, Any]:
    data_dir = Path(data_dir)
    today = date.today()
    prev = _load(data_dir / "ipo_calendar.json", {})
    prev_rows = {r.get("symbol"): r for r in (prev.get("upcoming") or [])}

    fetched = _fetch_fmp_calendar()
    if fetched is None:
        fetched = _fetch_finnhub_calendar()
    rows: Dict[str, Dict[str, Any]] = {}
    # last-known calendar survives an offline cycle
    for s, r in prev_rows.items():
        rows[s] = dict(r)
    if fetched is not None:
        for r in fetched:
            rows[r["symbol"]] = r
    for r in SEED:
        rows.setdefault(r["symbol"], dict(r))
        rows[r["symbol"]].update({k: v for k, v in r.items() if k not in rows[r["symbol"]] or rows[r["symbol"]][k] in (None, "")})

    # universe + news overlap
    sig = _load(data_dir / "signals.json", {})
    uni = {str(d.get("ticker") or "").upper() for d in (sig.get("debates") or [])}

    upcoming: List[Dict[str, Any]] = []
    for s, r in rows.items():
        dt = _days_to(str(r.get("date") or ""), today)
        if dt is None or dt < -7 or dt > LOOKAHEAD_DAYS:
            continue  # keep one week of post-debut tracking, drop stale
        r2 = dict(r)
        r2["days_to_debut"] = dt
        r2["phase"] = ("debut_window" if -7 <= dt <= 1 else
                       "imminent" if dt <= 7 else
                       "approaching" if dt <= 30 else "watch")
        r2["in_universe"] = s in uni
        upcoming.append(r2)
    upcoming.sort(key=lambda x: (x["days_to_debut"], x["symbol"]))

    payload = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": ("fmp+seed" if fetched is not None else "stored+seed (fetch unavailable)"),
        "lookahead_days": LOOKAHEAD_DAYS,
        "count": len(upcoming),
        "debut_window": [r["symbol"] for r in upcoming if r["phase"] == "debut_window"],
        "imminent": [r["symbol"] for r in upcoming if r["phase"] == "imminent"],
        "upcoming": upcoming,
        "note": ("Debut-window names are where the IPO phrase layer "
                 "(prices above/below range, oversubscribed, delayed) carries "
                 "the most signal; capital-flow learning around debuts runs "
                 "through news_fingerprint as these names enter the universe."),
    }
    _dump(data_dir / "ipo_calendar.json", payload)
    return {"count": len(upcoming), "source": payload["source"],
            "imminent": payload["imminent"][:5]}


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(build_ipo_calendar(
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")), indent=2))
