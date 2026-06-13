"""silmaril.learning.cross_agent_learning — Alpha 6.0 collective learning.

What it does
────────────
The master directive: "make sure all learning is going into all agents."

Today, each agent has its own:
  - beliefs (agent_beliefs.json)
  - evolution card (agent_evolution_cards.json)
  - portfolio (agent_portfolios.json)

But there's no propagation: if AEGIS learns that energy is overbought
during high VIX, that insight stays inside AEGIS. This module computes
**cross-agent transfer signals** so insights diffuse:

1. **Regime consensus posterior** — aggregate top-quintile agents'
   posterior in each regime → publish as a "regime confidence" signal
   any agent can read to scale conviction.

2. **Sector specialization map** — identifies which agent has the
   strongest evidence base for each sector. Agents without that
   evidence implicitly defer in close votes.

3. **Setup-archetype transfer** — when an agent has a strong record
   on a setup archetype (GAP_AND_GO, MOMENTUM_BREAKOUT, etc.), other
   agents inherit a conviction lift on the same archetype.

4. **Time-of-day shared learning** — when one agent's 09:30-10:00 ET
   bucket is weak, all agents see the dampener.

Output (docs/data/cross_agent_learning.json)
────────────────────────────────────────────
{
  "version": "6.0", "generated_at": "...",
  "regime_consensus_posteriors": {
     "RISK_ON":  {"mean": 0.62, "n_strong_agents": 8, "lift": 1.08},
     "RISK_OFF": {"mean": 0.51, "n_strong_agents": 3, "lift": 0.96},
     ...
  },
  "sector_specialists": {
     "Energy":      "BARON",
     "Technology":  "ZENITH",
     "Crypto":      "CRYPTOBRO",
     "Real Estate": null,
     ...
  },
  "archetype_transfer_lifts": {
     "GAP_AND_GO": 1.05, "BREAKOUT_CONTINUATION": 1.03, ...
  },
  "time_of_day_dampeners": {
     "MARKET_OPEN":      0.92,
     "MID_MORNING":      1.00, ...
  }
}

The conviction-multiplier pipeline in cli.py already consumes
agent-level multipliers; this sidecar's outputs feed a NEW multiplier
that scales every agent's conviction by the cross-agent learning lift
for their setup + sector + regime context.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION  = "6.0"
FILENAME = "cross_agent_learning.json"

# Lift bounds — keep multipliers conservative to avoid runaway feedback.
LIFT_MIN, LIFT_MAX = 0.88, 1.12

# Min evidence to count as a "strong agent" for a regime
STRONG_REGIME_N = 20

# Min evidence + win rate threshold for sector specialization
SPECIALIST_N = 25
SPECIALIST_MIN_WR = 0.55


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


def _clamp(v: float, lo: float = LIFT_MIN, hi: float = LIFT_MAX) -> float:
    return max(lo, min(hi, v))


# ── Component 1: regime consensus posterior ──────────────────────────

def compute_regime_consensus(
    beliefs: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """For each market regime, average the top-quintile posterior means.

    A regime where many agents have strong, similar evidence produces
    a higher 'lift' for that regime's calls in subsequent cycles.
    """
    if not isinstance(beliefs, dict):
        return {}
    # beliefs structure: { agent: { regime: {alpha, beta, n} } }
    by_regime: Dict[str, List[Tuple[float, int]]] = {}
    for agent, regimes in (beliefs or {}).items():
        if not isinstance(regimes, dict):
            continue
        for regime, v in regimes.items():
            if not isinstance(v, dict):
                continue
            n = int(v.get("n") or 0)
            a = float(v.get("alpha") or 1)
            b = float(v.get("beta") or 1)
            if (a + b) <= 0 or n < STRONG_REGIME_N:
                continue
            mean = a / (a + b)
            by_regime.setdefault(regime, []).append((mean, n))

    out: Dict[str, Dict[str, Any]] = {}
    for regime, lst in by_regime.items():
        lst.sort(key=lambda x: -x[0])
        top = lst[:max(1, len(lst) // 4)]
        if not top:
            continue
        w_sum = sum(x[1] for x in top) or 1
        avg = sum(x[0] * x[1] for x in top) / w_sum
        # Map 0.5 → 1.00, 0.60 → 1.08, 0.40 → 0.92 (linear, clamped)
        lift = _clamp(1.0 + (avg - 0.50) * 0.80)
        out[regime] = {
            "mean":             round(avg, 4),
            "n_strong_agents":  len(top),
            "lift":             round(lift, 4),
        }
    return out


# ── Component 2: sector specialists ──────────────────────────────────

def compute_sector_specialists(
    scoring_raw: Dict[str, Any],
    agent_sectors_hint: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Optional[str]]:
    """Identify the single best agent for each sector by realized win rate.

    Reads scoring.json's by_agent rollup. Returns None for sectors with
    no qualified specialist.
    """
    if not isinstance(scoring_raw, dict):
        return {}
    by_agent = scoring_raw.get("by_agent") or {}
    by_sector: Dict[str, List[Tuple[str, float, int]]] = {}
    for agent, stats in by_agent.items():
        if not isinstance(stats, dict):
            continue
        per_sec = stats.get("by_sector") or {}
        for sec, s in per_sec.items():
            n = int((s or {}).get("n") or 0)
            wr = _safe_f((s or {}).get("win_rate"))
            if n < SPECIALIST_N or wr < SPECIALIST_MIN_WR:
                continue
            by_sector.setdefault(sec, []).append((agent, wr, n))
    out: Dict[str, Optional[str]] = {}
    for sec, lst in by_sector.items():
        lst.sort(key=lambda x: (-x[1], -x[2]))
        out[sec] = lst[0][0] if lst else None
    return out


# ── Component 3: archetype transfer lifts ────────────────────────────

def compute_archetype_lifts(
    expectancy_lab: Dict[str, Any],
) -> Dict[str, float]:
    """Each setup archetype's lift comes from its empirical expectancy.

    expectancy_lab.buckets is { "ARCHETYPE::SECTOR::REGIME": {n, wr, avg_pl} }
    We collapse to per-archetype averages weighted by n.
    """
    if not isinstance(expectancy_lab, dict):
        return {}
    buckets = expectancy_lab.get("buckets") or {}
    per_arch: Dict[str, Tuple[float, int]] = {}
    for key, b in buckets.items():
        if not isinstance(b, dict):
            continue
        n = int(b.get("n") or 0)
        wr = _safe_f(b.get("win_rate"), 0.5)
        if n < 10:
            continue
        arch = (key.split("::")[0] or "").strip()
        if not arch:
            continue
        prev_wr, prev_n = per_arch.get(arch, (0.0, 0))
        new_n = prev_n + n
        new_wr = (prev_wr * prev_n + wr * n) / new_n if new_n else wr
        per_arch[arch] = (new_wr, new_n)
    out: Dict[str, float] = {}
    for arch, (wr, n) in per_arch.items():
        # 0.5 wr → 1.00; 0.65 → 1.10; 0.35 → 0.90
        lift = _clamp(1.0 + (wr - 0.50) * 0.70)
        out[arch] = round(lift, 4)
    return out


# ── Component 4: time-of-day cross-agent dampener ────────────────────

def compute_tod_dampeners(
    tod_perf: Dict[str, Any],
) -> Dict[str, float]:
    """Aggregate per-bucket win rates across agents → system-wide dampener."""
    if not isinstance(tod_perf, dict):
        return {}
    # Schema: { agent: { bucket: {wins, losses} } }
    bucket_totals: Dict[str, Tuple[int, int]] = {}
    for agent, buckets in tod_perf.items():
        if not isinstance(buckets, dict):
            continue
        for bucket, v in buckets.items():
            if not isinstance(v, dict):
                continue
            w = int(v.get("wins") or 0)
            l = int(v.get("losses") or 0)
            if w + l < 5:
                continue
            pw, pl = bucket_totals.get(bucket, (0, 0))
            bucket_totals[bucket] = (pw + w, pl + l)
    out: Dict[str, float] = {}
    for bucket, (w, l) in bucket_totals.items():
        n = w + l
        if n < 20:
            continue
        wr = w / n
        out[bucket] = round(_clamp(1.0 + (wr - 0.50) * 0.50), 4)
    return out


# ── Compose conviction lift for one verdict ──────────────────────────

def cross_agent_lift_for(
    *,
    agent: str,
    regime: str,
    sector: Optional[str],
    archetype: Optional[str],
    tod_bucket: Optional[str],
    payload: Dict[str, Any],
) -> Tuple[float, str]:
    """Return (multiplier, rationale) to apply to one verdict's conviction.

    The four components multiply (clamped to [LIFT_MIN, LIFT_MAX] overall).
    """
    bits: List[str] = []
    m = 1.0
    rc = (payload.get("regime_consensus_posteriors") or {}).get(regime)
    if rc:
        m *= _safe_f(rc.get("lift"), 1.0)
        bits.append(f"regime {regime}={_safe_f(rc.get('lift'),1.0):.2f}")
    spec = (payload.get("sector_specialists") or {}).get(sector or "")
    if spec and agent and spec.upper() != agent.upper():
        m *= 0.98     # tiny dampener: a specialist exists and it's not you
        bits.append(f"defer to {spec}")
    al = (payload.get("archetype_transfer_lifts") or {}).get(archetype or "")
    if al:
        m *= _safe_f(al, 1.0)
        bits.append(f"arch {archetype}={_safe_f(al,1.0):.2f}")
    tl = (payload.get("time_of_day_dampeners") or {}).get(tod_bucket or "")
    if tl:
        m *= _safe_f(tl, 1.0)
        bits.append(f"TOD {tod_bucket}={_safe_f(tl,1.0):.2f}")
    return (_clamp(m), " · ".join(bits) or "no signal")


# ── Public build entry ───────────────────────────────────────────────

def build_cross_agent_learning(
    data_dir: Path,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute + persist cross-agent learning rollup."""
    n_now = now or datetime.now(timezone.utc)

    beliefs        = _load_json(data_dir / "agent_beliefs.json") or {}
    scoring_raw    = _load_json(data_dir / "scoring.json") or {}
    expectancy_lab = _load_json(data_dir / "expectancy_lab.json") or {}
    tod_perf       = _load_json(data_dir / "time_of_day_performance.json") or {}

    regime_posteriors = compute_regime_consensus(beliefs)
    sector_specialists = compute_sector_specialists(scoring_raw)
    archetype_lifts = compute_archetype_lifts(expectancy_lab)
    tod_dampeners = compute_tod_dampeners(tod_perf)

    summary = {
        "regimes_scored":     len(regime_posteriors),
        "sector_specialists": len([v for v in sector_specialists.values() if v]),
        "archetype_lifts":    len(archetype_lifts),
        "tod_buckets":        len(tod_dampeners),
    }

    bits: List[str] = []
    if regime_posteriors:
        bits.append(f"{len(regime_posteriors)} regimes scored")
    if sector_specialists:
        bits.append(f"{summary['sector_specialists']} specialists")
    if archetype_lifts:
        bits.append(f"{len(archetype_lifts)} archetype lifts")

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "regime_consensus_posteriors": regime_posteriors,
        "sector_specialists":          sector_specialists,
        "archetype_transfer_lifts":    archetype_lifts,
        "time_of_day_dampeners":       tod_dampeners,
        "summary":                     summary,
        "rationale":                   " · ".join(bits) or "insufficient evidence",
        "config": {
            "lift_min":          LIFT_MIN,
            "lift_max":          LIFT_MAX,
            "strong_regime_n":   STRONG_REGIME_N,
            "specialist_n":      SPECIALIST_N,
            "specialist_min_wr": SPECIALIST_MIN_WR,
        },
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[cross_agent_learning] write failed: {e}")
    return payload


def load_cross_agent_learning(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION,
             "regime_consensus_posteriors": {},
             "sector_specialists": {},
             "archetype_transfer_lifts": {},
             "time_of_day_dampeners": {}}


__all__ = [
    "VERSION", "LIFT_MIN", "LIFT_MAX",
    "compute_regime_consensus", "compute_sector_specialists",
    "compute_archetype_lifts", "compute_tod_dampeners",
    "cross_agent_lift_for", "build_cross_agent_learning",
    "load_cross_agent_learning",
]
