"""silmaril.diagnostics.drift_sentinel — Anti-drift invariant sentinel.

Purpose
───────
A learning system that runs unattended drifts: a default flips, a feed goes
silent, a counter creeps, a roster diverges — each small, none fatal, but
together they rot the foundation. This module asserts the invariants that
*must* hold every cycle and records the result, so drift is caught the day it
starts instead of weeks later in an audit.

It is **read-only and additive**: it reads the same JSON the cockpit reads and
writes one new file, `docs/data/drift_sentinel.json`. It never mutates state,
scoring, or orders. Each invariant returns pass / warn / fail with evidence,
and an append-only `drift_log` accumulates a daily record (itself learnable —
drift trends are data).

Notable guard: `narrative_fed` watches `narrative_tracker.headline_count > 0`.
The Alpha-5.0 narrative engine was once silently starved by a field-name
mismatch (it read `news`/`headlines` while signals.json used
`recent_headlines`); this invariant makes that regression impossible to miss.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PASS, WARN, FAIL = "pass", "warn", "fail"
_RANK = {PASS: 0, WARN: 1, FAIL: 2}

BASELINE = 10000.0
ACCOUNTS = [("LEGACY", "alpaca_paper_state.json"),
            ("HARVEST_3", "alpaca_h3_state.json"),
            ("HARVEST_5", "alpaca_h5_state.json")]
KNOWN_DISCONNECTED = 4  # from opus_file_archive.json — grows = new dead code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rj(data_dir: Path, name: str) -> Optional[Any]:
    try:
        return json.loads((data_dir / name).read_text())
    except Exception:
        return None


def _age_days(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        return (_now() - datetime.fromisoformat(str(iso).replace("Z", "+00:00"))).total_seconds() / 86400.0
    except Exception:
        return None


def _inv(name: str, status: str, detail: str, value: Any = None) -> Dict[str, Any]:
    return {"name": name, "status": status, "detail": detail, "value": value}


# ── individual invariants ────────────────────────────────────────────────
def _check_baseline(dd: Path) -> Dict[str, Any]:
    bad = []
    for acct, f in ACCOUNTS:
        s = _rj(dd, f) or {}
        pt = s.get("principal_target")
        if pt is not None and float(pt) != BASELINE:
            bad.append(f"{acct}={pt}")
    if bad:
        return _inv("principal_baseline", FAIL,
                    f"baseline must be $10,000 everywhere; off: {', '.join(bad)}", bad)
    return _inv("principal_baseline", PASS, "all accounts anchored to $10,000", BASELINE)


def _check_no_100k(dd: Path) -> Dict[str, Any]:
    e = _rj(dd, "alpaca_equity_curve.json") or {}
    snaps = e.get("snapshots") or []
    if snaps:
        base = snaps[0].get("equity")
        if base and abs(base - BASELINE) > BASELINE * 0.5:
            return _inv("no_legacy_100k", FAIL,
                        f"equity curve seeded at {base:.0f} — legacy $100k base resurfaced", base)
    return _inv("no_legacy_100k", PASS, "no legacy $100k base present", len(snaps))


def _check_narrative_fed(dd: Path) -> Dict[str, Any]:
    nt = _rj(dd, "narrative_tracker.json") or {}
    hc = nt.get("headline_count")
    if hc is None:
        return _inv("narrative_fed", WARN, "narrative_tracker.json missing", None)
    if hc <= 0:
        return _inv("narrative_fed", FAIL,
                    "narrative engine is receiving ZERO headlines — edge-in-words is starved "
                    "(check the recent_headlines field wiring)", hc)
    return _inv("narrative_fed", PASS, f"narrative engine fed by {hc} headlines", hc)


def _check_accounts_active(dd: Path) -> Dict[str, Any]:
    dormant = []
    for acct, f in ACCOUNTS:
        s = _rj(dd, f) or {}
        age = _age_days(s.get("last_run"))
        if age is not None and age > 2.0:
            dormant.append(f"{acct} ({age:.0f}d)")
    if dormant:
        return _inv("accounts_active", WARN,
                    f"account(s) quiet >2d: {', '.join(dormant)} — check secrets/funding", dormant)
    return _inv("accounts_active", PASS, "all accounts active within 2 days", None)


def _check_stale(dd: Path, prior: Optional[Dict]) -> Dict[str, Any]:
    sc = _rj(dd, "scoring.json") or {}
    outs = sc.get("outcomes") or []
    if not outs:
        return _inv("stale_bounded", WARN, "no outcomes yet", None)
    stale = sum(1 for o in outs if o.get("stale_price_suspected"))
    pct = round(100 * stale / len(outs), 1)
    prior_pct = (prior or {}).get("stale_pct") if prior else None
    trend = ""
    if isinstance(prior_pct, (int, float)):
        d = pct - prior_pct
        trend = f" (was {prior_pct}%, {'+' if d>=0 else ''}{round(d,1)})"
    # On the first clean trading week, stale% should fall, not climb.
    if isinstance(prior_pct, (int, float)) and pct > prior_pct + 3:
        return _inv("stale_bounded", WARN,
                    f"stale share climbing: {pct}%{trend} — price overlay may be failing in Actions", pct)
    if pct > 60:
        return _inv("stale_bounded", WARN, f"stale share high at {pct}%{trend}", pct)
    return _inv("stale_bounded", PASS, f"stale share {pct}%{trend}", pct)


def _check_frozen(dd: Path) -> Dict[str, Any]:
    rs = _rj(dd, "risk_state.json") or {}
    summ = rs.get("summary") or {}
    n = summ.get("frozen_count")
    names = []
    if n is None:
        agents = rs.get("agents") or {}
        if isinstance(agents, dict):
            names = [k for k, v in agents.items() if isinstance(v, dict) and v.get("frozen")]
            n = len(names)
        else:
            n = 0
    else:
        agents = rs.get("agents") or {}
        if isinstance(agents, dict):
            names = [k for k, v in agents.items() if isinstance(v, dict) and v.get("frozen")]
    detail_names = f": {', '.join(names)}" if names else ""
    if n > 4:
        return _inv("frozen_bounded", WARN,
                    f"{n} agents frozen{detail_names} — cluster freeze may be spreading", n)
    return _inv("frozen_bounded", PASS,
                f"{n} agents frozen{detail_names} (expected ≤4 on stale-era scores)", n)


def _check_orphans(dd: Path) -> Dict[str, Any]:
    a = _rj(dd, "opus_file_archive.json") or {}
    disc = a.get("truly_disconnected")
    if disc is None:
        return _inv("orphans_bounded", WARN, "no file archive to compare", None)
    if len(disc) > KNOWN_DISCONNECTED:
        return _inv("orphans_bounded", WARN,
                    f"{len(disc)} disconnected files (was {KNOWN_DISCONNECTED}) — new dead code", disc)
    return _inv("orphans_bounded", PASS, f"{len(disc)} disconnected files (known)", len(disc))


def _check_canceller(dd: Path) -> Dict[str, Any]:
    seen = []
    for acct, f in ACCOUNTS:
        s = _rj(dd, f) or {}
        lc = s.get("last_stale_cancel")
        if isinstance(lc, dict):
            seen.append(f"{acct}:{lc.get('cancelled', 0)}")
    if not seen:
        return _inv("order_hygiene", WARN,
                    "stale-order canceller has not reported yet (runs at cycle start with keys)", None)
    return _inv("order_hygiene", PASS, f"stale-order cleanup active ({', '.join(seen)})", seen)


def _check_deal_linking(dd: Path) -> Dict[str, Any]:
    dj = _rj(dd, "deal_journal.json") or {}
    linked = dj.get("linked_count")
    if linked is None:
        return _inv("deal_linking", WARN, "deal journal missing", None)
    if linked <= 0:
        return _inv("deal_linking", WARN, "no trades linked to outcomes yet", 0)
    return _inv("deal_linking", PASS, f"{linked} trades linked to outcomes", linked)


# ── orchestration ─────────────────────────────────────────────────────────
def build_sentinel(data_dir: Path) -> Dict[str, Any]:
    """Run all invariants, append to the drift log, write drift_sentinel.json."""
    prior = _rj(data_dir, "drift_sentinel.json") or {}
    checks: List[Dict[str, Any]] = [
        _check_baseline(data_dir),
        _check_no_100k(data_dir),
        _check_narrative_fed(data_dir),
        _check_accounts_active(data_dir),
        _check_stale(data_dir, prior),
        _check_frozen(data_dir),
        _check_orphans(data_dir),
        _check_canceller(data_dir),
        _check_deal_linking(data_dir),
    ]
    overall = max((c["status"] for c in checks), key=lambda s: _RANK[s])
    n_pass = sum(1 for c in checks if c["status"] == PASS)
    n_warn = sum(1 for c in checks if c["status"] == WARN)
    n_fail = sum(1 for c in checks if c["status"] == FAIL)
    stale_pct = next((c["value"] for c in checks if c["name"] == "stale_bounded"), None)
    headline_count = next((c["value"] for c in checks if c["name"] == "narrative_fed"), None)

    today = _now().date().isoformat()
    log = prior.get("drift_log") or []
    # one entry per day (replace today's if re-run)
    log = [e for e in log if e.get("date") != today]
    log.append({"date": today, "overall": overall, "pass": n_pass,
                "warn": n_warn, "fail": n_fail, "stale_pct": stale_pct,
                "headline_count": headline_count})
    log = log[-120:]

    payload = {
        "version": "drift-sentinel-1.0",
        "generated_at": _now().isoformat(),
        "overall": overall,
        "summary": f"{n_pass}/{len(checks)} invariants holding"
                   + (f" · {n_fail} FAILING" if n_fail else "")
                   + (f" · {n_warn} warning" if n_warn else ""),
        "counts": {"pass": n_pass, "warn": n_warn, "fail": n_fail, "total": len(checks)},
        "stale_pct": stale_pct,
        "headline_count": headline_count,
        "invariants": checks,
        "drift_log": log,
    }
    try:
        (data_dir / "drift_sentinel.json").write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:  # noqa: BLE001
        print(f"[drift_sentinel] write failed: {e}")
    return payload
