"""
silmaril.agents.hybrid_voter — genome-driven offspring (ALPHA 1.0, #4).

Offspring are GENOMES, not generated code. FABLEBOY_5 and GOLDSMITH are
the same word-led judge with different constants; that judge is the
species' shared body, and a genome is the heritable parameter set:

  weights      W_SENT / W_ANTIC / W_CAT      (blend of the word layers)
  thresholds   STRONG_T / LEAN_T             (signal mapping)
  mults        follower / fader / immune     (personality shaping)
  ceilings     conviction_ceiling, thin_tape_cap, breadth_min

A HybridVoter instantiates from a genome row in docs/data/
agent_genomes.json. The senate's existing shadow machinery treats every
hybrid as a CANDIDATE: votes recorded + scored, excluded from consensus,
until elections promote it. Fully deterministic and explainable — the
genome rides in every verdict's factors, so any human or future session
can read exactly why a child voted as it did. No code generation, no
LLMs, nothing synthetic in the decision path: genomes are CONFIG bred
from measured fitness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .base import Agent, AssetContext, Signal, Verdict

GENOME_FILE = "agent_genomes.json"

_JURISDICTION_CLASSES = {
    "stocks": ("equity", "etf"),
    "valuables": ("crypto", "token", "commodity", "commodities",
                  "fx", "macro", "bonds/rates"),
}

DEFAULT_GENES = {
    "W_SENT": 0.45, "W_ANTIC": 0.25, "W_CAT": 0.30,
    "STRONG_T": 0.55, "LEAN_T": 0.22,
    "FOLLOWER_MULT": 1.25, "FADER_MULT": 0.60, "IMMUNE_MULT": 0.70,
    "CONVICTION_CEILING": 0.85, "THIN_TAPE_CAP": 0.50, "BREADTH_MIN": 3,
}


class HybridVoter(Agent):
    """One bred voter. Identity and behavior come entirely from genome."""

    def __init__(self, genome: Dict[str, Any]):
        self.genome = dict(genome or {})
        g = self.genome
        self.codename = str(g.get("codename") or "HYBRID_UNNAMED")
        jur = str(g.get("jurisdiction") or "stocks")
        self.asset_classes = _JURISDICTION_CLASSES.get(
            jur, _JURISDICTION_CLASSES["stocks"])
        self.specialty = (f"Gen-{g.get('generation', '?')} word-genome "
                          f"hybrid · jurisdiction {jur} · parents "
                          f"{'+'.join(g.get('parents') or ['?'])}")
        self.temperament = ("Bred, not written: carries its parents' "
                            "constants with a measured mutation.")
        self.inspiration = ("The senate's first automated bloodline — "
                            "evolution with receipts.")
        self.genes = {**DEFAULT_GENES, **(g.get("genes") or {})}

    # the species' shared judge body (FABLEBOY/GOLDSMITH template)
    def _judge(self, ctx: AssetContext) -> Verdict:
        G = self.genes
        n_art = int(ctx.article_count or 0)
        if n_art <= 0:
            return Verdict(agent=self.codename, ticker=ctx.ticker,
                           signal=Signal.ABSTAIN, conviction=0.0,
                           rationale="No headlines — the word genome has "
                                     "nothing to express.",
                           factors={"articles": 0,
                                    "genome": self.genome.get("codename")})

        sent = float(ctx.sentiment_score or 0.0)
        cat = ctx.news_catalyst
        cat_label = ctx.news_catalyst_label
        pers = ctx.news_personality

        antic = 0.0
        try:
            from ..analytics.sentiment import anticipation_score
            vals = [anticipation_score(str((h or {}).get("title") or ""))
                    for h in (ctx.recent_headlines or [])]
            vals = [v for v in vals if v]
            antic = sum(vals) / len(vals) if vals else 0.0
        except Exception:
            antic = 0.0

        if cat is not None:
            w = (G["W_SENT"] * sent + G["W_ANTIC"] * antic
                 + G["W_CAT"] * float(cat))
        else:
            tot = G["W_SENT"] + G["W_ANTIC"]
            w = ((G["W_SENT"] / tot) * sent
                 + (G["W_ANTIC"] / tot) * antic) if tot else 0.0

        note = ""
        if pers == "news-follower":
            w *= G["FOLLOWER_MULT"]
            note = "follower — genome rides it"
        elif pers == "news-fader":
            if cat is not None and cat > 0 and w > 0:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.HOLD, conviction=0.50,
                    rationale=(f"{cat_label or 'catalyst'} pop on a fader — "
                               f"inherited fade-trap reflex stands down."),
                    factors={"personality": pers,
                             "genome": self.codename,
                             "decision": "fade-trap avoided"})
            w *= G["FADER_MULT"]
            note = "fader — genome discounts"
        elif pers == "news-immune":
            w *= G["IMMUNE_MULT"]
            note = "immune — genome shrugs"

        breadth = int(G.get("BREADTH_MIN", 3))
        decisive = (cat is not None) or (abs(antic) >= 0.5)
        if w >= G["STRONG_T"] and n_art >= breadth and decisive:
            sig = Signal.STRONG_BUY
        elif w >= G["LEAN_T"]:
            sig = Signal.BUY
        elif w <= -G["STRONG_T"] and n_art >= breadth and decisive:
            sig = Signal.STRONG_SELL
        elif w <= -G["LEAN_T"]:
            sig = Signal.SELL
        else:
            sig = Signal.HOLD

        if sig == Signal.HOLD:
            conviction = 0.30
        else:
            conviction = min(float(G["CONVICTION_CEILING"]),
                             0.28 + abs(w) * 0.7)
            if n_art < 2:
                conviction = min(conviction, float(G["THIN_TAPE_CAP"]))
                note = (note + "; " if note else "") + "thin-tape cap"

        return Verdict(
            agent=self.codename, ticker=ctx.ticker, signal=sig,
            conviction=round(conviction, 2),
            rationale=(f"genome blend {w:+.2f} ({n_art} arts)"
                       + (f"; catalyst: {cat_label}" if cat_label else "")
                       + (f"; {note}" if note else "") + "."),
            factors={"blended": round(w, 3), "articles": n_art,
                     "personality": pers, "genome": self.codename,
                     "genes": {k: round(v, 4) if isinstance(v, float) else v
                               for k, v in self.genes.items()},
                     "generation": self.genome.get("generation"),
                     "parents": self.genome.get("parents")},
            invalidation="Word signal flip or catalyst walk-back kills it.")


def load_hybrids(data_dir="docs/data") -> List[HybridVoter]:
    """Instantiate every ACTIVE (non-retired) hybrid from the genome file.
    Missing/corrupt file -> empty list; a bad row never breaks the roster."""
    try:
        doc = json.loads((Path(data_dir) / GENOME_FILE).read_text())
        rows = doc.get("genomes") or []
    except Exception:
        return []
    out: List[HybridVoter] = []
    for g in rows:
        try:
            if str(g.get("status") or "") in ("RETIRED", "ATTIC"):
                continue
            out.append(HybridVoter(g))
        except Exception as e:  # pragma: no cover
            print(f"[breeding] genome {g.get('codename')} failed to load: {e}")
    return out
