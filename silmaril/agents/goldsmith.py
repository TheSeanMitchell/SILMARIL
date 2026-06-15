"""
GOLDSMITH — the valuables zone's own agent (ALPHA 1.0, spec A1).

The parity wedge: stocks got FABLEBOY_5 — a voter built entirely on the
word engine. GOLDSMITH is the same thesis pointed at everything that is
NOT a traditional stock: crypto majors, tokens, and the macro-commodity
complex (gold, silver, oil, gas, copper expressed through their tickers).
Because GOLDSMITH is a roster agent, the ENTIRE existing machinery —
career scorecards, profit-weighted Bayesian beliefs, senate elections,
benches, amnesty, and the upcoming breeding automation — covers the
valuables jurisdiction automatically. Separate but equal, one shared spine.

JURISDICTION LAW: GOLDSMITH abstains on every equity/ETF. The stocks-only
mission guard at the Alpaca order choke point means its votes can never
reach a brokerage order — by design. Its career record builds through the
agent simulation books, exactly where a future valuables account will
plug in.

VALUABLES DOCTRINE (differs from equities, deterministically):
  - 24/7 markets have no closing bell to mean-revert into: momentum-with-
    words carries further -> follower multiplier slightly stronger.
  - No earnings, no analyst ratings: catalysts are rarer and DIRTIER
    (regulatory, ETF-flow, geopolitical, supply shocks). A decisive
    catalyst therefore carries MORE weight than in equities.
  - Liquidity cliffs: thin names whipsaw on nothing. Without breadth
    (>=2 articles) conviction is hard-capped at 0.45.
  - Fee gravity: crypto's taker fees are notorious — conviction never
    exceeds 0.80 so sizing stays survivable after real-world drag
    (fees_truth CRYPTO_TAKER_BPS will gate the future live book).

No LLMs, no synthetic data, fully explainable, additive. Career capital
$10K like every main voter; judged by realized profit like everyone.
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict

_VALUABLE_CLASSES = ("crypto", "token", "commodity", "commodities",
                     "fx", "macro", "bonds/rates")


class Goldsmith(Agent):
    codename = "GOLDSMITH"
    specialty = ("Valuables-jurisdiction word rider: crypto, tokens and the "
                 "macro-commodity complex — never touches a stock.")
    temperament = ("Old-world assayer's patience with degen-hours stamina; "
                   "weighs words like metal, distrusts thin tape.")
    inspiration = ("FABLEBOY_5's thesis exported to the markets that never "
                   "close — the wedge that gives valuables their own "
                   "senate bloodline.")
    asset_classes = _VALUABLE_CLASSES

    # tunables (deterministic, documented; vs Fableboy: catalysts weigh
    # more, sentiment slightly less — see VALUABLES DOCTRINE above)
    W_SENT, W_ANTIC, W_CAT = 0.35, 0.25, 0.40
    STRONG_T, LEAN_T = 0.55, 0.20
    FOLLOWER_MULT, FADER_MULT, IMMUNE_MULT = 1.35, 0.55, 0.7
    THIN_TAPE_CAP = 0.45      # breadth < 2 articles
    CONVICTION_CEILING = 0.80  # fee gravity

    def _judge(self, ctx: AssetContext) -> Verdict:
        n_art = int(ctx.article_count or 0)
        if n_art <= 0:
            return Verdict(agent=self.codename, ticker=ctx.ticker,
                           signal=Signal.ABSTAIN, conviction=0.0,
                           rationale=("No headlines this cycle — Goldsmith "
                                      "assays words, and there is no metal "
                                      "to weigh."),
                           factors={"articles": 0})

        sent = float(ctx.sentiment_score or 0.0)
        cat = ctx.news_catalyst
        cat_label = ctx.news_catalyst_label
        pers = ctx.news_personality
        horizon = ctx.news_best_horizon

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
            w = (self.W_SENT * sent + self.W_ANTIC * antic
                 + self.W_CAT * float(cat))
        else:
            tot = self.W_SENT + self.W_ANTIC
            w = (self.W_SENT / tot) * sent + (self.W_ANTIC / tot) * antic

        note = ""
        if pers == "news-follower":
            w *= self.FOLLOWER_MULT
            note = (f"confirmed news-follower ({horizon}d) — 24/7 tape lets "
                    f"words run")
        elif pers == "news-fader":
            if cat is not None and cat > 0 and w > 0:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.HOLD, conviction=0.50,
                    rationale=(f"{cat_label or 'positive catalyst'} on a "
                               f"confirmed fader in a 24/7 market — the pop "
                               f"is exit liquidity, not an invitation."),
                    factors={"sent": round(sent, 3), "antic": round(antic, 3),
                             "catalyst": cat, "catalyst_label": cat_label,
                             "personality": pers,
                             "decision": "fade-trap avoided"},
                    invalidation=("Two sessions of follow-through would "
                                  "weaken the fader read."))
            w *= self.FADER_MULT
            note = "confirmed news-fader — words heavily discounted"
        elif pers == "news-immune":
            w *= self.IMMUNE_MULT
            note = "news-immune — this valuable ignores its headlines"

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

        if sig == Signal.HOLD:
            conviction = 0.30
        else:
            conviction = min(self.CONVICTION_CEILING, 0.28 + abs(w) * 0.7)
            if n_art < 2:
                conviction = min(conviction, self.THIN_TAPE_CAP)
                note = (note + "; " if note else "") + \
                    "thin tape: single-source cap"

        pieces = [f"words {w:+.2f} ({n_art} arts)"]
        if cat is not None:
            pieces.append(f"catalyst: {cat_label or f'{cat:+.1f}'}")
        if abs(antic) >= 0.15:
            pieces.append(f"anticipation {antic:+.2f}")
        if note:
            pieces.append(note)

        return Verdict(
            agent=self.codename, ticker=ctx.ticker, signal=sig,
            conviction=round(conviction, 2),
            rationale="; ".join(pieces) + ".",
            factors={"sent": round(sent, 3), "antic": round(antic, 3),
                     "catalyst": cat, "catalyst_label": cat_label,
                     "personality": pers, "horizon_days": horizon,
                     "blended": round(w, 3), "articles": n_art,
                     "jurisdiction": "valuables"},
            invalidation=("Word signal flipping sign, a catalyst walked "
                          "back, or a liquidity cliff (spread blowout) "
                          "kills the thesis."))


goldsmith = Goldsmith()
