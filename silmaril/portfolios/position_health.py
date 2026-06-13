"""silmaril.portfolios.position_health — Alpha 5.0 unified position health matrix.

What it does
────────────
The master directive identifies the "weak positions surviving too long"
failure mode and demands a per-position health matrix surfacing:

  Unrealized P/L, Momentum, Narrative Drift, Vulnerability,
  Rotation Score, Time Held, Relative Strength, Bleed Risk,
  Replacement Candidate, Force-Rotation Status.

This module fuses data from existing sidecars (profit_at_risk,
conviction_ranking, narrative_tracker, sector_rotation,
execution_policy, multi-account state) into ONE flat array of position
rows so the dashboard can render a triage table without doing JS joins.

This module does NOT change execution. It is purely the operator-facing
view layer. The forced-rotation directives in conviction_engine.py are
the authoritative actuator; this row table reflects them so the operator
can see what's already been queued and what's just borderline.

Output (docs/data/position_health.json)
───────────────────────────────────────
{
  "version": "5.0",
  "generated_at": "...",
  "summary": {
     "total_positions":     12,
     "force_rotation":       2,
     "watch":                4,
     "healthy":              6
  },
  "rows": [
    {
      "owner":              "HARVEST_5",
      "ticker":             "NVDA",
      "sector":             "Technology",
      "qty":                4.0,
      "avg_entry":          910.25,
      "current_price":      934.10,
      "unrealized_pl":       95.40,
      "unrealized_pl_pct":   1.05,
      "momentum_score":      0.72,
      "narrative_drift":    -0.12,
      "vulnerability_score": 0.18,
      "rotation_score":      0.55,
      "time_held_days":      4.2,
      "relative_strength":   0.30,
      "bleed_risk":          0.05,
      "replacement_candidate": "AMD",
      "force_rotation":      false,
      "status":              "WATCH",
      "rationale":           "narrative cooling; alt AMD scores 0.74"
    }, ...
  ]
}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


VERSION  = "5.0"
FILENAME = "position_health.json"

# Status thresholds
STATUS_FORCE_ROTATE = 0.0    # set by conviction_ranking forced_rotation
STATUS_WATCH_VULN   = 0.45
STATUS_WATCH_ROT    = 0.55
STATUS_HEALTHY_FLOOR = 0.55


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


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _build_position_index(
    multi_account_results: Optional[Dict[str, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Flatten {account: state} → flat list of position rows."""
    out: List[Dict[str, Any]] = []
    if not isinstance(multi_account_results, dict):
        return out
    for aid, astate in multi_account_results.items():
        if not isinstance(astate, dict) or not astate.get("enabled"):
            continue
        snap = astate.get("positions_snapshot") or []
        meta = astate.get("position_meta") or {}
        if snap:
            for p in snap:
                if not isinstance(p, dict):
                    continue
                sym = (p.get("symbol") or p.get("ticker") or "").upper()
                if not sym or sym in ("SGOV", "BIL", "SHY", "TFLO", "USFR"):
                    continue
                m = meta.get(sym, {}) if isinstance(meta, dict) else {}
                out.append({
                    "owner":           aid,
                    "ticker":          sym,
                    "qty":             _safe_f(p.get("qty")),
                    "avg_entry":       _safe_f(p.get("avg_entry_price")
                                                 or m.get("entry_price")),
                    "current_price":   _safe_f(p.get("current_price")),
                    "peak_price":      _safe_f(p.get("peak_price")
                                                 or m.get("peak_price")),
                    "unrealized_pl":   _safe_f(p.get("unrealized_pl")),
                    "unrealized_plpc": _safe_f(p.get("unrealized_plpc")),
                    "first_seen":      m.get("first_seen"),
                })
        else:
            # Fall back to position_meta only.
            if not isinstance(meta, dict):
                continue
            for sym, m in meta.items():
                if not sym or sym.upper() in ("SGOV", "BIL", "SHY", "TFLO", "USFR"):
                    continue
                out.append({
                    "owner":         aid,
                    "ticker":        sym.upper(),
                    "qty":           _safe_f(m.get("qty")),
                    "avg_entry":     _safe_f(m.get("entry_price")),
                    "current_price": _safe_f(m.get("entry_price")),
                    "peak_price":    _safe_f(m.get("peak_price")),
                    "unrealized_pl":   0.0,
                    "unrealized_plpc": 0.0,
                    "first_seen":    m.get("first_seen"),
                })
    return out


def _momentum_score(row: Dict[str, Any]) -> float:
    """Compose a momentum proxy from peak/current/avg_entry."""
    cur = _safe_f(row.get("current_price"))
    peak = _safe_f(row.get("peak_price"))
    avg = _safe_f(row.get("avg_entry"))
    if cur <= 0 or avg <= 0:
        return 0.5
    # gain leg
    gain = (cur - avg) / avg if avg > 0 else 0.0
    # giveback leg
    giveback = 0.0
    if peak > 0:
        giveback = (cur - peak) / peak  # negative when below peak
    # gain saturates at +20%, giveback at -10%.
    gain_n = max(0.0, min(1.0, (gain + 0.05) / 0.25))
    gb_n   = max(0.0, min(1.0, 1.0 + giveback / 0.10))
    return round(0.6 * gain_n + 0.4 * gb_n, 4)


def _time_held_days(row: Dict[str, Any], now: datetime) -> float:
    first = _parse_iso(row.get("first_seen"))
    if not first:
        return 0.0
    delta = now - first
    return round(max(0.0, delta.total_seconds() / 86_400.0), 2)


def _bleed_risk(row: Dict[str, Any]) -> float:
    """Higher = position is bleeding from peak. 0..1."""
    cur = _safe_f(row.get("current_price"))
    peak = _safe_f(row.get("peak_price"))
    if cur <= 0 or peak <= 0:
        return 0.0
    gb = (peak - cur) / peak if peak > 0 else 0.0
    # 5% giveback = score 0.5; 10% giveback = 1.0.
    return round(max(0.0, min(1.0, gb / 0.10)), 4)


def build_position_health(
    data_dir: Path,
    multi_account_results: Optional[Dict[str, Dict[str, Any]]] = None,
    sector_lookup: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Assemble the position-health rollup from existing sidecars."""
    n_now = now or datetime.now(timezone.utc)
    sector_lookup = sector_lookup or {}

    # Pull dependencies
    profit_at_risk     = _load_json(data_dir / "profit_at_risk.json") or {}
    conviction_ranking = _load_json(data_dir / "conviction_ranking.json") or {}
    narrative          = _load_json(data_dir / "narrative_tracker.json") or {}
    rotation           = _load_json(data_dir / "sector_rotation.json") or {}
    policy             = _load_json(data_dir / "execution_policy.json") or {}

    # PAR positions index by ticker
    par_by_ticker: Dict[str, Dict[str, Any]] = {}
    for p in (profit_at_risk.get("positions") or []):
        if isinstance(p, dict):
            t = (p.get("ticker") or "").upper()
            if t:
                par_by_ticker[t] = p

    # Holdings review index by (owner, ticker)
    holdings_review = conviction_ranking.get("holdings_review") or []
    hr_index: Dict[str, Dict[str, Any]] = {}
    for h in holdings_review:
        key = f"{h.get('owner', '')}::{(h.get('ticker') or '').upper()}"
        hr_index[key] = h

    forced_rotations = conviction_ranking.get("forced_rotation_directives") or []
    forced_index: Dict[str, Dict[str, Any]] = {}
    for d in forced_rotations:
        key = f"{d.get('owner', '')}::{(d.get('sell_ticker') or '').upper()}"
        forced_index[key] = d

    # Policy force_close map
    force_close_map: Dict[str, Dict[str, Any]] = (policy.get("force_close") or {})
    vulnerable_set = set((policy.get("vulnerable_tickers") or []))

    # Sector pressure + rotation lift maps
    sec_pressure_map = (narrative.get("sector_pressure") or {})
    rotation_sectors = (rotation.get("sectors") or {})

    positions = _build_position_index(multi_account_results)
    rows: List[Dict[str, Any]] = []
    counts = {"force_rotation": 0, "watch": 0, "healthy": 0}

    for row in positions:
        sym = row["ticker"]
        owner = row["owner"]
        sector = sector_lookup.get(sym) or "Unknown"
        hr_key = f"{owner}::{sym}"

        par = par_by_ticker.get(sym, {})
        hr  = hr_index.get(hr_key, {})
        forced = forced_index.get(hr_key)

        momentum = _momentum_score(row)
        bleed = _bleed_risk(row)
        time_held = _time_held_days(row, n_now)
        narrative_drift = _safe_f(sec_pressure_map.get(sector, 0.0))
        rel_strength = _safe_f((rotation_sectors.get(sector) or {})
                                  .get("relative_strength", 0.0))
        # Vulnerability score from PAR (0..1)
        vuln = _safe_f(par.get("score"))
        # Rotation score from holdings_review (0..1)
        rot_score = _safe_f(hr.get("holding_score"))
        # Replacement candidate from holdings_review
        replacement = hr.get("alternative")

        is_force = bool(forced) or sym in force_close_map
        is_critical_policy = sym in force_close_map
        is_watch = (not is_force) and (
            vuln >= STATUS_WATCH_VULN
            or rot_score < STATUS_WATCH_ROT
            or sym in vulnerable_set
            or bleed >= 0.5
        )
        if is_force:
            status = "FORCE_ROTATE"
            counts["force_rotation"] += 1
        elif is_watch:
            status = "WATCH"
            counts["watch"] += 1
        else:
            status = "HEALTHY"
            counts["healthy"] += 1

        bits: List[str] = []
        if forced:
            bits.append(f"Δ {_safe_f(forced.get('score_delta')):+.2f} vs {forced.get('buy_ticker')}")
        elif replacement:
            bits.append(f"alt {replacement} {_safe_f(hr.get('alt_score')):.2f}")
        if vuln >= 0.5:
            bits.append(f"vuln {vuln:.2f}")
        if bleed >= 0.4:
            bits.append(f"bleed {bleed:.2f}")
        if narrative_drift <= -0.20:
            bits.append(f"sector {narrative_drift:+.2f}")
        if is_critical_policy:
            bits.append("policy force_close")
        rationale = " · ".join(bits) or (hr.get("rationale") or "")

        rows.append({
            "owner":               owner,
            "ticker":              sym,
            "sector":              sector,
            "qty":                 row["qty"],
            "avg_entry":           row["avg_entry"],
            "current_price":       row["current_price"],
            "unrealized_pl":       row["unrealized_pl"],
            "unrealized_pl_pct":   row["unrealized_plpc"],
            "momentum_score":      momentum,
            "narrative_drift":     round(narrative_drift, 4),
            "vulnerability_score": round(vuln, 4),
            "rotation_score":      round(rot_score, 4),
            "time_held_days":      time_held,
            "relative_strength":   round(rel_strength, 4),
            "bleed_risk":          bleed,
            "replacement_candidate": replacement,
            "force_rotation":      bool(is_force),
            "status":              status,
            "rationale":           rationale,
        })

    # Sort: FORCE_ROTATE first, then WATCH, then HEALTHY; within each
    # bucket, lowest rotation_score first so triage starts at the worst.
    bucket_rank = {"FORCE_ROTATE": 0, "WATCH": 1, "HEALTHY": 2}
    rows.sort(key=lambda r: (bucket_rank.get(r["status"], 9),
                                _safe_f(r.get("rotation_score")),
                                -_safe_f(r.get("vulnerability_score"))))

    summary = {
        "total_positions": len(rows),
        **counts,
    }

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "summary":      summary,
        "rows":         rows,
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[position_health] write failed: {e}")
    return payload


def load_position_health(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "summary": {"total_positions": 0,
             "force_rotation": 0, "watch": 0, "healthy": 0}, "rows": []}


__all__ = [
    "VERSION", "build_position_health", "load_position_health",
]
