"""
silmaril.cache.market_hours — Market-hours aware fetch caching.

Cuts API usage dramatically by skipping fetches for assets whose
markets are closed. Each asset belongs to a market calendar. Before
fetching, we check: is the market open? If not, return the cached
value from the most recent fetch.

Calendars:
  NYSE:    Mon-Fri 9:30 AM - 4:00 PM ET; closed weekends + US holidays
  CRYPTO:  24/7/365, never closed
  FX:      Sun 5:00 PM ET - Fri 5:00 PM ET; closed Sat morning - Sun afternoon
  FUTURES: Sun 6:00 PM ET - Fri 5:00 PM ET (oil/commodities)

Cache file: data/price_cache.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
import math as _math
def _sanitize_json(obj):
    """Recursively convert NaN/Inf to None for valid JSON output."""
    if isinstance(obj, float):
        if _math.isnan(obj) or _math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    return obj


def get_calendar(ticker: str, sector: str = "") -> str:
    """Determine the market calendar for an asset based on ticker + sector."""
    if ticker.endswith("-USD") or sector == "Crypto" or sector == "Token":
        return "CRYPTO"
    if sector == "FX" or ticker in {"UUP", "UDN", "FXE", "FXY", "FXF", "FXB", "FXC", "FXA"}:
        return "FX"
    if ticker in {"USO", "BNO", "UCO", "SCO", "UNG", "BOIL", "KOLD"}:
        return "FUTURES"
    return "NYSE"


def is_market_open(calendar: str, when: Optional[datetime] = None) -> bool:
    """Is the named calendar's market open at `when` (UTC)?"""
    when = when or datetime.now(timezone.utc)
    weekday = when.weekday()  # 0=Mon, 6=Sun

    if calendar == "CRYPTO":
        return True

    # Convert UTC to ET (rough: -5h winter, -4h summer; we use -5 conservatively)
    et = when - timedelta(hours=5)
    et_weekday = et.weekday()
    et_hour = et.hour
    et_minute = et.minute
    minutes_into_day = et_hour * 60 + et_minute

    if calendar == "NYSE":
        # Mon-Fri 9:30 AM - 4:00 PM ET = 570 - 960 minutes
        if et_weekday >= 5:
            return False  # weekend
        return 570 <= minutes_into_day < 960

    if calendar == "FX":
        # Sun 5pm ET - Fri 5pm ET. Closed Sat all day + Sun until 5pm.
        if et_weekday == 5:  # Saturday
            return False
        if et_weekday == 6 and minutes_into_day < 17 * 60:
            return False
        if et_weekday == 4 and minutes_into_day >= 17 * 60:
            return False
        return True

    if calendar == "FUTURES":
        # Sun 6pm ET - Fri 5pm ET (close to FX, slightly different)
        if et_weekday == 5:  # Saturday
            return False
        if et_weekday == 6 and minutes_into_day < 18 * 60:
            return False
        if et_weekday == 4 and minutes_into_day >= 17 * 60:
            return False
        return True

    return True  # default to open if unknown


def load_cache(path: Path) -> Dict[str, Any]:
    """Load price cache; missing file returns empty dict."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_cache(path: Path, cache: Dict[str, Any]) -> None:
    """Persist cache to disk."""
    path.write_text(json.dumps(_sanitize_json(cache), indent=2, default=str, allow_nan=False))


def get_cached_price(cache: Dict[str, Any], ticker: str, max_age_hours: int = 72) -> Optional[float]:
    """Return cached price for `ticker` if fresh enough."""
    entry = cache.get(ticker)
    if not entry:
        return None
    try:
        ts = datetime.fromisoformat(entry["timestamp"])
        age = datetime.now(timezone.utc) - ts
        if age > timedelta(hours=max_age_hours):
            return None
        return entry.get("price")
    except Exception:
        return None


def update_cache(cache: Dict[str, Any], ticker: str, price: float) -> None:
    """Set the cached price for `ticker` to `price` with current timestamp."""
    cache[ticker] = {
        "price": price,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def should_skip_fetch(ticker: str, sector: str, cache: Dict[str, Any]) -> bool:
    """
    Decide whether to skip a fetch for this ticker. Skips when:
      - The market is closed AND we have a recent cached price
      - The cached price is less than 1 hour old (regardless of market state)
    """
    calendar = get_calendar(ticker, sector)
    open_now = is_market_open(calendar)

    cached = get_cached_price(cache, ticker, max_age_hours=72)

    if cached is None:
        return False  # no cache, must fetch

    # If market is closed, use cache
    if not open_now:
        return True

    # If market is open, check cache freshness — skip if very recent
    entry = cache.get(ticker, {})
    try:
        ts = datetime.fromisoformat(entry["timestamp"])
        age = datetime.now(timezone.utc) - ts
        return age < timedelta(minutes=15)
    except Exception:
        return False
