"""silmaril.portfolios.sector_rotation — Alpha 5.0 sector flow engine.

What it does
────────────
The master directive requires a sector-rotation engine that:
  - understands sector transitions,
  - dynamically reweights opportunity scoring,
  - identifies broad market migrations.

This module fuses three deterministic signals into a per-sector "flow" score:

  1. NARRATIVE PRESSURE     (from narrative_tracker.sector_pressure)
     What the news is saying about each sector right now.

  2. RELATIVE STRENGTH      (from per-ticker price snapshots in contexts)
     Average 5-day return of each sector's component tickers minus the
     market-wide average. Positive = outperforming.

  3. CAPITAL MOMENTUM       (from current portfolio holdings)
     Are the accounts NET BUYING or NET SELLING this sector cycle-over-cycle?
     Read from `decision_ledger.json` recent rows.

Each signal is normalised to [-1, +1] then weighted into a single
`flow_score` per sector. The output also surfaces:
  - `strengthening` / `weakening` / `accelerating` tags (3.3 wording),
  - a `rotation_lift` multiplier (1.0 ± 0.30) downstream conviction
    engines can apply to plan scores in that sector,
  - `top_pairs` showing the strongest "out of X → into Y" rotations
    so the dashboard can render them as Bloomberg-style flow arrows.

This is the second piece the master prompt asks for explicitly:

  AI weakening
  Oil strengthening
  Defense strengthening
  Biotech accelerating
  Retail deteriorating

Output (docs/data/sector_rotation.json)
───────────────────────────────────────
{
  "version": "5.0",
  "generated_at": "...",
  "sectors": {
    "Technology": {
      "flow_score":      -0.42,
      "tag":             "weakening",
      "rotation_lift":   0.85,
      "narrative_pressure": -0.40,
      "relative_strength":  -0.12,
      "capital_momentum":   -0.08,
      "rationale":         "AI cooldown narrative + 5d underperformance"
    },
    "Energy": { "flow_score": +0.38, "tag": "strengthening", ... },
    ...
  },
  "top_pairs": [
     {"from":"Technology","to":"Energy","strength":0.80,"rationale":"..."},
     ...
  ],
  "rationale":  "..."
}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION  = "5.0"
FILENAME = "sector_rotation.json"

# Score weighting (sum ≤ 1.0).
W_NARRATIVE     = 0.45
W_REL_STRENGTH  = 0.35
W_CAPITAL_MOM   = 0.20

# Lift multiplier range applied to conviction in downstream engines.
LIFT_MIN = 0.75
LIFT_MAX = 1.30

# Tagging thresholds.
TAG_STRONG_THRESHOLD = 0.25
TAG_WEAK_THRESHOLD   = -0.25
TAG_ACCEL_DELTA      = 0.20

# Recent ledger lookback window for capital-momentum sampling.
LEDGER_LOOKBACK_HRS = 48

# Decision-ledger categories that count as "deployment" / "exit".
_DEPLOY_CATEGORIES = {
    "open_executed", "open_placed", "rotation_opened",
    "news_boost_fired", "elite_opened",
}
_EXIT_CATEGORIES = {
    "close_executed", "close_placed", "stale_close_fired",
    "bleed_exit_fired", "instant_sweep_fired",
}


def _safe_f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


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


# ─── Inputs aggregation ───────────────────────────────────────────────

def _relative_strength_by_sector(
    contexts_by_ticker: Dict[str, Any],
    sector_lookup: Dict[str, str],
) -> Dict[str, float]:
    """Compute the average 5-day return of each sector's tickers minus the
    market-wide 5-day return. Positive → outperforming.

    Tolerates missing fields: tickers with no five_day_return are ignored.
    """
    if not contexts_by_ticker:
        return {}

    # Pull per-ticker 5d return (or close-vs-5dEMA proxy if return field missing).
    per_ticker: List[Tuple[str, str, float]] = []  # (ticker, sector, ret)
    for tkr, ctx in (contexts_by_ticker or {}).items():
        if not ctx:
            continue
        ret = None
        for attr in ("five_day_return", "return_5d", "ret_5d", "weekly_return"):
            v = (getattr(ctx, attr, None) if not isinstance(ctx, dict)
                  else ctx.get(attr))
            if v is not None:
                ret = _safe_f(v, None)
                if ret is not None:
                    break
        if ret is None:
            # Proxy: current vs sma_5 (or sma_20) if available.
            cur = (getattr(ctx, "price", None) if not isinstance(ctx, dict)
                    else ctx.get("price"))
            sma = None
            for attr in ("sma_5", "sma_20", "sma_50"):
                v = (getattr(ctx, attr, None) if not isinstance(ctx, dict)
                      else ctx.get(attr))
                if v:
                    sma = _safe_f(v, None)
                    if sma:
                        break
            if cur and sma and sma > 0:
                ret = (float(cur) - sma) / sma
        if ret is None:
            continue
        sector = sector_lookup.get((tkr or "").upper()) or "Unknown"
        per_ticker.append((tkr.upper(), sector, float(ret)))

    if not per_ticker:
        return {}

    market_avg = sum(r for _, _, r in per_ticker) / float(len(per_ticker))

    by_sector: Dict[str, List[float]] = {}
    for _t, sec, r in per_ticker:
        by_sector.setdefault(sec, []).append(r)

    out: Dict[str, float] = {}
    for sec, rets in by_sector.items():
        if not rets:
            continue
        sec_avg = sum(rets) / float(len(rets))
        delta = sec_avg - market_avg
        # Saturate at ±5% (which is enormous in 5d terms) → clamp to ±1.
        out[sec] = _clamp(delta / 0.05, -1.0, 1.0)
    return out


def _capital_momentum_by_sector(
    decision_ledger: Optional[Dict[str, Any]],
    sector_lookup: Dict[str, str],
    now: Optional[datetime] = None,
) -> Dict[str, float]:
    """+1 = all opens this sector / -1 = all closes / 0 = no flow.

    Walks the recent decision_ledger rows; nets opens vs closes by sector.
    """
    if not isinstance(decision_ledger, dict):
        return {}
    rows = decision_ledger.get("rows") or []
    if not rows:
        return {}
    n = now or datetime.now(timezone.utc)
    cutoff = n - timedelta(hours=LEDGER_LOOKBACK_HRS)
    opens: Dict[str, int] = {}
    closes: Dict[str, int] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        ts = _parse_iso(r.get("ts"))
        if ts and ts < cutoff:
            continue
        cat = r.get("category") or ""
        tkr = (r.get("ticker") or "").upper()
        if not tkr:
            continue
        sec = sector_lookup.get(tkr) or "Unknown"
        if cat in _DEPLOY_CATEGORIES:
            opens[sec] = opens.get(sec, 0) + 1
        elif cat in _EXIT_CATEGORIES:
            closes[sec] = closes.get(sec, 0) + 1
    if not opens and not closes:
        return {}
    sectors = set(list(opens.keys()) + list(closes.keys()))
    out: Dict[str, float] = {}
    for s in sectors:
        o = opens.get(s, 0)
        c = closes.get(s, 0)
        total = o + c
        if total <= 0:
            continue
        # Net flow normalised by total flow → [-1, +1].
        out[s] = _clamp((o - c) / float(total), -1.0, 1.0)
    return out


# ─── Composite ────────────────────────────────────────────────────────

def compute_sector_rotation(
    narrative_payload: Optional[Dict[str, Any]] = None,
    contexts_by_ticker: Optional[Dict[str, Any]] = None,
    sector_lookup: Optional[Dict[str, str]] = None,
    decision_ledger: Optional[Dict[str, Any]] = None,
    prior_state: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Pure function: compute the per-sector flow scorecard.

    `prior_state` is the previous cycle's output; used only to detect
    "accelerating" tags by comparing flow_score deltas.
    """
    contexts_by_ticker = contexts_by_ticker or {}
    sector_lookup = sector_lookup or {}
    n_now = now or datetime.now(timezone.utc)

    narrative_pressure = ((narrative_payload or {}).get("sector_pressure") or {})
    rel_strength = _relative_strength_by_sector(contexts_by_ticker, sector_lookup)
    cap_momentum = _capital_momentum_by_sector(decision_ledger, sector_lookup,
                                                 now=n_now)

    sectors = set(narrative_pressure.keys()) | set(rel_strength.keys()) | set(cap_momentum.keys())
    # Always include a stable base set so the dashboard has consistent rows.
    sectors |= {"Technology", "Energy", "Industrials", "Health Care",
                "Financials", "Consumer Discretionary", "Consumer Staples",
                "Communication Services", "Real Estate", "Utilities",
                "Materials"}

    prior_sectors = ((prior_state or {}).get("sectors") or {}) if isinstance(prior_state, dict) else {}

    out_sectors: Dict[str, Dict[str, Any]] = {}
    for sec in sectors:
        np = _safe_f(narrative_pressure.get(sec, 0.0))
        rs = _safe_f(rel_strength.get(sec, 0.0))
        cm = _safe_f(cap_momentum.get(sec, 0.0))
        flow_score = (
            W_NARRATIVE     * np
            + W_REL_STRENGTH * rs
            + W_CAPITAL_MOM  * cm
        )
        flow_score = round(_clamp(flow_score, -1.0, 1.0), 4)

        # Tagging
        prior_score = _safe_f((prior_sectors.get(sec) or {}).get("flow_score"))
        delta = flow_score - prior_score
        if flow_score >= TAG_STRONG_THRESHOLD:
            if delta >= TAG_ACCEL_DELTA:
                tag = "accelerating"
            else:
                tag = "strengthening"
        elif flow_score <= TAG_WEAK_THRESHOLD:
            if delta <= -TAG_ACCEL_DELTA:
                tag = "deteriorating"
            else:
                tag = "weakening"
        else:
            tag = "neutral"

        # Lift multiplier: convert flow_score into a 0.75..1.30 multiplier.
        # +1.0 → 1.30, 0.0 → 1.0, -1.0 → 0.75.
        if flow_score >= 0:
            lift = 1.0 + flow_score * (LIFT_MAX - 1.0)
        else:
            lift = 1.0 + flow_score * (1.0 - LIFT_MIN)
        lift = round(_clamp(lift, LIFT_MIN, LIFT_MAX), 4)

        # Rationale
        rb: List[str] = []
        if abs(np) >= 0.2:
            rb.append(f"narrative {np:+.2f}")
        if abs(rs) >= 0.2:
            rb.append(f"5d strength {rs:+.2f}")
        if abs(cm) >= 0.2:
            rb.append(f"capital flow {cm:+.2f}")
        rationale = " · ".join(rb) if rb else "no dominant signal"

        out_sectors[sec] = {
            "flow_score":          flow_score,
            "tag":                 tag,
            "rotation_lift":       lift,
            "narrative_pressure":  round(np, 4),
            "relative_strength":   round(rs, 4),
            "capital_momentum":    round(cm, 4),
            "delta_vs_prior":      round(delta, 4),
            "rationale":           rationale,
        }

    # Top rotation pairs: strongest negative → strongest positive.
    sorted_pairs = sorted(out_sectors.items(),
                            key=lambda kv: kv[1]["flow_score"])
    weakest = [s for s, v in sorted_pairs[:3] if v["flow_score"] <= TAG_WEAK_THRESHOLD]
    strongest = [s for s, v in sorted_pairs[-3:] if v["flow_score"] >= TAG_STRONG_THRESHOLD][::-1]

    top_pairs: List[Dict[str, Any]] = []
    for src in weakest:
        for dst in strongest:
            if src == dst:
                continue
            strength = round(out_sectors[dst]["flow_score"]
                              - out_sectors[src]["flow_score"], 4)
            if strength <= 0:
                continue
            top_pairs.append({
                "from":       src,
                "to":         dst,
                "strength":   strength,
                "rationale":  f"{src} {out_sectors[src]['flow_score']:+.2f} "
                                 f"→ {dst} {out_sectors[dst]['flow_score']:+.2f}",
            })
    top_pairs = sorted(top_pairs, key=lambda d: d["strength"], reverse=True)[:5]

    # Headline rationale
    strongest_name = strongest[0] if strongest else None
    weakest_name   = weakest[0]   if weakest   else None
    if strongest_name and weakest_name:
        rationale = (f"{strongest_name} "
                      f"({out_sectors[strongest_name]['tag']}) "
                      f"vs {weakest_name} "
                      f"({out_sectors[weakest_name]['tag']})")
    elif strongest_name:
        rationale = (f"{strongest_name} "
                      f"({out_sectors[strongest_name]['tag']}); "
                      f"no clear weak sector")
    elif weakest_name:
        rationale = (f"{weakest_name} "
                      f"({out_sectors[weakest_name]['tag']}); "
                      f"no clear strong sector")
    else:
        rationale = "no dominant rotation"

    return {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "sectors":      out_sectors,
        "top_pairs":    top_pairs,
        "rationale":    rationale,
    }


def write_sector_rotation(
    data_dir: Path,
    narrative_payload: Optional[Dict[str, Any]] = None,
    contexts_by_ticker: Optional[Dict[str, Any]] = None,
    sector_lookup: Optional[Dict[str, str]] = None,
    decision_ledger: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute + persist docs/data/sector_rotation.json."""
    prior = _load_json(data_dir / FILENAME) or {}
    if decision_ledger is None:
        decision_ledger = _load_json(data_dir / "decision_ledger.json") or {}
    payload = compute_sector_rotation(
        narrative_payload=narrative_payload,
        contexts_by_ticker=contexts_by_ticker,
        sector_lookup=sector_lookup,
        decision_ledger=decision_ledger,
        prior_state=prior, now=now,
    )
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[sector_rotation] write failed: {e}")
    return payload


def load_sector_rotation(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "sectors": {}, "top_pairs": [],
             "rationale": "no sector rotation file"}


def rotation_lift_for_ticker(
    rotation: Dict[str, Any],
    ticker_sector: Optional[str],
) -> float:
    """Return the rotation_lift multiplier for a ticker's sector.
    Safe default 1.0 when sector unknown."""
    if not ticker_sector:
        return 1.0
    sectors = (rotation or {}).get("sectors") or {}
    info = sectors.get(ticker_sector) or {}
    try:
        v = float(info.get("rotation_lift", 1.0) or 1.0)
        return _clamp(v, LIFT_MIN, LIFT_MAX)
    except Exception:
        return 1.0


__all__ = [
    "VERSION", "LIFT_MIN", "LIFT_MAX",
    "compute_sector_rotation", "write_sector_rotation",
    "load_sector_rotation", "rotation_lift_for_ticker",
]
