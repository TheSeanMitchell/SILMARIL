"""
silmaril.debate.arbiter — The multi-agent orchestrator.

The arbiter is where the fifteen voting agents become a debate. For each
asset in the universe, the arbiter:

  1. Asks every applicable agent for a Verdict
  2. Computes a consensus signal, weighted by conviction
  3. Measures agreement (how unified are the voting agents?)
  4. Identifies the dissenters (who disagreed with consensus, and why?)
  5. Applies AEGIS's veto power (defensive override)
  6. Produces a Debate object ready for JSON output

The output is designed to render as a transcript, not a scoreboard.
The disagreement is the product.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..agents.base import Agent, AssetContext, Signal, Verdict


# Signal numeric mapping for consensus math
SIGNAL_SCORE = {
    Signal.STRONG_BUY: 2,
    Signal.BUY: 1,
    Signal.HOLD: 0,
    Signal.SELL: -1,
    Signal.STRONG_SELL: -2,
    Signal.ABSTAIN: None,  # excluded from math
}

SCORE_TO_SIGNAL = [
    (1.25, Signal.STRONG_BUY),
    (0.35, Signal.BUY),
    (-0.35, Signal.HOLD),
    (-1.25, Signal.SELL),
    (-999, Signal.STRONG_SELL),
]


@dataclass
class Debate:
    """A resolved debate for one asset."""
    ticker: str
    name: str
    price: Optional[float]
    change_pct: Optional[float]

    # Consensus results
    consensus_signal: Signal
    consensus_score: float           # 0.0 to 1.0, strength of consensus
    avg_conviction: float
    agreement_score: float           # 0.0 = totally split, 1.0 = unanimous

    # All verdicts (including abstentions, for transparency)
    verdicts: List[Verdict] = field(default_factory=list)

    # The named dissenters — agents who disagreed with consensus
    dissenters: List[str] = field(default_factory=list)
    dissent_summary: str = ""

    # AEGIS veto flag
    aegis_veto: bool = False
    aegis_veto_reason: Optional[str] = None

    # Plain-English transcript
    transcript: str = ""

    # Consensus debug: the math transparently shown
    consensus_debug: Dict[str, Any] = field(default_factory=dict)

    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "price": self.price,
            "change_pct": self.change_pct,
            "consensus": {
                "signal": self.consensus_signal.value,
                "score": round(self.consensus_score, 3),
                "avg_conviction": round(self.avg_conviction, 3),
                "agreement_score": round(self.agreement_score, 3),
            },
            "verdicts": [v.to_dict() for v in self.verdicts],
            "dissenters": self.dissenters,
            "dissent_summary": self.dissent_summary,
            "aegis_veto": self.aegis_veto,
            "aegis_veto_reason": self.aegis_veto_reason,
            "transcript": self.transcript,
            "consensus_debug": self.consensus_debug,
            "generated_at": self.generated_at.isoformat(),
        }


class Arbiter:
    """Runs the full debate for a set of assets."""

    def __init__(self, agents: List[Agent], aegis_veto_enabled: bool = True):
        self.agents = agents
        self.aegis_veto_enabled = aegis_veto_enabled

    def resolve(self, contexts: List[AssetContext]) -> List[Debate]:
        """Run every agent on every context; produce Debate objects."""
        return [self.resolve_one(ctx) for ctx in contexts]

    def resolve_one(self, ctx: AssetContext) -> Debate:
        # ── Collect all verdicts ─────────────────────────────────
        verdicts = [a.evaluate(ctx) for a in self.agents]

        # ── Compute consensus from NON-abstaining verdicts ───────
        voting = [v for v in verdicts if v.signal != Signal.ABSTAIN]

        if not voting:
            return self._no_voters_debate(ctx, verdicts)

        consensus_signal, consensus_score, avg_conviction = self._compute_consensus(voting)
        agreement = self._agreement_score(voting)

        # ── Identify dissenters ──────────────────────────────────
        dissenters = [
            v for v in voting
            if self._opposes(v.signal, consensus_signal)
        ]
        dissenter_names = [v.agent for v in dissenters]
        dissent_summary = self._summarize_dissent(consensus_signal, dissenters)

        # ── AEGIS veto check ─────────────────────────────────────
        aegis_veto = False
        aegis_veto_reason = None
        if self.aegis_veto_enabled:
            aegis_verdict = next((v for v in verdicts if v.agent == "AEGIS"), None)
            if (
                aegis_verdict
                and aegis_verdict.conviction >= 0.65
                and aegis_verdict.signal in (Signal.SELL, Signal.STRONG_SELL, Signal.HOLD)
                and consensus_signal in (Signal.BUY, Signal.STRONG_BUY)
            ):
                aegis_veto = True
                aegis_veto_reason = aegis_verdict.rationale
                # Downgrade consensus to HOLD when AEGIS vetoes
                consensus_signal = Signal.HOLD

        # ── Compose transcript ───────────────────────────────────
        transcript = self._compose_transcript(
            ctx=ctx,
            voting=voting,
            consensus_signal=consensus_signal,
            dissenters=dissenters,
            aegis_veto=aegis_veto,
        )

        # ── Consensus debug: show the math transparently ────────
        debug = self._build_consensus_debug(
            verdicts=verdicts,
            voting=voting,
            consensus_signal=consensus_signal,
            aegis_veto=aegis_veto,
        )

        return Debate(
            ticker=ctx.ticker,
            name=ctx.name,
            price=ctx.price,
            change_pct=ctx.change_pct,
            consensus_signal=consensus_signal,
            consensus_score=consensus_score,
            avg_conviction=avg_conviction,
            agreement_score=agreement,
            verdicts=verdicts,
            dissenters=dissenter_names,
            dissent_summary=dissent_summary,
            aegis_veto=aegis_veto,
            aegis_veto_reason=aegis_veto_reason,
            transcript=transcript,
            consensus_debug=debug,
        )

    # ─────────────────────────────────────────────────────────────

    def _compute_consensus(
        self, voting: List[Verdict]
    ) -> Tuple[Signal, float, float]:
        """Weighted average: each agent's signal × its conviction."""
        total_weight = 0.0
        weighted_sum = 0.0
        total_conviction = 0.0
        for v in voting:
            score = SIGNAL_SCORE.get(v.signal)
            if score is None:
                continue
            weight = max(v.conviction, 0.01)
            weighted_sum += score * weight
            total_weight += weight
            total_conviction += v.conviction

        avg_score = weighted_sum / total_weight if total_weight else 0.0
        avg_conviction = total_conviction / len(voting) if voting else 0.0

        signal = self._score_to_signal(avg_score)
        consensus_strength = min(abs(avg_score) / 2.0, 1.0)  # 0..1

        return signal, consensus_strength, avg_conviction

    @staticmethod
    def _score_to_signal(score: float) -> Signal:
        for threshold, sig in SCORE_TO_SIGNAL:
            if score >= threshold:
                return sig
        return Signal.STRONG_SELL

    @staticmethod
    def _agreement_score(voting: List[Verdict]) -> float:
        """
        1.0 if all agents agree on the same signal,
        0.0 if perfectly split across signals.
        Uses normalized entropy.
        """
        if not voting:
            return 0.0
        counts = Counter(v.signal.value for v in voting)
        total = sum(counts.values())
        n_distinct = len(counts)
        if n_distinct == 1:
            return 1.0
        # Simple metric: proportion of the most-popular signal
        top_share = counts.most_common(1)[0][1] / total
        return round(top_share, 3)

    @staticmethod
    def _opposes(verdict_signal: Signal, consensus: Signal) -> bool:
        """A verdict 'opposes' consensus if they are on opposite sides of HOLD."""
        bullish = {Signal.BUY, Signal.STRONG_BUY}
        bearish = {Signal.SELL, Signal.STRONG_SELL}
        if consensus in bullish and verdict_signal in bearish:
            return True
        if consensus in bearish and verdict_signal in bullish:
            return True
        # HOLD dissents against strong consensus either way
        if consensus in bullish and verdict_signal == Signal.HOLD:
            return True
        if consensus in bearish and verdict_signal == Signal.HOLD:
            return True
        return False

    @staticmethod
    def _summarize_dissent(consensus: Signal, dissenters: List[Verdict]) -> str:
        if not dissenters:
            return "No dissent. The team agrees."
        names = ", ".join(d.agent for d in dissenters)
        signals = set(d.signal.value for d in dissenters)
        return (
            f"Consensus is {consensus.value}, but {names} "
            f"({'/'.join(signals)}) disagree."
        )

    @staticmethod
    def _compose_transcript(
        ctx: AssetContext,
        voting: List[Verdict],
        consensus_signal: Signal,
        dissenters: List[Verdict],
        aegis_veto: bool,
    ) -> str:
        """Compose a readable debate narrative."""
        lines: List[str] = []
        lines.append(f"— Debate on {ctx.ticker} ({ctx.name}) —")

        # Majority bloc first
        majority = [v for v in voting if v not in dissenters]
        if majority:
            lines.append(f"\nMAJORITY ({consensus_signal.value}):")
            for v in sorted(majority, key=lambda x: -x.conviction):
                lines.append(f"  • {v.agent}: {v.rationale}")

        # Dissent
        if dissenters:
            lines.append(f"\nDISSENT:")
            for v in sorted(dissenters, key=lambda x: -x.conviction):
                lines.append(f"  • {v.agent} ({v.signal.value}): {v.rationale}")

        # Veto
        if aegis_veto:
            lines.append(
                f"\n⚔ AEGIS VETO APPLIED. "
                f"Despite bullish consensus, defensive guard downgrades to HOLD."
            )

        return "\n".join(lines)

    @staticmethod
    def _build_consensus_debug(
        verdicts: List[Verdict],
        voting: List[Verdict],
        consensus_signal: Signal,
        aegis_veto: bool,
    ) -> Dict[str, Any]:
        """
        Produce a per-vote breakdown of exactly how the consensus number
        was computed. Rendered by the dashboard so users can see whether
        agreement is genuine, thin, or driven by one loud voter.
        """
        contributions: List[Dict[str, Any]] = []
        total_weight = 0.0
        weighted_sum = 0.0
        for v in verdicts:
            score = SIGNAL_SCORE.get(v.signal)
            if score is None:
                contributions.append({
                    "agent": v.agent,
                    "signal": v.signal.value,
                    "conviction": round(v.conviction, 3),
                    "signal_score": None,
                    "weight": 0.0,
                    "contribution": 0.0,
                    "excluded": True,
                    "reason": "ABSTAIN — outside specialty or no setup",
                })
                continue
            weight = max(v.conviction, 0.01)
            contribution = score * weight
            weighted_sum += contribution
            total_weight += weight
            contributions.append({
                "agent": v.agent,
                "signal": v.signal.value,
                "conviction": round(v.conviction, 3),
                "signal_score": score,
                "weight": round(weight, 3),
                "contribution": round(contribution, 3),
                "excluded": False,
            })

        weighted_score = (weighted_sum / total_weight) if total_weight else 0.0
        voting_count = len(voting)
        abstaining_count = len(verdicts) - voting_count

        # Agreement breakdown by signal
        signal_counts: Dict[str, int] = {}
        for v in voting:
            signal_counts[v.signal.value] = signal_counts.get(v.signal.value, 0) + 1

        # How lopsided is the conviction distribution?
        top3_weight = sum(
            sorted([max(v.conviction, 0.01) for v in voting], reverse=True)[:3]
        )
        conviction_concentration = (
            round(top3_weight / total_weight, 3) if total_weight else 0.0
        )

        return {
            "total_agents": len(verdicts),
            "voting_count": voting_count,
            "abstaining_count": abstaining_count,
            "weighted_sum": round(weighted_sum, 3),
            "total_weight": round(total_weight, 3),
            "weighted_score": round(weighted_score, 3),
            "signal_thresholds": {
                "STRONG_BUY":  "≥ 1.25",
                "BUY":         "0.35 to 1.25",
                "HOLD":        "−0.35 to 0.35",
                "SELL":        "−1.25 to −0.35",
                "STRONG_SELL": "< −1.25",
            },
            "landed_on": consensus_signal.value,
            "signal_distribution": signal_counts,
            "conviction_concentration_top3": conviction_concentration,
            "contributions": contributions,
            "aegis_vetoed": aegis_veto,
            "interpretation": Arbiter._debug_interpretation(
                voting_count, abstaining_count, signal_counts,
                conviction_concentration, aegis_veto,
            ),
        }

    @staticmethod
    def _debug_interpretation(
        voting_count: int,
        abstaining_count: int,
        signal_counts: Dict[str, int],
        conviction_concentration: float,
        aegis_veto: bool,
    ) -> str:
        """A short, plain-English read of the debate quality."""
        bits: List[str] = []
        if voting_count < 3:
            bits.append(f"Thin debate — only {voting_count} agents spoke; "
                        f"{abstaining_count} abstained.")
        elif voting_count >= 8:
            bits.append(f"Deep debate — {voting_count} agents voted.")
        else:
            bits.append(f"{voting_count} of {voting_count + abstaining_count} "
                        f"agents voted.")

        distinct = len(signal_counts)
        if distinct == 1:
            bits.append("Unanimous across signals.")
        elif distinct == 2:
            bits.append("Two signal camps — mild disagreement.")
        else:
            bits.append(f"Split across {distinct} signals — genuine debate.")

        if conviction_concentration >= 0.75:
            bits.append("Heavy conviction concentration in top 3 voters — "
                        "result driven by a small bloc.")

        if aegis_veto:
            bits.append("AEGIS vetoed the bullish lean on risk grounds.")

        return " ".join(bits)

    @staticmethod
    def _no_voters_debate(
        ctx: AssetContext, verdicts: List[Verdict]
    ) -> Debate:
        return Debate(
            ticker=ctx.ticker,
            name=ctx.name,
            price=ctx.price,
            change_pct=ctx.change_pct,
            consensus_signal=Signal.HOLD,
            consensus_score=0.0,
            avg_conviction=0.0,
            agreement_score=0.0,
            verdicts=verdicts,
            dissenters=[],
            dissent_summary="No agents voted (all abstained for this asset class).",
            transcript=f"— No coverage for {ctx.ticker} —\nAll agents abstained.",
        )
