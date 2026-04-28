"""silmaril.catalysts — catalyst roundup writer.

This combines:
  - The original write_catalysts_json (stub — your real one wasn't in the
    v2 upload; paste it back if needed)
  - The 6 new v2 catalyst sources (OPEX, index rebalance, macro releases,
    crypto unlocks, ex-dividend, earnings calendar)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger(__name__)


def write_catalysts_json(path: Path, today_iso: str) -> None:
    """Write catalysts.json with all known upcoming events.

    Pulls from the 6 v2 sources. Each source is best-effort — a single
    source failing won't block the others.
    """
    events: List[Dict[str, Any]] = []

    # v2 sources — all best-effort, all gracefully no-op if their
    # dependencies aren't met.
    try:
        from .opex import fetch_opex_calendar
        events.extend(fetch_opex_calendar() or [])
    except Exception as e:
        log.info("[catalysts] opex skipped: %s", e)

    try:
        from .index_rebalance import fetch_index_rebalances
        events.extend(fetch_index_rebalances() or [])
    except Exception as e:
        log.info("[catalysts] index_rebalance skipped: %s", e)

    try:
        from .macro_releases import fetch_macro_calendar
        events.extend(fetch_macro_calendar() or [])
    except Exception as e:
        log.info("[catalysts] macro_releases skipped: %s", e)

    try:
        from .crypto_unlocks import fetch_crypto_unlocks
        events.extend(fetch_crypto_unlocks() or [])
    except Exception as e:
        log.info("[catalysts] crypto_unlocks skipped: %s", e)

    try:
        from .ex_dividend import fetch_ex_dividend_calendar
        events.extend(fetch_ex_dividend_calendar() or [])
    except Exception as e:
        log.info("[catalysts] ex_dividend skipped: %s", e)

    try:
        from .earnings_calendar import fetch_earnings_calendar
        events.extend(fetch_earnings_calendar() or [])
    except Exception as e:
        log.info("[catalysts] earnings_calendar skipped: %s", e)

    # Sort by date, dedupe by (date, type, ticker, title)
    seen = set()
    unique = []
    for e in sorted(events, key=lambda x: (x.get("date", ""), x.get("type", ""))):
        key = (e.get("date"), e.get("type"), e.get("ticker"), e.get("title"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)

    payload = {
        "generated_at": today_iso,
        "count": len(unique),
        "events": unique,
    }
    with path.open("w") as f:
        json.dump(payload, f, indent=2, default=str)
    log.info("[catalysts] wrote %d events to %s", len(unique), path)
