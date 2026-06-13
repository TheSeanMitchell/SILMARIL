"""
FABLEBOY 5 — the word-engine's own agent.

Every other voter predates the new intelligence layers. Fableboy 5 is built ON
them — the first agent whose entire thesis is the project's thesis: words
predict, numbers act. It reads, per stock, all four word-derived signals the
system now produces and nothing else:

  1. SENTIMENT      what the tape's headlines say happened (backward words)
  2. ANTICIPATION   what the headlines expect to happen (forward words)
  3. CATALYST       a decisive directional event (downgrade-to-sell, guidance
                    cut, FDA verdict, IPO pricing, insider buys, short report)
  4. PERSONALITY    how THIS stock historically treats its news — follower
                    (ride it), fader (don't chase it), immune (discount it)

Discipline rules:
  - No words, no opinion: zero articles -> ABSTAIN. Fableboy never votes on
    price action alone.
  - Confirmed news-FADERS invert the chase: a catalyst pop on a fader is a
    reason to stand down (HOLD) or lean against, never to pile in.
  - STRONG_* requires breadth (>=3 articles) AND either a decisive catalyst or
    aligned anticipation — one headline can move a vote, not slam it.
  - Conviction is earned: starts modest, grows with alignment of layers, capped
    at 0.85 so the Bayesian career record—not bravado—does the talking.

Deterministic, explainable, no LLM, additive. Career capital $10K like every
main voter; the profit-weighted belief loop will judge it like everyone else.
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Fableboy5(Agent):
    codename = "FABLEBOY_5"
    specialty = ("Word-led catalyst rider: trades only what the headlines say, "
                 "shaped by each stock's learned news personality.")
    temperament = ("Bookish and patient — silent without text, decisive when "
                   "the words align, allergic to chasing faders.")
    inspiration = ("The project's own thesis, given a chair at the table: "
                   "words predict, numbers act.")
    asset_classes = ("equity", "etf")

    # tunables (deterministic, documented)
    W_SENT, W_ANTIC, W_CAT = 0.45, 0.25, 0.30
    STRONG_T, LEAN_T = 0.55, 0.22

    def _judge(self, ctx: AssetContext) -> Verdict:
        n_art = int(ctx.article_count or 0)
        if n_art <= 0:
            return Verdict(agent=self.codename, ticker=ctx.ticker,
                           signal=Signal.ABSTAIN, conviction=0.0,
                           rationale="No headlines this cycle — Fableboy only "
                                     "trades words, so no words, no opinion.",
                           factors={"articles": 0})

        sent = float(ctx.sentiment_score or 0.0)
        cat = ctx.news_catalyst
        cat_label = ctx.news_catalyst_label
        pers = ctx.news_personality          # news-follower / news-fader / news-immune / None
        horizon = ctx.news_best_horizon

        # forward-looking anticipation, computed from this cycle's headlines
        antic = 0.0
        try:
            from ..analytics.sentiment import anticipation_score
            vals = [anticipation_score(str((h or {}).get("title") or ""))
                    for h in (ctx.recent_headlines or [])]
            vals = [v for v in vals if v]
            antic = sum(vals) / len(vals) if vals else 0.0
        except Exception:
            antic = 0.0

        # blended word score; redistribute catalyst weight when absent
        if cat is not None:
            w = self.W_SENT * sent + self.W_ANTIC * antic + self.W_CAT * float(cat)
        else:
            tot = self.W_SENT + self.W_ANTIC
            w = (self.W_SENT / tot) * sent + (self.W_ANTIC / tot) * antic

        # personality shaping — the heart of the agent
        note = ""
        mult = 1.0
        if pers == "news-follower":
            mult = 1.25
            note = f"confirmed news-follower ({horizon}d horizon) — ride the words"
        elif pers == "news-fader":
            if cat is not None and cat > 0 and w > 0:
                # a catalyst pop on a fader is the trap, not the trade
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker, signal=Signal.HOLD,
                    conviction=0.55,
                    rationale=(f"{cat_label or 'positive catalyst'} on a confirmed "
                               f"news-FADER — its pops get sold by tomorrow; "
                               f"standing down instead of chasing."),
                    factors={"sent": round(sent, 3), "antic": round(antic, 3),
                             "catalyst": cat, "catalyst_label": cat_label,
                             "personality": pers, "decision": "fade-trap avoided"},
                    invalidation="A second straight day of follow-through would "
                                 "weaken the fader read.")
            mult = 0.6
            note = "confirmed news-fader — words discounted"
        elif pers == "news-immune":
            mult = 0.7
            note = "news-immune — headlines rarely predict its moves"
        w *= mult

        # map to signal; STRONG needs breadth + a decisive layer
        decisive = (cat is not None) or (abs(antic) >= 0.5)
        if w >= self.STRONG_T and n_art >= 3 and decisive:
            sig = Signal.STRONG_BUY
        elif w >= self.LEAN_T:
            sig = Signal.BUY
        elif w <= -self.STRONG_T and n_art >= 3 and decisive:
            sig = Signal.STRONG_SELL
        elif w <= -self.LEAN_T:
            sig = Signal.SELL
        else:
            sig = Signal.HOLD

        conviction = 0.0 if sig == Signal.HOLD else min(0.85, 0.30 + abs(w) * 0.7)
        if sig == Signal.HOLD:
            conviction = 0.30
        # Debut-window discipline: first sessions are price discovery — the
        # words still lead, but conviction is capped so no one slams a debut.
        if getattr(ctx, "ipo_phase", None) == "debut_window" and sig != Signal.ABSTAIN:
            conviction = min(conviction, 0.60)
            note = (note + "; " if note else "") + "debut-window: sized for price discovery"


        pieces = [f"words {w:+.2f} ({n_art} arts)"]
        if cat is not None:
            pieces.append(f"catalyst: {cat_label or f'{cat:+.1f}'}")
        if abs(antic) >= 0.15:
            pieces.append(f"anticipation {antic:+.2f}")
        if note:
            pieces.append(note)
        rationale = "; ".join(pieces) + "."

        return Verdict(
            agent=self.codename, ticker=ctx.ticker, signal=sig,
            conviction=round(conviction, 2), rationale=rationale,
            factors={"sent": round(sent, 3), "antic": round(antic, 3),
                     "catalyst": cat, "catalyst_label": cat_label,
                     "personality": pers, "horizon_days": horizon,
                     "blended": round(w, 3), "articles": n_art},
            invalidation=("Word signal flipping sign, or the catalyst being "
                          "walked back, kills the thesis."))


fableboy5 = Fableboy5()
