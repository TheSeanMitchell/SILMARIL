"""
silmaril.handoff.blocks — Build Handoff Blocks from debate context.

A Handoff Block is a pre-framed prompt the user can copy into any LLM
(ChatGPT, Claude, Gemini, Perplexity, Grok) to continue their research.
SILMARIL does the hardest part of prompting — turning "I'm curious about
AAPL" into a question loaded with context: the full debate, the price
action, the dissenting agents, the recent headlines.

Every Handoff Block has two parts:
  1. context_text — the copyable context (what the user pastes)
  2. handoffs     — deep-links with the context pre-loaded where supported

Templates live here so the prompts are editable without touching the
core pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .deeplinks import build_handoffs


# ─────────────────────────────────────────────────────────────────
# Prompt templates
# ─────────────────────────────────────────────────────────────────

ASSET_DEEP_DIVE = """I'm researching {ticker} ({name}) and want your independent take.

Here is the current multi-agent analysis from SILMARIL (an educational simulation, not advice):

Price: ${price:.2f} ({change_pct:+.2f}% today)
Consensus signal: {consensus_signal} (agreement score {agreement:.0%})

Agent verdicts:
{verdict_block}

Dissent: {dissent_summary}

Recent headlines:
{headlines_block}

Questions I'd like you to address:
1. Do you agree or disagree with the consensus? Why?
2. Which dissenting agent's view most deserves serious consideration, and what would have to happen for them to be right?
3. What critical data or perspective is missing from this analysis?
4. If I were considering a position, what questions should I ask myself first?

Please be direct. This is for learning, not execution."""


SCROOGE_NARRATIVE = """I'm tracking an educational simulation called SCROOGE: a hypothetical account that started with $1 on {life_start_date} and puts its entire balance into the single highest-consensus trade each day.

SCROOGE's current state:
- Life #{current_life}
- Current balance: ${balance:.4f}
- Days alive: {days_alive}
- Lifetime peak: ${lifetime_peak:.4f}
- Previous deaths: {death_count}

Most recent actions:
{recent_actions}

I'd like to understand:
1. What does this simulation teach about position sizing and concentration?
2. What are the realistic failure modes of an all-in-one-name strategy?
3. What's the mathematical expected outcome of full-conviction daily rolls over time?
4. What would change if the same strategy were applied with 10%, 25%, or 50% position sizing instead of 100%?

Help me reason about this like a student of markets, not a gambler."""


DEBATE_SUMMARY = """I'm reviewing today's output from SILMARIL, a transparent multi-agent market analysis simulation. Here's the headline debate:

Market regime: {market_regime} (VIX {vix})

Top opportunities by consensus:
{top_block}

Today's most contested asset: {contested_ticker}
  - Consensus: {contested_signal} (agreement {contested_agreement:.0%})
  - {contested_dissent}

I want to stress-test the day's top-consensus picks. For each, ask:
  - What is the strongest argument AGAINST this trade?
  - What specific price or news event would invalidate the thesis?
  - What is the base rate of success for this kind of setup historically?

Be skeptical. My default assumption is that consensus can be wrong."""


# ─────────────────────────────────────────────────────────────────
# Block builders
# ─────────────────────────────────────────────────────────────────

def build_asset_deep_dive(debate: Dict[str, Any]) -> Dict[str, Any]:
    """Build a Handoff Block for one asset's debate."""
    verdicts = debate.get("verdicts", [])
    voting = [v for v in verdicts if v.get("signal") != "ABSTAIN"]

    verdict_block = "\n".join(
        f"  - {v['agent']}: {v['signal']} "
        f"(conviction {v['conviction']:.0%}) — {v['rationale']}"
        for v in voting
    ) or "  - (no agents weighed in)"

    headlines = debate.get("recent_headlines") or []
    headlines_block = "\n".join(
        f"  - {h.get('title', '(untitled)')} [{h.get('source', '?')}]"
        for h in headlines[:5]
    ) or "  - (no headlines captured in this run)"

    context_text = ASSET_DEEP_DIVE.format(
        ticker=debate["ticker"],
        name=debate.get("name", debate["ticker"]),
        price=debate.get("price") or 0.0,
        change_pct=debate.get("change_pct") or 0.0,
        consensus_signal=debate["consensus"]["signal"],
        agreement=debate["consensus"]["agreement_score"],
        verdict_block=verdict_block,
        dissent_summary=debate.get("dissent_summary", "None"),
        headlines_block=headlines_block,
    )

    return {
        "template": "asset_deep_dive",
        "context_text": context_text,
        "handoffs": build_handoffs(context_text),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_scrooge_narrative(scrooge_state: Dict[str, Any]) -> Dict[str, Any]:
    """Build a Handoff Block for the SCROOGE storyline."""
    history = scrooge_state.get("history", [])
    recent = history[-5:]
    recent_lines = []
    for h in recent:
        action = h.get("action", "?")
        date = h.get("date", "?")
        ticker = h.get("ticker", "—")
        if action == "BUY":
            recent_lines.append(f"  - {date}: BUY {ticker} with ${h.get('allocated', 0):.4f}")
        elif action == "SELL":
            recent_lines.append(
                f"  - {date}: SELL {ticker} → ${h.get('balance_after', 0):.4f} "
                f"({h.get('pnl_pct', 0):+.1f}%)"
            )
        elif action == "REINCARNATION":
            recent_lines.append(f"  - {date}: DEATH & REBIRTH (new life)")
        elif action == "CASH":
            recent_lines.append(f"  - {date}: HELD CASH ({h.get('reason', '')})")
    recent_actions = "\n".join(recent_lines) if recent_lines else "  - (no actions yet)"

    context_text = SCROOGE_NARRATIVE.format(
        life_start_date=scrooge_state.get("life_start_date", "?"),
        current_life=scrooge_state.get("current_life", 1),
        balance=scrooge_state.get("balance", 0.0),
        days_alive=scrooge_state.get("days_alive", 0),
        lifetime_peak=scrooge_state.get("lifetime_peak", 0.0),
        death_count=len(scrooge_state.get("deaths", [])),
        recent_actions=recent_actions,
    )

    return {
        "template": "scrooge_narrative",
        "context_text": context_text,
        "handoffs": build_handoffs(context_text),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_debate_summary(
    debates: List[Dict[str, Any]],
    market_regime: str = "NEUTRAL",
    vix: Optional[float] = None,
) -> Dict[str, Any]:
    """Build a Handoff Block for the overall daily debate."""
    top = sorted(
        [d for d in debates if d["consensus"]["signal"] in ("BUY", "STRONG_BUY")],
        key=lambda d: -d["consensus"]["score"],
    )[:5]
    top_block = "\n".join(
        f"  - {d['ticker']}: {d['consensus']['signal']} "
        f"(score {d['consensus']['score']:.2f}, agreement {d['consensus']['agreement_score']:.0%})"
        for d in top
    ) or "  - (no BUY-consensus picks today)"

    # Most contested = lowest agreement with non-HOLD consensus
    contested_candidates = [
        d for d in debates
        if d["consensus"]["signal"] != "HOLD"
        and d["consensus"]["agreement_score"] < 0.6
    ]
    contested = (
        min(contested_candidates, key=lambda d: d["consensus"]["agreement_score"])
        if contested_candidates
        else None
    )

    context_text = DEBATE_SUMMARY.format(
        market_regime=market_regime,
        vix=f"{vix:.1f}" if vix else "n/a",
        top_block=top_block,
        contested_ticker=contested["ticker"] if contested else "—",
        contested_signal=contested["consensus"]["signal"] if contested else "—",
        contested_agreement=contested["consensus"]["agreement_score"] if contested else 0,
        contested_dissent=contested.get("dissent_summary", "—") if contested else "no contested names today",
    )

    return {
        "template": "debate_summary",
        "context_text": context_text,
        "handoffs": build_handoffs(context_text),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
