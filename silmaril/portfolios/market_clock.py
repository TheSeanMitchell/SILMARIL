"""silmaril.portfolios.market_clock — Market open/close reference clock.

Writes docs/data/market_clock.json on every cycle. The dashboard reads
the reference timestamps and ticks the countdown / elapsed-since in
client JS so it stays accurate between full reloads.

Shape:
  {
    "version": "3.1",
    "generated_at": "...",
    "now_utc": "...",
    "is_open": false,
    "last_close_utc": "2026-05-09T20:00:00+00:00",
    "next_open_utc":  "2026-05-12T13:30:00+00:00",
    "session": "weekend" | "pre-market" | "regular" | "after-hours" | "overnight",
    "et_label": "Mon May 12, 9:30 AM ET",
    "dst_active": true
  }

Holidays are intentionally NOT modeled — a 1-day approximation drift on
NYSE half-days / federal holidays is acceptable; the dashboard is for
operator awareness, not order routing.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone, time as dtime
from pathlib import Path
from typing import Any, Dict


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_us_dst(d: datetime) -> bool:
    """Rough US DST check: second Sunday of March → first Sunday of November.
    No tzdb dependency — close enough for a UI clock.
    """
    year = d.year
    # second Sunday of March
    march = datetime(year, 3, 1, tzinfo=timezone.utc)
    march_sundays = [march + timedelta(days=i) for i in range(14)
                     if (march + timedelta(days=i)).weekday() == 6]
    dst_start = march_sundays[1].replace(hour=7)  # 2 AM ET ≈ 7 AM UTC
    # first Sunday of November
    nov = datetime(year, 11, 1, tzinfo=timezone.utc)
    nov_sundays = [nov + timedelta(days=i) for i in range(7)
                   if (nov + timedelta(days=i)).weekday() == 6]
    dst_end = nov_sundays[0].replace(hour=6)  # 2 AM ET ≈ 6 AM UTC
    return dst_start <= d < dst_end


def _et_offset_hours(d: datetime) -> int:
    """Eastern Time offset from UTC. -4 during EDT, -5 during EST."""
    return -4 if _is_us_dst(d) else -5


def _et_to_utc(d_et: datetime, dst: bool) -> datetime:
    offset = -4 if dst else -5
    # d_et is naive-with-ET semantics; convert by subtracting offset to get UTC
    return d_et.replace(tzinfo=timezone.utc) - timedelta(hours=offset)


def _next_market_open(now: datetime) -> datetime:
    """Next NYSE regular open (9:30 ET, weekday) after `now` in UTC."""
    cur = now
    for _ in range(10):  # search up to 10 days forward (covers long weekends)
        dst = _is_us_dst(cur)
        # Build today's 9:30 ET in UTC
        et_offset_h = -4 if dst else -5
        today_utc = cur.replace(hour=9, minute=30, second=0, microsecond=0) \
                       - timedelta(hours=et_offset_h)
        if cur.weekday() < 5 and cur <= today_utc:
            return today_utc
        cur = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return cur  # fallback


def _last_market_close(now: datetime) -> datetime:
    """Most recent NYSE 16:00 ET close prior to `now` in UTC."""
    cur = now
    for _ in range(10):
        dst = _is_us_dst(cur)
        et_offset_h = -4 if dst else -5
        close_utc = cur.replace(hour=16, minute=0, second=0, microsecond=0) \
                       - timedelta(hours=et_offset_h)
        if cur.weekday() < 5 and cur >= close_utc:
            return close_utc
        cur = (cur - timedelta(days=1)).replace(hour=23, minute=59, second=0, microsecond=0)
    return cur


def _session_for(now: datetime) -> str:
    """Approximate session label."""
    if now.weekday() >= 5:
        return "weekend"
    dst = _is_us_dst(now)
    et_off = -4 if dst else -5
    open_utc = now.replace(hour=9, minute=30, second=0, microsecond=0) - timedelta(hours=et_off)
    close_utc = now.replace(hour=16, minute=0, second=0, microsecond=0) - timedelta(hours=et_off)
    pre_utc = now.replace(hour=4, minute=0, second=0, microsecond=0) - timedelta(hours=et_off)
    after_utc = now.replace(hour=20, minute=0, second=0, microsecond=0) - timedelta(hours=et_off)
    if open_utc <= now < close_utc:
        return "regular"
    if pre_utc <= now < open_utc:
        return "pre-market"
    if close_utc <= now < after_utc:
        return "after-hours"
    return "overnight"


def _format_et_label(dt_utc: datetime) -> str:
    dst = _is_us_dst(dt_utc)
    et = dt_utc + timedelta(hours=(-4 if dst else -5))
    return et.strftime("%a %b %-d, %-I:%M %p ET") if hasattr(et, "strftime") else et.isoformat()


def build_clock() -> Dict[str, Any]:
    now = _utc_now()
    is_open = (now.weekday() < 5
               and _last_market_close(now) <= now <= _next_market_open(now) + timedelta(seconds=1)
               and _session_for(now) == "regular")
    last_close = _last_market_close(now)
    next_open = _next_market_open(now)
    return {
        "version": "3.1",
        "generated_at": now.isoformat(),
        "now_utc": now.isoformat(),
        "is_open": _session_for(now) == "regular",
        "last_close_utc": last_close.isoformat(),
        "next_open_utc": next_open.isoformat(),
        "session": _session_for(now),
        "et_label_now": _format_et_label(now),
        "et_label_last_close": _format_et_label(last_close),
        "et_label_next_open": _format_et_label(next_open),
        "dst_active": _is_us_dst(now),
    }


def write_clock(data_dir: Path) -> Dict[str, Any]:
    clock = build_clock()
    try:
        (data_dir / "market_clock.json").write_text(
            json.dumps(clock, indent=2, default=str))
    except Exception as e:
        print(f"[market_clock] write failed: {e}")
    return clock


__all__ = ["build_clock", "write_clock"]
