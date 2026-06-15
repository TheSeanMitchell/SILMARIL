"""
silmaril.analytics.edgar_watch — official company releases, straight from the SEC.

Alpha 0.007 (MASTER SPCX UPDATE). Headlines paraphrase; filings ARE the event.
This module polls EDGAR full-text search for a small watch map (SpaceX first)
and flags the filing types that move IPOs:

    S-1/A   amended prospectus (terms changing)
    424B4   FINAL PRICING PROSPECTUS — the night-before signal itself
    8-K     material events
    SC 13D/G  big-holder stakes (post-listing)

Output: docs/data/edgar_watch.json — per-entity filing list (form, filed_at,
title, url) + alert flags (priced=True when a 424B* appears). The briefing's
debut console and the news engine both read it; a 424B4 hit also lands in the
word stack as an "ipo pricing" catalyst via the title text.

stdlib-only, fully offline-safe (sandbox has no SEC egress; Actions does),
defensive parsing, polite UA per SEC fair-access rules, cached + additive.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

WATCH: Dict[str, Dict[str, str]] = {
    # ticker -> full-text query (entity names as filed)
    "SPCX": {"q": "\"Space Exploration Technologies\"", "label": "SpaceX"},
}
FORMS_HOT = ("424B4", "424B3", "424B1", "S-1/A", "S-1", "8-K")
_UA = {"User-Agent": "SILMARIL research bot (paper-trading; contact: repo owner)"}
_EFTS = ("https://efts.sec.gov/LATEST/search-index?q={q}"
         "&dateRange=custom&startdt={d0}&enddt={d1}&forms={forms}")
_EFTS_FALLBACK = "https://efts.sec.gov/LATEST/search-index?q={q}&forms={forms}"


def _fetch_json(url: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _parse_hits(data: Optional[dict]) -> List[Dict[str, Any]]:
    """EDGAR full-text response -> normalized filing rows. Defensive."""
    out: List[Dict[str, Any]] = []
    try:
        hits = (((data or {}).get("hits") or {}).get("hits")) or []
        for h in hits:
            src = h.get("_source") or {}
            form = str(src.get("file_type") or src.get("form") or "").upper()
            adsh = str(src.get("_id") or h.get("_id") or "").split(":")[0]
            out.append({
                "form": form,
                "filed_at": str(src.get("file_date") or src.get("filed_at")
                                or "")[:10],
                "title": str(src.get("display_names") or src.get("title")
                             or "")[:160],
                "url": (f"https://www.sec.gov/Archives/edgar/data/"
                        f"{str(src.get('cik') or '').lstrip('0')}/"
                        f"{adsh.replace('-', '')}.txt") if adsh else None,
            })
    except Exception:
        return out
    return out


def build_edgar_watch(out_dir: str, fetcher=None) -> Dict[str, Any]:
    """fetcher injectable for tests: fetcher(query, forms) -> response dict."""
    out = Path(out_dir)
    path = out / "edgar_watch.json"
    try:
        prev = json.loads(path.read_text())
    except Exception:
        prev = {}
    now = datetime.now(timezone.utc)
    entities: Dict[str, Any] = prev.get("entities") or {}

    fetched = 0
    for tkr, spec in WATCH.items():
        if fetcher is not None:
            data = fetcher(spec["q"], ",".join(FORMS_HOT))
        else:
            url = _EFTS_FALLBACK.format(
                q=urllib.request.quote(spec["q"]),
                forms=",".join(FORMS_HOT))
            data = _fetch_json(url)
        rows = _parse_hits(data)
        if data is not None:
            fetched += 1
        ent = entities.setdefault(tkr, {"label": spec["label"], "filings": []})
        known = {(f.get("form"), f.get("filed_at"), f.get("title"))
                 for f in ent["filings"]}
        fresh = [r for r in rows
                 if (r["form"], r["filed_at"], r["title"]) not in known]
        ent["filings"] = (ent["filings"] + fresh)[-100:]
        ent["priced"] = any(str(f.get("form", "")).startswith("424B")
                            for f in ent["filings"])
        ent["latest_hot"] = next(
            (f for f in reversed(ent["filings"]) if f.get("form") in FORMS_HOT),
            None)
        ent["new_this_run"] = len(fresh)

    payload = {
        "generated_at": now.isoformat(),
        "entities": entities,
        "note": ("Official filings are first-party events — a 424B* here is "
                 "the pricing itself, hours before most headlines. Offline "
                 "runs keep the stored ledger untouched."),
        "fetch_ok": fetched,
    }
    path.write_text(json.dumps(payload, indent=2))
    spcx = entities.get("SPCX") or {}
    return {"entities": len(entities), "fetch_ok": fetched,
            "spcx_priced": bool(spcx.get("priced")),
            "spcx_filings": len(spcx.get("filings") or [])}
