"""silmaril.learning.agent_evolution — Alpha 6.0 Pokémon-style offspring.

What it does
────────────
The master directive: "agent Pokémon style evolution offspring will be
occurring."

The existing `evolution_cards.py` tracks XP and levels per agent (cards
only grow). The existing `conclave.py` proposes ONE new candidate agent
SPEC for human review.

This module bridges the two by proposing **offspring** — new candidate
agents that inherit traits from TWO parent agents. The two parents are
selected by a deterministic compatibility scoring algorithm:

  PARENT_FITNESS  =  evolution_card.level × lifetime_win_rate
  PARENT_PAIR_COMPATIBILITY:
     same asset_class  → +1.0
     complementary regime expertise → +0.5
     distinct sectors (no overlap)  → +0.3
     similar conviction temperaments→ +0.2

The top-fitness eligible pair (level≥4, lifetime_calls≥200) produces an
offspring spec:

  Offspring asset_classes = union(parent_a, parent_b)
  Offspring inspiration   = "child of {parent_a} + {parent_b}"
  Offspring specialty     = blend of both specialties
  Offspring inherits:
     +5% conviction lift on regimes where BOTH parents have >0.55 mean
     +3% conviction lift on sectors where EITHER parent is specialist
     Born with parent_a's risk style + parent_b's entry quality

Cadence: runs on the 15th of each month inside the existing senate
workflow (alongside Conclave). Only produces SPECS — humans review and
manually instantiate. This is identical to Conclave's posture; the
difference is that Conclave proposes from GAPS, Evolution proposes from
COMPATIBILITY.

Output (docs/data/agent_evolution_offspring.json)
─────────────────────────────────────────────────
{
  "version": "6.0", "proposed_at": "...", "status": "PENDING_REVIEW",
  "lineage": {
     "parent_a": {"codename": "ZENITH",  "level": 7, "win_rate": 0.58},
     "parent_b": {"codename": "BARNACLE","level": 6, "win_rate": 0.61},
     "compatibility_score": 1.8
  },
  "offspring": {
     "proposed_codename":  "PHOENIX",
     "specialty":          "Energy-tech rotation specialist",
     "temperament":        "Patient on entries, aggressive on profit-take",
     "inherited_lifts": {
        "regimes":   {"RISK_ON": 1.05, "ROTATION": 1.05},
        "sectors":   {"Energy": 1.03, "Technology": 1.03},
        "archetypes":{"BREAKOUT_CONTINUATION": 1.04}
     },
     "starting_capital":   10000.0,
     "rationale": "PARENT_A=ZENITH(L7,58%) × PARENT_B=BARNACLE(L6,61%) — "
                     "complementary regime expertise, distinct sectors, "
                     "compatibility=1.8"
  }
}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION  = "6.0"
FILENAME = "agent_evolution_offspring.json"

MIN_PARENT_LEVEL    = 4
MIN_PARENT_CALLS    = 200
MIN_PARENT_WR       = 0.52


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


def _eligible_agents(
    cards: Dict[str, Any],
    scoring_raw: Dict[str, Any],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    by_agent = (scoring_raw or {}).get("by_agent") or {}
    for codename, card in (cards or {}).items():
        if not isinstance(card, dict):
            continue
        level = _level_for_xp(int(card.get("xp") or 0))
        if level < MIN_PARENT_LEVEL:
            continue
        calls = int(card.get("lifetime_calls") or 0)
        if calls < MIN_PARENT_CALLS:
            continue
        wins  = int(card.get("lifetime_wins") or 0)
        wr = (wins / calls) if calls else 0.0
        if wr < MIN_PARENT_WR:
            continue
        # Optional richer per-agent stats
        per = by_agent.get(codename) or {}
        out.append({
            "codename":            codename,
            "level":               level,
            "lifetime_calls":      calls,
            "lifetime_wins":       wins,
            "win_rate":            round(wr, 4),
            "best_win_streak":     int(card.get("best_win_streak") or 0),
            "achievements":        list(card.get("achievements_unlocked") or []),
            "by_regime":           per.get("by_regime") or {},
            "by_sector":           per.get("by_sector") or {},
            "rolling_30d":         _safe_f(per.get("rolling_30d_win_rate")),
        })
    return out


def _level_for_xp(xp: int) -> int:
    thresholds = [0, 100, 300, 700, 1500, 3000, 6000, 12000, 25000, 50000, 100000]
    for i, t in enumerate(thresholds):
        if xp < t:
            return max(1, i)
    return len(thresholds) + (xp - thresholds[-1]) // 50000


def _compatibility(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Score how well a pair would breed.

    Rules:
      - Strong sectors (where each agent shines) must not fully overlap → +0.3
      - Strong regimes (one strong in RISK_ON, other in RISK_OFF) → +0.5
      - Both have rolling > 0.55 → +0.5
      - Win-rate gap < 8 points → +0.2
    """
    score = 0.0
    bits: List[str] = []

    def _strong_keys(by: Dict[str, Any], min_n: int = 15, min_wr: float = 0.55) -> set:
        out = set()
        for k, v in (by or {}).items():
            n = int((v or {}).get("n") or 0)
            wr = _safe_f((v or {}).get("win_rate"))
            if n >= min_n and wr >= min_wr:
                out.add(k)
        return out

    a_sectors = _strong_keys(a.get("by_sector"))
    b_sectors = _strong_keys(b.get("by_sector"))
    a_regimes = _strong_keys(a.get("by_regime"))
    b_regimes = _strong_keys(b.get("by_regime"))

    if a_sectors and b_sectors:
        overlap = a_sectors & b_sectors
        diff = (a_sectors | b_sectors) - overlap
        if len(diff) >= 2 and len(overlap) <= 1:
            score += 0.3
            bits.append("distinct sectors")
    if a_regimes and b_regimes:
        if a_regimes != b_regimes and (a_regimes | b_regimes):
            score += 0.5
            bits.append("complementary regime expertise")
    if a["rolling_30d"] >= 0.55 and b["rolling_30d"] >= 0.55:
        score += 0.5
        bits.append("both hot 30d")
    if abs(a["win_rate"] - b["win_rate"]) <= 0.08:
        score += 0.2
        bits.append("similar caliber")
    # Add fitness-derived bonus to break ties: average level × wr
    fitness = (a["level"] + b["level"]) / 2.0 * ((a["win_rate"] + b["win_rate"]) / 2.0)
    score += fitness * 0.05
    return (round(score, 4), bits)


def _select_pair(agents: List[Dict[str, Any]]) -> Optional[Tuple[Dict, Dict, float, List[str]]]:
    if len(agents) < 2:
        return None
    best: Optional[Tuple[Dict, Dict, float, List[str]]] = None
    for i, a in enumerate(agents):
        for b in agents[i+1:]:
            sc, bits = _compatibility(a, b)
            if best is None or sc > best[2]:
                best = (a, b, sc, bits)
    if best and best[2] >= 0.5:
        return best
    return None


# Names pool for offspring suggestions (Roman/mythic flavour to match
# existing agent codenames).
_NAME_POOL = [
    "PHOENIX","AURELIA","ORACLE","RAVEN","HALO","SOLACE","KAIRO","NEMO",
    "ASTRA","CRYO","ECHO","FALCON","GALE","HALCYON","IBIS","JADE_II",
    "KOI","LUMEN","MERIDIAN","NOVA","OBELISK","PRISM","QUARTZ","RIVET",
    "SABLE","TALON_II","UMBRA","VESTA","WRAITH","XENON","YOMI","ZEPHYR",
]


def _propose_name(existing: List[str]) -> str:
    taken = {n.upper() for n in (existing or [])}
    for name in _NAME_POOL:
        if name not in taken:
            return name
    # Fall back to deterministic synth
    return f"CANDIDATE_OFFSPRING_{len(taken)+1}"


def propose_offspring(
    cards: Dict[str, Any],
    scoring_raw: Dict[str, Any],
    cross_agent: Optional[Dict[str, Any]] = None,
    existing_agent_names: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Pick top compatible pair → emit offspring spec. Returns None when
    no eligible pair exists."""
    eligible = _eligible_agents(cards, scoring_raw)
    if len(eligible) < 2:
        return None
    pair = _select_pair(eligible)
    if pair is None:
        return None
    a, b, score, bits = pair
    name = _propose_name((existing_agent_names or []) + [a["codename"], b["codename"]])

    # Inherited regime lifts: union of regimes either parent is strong in
    inherited_regimes: Dict[str, float] = {}
    rcp = (cross_agent or {}).get("regime_consensus_posteriors") or {}
    for parent in (a, b):
        for regime, info in (parent.get("by_regime") or {}).items():
            if int((info or {}).get("n") or 0) < 15:
                continue
            if _safe_f((info or {}).get("win_rate")) >= 0.55:
                base = _safe_f((rcp.get(regime) or {}).get("lift"), 1.0)
                inherited_regimes[regime] = round(min(1.10, max(1.02, base * 1.02)), 4)

    inherited_sectors: Dict[str, float] = {}
    specialists = (cross_agent or {}).get("sector_specialists") or {}
    for parent in (a, b):
        for sec, info in (parent.get("by_sector") or {}).items():
            if _safe_f((info or {}).get("win_rate")) >= 0.55 and \
                int((info or {}).get("n") or 0) >= 15:
                inherited_sectors[sec] = 1.03
        if specialists.get(parent.get("codename")):
            pass

    inherited_archetypes: Dict[str, float] = {}
    arch_lifts = (cross_agent or {}).get("archetype_transfer_lifts") or {}
    for arch, lift in arch_lifts.items():
        if _safe_f(lift, 1.0) > 1.02:
            inherited_archetypes[arch] = round(min(1.06, _safe_f(lift, 1.0)), 4)

    # Build specialty as a blend of parents' specialties (truncated)
    spec_a = a.get("codename","?")
    spec_b = b.get("codename","?")
    specialty_blend = f"Hybrid specialist — inherits {spec_a}'s pacing and {spec_b}'s timing"

    rationale = (
        f"PARENT_A={spec_a}(L{a['level']},{a['win_rate']*100:.0f}%) × "
        f"PARENT_B={spec_b}(L{b['level']},{b['win_rate']*100:.0f}%) — "
        + (", ".join(bits) if bits else "fitness blend")
        + f"; compatibility={score:.2f}"
    )

    return {
        "version":      VERSION,
        "proposed_at":  datetime.now(timezone.utc).isoformat(),
        "status":       "PENDING_REVIEW",
        "lineage": {
            "parent_a": {"codename": spec_a,
                         "level": a["level"],
                         "win_rate": a["win_rate"],
                         "lifetime_calls": a["lifetime_calls"]},
            "parent_b": {"codename": spec_b,
                         "level": b["level"],
                         "win_rate": b["win_rate"],
                         "lifetime_calls": b["lifetime_calls"]},
            "compatibility_score": score,
            "compatibility_reasons": bits,
        },
        "offspring": {
            "proposed_codename":  name,
            "specialty":          specialty_blend,
            "temperament":        ("Patient on entries (from " + spec_a + "), " +
                                       "aggressive on profit-take (from " + spec_b + ")"),
            "asset_classes":      ["equity", "etf"],
            "inherited_lifts": {
                "regimes":      inherited_regimes,
                "sectors":      inherited_sectors,
                "archetypes":   inherited_archetypes,
            },
            "starting_capital":   10_000.0,
            "rationale":          rationale,
        },
        "next_steps": (
            "Review the offspring spec. If approved, scaffold the agent at "
            f"silmaril/agents/{name.lower()}.py inheriting from Agent base, "
            "applying the inherited_lifts inside _judge(). Then add it to "
            "silmaril/senate/candidates.py CANDIDATE_REGISTRY."
        ),
    }


def write_offspring_proposal(
    data_dir: Path,
    cards: Dict[str, Any],
    scoring_raw: Dict[str, Any],
    cross_agent: Optional[Dict[str, Any]] = None,
    existing_agent_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    proposal = propose_offspring(cards, scoring_raw, cross_agent, existing_agent_names)
    out_path = data_dir / FILENAME
    if proposal is None:
        # Write a "no breeding" record so the dashboard knows we tried.
        proposal = {
            "version":      VERSION,
            "proposed_at":  datetime.now(timezone.utc).isoformat(),
            "status":       "NO_ELIGIBLE_PAIR",
            "rationale":    ("No agent pair currently meets breeding thresholds "
                                f"(level≥{MIN_PARENT_LEVEL}, calls≥{MIN_PARENT_CALLS}, "
                                f"win-rate≥{MIN_PARENT_WR:.0%}). Will re-evaluate next cycle."),
        }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(proposal, indent=2, default=str))
    except Exception as e:
        print(f"[agent_evolution] write failed: {e}")
    return proposal


def load_offspring_proposal(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "status": "NEVER_RUN"}


__all__ = [
    "VERSION", "MIN_PARENT_LEVEL", "MIN_PARENT_CALLS", "MIN_PARENT_WR",
    "propose_offspring", "write_offspring_proposal",
    "load_offspring_proposal",
]
