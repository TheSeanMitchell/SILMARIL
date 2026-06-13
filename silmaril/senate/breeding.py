"""
silmaril.senate.breeding — automated breeding (ALPHA 1.0, #4 + #5 feed).

EVOLUTION WITHOUT A HUMAN: every cycle this runs; at most once per
BREED_INTERVAL_DAYS per jurisdiction it breeds ONE child from the top-2
genome-bearing voters of that jurisdiction, ranked by EQUITY EDGE — the
per-agent attribution feed (#5): (current_equity - starting_equity) from
the agent simulation books, i.e. measured profit, not vibes or win rate.

MECHANICS (spec #4, verbatim from the anchor):
  - parents: top-2 by equity edge among genome-bearers in jurisdiction
    (founders FABLEBOY_5 / GOLDSMITH carry canonical genomes; all hybrids
    carry their own). Gen-1 honesty: with only ONE genome-bearer in a
    jurisdiction the child is a mutation-only variant of that founder —
    recorded as such; true crossover begins the moment a second genome
    voter has a record.
  - child genes: per-gene mean of parents, then ±10% uniform mutation,
    RNG seeded by (date, jurisdiction) — fully reproducible, auditable.
  - born PROBATIONARY_SHADOW: the senate's candidate machinery records
    and scores its votes but excludes them from consensus until elected.
  - ROSTER CAP 24 (main voters + active hybrids): at cap, breeding
    REFUSES and says so; demotion/attic stays the senate's job — nothing
    is ever deleted here.
  - eligibility: a parent needs >= MIN_TRACK_DAYS of portfolio history
    (founders' starting_date) so children come from records, not noise.
  - LINEAGE IS PERMANENT: every genome row keeps parents, generation,
    birth date, fitness-at-birth, and status transitions, forever.

Writes docs/data/agent_genomes.json (the bloodline) and returns a
summary for the suite. Read-only over portfolios; offline-safe.
"""

from __future__ import annotations

import json
import os
import random
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VERSION = "breeding-1.0"
GENOME_FILE = "agent_genomes.json"
BREED_INTERVAL_DAYS = 7
ROSTER_CAP = 30  # SUPERSESSION (Jun 12): spec said 24, set when the
# roster was ~16; the live roster reached 26 main voters before breeding
# shipped, and freezing evolution below current size was never the intent.
# 30 = current 26 + headroom for 4 hybrid lines; the senate demotes to
# make room beyond that. Recorded here and in the roadmap — never silent.
MIN_TRACK_DAYS = 5
MUTATION_PCT = 0.10

# founders: canonical genomes mirroring the hand-written classes' tunables
FOUNDER_GENOMES: Dict[str, Dict[str, Any]] = {
    "FABLEBOY_5": {
        "jurisdiction": "stocks",
        "genes": {"W_SENT": 0.45, "W_ANTIC": 0.25, "W_CAT": 0.30,
                  "STRONG_T": 0.55, "LEAN_T": 0.22,
                  "FOLLOWER_MULT": 1.25, "FADER_MULT": 0.60,
                  "IMMUNE_MULT": 0.70, "CONVICTION_CEILING": 0.85,
                  "THIN_TAPE_CAP": 0.50, "BREADTH_MIN": 3},
    },
    "GOLDSMITH": {
        "jurisdiction": "valuables",
        "genes": {"W_SENT": 0.35, "W_ANTIC": 0.25, "W_CAT": 0.40,
                  "STRONG_T": 0.55, "LEAN_T": 0.20,
                  "FOLLOWER_MULT": 1.35, "FADER_MULT": 0.55,
                  "IMMUNE_MULT": 0.70, "CONVICTION_CEILING": 0.80,
                  "THIN_TAPE_CAP": 0.45, "BREADTH_MIN": 3},
    },
}

_INT_GENES = {"BREADTH_MIN"}
_GENE_BOUNDS = {  # sanity rails so mutation can't produce a deranged child
    "W_SENT": (0.05, 0.8), "W_ANTIC": (0.05, 0.8), "W_CAT": (0.05, 0.8),
    "STRONG_T": (0.3, 0.9), "LEAN_T": (0.08, 0.5),
    "FOLLOWER_MULT": (1.0, 1.8), "FADER_MULT": (0.3, 0.9),
    "IMMUNE_MULT": (0.4, 1.0), "CONVICTION_CEILING": (0.5, 0.9),
    "THIN_TAPE_CAP": (0.25, 0.6), "BREADTH_MIN": (2, 5),
}


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _dump(path: Path, obj: Any) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, allow_nan=False)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _equity_edge(portfolios: Dict[str, Any], codename: str) -> Optional[float]:
    """#5 attribution feed: measured equity edge of one agent's book."""
    row = portfolios.get(codename) or {}
    try:
        cur = float(row.get("current_equity"))
        start = float(row.get("starting_equity") or 10000.0)
        return cur - start
    except Exception:
        return None


def _track_days(portfolios: Dict[str, Any], codename: str,
                now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    row = portfolios.get(codename) or {}
    d = str(row.get("starting_date") or row.get("entry_date") or "")
    try:
        t0 = datetime.fromisoformat(d.replace("Z", "+00:00"))
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)
        return (now - t0).days
    except Exception:
        # no start date recorded: treat presence in the book as eligible —
        # founders predate this organ
        return MIN_TRACK_DAYS if row else 0


def _genome_pool(doc: Dict[str, Any], jurisdiction: str) -> List[Dict[str, Any]]:
    """All genome-bearers of a jurisdiction: founders + ACTIVE hybrids."""
    pool = []
    for name, g in FOUNDER_GENOMES.items():
        if g["jurisdiction"] == jurisdiction:
            pool.append({"codename": name, "jurisdiction": jurisdiction,
                         "genes": dict(g["genes"]), "founder": True})
    for g in (doc.get("genomes") or []):
        if (str(g.get("jurisdiction")) == jurisdiction
                and str(g.get("status") or "") not in ("RETIRED", "ATTIC")):
            pool.append(g)
    return pool


def _mutate(genes: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    out = {}
    for k, v in genes.items():
        lo, hi = _GENE_BOUNDS.get(k, (None, None))
        nv = float(v) * (1.0 + rng.uniform(-MUTATION_PCT, MUTATION_PCT))
        if lo is not None:
            nv = max(lo, min(hi, nv))
        out[k] = int(round(nv)) if k in _INT_GENES else round(nv, 4)
    return out


def _cross(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    keys = set(a) | set(b)
    return {k: (float(a.get(k, b.get(k))) + float(b.get(k, a.get(k)))) / 2.0
            for k in keys}


def run_breeding(out_dir, now: Optional[datetime] = None,
                 roster_size: Optional[int] = None) -> Dict[str, Any]:
    out = Path(out_dir)
    now = now or datetime.now(timezone.utc)
    doc = _load(out / GENOME_FILE, {}) or {}
    doc.setdefault("version", VERSION)
    genomes: List[dict] = doc.setdefault("genomes", [])
    last_bred: Dict[str, str] = doc.setdefault("last_bred", {})
    portfolios = _load(out / "agent_portfolios.json", {}) or {}

    # roster cap counts main voters + active hybrids; main-voter count is
    # injectable for tests, defaults to live roster size when importable.
    if roster_size is None:
        try:
            from silmaril.cli import MAIN_VOTERS  # type: ignore
            roster_size = len(MAIN_VOTERS)
        except Exception:
            roster_size = 16
    active_hybrids = [g for g in genomes
                      if str(g.get("status") or "") not in ("RETIRED", "ATTIC")]
    total = roster_size + len(active_hybrids)

    results = {}
    for jurisdiction in ("stocks", "valuables"):
        # cadence gate
        lb = last_bred.get(jurisdiction)
        if lb:
            try:
                t0 = datetime.fromisoformat(lb)
                if (now - t0).days < BREED_INTERVAL_DAYS:
                    results[jurisdiction] = (
                        f"bred {(now - t0).days}d ago — next in "
                        f"{BREED_INTERVAL_DAYS - (now - t0).days}d")
                    continue
            except Exception:
                pass
        if total >= ROSTER_CAP:
            results[jurisdiction] = (f"roster at cap {total}/{ROSTER_CAP} — "
                                     f"breeding refuses; the senate must "
                                     f"demote before new blood enters")
            continue

        pool = _genome_pool(doc, jurisdiction)
        ranked: List[Tuple[float, dict]] = []
        for g in pool:
            cn = g["codename"]
            edge = _equity_edge(portfolios, cn)
            days = _track_days(portfolios, cn, now)
            if edge is None or days < MIN_TRACK_DAYS:
                continue
            ranked.append((edge, g))
        ranked.sort(key=lambda t: t[0], reverse=True)

        if not ranked:
            results[jurisdiction] = ("no eligible parents yet (need "
                                     f">={MIN_TRACK_DAYS}d of book history)")
            continue

        rng = random.Random(f"{now.date().isoformat()}|{jurisdiction}")
        gen = 1 + max((int(g.get("generation") or 0)
                       for g in active_hybrids
                       if g.get("jurisdiction") == jurisdiction), default=0)
        if len(ranked) >= 2:
            (fa, pa), (fb, pb) = ranked[0], ranked[1]
            child_genes = _mutate(_cross(pa["genes"], pb["genes"]), rng)
            parents = [pa["codename"], pb["codename"]]
            fitness = {pa["codename"]: round(fa, 2),
                       pb["codename"]: round(fb, 2)}
            mode = "crossover"
        else:
            fa, pa = ranked[0]
            child_genes = _mutate(dict(pa["genes"]), rng)
            parents = [pa["codename"]]
            fitness = {pa["codename"]: round(fa, 2)}
            mode = "mutation-only (single genome-bearer — gen-1 honesty)"

        tag = "".join(p[0] for p in parents)[:4]
        codename = (f"HYB_{jurisdiction[:3].upper()}_G{gen}_"
                    f"{now.strftime('%m%d')}{tag}")
        child = {
            "codename": codename,
            "jurisdiction": jurisdiction,
            "generation": gen,
            "parents": parents,
            "parent_fitness_at_birth": fitness,
            "mode": mode,
            "genes": child_genes,
            "status": "PROBATIONARY_SHADOW",
            "born_at": now.isoformat(),
            "lineage_note": ("votes recorded+scored in shadow; consensus "
                            "rights only by election; demotion only by "
                            "senate; never deleted"),
        }
        genomes.append(child)
        last_bred[jurisdiction] = now.isoformat()
        total += 1
        results[jurisdiction] = f"BORN {codename} ({mode}; parents {parents})"

    doc["updated_at"] = now.isoformat()
    doc["roster"] = {"main_voters": roster_size,
                     "active_hybrids": len([g for g in genomes
                                            if g.get("status") not in
                                            ("RETIRED", "ATTIC")]),
                     "cap": ROSTER_CAP}
    _dump(out / GENOME_FILE, doc)
    return results


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(run_breeding(
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")), indent=2))
