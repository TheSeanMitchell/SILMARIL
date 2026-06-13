"""
silmaril.analytics.domain_clock — per-domain fetch gating (ALPHA 1.0 item #1).

WHY THIS EXISTS
The external cron (cron-job.org) wants to go 24/7 every 20 minutes so the
24/7 organs (crypto, gold, oil, macro — the valuables book) get the same
dense coverage the stock book gets during the session. But the EXPENSIVE
fetch families (stock news at ~8s/ticker, earnings calendar, IPO calendar)
produce nothing useful at 3 AM Sunday and only burn provider quota. This
module is the single gate every fetch family consults before spending quota.

THE DOMAINS (spec from ROADMAP_TO_ALPHA_1.md #1)
  stocks     equity news / earnings / IPO-calendar fetches.
             OPEN 08:30–16:30 ET, Mon–Fri (proper America/New_York tz,
             DST-correct — unlike the sentinel's hardcoded UTC-4).
  valuables  crypto / gold / oil / metals / macro. ALWAYS OPEN — these
             markets never close and the valuables organ is the whole
             reason the cron widens.
  social     social-pulse scrape. OPEN at most once per hour
             (55-minute interval so a :00/:20/:40 cron lands exactly one
             allowed run per hour even with scheduler jitter).
  edgar      SEC full-text watch. ALWAYS OPEN during the SPCX intensive
             window (debut week + aftermarket, through 2026-07-03), then
             at most every 4 hours (230-minute interval).

DESIGN RULES (house law)
  - Pure stdlib, zero network, injectable `now` — offline-safe, testable.
  - Interval domains persist state in docs/data/domain_clock_state.json
    (committed by daily.yml's `git add docs/data/`, so state survives the
    stateless Actions checkout).
  - Every decision is COUNTED (allowed/skipped per domain per UTC day) and
    api_health renders the budget — quota discipline is observable, not
    assumed.
  - Fail-open: if the state file is corrupt or the clock errors, the gate
    answers True. A lost fetch-skip costs pennies; a silently starved organ
    is the failure mode this project keeps re-learning.
  - Escape hatches: SILMARIL_DOMAIN_CLOCK_DISABLE=1 opens everything
    (manual workflow_dispatch debugging); SILMARIL_DOMAIN_FORCE="social,edgar"
    force-opens listed domains for one run.

USAGE
    from silmaril.analytics.domain_clock import domain_clock
    if domain_clock("stocks", data_dir):
        news_map = fetch_news_bulk(...)
    else:
        news_map = {}

`domain_clock(...)` RECORDS the decision (and, for interval domains that
answer True, stamps last_allowed). `domain_clock_report(...)` is the
check-only snapshot for api_health — it never mutates state.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:  # zoneinfo is stdlib on py>=3.9; Actions runners ship tzdata
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover — fallback keeps the gate fail-open
    _ET = None

VERSION = "domain-clock-1.0"
STATE_FILE = "domain_clock_state.json"

DOMAINS = ("stocks", "stocks_news", "valuables", "social", "edgar")

# stocks window (ET minutes-of-day, inclusive): 08:30 .. 16:30, Mon-Fri
_STOCKS_OPEN_MIN = 8 * 60 + 30
_STOCKS_CLOSE_MIN = 16 * 60 + 30

# social: at most hourly; 55-min interval tolerates cron jitter
_SOCIAL_INTERVAL_MIN = 55.0

# edgar: SPCX intensive window — every run through this UTC date (inclusive),
# covering debut week (Jun 12) plus three weeks of priced/aftermarket filings.
SPCX_INTENSIVE_UNTIL = "2026-07-03"
_EDGAR_INTERVAL_MIN = 230.0  # ~4h, minus jitter margin

_COUNTER_DAYS_KEPT = 14


# ── persistence ─────────────────────────────────────────────────────────

def _state_path(data_dir) -> Path:
    return Path(data_dir) / STATE_FILE

def _load_state(data_dir) -> Dict[str, Any]:
    try:
        doc = json.loads(_state_path(data_dir).read_text())
        if not isinstance(doc, dict):
            return {}
        return doc
    except Exception:
        return {}

def _dump_state(data_dir, doc: Dict[str, Any]) -> None:
    path = _state_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(doc, f, indent=2)
            os.replace(tmp, str(path))
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    except Exception:
        # Persistence failure must never break a cycle; next run re-decides.
        pass


# ── the clock decisions (pure; injectable now) ─────────────────────────

def _now_utc(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now

def _stocks_open(now_utc: datetime) -> bool:
    """08:30–16:30 ET Mon–Fri, DST-correct. Fail-open if tz data missing."""
    if _ET is None:  # pragma: no cover
        return True
    et = now_utc.astimezone(_ET)
    if et.weekday() >= 5:
        return False
    mins = et.hour * 60 + et.minute
    return _STOCKS_OPEN_MIN <= mins <= _STOCKS_CLOSE_MIN

def _minutes_since(iso: Optional[str], now_utc: datetime) -> float:
    if not iso:
        return float("inf")
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        gap = (now_utc - t).total_seconds() / 60.0
        # Clock-skew safety: a FUTURE stamp (negative gap) must never lock
        # a domain shut — treat as "never ran" and fail-open.
        return gap if gap >= 0 else float("inf")
    except Exception:
        return float("inf")

def _edgar_intensive(now_utc: datetime) -> bool:
    return now_utc.date().isoformat() <= SPCX_INTENSIVE_UNTIL

def _decide(domain: str, state: Dict[str, Any], now_utc: datetime) -> (bool, str):
    """Return (open?, reason). Pure — reads state, never writes it."""
    last = (state.get("last_allowed") or {})
    if domain == "stocks":
        ok = _stocks_open(now_utc)
        return ok, ("session window 08:30-16:30 ET Mon-Fri"
                    if ok else "outside 08:30-16:30 ET Mon-Fri")
    if domain == "stocks_news":
        # OPERATOR CORRECTION (June 11): only TRADING keeps market hours —
        # information does not. Earnings drop after the close; catalysts
        # break on weekends. In-window: every run. Off-window: hourly, so
        # the word engine never goes blind while quota stays sane.
        if _stocks_open(now_utc):
            return True, "session window — every run"
        gap = _minutes_since(last.get("stocks_news"), now_utc)
        ok = gap >= _SOCIAL_INTERVAL_MIN  # same 55-min hourly cadence
        return ok, (f"off-hours hourly news sweep — {gap:.0f} min since last"
                    if gap != float("inf")
                    else "off-hours hourly news sweep — first run")
    if domain == "valuables":
        return True, "always open — markets never close"
    if domain == "social":
        gap = _minutes_since(last.get("social"), now_utc)
        ok = gap >= _SOCIAL_INTERVAL_MIN
        return ok, (f"hourly cadence — {gap:.0f} min since last"
                    if gap != float("inf") else "hourly cadence — first run")
    if domain == "edgar":
        if _edgar_intensive(now_utc):
            return True, f"SPCX intensive window (through {SPCX_INTENSIVE_UNTIL})"
        gap = _minutes_since(last.get("edgar"), now_utc)
        ok = gap >= _EDGAR_INTERVAL_MIN
        return ok, (f"4h cadence — {gap:.0f} min since last"
                    if gap != float("inf") else "4h cadence — first run")
    # Unknown domain: fail-open and say so loudly in the reason.
    return True, f"unknown domain '{domain}' — fail-open"


# ── env escape hatches ──────────────────────────────────────────────────

def _env_disabled() -> bool:
    return str(os.environ.get("SILMARIL_DOMAIN_CLOCK_DISABLE", "")).strip() in (
        "1", "true", "TRUE", "yes")

def _env_forced(domain: str) -> bool:
    raw = str(os.environ.get("SILMARIL_DOMAIN_FORCE", "") or "")
    forced = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return domain.lower() in forced

def _env_blocked(domain: str) -> bool:
    """SILMARIL_DOMAIN_BLOCK="stocks,social" force-CLOSES listed domains —
    the operator kill-switch for a runaway provider, and the way to prove
    the skip path on demand. Block beats force if both name a domain."""
    raw = str(os.environ.get("SILMARIL_DOMAIN_BLOCK", "") or "")
    blocked = {p.strip().lower() for p in raw.split(",") if p.strip()}
    return domain.lower() in blocked


# ── public API ──────────────────────────────────────────────────────────

def domain_clock(domain: str, data_dir="docs/data",
                 now: Optional[datetime] = None,
                 record: bool = True) -> bool:
    """The gate. Consult before every fetch family.

    Records the allowed/skipped counter and (for interval domains answering
    True) stamps last_allowed, so the budget is enforced and observable.
    Set record=False for a what-if probe that must not consume the interval.
    """
    now_utc = _now_utc(now)
    state = _load_state(data_dir)

    if _env_blocked(domain):
        ok, reason = False, "env override: SILMARIL_DOMAIN_BLOCK"
    elif _env_disabled() or _env_forced(domain):
        ok, reason = True, ("env override: SILMARIL_DOMAIN_CLOCK_DISABLE"
                            if _env_disabled() else
                            "env override: SILMARIL_DOMAIN_FORCE")
    else:
        try:
            ok, reason = _decide(domain, state, now_utc)
        except Exception as e:  # fail-open, loudly
            ok, reason = True, f"clock error ({e}) — fail-open"

    if record:
        try:
            state.setdefault("version", VERSION)
            la = state.setdefault("last_allowed", {})
            if ok and domain in ("social", "edgar", "stocks_news"):
                la[domain] = now_utc.isoformat()
            day = now_utc.date().isoformat()
            counters = state.setdefault("counters", {})
            dc = counters.setdefault(day, {}).setdefault(
                domain, {"allowed": 0, "skipped": 0})
            dc["allowed" if ok else "skipped"] += 1
            # trim counters to the last N days
            for k in sorted(counters.keys())[:-_COUNTER_DAYS_KEPT]:
                counters.pop(k, None)
            state["last_decision"] = {
                "domain": domain, "open": ok, "reason": reason,
                "at": now_utc.isoformat(),
            }
            _dump_state(data_dir, state)
        except Exception:
            pass

    tag = "OPEN" if ok else "CLOSED"
    print(f"[domain-clock] {domain}: {tag} — {reason}")
    return ok


def domain_clock_report(data_dir="docs/data",
                        now: Optional[datetime] = None) -> Dict[str, Any]:
    """Check-only snapshot of every domain + budget counters (for api_health).
    Never mutates state — safe to call any number of times."""
    now_utc = _now_utc(now)
    state = _load_state(data_dir)
    domains: Dict[str, Any] = {}
    for d in DOMAINS:
        try:
            ok, reason = _decide(d, state, now_utc)
        except Exception as e:
            ok, reason = True, f"clock error ({e}) — fail-open"
        if _env_blocked(d):
            ok, reason = False, "env override: SILMARIL_DOMAIN_BLOCK"
        elif _env_disabled() or _env_forced(d):
            ok, reason = True, "env override"
        domains[d] = {"open": ok, "reason": reason}
    today = now_utc.date().isoformat()
    return {
        "version": VERSION,
        "checked_at": now_utc.isoformat(),
        "domains": domains,
        "last_allowed": state.get("last_allowed") or {},
        "today_budget": (state.get("counters") or {}).get(today, {}),
        "spcx_intensive_until": SPCX_INTENSIVE_UNTIL,
        "note": ("the cron may run 24/7: stock TRADING-adjacent fetches "
                 "(earnings/ipo-cal) keep 08:30-16:30 ET Mon-Fri; equity NEWS "
                 "runs every cycle in-window and hourly off-hours (information "
                 "never sleeps); valuables always; social hourly; EDGAR every "
                 "run through the SPCX window then 4h"),
    }


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(domain_clock_report(
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")), indent=2))
