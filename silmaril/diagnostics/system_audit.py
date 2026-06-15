"""silmaril.diagnostics.system_audit — Alpha 6.0 full-system audit emitter.

What it does
────────────
The master directive demands "a full project audit before any further
architecture drift." This module produces ONE consolidated audit
report covering every connected subsystem:

  • brain modules emitting expected sidecars?
  • execution modules consuming those sidecars?
  • workflows firing on schedule?
  • account state in expected band?
  • learning files being updated?
  • orphaned / stale modules?

Output (docs/data/system_audit.json) is shaped for the dashboard.

Each row is one subsystem with a green/yellow/red status and a 1-line
explanation. The operator can see at a glance which limb of the system
needs attention.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


VERSION  = "6.0"
FILENAME = "system_audit.json"


# Files we expect to be updated each cycle. Keyed by "module name shown
# to the operator". Values are (filename, max_age_minutes).
_HEALTH_FILES: Dict[str, tuple] = {
    # ─ Brain
    "orchestrator":            ("orchestrator.json",            90),
    "deployment_floor":        ("deployment_floor.json",        90),
    "capital_efficiency":      ("capital_efficiency.json",      90),
    "position_directives":     ("position_directives.json",     90),
    "conviction_ranking":      ("conviction_ranking.json",      90),
    "policy_router":           ("execution_policy.json",        90),
    # ─ Risk
    "hard_stops":              ("hard_stops.json",              90),
    "risk_state":              ("risk_state.json",              90),
    # ─ Execution
    "alpaca_LEGACY":           ("alpaca_paper_state.json",      90),
    "alpaca_HARVEST_3":        ("alpaca_h3_state.json",         90),
    "alpaca_HARVEST_5":        ("alpaca_h5_state.json",         90),
    # ─ Market intelligence
    "market_state":            ("market_state.json",            90),
    "narrative_tracker":       ("narrative_tracker.json",       90),
    "sector_rotation":         ("sector_rotation.json",         90),
    "correlation_book":        ("correlation_book.json",        90),
    "order_quality":           ("order_quality.json",           90),
    # ─ Learning
    "cross_agent_learning":    ("cross_agent_learning.json",   1440),
    "agent_beliefs":           ("agent_beliefs.json",          1440),
    "agent_evolution_cards":   ("agent_evolution_cards.json",  1440),
    "expectancy_lab":          ("expectancy_lab.json",         1440),
    # ─ Senate
    "senate_state":            ("senate_state.json",           20160),  # weekly
    "senate_results":          ("senate_results.json",         20160),
    # ─ Health
    "run_health":              ("run_health.json",               90),
    "persistence_status":      ("persistence_status.json",     1440),
}


def _safe_f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def _load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _age_minutes(path: Path, now: datetime) -> Optional[float]:
    if not path.exists():
        return None
    body = _load_json(path)
    if not isinstance(body, dict):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            return (now - mtime).total_seconds() / 60.0
        except Exception:
            return None
    gen = body.get("generated_at") or body.get("ran_at") or body.get("last_run") \
          or body.get("election_date")
    if gen:
        try:
            dt = datetime.fromisoformat(str(gen).replace("Z", "+00:00"))
            return (now - dt).total_seconds() / 60.0
        except Exception:
            pass
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return (now - mtime).total_seconds() / 60.0
    except Exception:
        return None


def _status_for_age(age: Optional[float], threshold: int) -> str:
    if age is None:
        return "MISSING"
    if age > threshold * 4:
        return "STALE_RED"
    if age > threshold:
        return "STALE_YELLOW"
    return "FRESH"


# ── Wiring checks: are the directives actually flowing to execution? ──

def _check_directive_flow(data_dir: Path) -> Dict[str, Any]:
    """Verify position_directives are being CONSUMED by alpaca_paper."""
    pd = _load_json(data_dir / "position_directives.json") or {}
    n_directives = len((pd.get("directives") or []))

    # Walk the LEGACY state's orders looking for any directive-tagged action
    # in the last 24h.
    consumed_count = 0
    for fname in ("alpaca_paper_state.json", "alpaca_h3_state.json", "alpaca_h5_state.json"):
        s = _load_json(data_dir / fname) or {}
        orders = (s.get("orders") or [])[-200:]
        for o in orders:
            tag = (o.get("directive") or "").upper()
            if tag in ("PROFIT_LOCK","MOMENTUM_DECAY","INTRADAY_EXHAUSTION",
                       "SCALE_OUT","SCALE_IN","FORCED_ROTATION","STOP_ADJUST"):
                consumed_count += 1
    return {
        "directives_emitted_this_cycle": n_directives,
        "directives_consumed_24h":       consumed_count,
        "wired":                         (n_directives == 0) or (consumed_count > 0),
        "rationale":                     (
            f"{n_directives} emitted, {consumed_count} consumed in last 24h"
        ),
    }


def _check_forced_rotation_flow(data_dir: Path) -> Dict[str, Any]:
    cr = _load_json(data_dir / "conviction_ranking.json") or {}
    n_forced = len((cr.get("forced_rotation_directives") or []))
    consumed = 0
    for fname in ("alpaca_paper_state.json", "alpaca_h3_state.json", "alpaca_h5_state.json"):
        s = _load_json(data_dir / fname) or {}
        for o in (s.get("orders") or [])[-200:]:
            if (o.get("directive") or "").upper() == "FORCED_ROTATION":
                consumed += 1
    return {
        "emitted_this_cycle": n_forced,
        "consumed_24h":       consumed,
        "wired":              (n_forced == 0) or (consumed > 0),
        "rationale":          f"{n_forced} forced-rotations queued; {consumed} executed",
    }


def _check_sweep_cap_enforcement(data_dir: Path) -> Dict[str, Any]:
    df = _load_json(data_dir / "deployment_floor.json") or {}
    violations = 0
    contracts = df.get("contracts") or {}
    for aid, c in contracts.items():
        if "OVER_SWEPT" in (c.get("violation_flags") or []):
            violations += 1
    return {
        "accounts_audited": len(contracts),
        "over_swept_count": violations,
        "wired":            violations == 0,
        "rationale":        ("no over-sweeps" if violations == 0
                                  else f"{violations} accounts breached sweep cap"),
    }


def _check_hard_stops_active(data_dir: Path) -> Dict[str, Any]:
    hs = _load_json(data_dir / "hard_stops.json") or {}
    accs = hs.get("accounts") or {}
    halted = [aid for aid, v in accs.items() if v.get("halt_opens")]
    safe = bool((hs.get("system") or {}).get("cohort_safe_mode"))
    return {
        "accounts_audited":  len(accs),
        "halted":            halted,
        "system_safe_mode":  safe,
        # Hard stops are "wired" so long as the sidecar exists and has
        # been scored for at least one account. Halts ARE the desired
        # behavior — they're not a wiring failure.
        "wired":             len(accs) > 0,
        "rationale": ("clear" if not (halted or safe) else
                          f"{len(halted)} halted" + (" + cohort safe-mode" if safe else "")),
    }


def _account_health(data_dir: Path) -> List[Dict[str, Any]]:
    out = []
    df = _load_json(data_dir / "deployment_floor.json") or {}
    contracts = df.get("contracts") or {}
    for aid, c in contracts.items():
        eq = _safe_f(c.get("live_equity"))
        base = _safe_f(c.get("deployment_base"), 10000)
        cash = _safe_f(c.get("live_cash"))
        sgov = _safe_f(c.get("live_sgov"))
        depr = _safe_f(c.get("deployed_ratio"))
        flags: List[str] = []
        if cash < -1:
            flags.append("NEGATIVE_CASH")
        if eq < base - 200:
            flags.append("BELOW_BASE")
        if depr < 0.30 and eq > base:
            flags.append("UNDER_DEPLOYED")
        if depr > 1.05:
            flags.append("OVER_DEPLOYED_MARGIN")
        if c.get("violation_flags"):
            flags.extend(c["violation_flags"])
        status = "GREEN"
        if any(f in flags for f in ("NEGATIVE_CASH","OVER_DEPLOYED_MARGIN","BELOW_BASE_SEVERE")):
            status = "RED"
        elif flags:
            status = "YELLOW"
        out.append({
            "account_id":      aid,
            "live_equity":     eq,
            "live_cash":       cash,
            "live_sgov":       sgov,
            "deployed_ratio":  depr,
            "status":          status,
            "flags":           flags,
            "rationale":       c.get("rationale") or "",
        })
    return out


def build_system_audit(
    data_dir: Path,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    n_now = now or datetime.now(timezone.utc)
    rows: List[Dict[str, Any]] = []
    fresh_count = 0
    stale_count = 0
    missing_count = 0

    for label, (fname, threshold) in _HEALTH_FILES.items():
        age = _age_minutes(data_dir / fname, n_now)
        status = _status_for_age(age, threshold)
        rows.append({
            "module":         label,
            "file":           fname,
            "age_minutes":    round(age, 1) if age is not None else None,
            "threshold_min":  threshold,
            "status":         status,
        })
        if status == "FRESH":
            fresh_count += 1
        elif status == "MISSING":
            missing_count += 1
        else:
            stale_count += 1

    wiring = {
        "directive_flow":          _check_directive_flow(data_dir),
        "forced_rotation_flow":    _check_forced_rotation_flow(data_dir),
        "sweep_cap_enforcement":   _check_sweep_cap_enforcement(data_dir),
        "hard_stops":              _check_hard_stops_active(data_dir),
    }
    n_wired = sum(1 for v in wiring.values() if v.get("wired"))
    n_total = len(wiring)

    accounts = _account_health(data_dir)
    red_accounts = [a for a in accounts if a["status"] == "RED"]
    yellow_accounts = [a for a in accounts if a["status"] == "YELLOW"]

    overall = "GREEN"
    if red_accounts or n_wired < n_total or missing_count > 3:
        overall = "RED"
    elif yellow_accounts or stale_count > 2 or n_wired < n_total:
        overall = "YELLOW"

    summary = {
        "overall_status":           overall,
        "files_fresh":              fresh_count,
        "files_stale":              stale_count,
        "files_missing":            missing_count,
        "wiring_intact":            n_wired,
        "wiring_total":             n_total,
        "accounts_green":           sum(1 for a in accounts if a["status"] == "GREEN"),
        "accounts_yellow":          len(yellow_accounts),
        "accounts_red":             len(red_accounts),
    }

    bits: List[str] = []
    if overall == "GREEN":
        bits.append("system green")
    if red_accounts:
        bits.append(f"{len(red_accounts)} accounts RED: " + ", ".join(a["account_id"] for a in red_accounts))
    if missing_count:
        bits.append(f"{missing_count} files missing")
    if n_wired < n_total:
        bits.append(f"{n_total - n_wired} wiring gaps")
    rationale = " · ".join(bits)

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "overall_status": overall,
        "summary":      summary,
        "rationale":    rationale or "system green",
        "files":        rows,
        "wiring":       wiring,
        "accounts":     accounts,
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[system_audit] write failed: {e}")
    return payload


def load_system_audit(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "overall_status": "UNKNOWN",
             "rationale": "audit not yet run"}


__all__ = ["VERSION", "build_system_audit", "load_system_audit"]
