"""
silmaril.debate.arbiter — Consensus engine.

Restored class interface for cli.py. The original `Arbiter` class is
preserved here. Alpha 2.0 learning enhancements (Thompson sampling,
drift dampening) are applied externally in cli.py via
`_apply_conviction_multipliers` and `_recompute_consensus_in_place`,
which scale verdict convictions AFTER this arbiter runs and refresh
the consensus block. This keeps the arbiter focused on its core job:
collect verdicts, compute consensus, identify dissents, apply AEGIS veto.

Public surface:

    Arbiter(agents=[...], aegis_veto_enabled=True)
    arbiter.resolve(contexts) -> List[DebateResult]
    debate_result.to_dict() -> dict

Output dict shape (consumed by cli.py and the dashboard):
    {
        "ticker": str,
        "price": float,
        "consensus": {
            "signal": "STRONG_BUY"|"BUY"|"HOLD"|"SELL"|"STRONG_SELL",
            "score": float,            # weighted score in [-2, +2]
            "avg_conviction": float,   # avg conviction of DIRECTIONAL voters only
            "agreement_score": float,  # 0..1 — how aligned were agents
        },
        "verdicts": [{agent, signal, conviction, rationale}, ...],
        "aegis_veto": bool,
        "dissent_summary": str,
    }

CONVICTION BUG FIX (Alpha 2.0):
    The original `avg_conviction` averaged conviction across ALL non-ABSTAIN
    voters, including agents that voted HOLD. A HOLD vote has 0 directional
    signal — including its low conviction (0.0–0.3) in the average diluted
    the true conviction of agents that actually voted BUY or SELL.

    Example with 3 BUY at 0.65 + 7 HOLD at 0.20 + 15 ABSTAIN:
      Old: avg_conviction = (3*0.65 + 7*0.20) / 10 = 0.335  → below 0.45 Alpaca threshold
      New: avg_conviction = (3*0.65) / 3            = 0.65   → above 0.45, order fires

    The weighted score for the consensus SIGNAL is unchanged — HOLDs still
    contribute 0 to the numerator and their conviction to the denominator,
    correctly pulling the signal toward HOLD when enough agents are
    indecisive. Only the avg_conviction metric (used by Alpaca's threshold
    gate) changes: it now measures the conviction of agents who actually
    have a directional view.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


# Map signal strings to numeric scores for weighted consensus
SIGNAL_SCORE: Dict[str, float] = {
    "STRONG_BUY":  +2.0,
    "BUY":         +1.0,
    "HOLD":         0.0,
    "ABSTAIN":      0.0,
    "SELL":        -1.0,
    "STRONG_SELL": -2.0,
}

# Score thresholds for emitting a consensus signal
STRONG_BUY_THRESHOLD  = +1.20
BUY_THRESHOLD         = +0.40
SELL_THRESHOLD        = -0.40
STRONG_SELL_THRESHOLD = -1.20


def _signal_str(sig) -> str:
    """Coerce a signal (enum or string) into its string form."""
    if hasattr(sig, "value"):
        return str(sig.value)
    return str(sig)


@dataclass
class DebateResult:
    """One ticker's debate outcome. Serializes via to_dict()."""
    ticker: str
    price: Optional[float]
    consensus_signal: str
    consensus_score: float
    avg_conviction: float
    agreement_score: float
    verdicts: List[dict] = field(default_factory=list)
    aegis_veto: bool = False
    dissent_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "consensus": {
                "signal": self.consensus_signal,
                "score": round(self.consensus_score, 4),
                "avg_conviction": round(self.avg_conviction, 4),
                "agreement_score": round(self.agreement_score, 4),
            },
            "verdicts": list(self.verdicts),
            "aegis_veto": self.aegis_veto,
            "dissent_summary": self.dissent_summary,
        }


class Arbiter:
    """Collects verdicts from a panel of agents and emits consensus per asset.

    Parameters
    ----------
    agents : Iterable[Agent]
        The voting panel. Each agent must implement:
            applies_to(context) -> bool
            evaluate(context) -> Verdict   # Verdict has agent, signal, conviction, rationale
    aegis_veto_enabled : bool
        If True, an AEGIS verdict of SELL or STRONG_SELL with conviction
        >= 0.65 can downgrade a bullish consensus to HOLD. AEGIS is
        identified by codename == "AEGIS" or "GUARDIAN" (Alpha 2.0 rename).
    """

    AEGIS_NAMES = ("AEGIS", "GUARDIAN")
    AEGIS_VETO_MIN_CONVICTION = 0.65

    def __init__(self, agents: Iterable, aegis_veto_enabled: bool = True):
        self.agents = list(agents)
        self.aegis_veto_enabled = aegis_veto_enabled

    # ── Public entry point ──────────────────────────────────────
    def resolve(self, contexts) -> List[DebateResult]:
        """Run a debate on each context. Returns one DebateResult per context."""
        results: List[DebateResult] = []
        for ctx in contexts:
            results.append(self._resolve_one(ctx))
        return results

    # ── Per-asset debate ────────────────────────────────────────
    def _resolve_one(self, ctx) -> DebateResult:
        verdicts_raw = []
        for agent in self.agents:
            try:
                if not agent.applies_to(ctx):
                    continue
                v = agent.evaluate(ctx)
                if v is None:
                    continue
                verdicts_raw.append(v)
            except Exception:
                # An agent that crashes shouldn't take down the debate.
                continue

        # Normalize to the dict shape the rest of the system expects
        verdict_dicts: List[dict] = []
        for v in verdicts_raw:
            agent_name = getattr(v, "agent", None) or "UNKNOWN"
            sig = _signal_str(getattr(v, "signal", "HOLD"))
            conviction = float(getattr(v, "conviction", 0.0) or 0.0)
            rationale = str(getattr(v, "rationale", "") or "")
            verdict_dicts.append({
                "agent": agent_name,
                "signal": sig,
                "conviction": max(0.0, min(1.0, conviction)),
                "rationale": rationale,
            })

        # Compute weighted consensus
        cons_signal, cons_score, avg_conv, agreement = self._compute_consensus(verdict_dicts)

        # AEGIS / GUARDIAN veto check
        aegis_veto = False
        if self.aegis_veto_enabled:
            aegis_veto = self._maybe_apply_aegis_veto(verdict_dicts, cons_signal)
            if aegis_veto:
                # Downgrade bullish consensus to HOLD; halve the conviction
                cons_signal = "HOLD"
                cons_score = 0.0

        # Build a short dissent summary
        dissent_summary = self._summarize_dissent(verdict_dicts, cons_signal)

        return DebateResult(
            ticker=getattr(ctx, "ticker", "?"),
            price=getattr(ctx, "price", None),
            consensus_signal=cons_signal,
            consensus_score=cons_score,
            avg_conviction=avg_conv,
            agreement_score=agreement,
            verdicts=verdict_dicts,
            aegis_veto=aegis_veto,
            dissent_summary=dissent_summary,
        )

    # ── Consensus math ──────────────────────────────────────────
    def _compute_consensus(self, verdicts: List[dict]) -> tuple:
        """Returns (signal_str, weighted_score, avg_conviction, agreement_score).

        CONVICTION FIX: avg_conviction is now computed only over directional
        voters (BUY/STRONG_BUY/SELL/STRONG_SELL). HOLD voters contribute to
        the weighted score (correctly pulling it toward 0) but are excluded
        from avg_conviction so that Alpaca's conviction threshold reflects the
        genuine confidence of agents that actually have a view.
        """
        if not verdicts:
            return ("HOLD", 0.0, 0.0, 0.0)

        # ── Weighted score: sum(signal_score * conviction) / sum(conviction) ──
        # HOLDs have score=0 so they contribute 0 to numerator but their
        # conviction to the denominator — this correctly pulls the signal
        # toward HOLD when many agents are indecisive. Unchanged from before.
        total_weighted = 0.0
        total_weight = 0.0
        n_voting = 0
        for v in verdicts:
            sig = v.get("signal", "HOLD")
            if sig == "ABSTAIN":
                continue
            score = SIGNAL_SCORE.get(sig, 0.0)
            conv = float(v.get("conviction", 0.0) or 0.0)
            total_weighted += score * conv
            total_weight += conv
            n_voting += 1

        if total_weight == 0 or n_voting == 0:
            return ("HOLD", 0.0, 0.0, 0.0)

        avg_score = total_weighted / total_weight

        # Map score to consensus signal
        if avg_score >= STRONG_BUY_THRESHOLD:
            cons = "STRONG_BUY"
        elif avg_score >= BUY_THRESHOLD:
            cons = "BUY"
        elif avg_score <= STRONG_SELL_THRESHOLD:
            cons = "STRONG_SELL"
        elif avg_score <= SELL_THRESHOLD:
            cons = "SELL"
        else:
            cons = "HOLD"

        # Agreement score: fraction of voters in the consensus camp (unchanged)
        cons_score_val = SIGNAL_SCORE.get(cons, 0.0)
        in_camp = 0
        for v in verdicts:
            sig = v.get("signal", "HOLD")
            if sig == "ABSTAIN":
                continue
            s = SIGNAL_SCORE.get(sig, 0.0)
            if cons_score_val > 0 and s > 0:
                in_camp += 1
            elif cons_score_val < 0 and s < 0:
                in_camp += 1
            elif cons_score_val == 0 and s == 0:
                in_camp += 1
        agreement = in_camp / max(1, n_voting)

        # ── CONVICTION FIX: only directional voters count toward avg_conviction ──
        # A HOLD vote expresses "I see no edge" — its low conviction should not
        # drag down the measured confidence of agents that actually voted BUY/SELL.
        directional_signals = ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL")
        dir_conv_total = 0.0
        n_directional = 0
        for v in verdicts:
            sig = v.get("signal", "HOLD")
            if sig in directional_signals:
                dir_conv_total += float(v.get("conviction", 0.0) or 0.0)
                n_directional += 1

        if n_directional > 0:
            avg_conv = dir_conv_total / n_directional
        else:
            # No directional voters — report the overall average (will be low, HOLD)
            avg_conv = total_weight / max(1, n_voting)

        return (cons, avg_score, avg_conv, agreement)

    # ── AEGIS / GUARDIAN veto ───────────────────────────────────
    def _maybe_apply_aegis_veto(self, verdicts: List[dict], current_consensus: str) -> bool:
        """AEGIS / GUARDIAN can downgrade bullish consensus when its own
        signal is bearish at sufficient conviction."""
        if current_consensus not in ("BUY", "STRONG_BUY"):
            return False

        for v in verdicts:
            agent = (v.get("agent") or "").upper()
            if agent not in self.AEGIS_NAMES:
                continue
            sig = v.get("signal", "HOLD")
            conv = float(v.get("conviction", 0.0) or 0.0)
            if sig in ("SELL", "STRONG_SELL") and conv >= self.AEGIS_VETO_MIN_CONVICTION:
                return True
        return False

    # ── Dissent summary text ────────────────────────────────────
    def _summarize_dissent(self, verdicts: List[dict], cons_signal: str) -> str:
        """One-line description of the most-divergent dissent, if any."""
        cons_score = SIGNAL_SCORE.get(cons_signal, 0.0)
        dissents = []
        for v in verdicts:
            sig = v.get("signal", "HOLD")
            if sig == "ABSTAIN":
                continue
            s = SIGNAL_SCORE.get(sig, 0.0)
            differs = (
                (cons_score > 0 and s <= 0) or
                (cons_score < 0 and s >= 0) or
                (cons_score == 0 and s != 0)
            )
            if differs:
                dissents.append(v)

        if not dissents:
            return ""

        dissents.sort(key=lambda x: float(x.get("conviction", 0) or 0), reverse=True)
        top = dissents[0]
        agent = top.get("agent", "?")
        sig = top.get("signal", "?")
        conv = float(top.get("conviction", 0) or 0)
        return f"{agent} dissents ({sig}, conviction {conv:.2f})"
