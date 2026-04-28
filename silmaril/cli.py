"""
silmaril.cli — The main runner.

Two modes:

  python -m silmaril --live    # Fetch real market data from yfinance + news RSS
  python -m silmaril --demo    # Use hand-crafted sample contexts for offline testing

The --live mode is what GitHub Actions runs on schedule. It populates
the live site at theseanmitchell.github.io/SILMARIL with real data.

The --demo mode is for local development and the repository's initial
commit, so the site renders meaningfully before the first scheduled run.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .agents.base import Agent, AssetContext
from .agents.aegis import aegis
from .agents.forge import forge
from .agents.scrooge import scrooge, scrooge_act, ScroogeState
from .agents.thunderhead import thunderhead
from .agents.jade import jade
from .agents.veil import veil
from .agents.kestrel import kestrel
from .agents.obsidian import obsidian
from .agents.zenith import zenith
from .agents.weaver import weaver
from .agents.hex_agent import hex_agent
from .agents.synth import synth
from .agents.speck import speck
from .agents.vespa import vespa
from .agents.magus import magus
from .agents.talon import talon
from .agents.midas import midas, midas_act, MidasState, MIDAS_UNIVERSE
from .agents.cryptobro import cryptobro, cryptobro_act, CryptoBroState, CRYPTOBRO_UNIVERSE
from .agents.baron import baron, BARON_UNIVERSE
from .agents.steadfast import steadfast, CROWN_JEWELS
from .agents.jrr_token import (
    jrr_token, jrr_token_act, JRRTokenState, JRR_UNIVERSE,
    SUB_100M_TOKENS, OVER_100M_TOKENS,
)
from .agents.bios import get_bio
from .agents.sports_bro import (
    sports_bro, sports_bro_act, SportsBroState,
)

# ── v2.0 agents ─────────────────────────────────────────────────
from .agents.atlas import atlas
from .agents.nightshade import nightshade
from .agents.cicada import cicada
from .agents.shepherd import shepherd
from .agents.nomad import nomad
from .agents.barnacle import barnacle
from .agents.kestrel_plus import kestrel_plus
from .sports import fetch_markets, write_markets_json
from .catalysts import write_catalysts_json
from .charts import write_charts_json
from .handoff.brokers import build_broker_links
from .portfolios.agent_portfolio import (
    AgentPortfolio, agent_portfolio_act, load_portfolios, save_portfolios,
)
from .scoring.regime_tags import tag_context
from .scoring.outcomes import (
    score_prior_run, build_scoring_summary, load_scoring, save_scoring,
)
from .risk.engine import (
    AgentRiskState, SystemRiskState, DEFAULT_CONFIG,
    evaluate_agent_risk, evaluate_cohort_risk,
    filter_plans_by_risk, load_risk_state, save_risk_state,
)

from .debate.arbiter import Arbiter
from .trade_engine.plans import build_plan_from_debate
from .handoff.blocks import (
    build_asset_deep_dive,
    build_scrooge_narrative,
    build_debate_summary,
    build_trade_plan_handoff,
)
from .universe.core import all_entries, asset_class_of
from .analytics import technicals as ti
from .analytics.sentiment import aggregate_ticker_sentiment
from .analytics.regime import classify_regime, spy_trend_label


# ─────────────────────────────────────────────────────────────────
# Full agent roster — the order here is the order shown in the UI
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# Agent Cohorts (Phase F)
#
# MAIN_VOTERS:  the panel of market experts. They vote in every debate.
#               Each runs a $10K career portfolio.
# SPECIALISTS:  niche operators. They act on consensus but DO NOT vote
#               (would muddy the consensus with ultra-narrow domain bias).
#               Some run $10K portfolios (Baron, Steadfast), some are
#               $1 compounders (Scrooge, Midas, CryptoBro, JRR Token).
# ─────────────────────────────────────────────────────────────────

MAIN_VOTERS: List[Agent] = [
    aegis, forge, thunderhead, jade, veil, kestrel, obsidian, zenith,
    weaver, hex_agent, synth, speck, vespa, magus, talon,
    # v2.0 additions:
    atlas, nightshade, cicada, shepherd, nomad, barnacle, kestrel_plus,
]

SPECIALIST_AGENTS: List[Agent] = [
    baron, steadfast,            # $10K career operators
    scrooge, midas, cryptobro, jrr_token, sports_bro,  # $1 compounders
]

# Backward compat alias — used elsewhere in the CLI for serialization
AGENTS: List[Agent] = MAIN_VOTERS + SPECIALIST_AGENTS


log = logging.getLogger("silmaril")


# ─────────────────────────────────────────────────────────────────
# Live mode — real market data
# ─────────────────────────────────────────────────────────────────

def build_live_contexts() -> List[AssetContext]:
    """Fetch prices + news, compute analytics, assemble AssetContexts."""
    from .ingestion.prices import fetch_universe_prices, fetch_vix, fetch_earnings_dates
    from .ingestion.news import fetch_news_bulk

    entries = all_entries()
    tickers = [tkr for tkr, _, _ in entries]

    log.info("Fetching prices for %d tickers...", len(tickers))
    price_snaps = fetch_universe_prices(tickers)

    log.info("Fetching VIX...")
    vix = fetch_vix()

    log.info("Fetching earnings dates (best-effort)...")
    earnings = fetch_earnings_dates([t for t in tickers if t not in {"^VIX"}])

    log.info("Fetching news for %d tickers (this takes a few minutes)...", len(tickers))
    name_pairs = [(tkr, name) for tkr, name, _ in entries]
    news_map = fetch_news_bulk(name_pairs, max_articles_per=5)

    # Regime from SPY + VIX
    spy = price_snaps.get("SPY")
    spy_sma_50 = ti.sma(spy.closes, 50) if spy else None
    spy_sma_200 = ti.sma(spy.closes, 200) if spy else None
    regime = classify_regime(
        spy_price=spy.price if spy else None,
        spy_sma_50=spy_sma_50,
        spy_sma_200=spy_sma_200,
        vix=vix,
    )
    log.info("Market regime: %s (VIX %s)", regime, f"{vix:.1f}" if vix else "n/a")

    contexts: List[AssetContext] = []
    now = datetime.now(timezone.utc).date()

    for tkr, name, sector in entries:
        snap = price_snaps.get(tkr)
        if not snap:
            continue

        indicators = ti.compute_all(snap.closes, snap.highs, snap.lows)
        articles = news_map.get(tkr, [])
        titles = [a.title for a in articles]
        sources = list({a.source for a in articles})
        sent_score, sent_count = aggregate_ticker_sentiment(titles)

        earn_date = earnings.get(tkr)
        days_to_earn = None
        if earn_date:
            try:
                ed = datetime.fromisoformat(earn_date).date()
                days_to_earn = (ed - now).days
            except Exception:
                pass

        ctx = AssetContext(
            ticker=tkr,
            name=name,
            sector=sector,
            asset_class=asset_class_of(tkr),
            price=snap.price,
            change_pct=snap.change_pct,
            volume=snap.volume,
            avg_volume_30d=snap.avg_volume_30d,
            price_history=snap.closes,
            sma_20=indicators["sma_20"],
            sma_50=indicators["sma_50"],
            sma_200=indicators["sma_200"],
            rsi_14=indicators["rsi_14"],
            atr_14=indicators["atr_14"],
            bb_width=indicators["bb_width"],
            sentiment_score=sent_score,
            article_count=sent_count,
            source_count=len(sources),
            recent_headlines=[
                {"title": a.title, "source": a.source, "url": a.url}
                for a in articles[:5]
            ],
            earnings_date=earn_date,
            days_to_earnings=days_to_earn,
            market_regime=regime,
            vix=vix,
        )
        contexts.append(ctx)

    log.info("Built %d contexts with full analytics", len(contexts))
    return contexts


# ─────────────────────────────────────────────────────────────────
# Demo mode — sample contexts (for initial commit + offline dev)
# ─────────────────────────────────────────────────────────────────

def build_demo_contexts() -> List[AssetContext]:
    """Hand-crafted sample contexts designed to exercise all 16 agents."""
    # Common price-history fill so statistical agents have data
    def gen_history(center: float, closes: int = 220, drift: float = 0.0002, vol: float = 0.015, seed_key: str = "") -> List[float]:
        """Generate a synthetic-but-plausible price history by random walk.
        Seeded deterministically by today's UTC date + a per-ticker key so
        every same-day cron run produces identical data (no spurious
        run-to-run drift), but each new UTC day evolves naturally."""
        import random
        from datetime import datetime, timezone
        today_iso = datetime.now(timezone.utc).date().isoformat()
        # Stable seed: hash of (ticker_key + today + price_anchor)
        seed_str = f"{seed_key}:{today_iso}:{int(center*100)}"
        seed_int = 0
        for ch in seed_str:
            seed_int = (seed_int * 31 + ord(ch)) & 0x7FFFFFFF
        random.seed(seed_int)
        out = [center * 0.85]
        for _ in range(closes):
            out.append(out[-1] * (1 + drift + random.gauss(0, vol)))
        return out

    base_regime = "RISK_ON"
    base_vix = 17.2

    def build(**overrides) -> AssetContext:
        defaults = dict(
            market_regime=base_regime,
            vix=base_vix,
            asset_class="equity",
            source_count=5,
        )
        defaults.update(overrides)
        # Auto-fill technicals if price_history is provided
        if "price_history" in defaults and defaults["price_history"]:
            ph = defaults["price_history"]
            closes = ph
            highs = [c * 1.012 for c in closes]
            lows = [c * 0.988 for c in closes]
            indicators = ti.compute_all(closes, highs, lows)
            for k, v in indicators.items():
                defaults.setdefault(k, v)
        return AssetContext(**defaults)

    return [
        build(
            ticker="NVDA", name="NVIDIA Corporation", sector="Technology",
            price=138.40, change_pct=2.15, volume=280_000_000, avg_volume_30d=220_000_000,
            price_history=gen_history(100, drift=0.003),
            sentiment_score=0.52, article_count=14,
            days_to_earnings=9,
            recent_headlines=[
                {"title": "NVIDIA earnings preview: analysts expect another beat", "source": "Reuters"},
                {"title": "Data center spending accelerates into 2026 cycle", "source": "Bloomberg"},
            ],
        ),
        build(
            ticker="AAPL", name="Apple Inc.", sector="Technology",
            price=179.20, change_pct=-0.42, volume=58_000_000, avg_volume_30d=55_000_000,
            price_history=gen_history(175, drift=0.0005, vol=0.011),
            sentiment_score=0.03, article_count=9,
        ),
        build(
            ticker="AMD", name="Advanced Micro Devices", sector="Technology",
            price=165.80, change_pct=4.25, volume=105_000_000, avg_volume_30d=60_000_000,
            price_history=gen_history(120, drift=0.0025),
            sentiment_score=0.58, article_count=11,
        ),
        build(
            ticker="MSFT", name="Microsoft Corporation", sector="Technology",
            price=414.00, change_pct=1.05, volume=22_000_000, avg_volume_30d=25_000_000,
            price_history=gen_history(360, drift=0.0012),
            sentiment_score=0.22, article_count=7,
        ),
        build(
            ticker="TSLA", name="Tesla Inc.", sector="Discretionary",
            price=178.40, change_pct=-4.80, volume=165_000_000, avg_volume_30d=110_000_000,
            price_history=gen_history(215, drift=-0.001),
            sentiment_score=-0.38, article_count=18,
        ),
        build(
            ticker="SPY", name="SPDR S&P 500 ETF", sector="Index",
            price=528.40, change_pct=0.35, volume=75_000_000, avg_volume_30d=80_000_000,
            price_history=gen_history(495, drift=0.0008, vol=0.008),
            sentiment_score=0.12, article_count=25,
            asset_class="etf",
        ),
        build(
            ticker="QQQ", name="Invesco QQQ (Nasdaq-100)", sector="Index",
            price=445.20, change_pct=0.75, volume=42_000_000, avg_volume_30d=48_000_000,
            price_history=gen_history(410, drift=0.0012, vol=0.011),
            sentiment_score=0.15, article_count=12,
            asset_class="etf",
        ),
        build(
            ticker="IWM", name="iShares Russell 2000", sector="Index",
            price=208.50, change_pct=-0.32, volume=28_000_000, avg_volume_30d=32_000_000,
            price_history=gen_history(200, drift=0.0002),
            sentiment_score=-0.08, article_count=3,
            asset_class="etf",
        ),
        build(
            ticker="XOM", name="Exxon Mobil", sector="Energy",
            price=114.20, change_pct=1.15, volume=15_000_000, avg_volume_30d=18_000_000,
            price_history=gen_history(108, drift=0.0008),
            sentiment_score=0.18, article_count=5,
        ),
        build(
            ticker="GLD", name="SPDR Gold Shares", sector="Commodities",
            price=218.40, change_pct=0.62, volume=8_000_000, avg_volume_30d=9_500_000,
            price_history=gen_history(198, drift=0.0012),
            sentiment_score=0.15, article_count=4,
            asset_class="etf",
        ),
        build(
            ticker="SLV", name="iShares Silver Trust", sector="Commodities",
            price=28.40, change_pct=0.85, volume=18_000_000, avg_volume_30d=16_000_000,
            price_history=gen_history(25, drift=0.0015, vol=0.018),
            sentiment_score=0.22, article_count=3,
            asset_class="etf",
        ),
        build(
            ticker="UUP", name="Invesco DB US Dollar Index", sector="FX",
            price=28.95, change_pct=-0.12, volume=1_800_000, avg_volume_30d=2_000_000,
            price_history=gen_history(28.5, drift=0.0001, vol=0.004),
            sentiment_score=0.05, article_count=2,
            asset_class="etf",
        ),
        build(
            ticker="TLT", name="iShares 20+ Year Treasury", sector="Rates",
            price=92.80, change_pct=0.45, volume=18_000_000, avg_volume_30d=20_000_000,
            price_history=gen_history(95, drift=-0.0003, vol=0.007),
            sentiment_score=-0.05, article_count=4,
            asset_class="etf",
        ),
        build(
            ticker="BTC-USD", name="Bitcoin", sector="Crypto",
            price=68420, change_pct=3.25, volume=0, avg_volume_30d=0,
            price_history=gen_history(52000, drift=0.0018, vol=0.03),
            sentiment_score=0.42, article_count=22,
            asset_class="crypto",
        ),
        build(
            ticker="ETH-USD", name="Ethereum", sector="Crypto",
            price=3520, change_pct=4.10, volume=0, avg_volume_30d=0,
            price_history=gen_history(2400, drift=0.0022, vol=0.034),
            sentiment_score=0.38, article_count=14,
            asset_class="crypto",
        ),
        build(
            ticker="SOL-USD", name="Solana", sector="Crypto",
            price=178.40, change_pct=6.85, volume=0, avg_volume_30d=0,
            price_history=gen_history(112, drift=0.003, vol=0.045),
            sentiment_score=0.55, article_count=8,
            asset_class="crypto",
        ),
        build(
            ticker="JPM", name="JPMorgan Chase & Co.", sector="Financials",
            price=196.20, change_pct=0.25, volume=9_500_000, avg_volume_30d=11_000_000,
            price_history=gen_history(180, drift=0.0008, vol=0.01),
            sentiment_score=0.10, article_count=4,
            days_to_earnings=18,
        ),
        # ── Phase F demo additions: oil/Baron + tokens/JRR + crown jewels/Steadfast ─
        build(
            ticker="USO", name="United States Oil Fund (WTI)", sector="Energy",
            price=78.40, change_pct=1.85, volume=4_200_000, avg_volume_30d=4_800_000,
            price_history=gen_history(72, drift=0.0010, vol=0.022),
            sentiment_score=0.18, article_count=6, asset_class="etf",
        ),
        build(
            ticker="XOM", name="Exxon Mobil", sector="Energy",
            price=118.90, change_pct=-0.85, volume=14_000_000, avg_volume_30d=15_500_000,
            price_history=gen_history(115, drift=0.0006, vol=0.014),
            sentiment_score=0.05, article_count=5,
        ),
        build(
            ticker="VLO", name="Valero Energy", sector="Energy",
            price=148.60, change_pct=2.10, volume=3_800_000, avg_volume_30d=4_500_000,
            price_history=gen_history(135, drift=0.0012, vol=0.018),
            sentiment_score=0.25, article_count=4,
        ),
        build(
            ticker="KO", name="Coca-Cola", sector="Staples",
            price=68.20, change_pct=-1.50, volume=14_000_000, avg_volume_30d=12_000_000,
            price_history=gen_history(72, drift=-0.0001, vol=0.008),
            sentiment_score=-0.05, article_count=2,
        ),
        build(
            ticker="DIS", name="Disney", sector="Communication",
            price=92.40, change_pct=-2.30, volume=11_000_000, avg_volume_30d=12_500_000,
            price_history=gen_history(98, drift=-0.0005, vol=0.014),
            sentiment_score=-0.18, article_count=8,
        ),
        build(
            ticker="PEPE-USD", name="Pepe (memecoin)", sector="Token",
            price=0.000018, change_pct=18.50, volume=0, avg_volume_30d=0,
            price_history=gen_history(0.000012, drift=0.005, vol=0.08),
            sentiment_score=0.55, article_count=14, asset_class="crypto",
        ),
        build(
            ticker="SHIB-USD", name="Shiba Inu", sector="Token",
            price=0.0000242, change_pct=6.20, volume=0, avg_volume_30d=0,
            price_history=gen_history(0.000022, drift=0.002, vol=0.045),
            sentiment_score=0.32, article_count=8, asset_class="crypto",
        ),
        build(
            ticker="ARB-USD", name="Arbitrum", sector="Token",
            price=0.74, change_pct=4.80, volume=0, avg_volume_30d=0,
            price_history=gen_history(0.65, drift=0.0018, vol=0.04),
            sentiment_score=0.28, article_count=5, asset_class="crypto",
        ),
    ]


# ─────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────

def run(mode: str = "demo", output_dir: str = "docs/data") -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    today_iso = now.date().isoformat()
    log.info("✦ SILMARIL run starting — mode=%s", mode)

    if mode == "live":
        contexts = build_live_contexts()
    else:
        contexts = build_demo_contexts()

    if not contexts:
        log.error("No contexts built — aborting")
        sys.exit(1)

    # ── Backfill demo headlines for assets that don't have hand-written ones ─
    # In live mode, recent_headlines is populated by news.py from RSS.
    # In demo mode, only a couple of assets have curated headlines, so we
    # generate plausible synthetic ones so the news-feed UI is demonstrable.
    if mode == "demo":
        _backfill_demo_headlines(contexts)

    # ── Run the debate ──────────────────────────────────────────
    # Only the main 15 vote in the debate. Specialists act on consensus
    # but their narrow universes would distort the cross-asset signal if
    # they could vote.
    arbiter = Arbiter(agents=MAIN_VOTERS, aegis_veto_enabled=True)
    debates = arbiter.resolve(contexts)
    debate_dicts = [d.to_dict() for d in debates]

    # ── Specialist votes (operator-only, never affects consensus) ─
    # Baron and Steadfast run $10K career portfolios; they need their
    # own verdicts attached to each debate so the portfolio system can
    # pick their best BUY. These verdicts are added AFTER consensus is
    # computed, so they don't influence the panel's vote.
    SPECIALIST_VOTERS = [baron, steadfast]
    ctx_by_ticker = {c.ticker: c for c in contexts}
    for d in debate_dicts:
        ctx = ctx_by_ticker.get(d["ticker"])
        if not ctx:
            continue
        for spec in SPECIALIST_VOTERS:
            if spec.applies_to(ctx):
                v = spec.evaluate(ctx)
                d.setdefault("verdicts", []).append({
                    "agent": v.agent,
                    "signal": v.signal.value,
                    "conviction": v.conviction,
                    "rationale": v.rationale,
                    "is_specialist": True,
                })

    # Annotate each debate with the context's asset_class (execution needs it)
    # and recent_headlines (so the dashboard can show what news drove the vote)
    # and regime tags (so we can later score performance by market condition)
    ctx_lookup = {c.ticker: c for c in contexts}
    for d in debate_dicts:
        c = ctx_lookup.get(d["ticker"])
        if c:
            d["asset_class"] = c.asset_class
            d["sector"] = c.sector
            d["recent_headlines"] = c.recent_headlines or []
            # Build a flat ctx-like dict for regime tagging
            ctx_flat = {
                "price": c.price,
                "sma_20": getattr(c, "sma_20", None),
                "sma_50": getattr(c, "sma_50", None),
                "sma_200": getattr(c, "sma_200", None),
                "atr_14": getattr(c, "atr_14", None),
                "volume": c.volume,
                "avg_volume_30d": c.avg_volume_30d,
                "article_count": c.article_count,
                "vix": c.vix,
                "market_regime": c.market_regime,
            }
            d["tags"] = tag_context(ctx_flat)

    debate_dicts.sort(
        key=lambda d: (d["consensus"]["score"], d["consensus"]["avg_conviction"]),
        reverse=True,
    )

    # ── Trade plans ─────────────────────────────────────────────
    # Top 16 by consensus across all debates (Phase F: was unbounded)
    TOP_PLAN_COUNT = 16
    plans = []
    for d in debate_dicts[:TOP_PLAN_COUNT]:
        plan = build_plan_from_debate(d, portfolio_size=10_000.0)
        if plan:
            plans.append(plan.to_dict())

    # ── SCROOGE ─────────────────────────────────────────────────
    scrooge_state_path = out / "scrooge.json"
    state = _load_or_init_scrooge(scrooge_state_path)
    top_for_scrooge = [
        {
            "ticker": d["ticker"],
            "signal": d["consensus"]["signal"],
            "consensus_score": d["consensus"]["score"],
            "avg_conviction": d["consensus"]["avg_conviction"],
            "rationale": d.get("dissent_summary", ""),
        }
        for d in debate_dicts
    ]
    prices = {ctx.ticker: ctx.price for ctx in contexts}

    # ── Once-per-day gate ─────────────────────────────────────────
    # The cron fires every 30 min during market hours. We want trade
    # decisions to happen ONCE per UTC day per agent, not on every
    # cron run. Multi-trade agents (CryptoBro/JRR/Sports/Baron) have
    # their own daily caps and reset counters at midnight UTC.
    def _scrooge_already_acted_today(s):
        # SCROOGE rotates at most 1× per day. If history shows action today, skip.
        return any((h.get("date") == today_iso) and h.get("action") in ("BUY", "SELL", "ROTATE", "HODL")
                   for h in (s.history or []))

    def _midas_already_acted_today(s):
        # MIDAS minimum cycle is 7 days, but in this gate we just check today
        return any(h.get("date") == today_iso for h in (s.history or []))

    if not _scrooge_already_acted_today(state):
        state = scrooge_act(state, top_for_scrooge, prices)
    scrooge_dict = state.to_dict()

    # ── MIDAS (parallel hard-currency compounder) ───────────────
    midas_state_path = out / "midas.json"
    mstate = _load_or_init_midas(midas_state_path)
    midas_candidates = [
        {
            "ticker": d["ticker"],
            "consensus": d["consensus"],
        }
        for d in debate_dicts
    ]
    if not _midas_already_acted_today(mstate):
        mstate = midas_act(mstate, midas_candidates, prices)
    midas_dict = mstate.to_dict()

    # ── CryptoBro (parallel multi-trade crypto compounder) ──────
    cbro_state_path = out / "cryptobro.json"
    cbstate = _load_or_init_cryptobro(cbro_state_path)
    cbro_candidates = [
        {
            "ticker": d["ticker"],
            "consensus": d["consensus"],
        }
        for d in debate_dicts
    ]
    # CryptoBro respects his per-day cap inside act(); pass through.
    cbstate = cryptobro_act(cbstate, cbro_candidates, prices)
    cryptobro_dict = cbstate.to_dict()

    # ── JRR Token (two-tier penny token compounder) ─────────────
    jrr_state_path = out / "jrr_token.json"
    jrrstate = _load_or_init_jrr_token(jrr_state_path)
    jrr_candidates = [
        {
            "ticker": d["ticker"],
            "consensus": d["consensus"],
        }
        for d in debate_dicts
        if d["ticker"] in JRR_UNIVERSE
    ]
    jrrstate = jrr_token_act(jrrstate, jrr_candidates, prices)
    jrr_token_dict = jrrstate.to_dict()

    # ── Sports Bro (Polymarket + Kalshi) ────────────────────────
    sports_state_path = out / "sports_bro.json"
    sb_state = _load_or_init_sports_bro(sports_state_path)
    sports_markets = fetch_markets(mode=mode)
    sb_state = sports_bro_act(sb_state, sports_markets)
    sports_bro_dict = sb_state.to_dict()
    write_markets_json(out / "sports_markets.json", sports_markets)

    # ── Catalysts roundup ───────────────────────────────────────
    write_catalysts_json(out / "catalysts.json", today_iso)

    # ── Chart bundles for each debated ticker ───────────────────
    write_charts_json(out / "charts.json", debate_dicts, ctx_lookup)

    # ── Per-agent $10K career portfolios ─────────────────────────
    # Includes the 15 main voters PLUS Baron and Steadfast (specialists
    # who run $10K career books). $1 compounders are excluded.
    portfolios_path = out / "agent_portfolios.json"
    portfolios = load_portfolios(portfolios_path)
    DOLLAR_COMPOUNDERS = {"SCROOGE", "MIDAS", "CRYPTOBRO", "JRR_TOKEN"}
    main_agents = [a.codename for a in AGENTS if a.codename not in DOLLAR_COMPOUNDERS]

    # Load any pre-existing risk state to know which agents enter today frozen
    risk_path = out / "risk_state.json"
    prior_agent_risk, prior_system_risk = load_risk_state(risk_path)
    frozen_today = {n for n, s in prior_agent_risk.items() if s.frozen}
    if prior_system_risk.safe_mode:
        log.warning("  ⚠ Entering run in SAFE MODE: %s", prior_system_risk.safe_mode_reason)
        # In safe mode, ALL agents skip new opens
        frozen_today = set(main_agents)

    for agent_name in main_agents:
        if agent_name not in portfolios:
            portfolios[agent_name] = AgentPortfolio(agent=agent_name)
        p = portfolios[agent_name]

        # Once-per-day gate: only run trade decision if the agent
        # hasn't already acted on a trade today. Mark-to-market the
        # current equity on every cron run so the dashboard stays fresh.
        already_acted_today = any(
            h.get("date") == today_iso and h.get("action") in ("BUY", "SELL", "ROTATE", "HODL", "OPEN", "CLOSE", "FROZEN")
            for h in (p.history or [])
        )

        if agent_name in frozen_today:
            # Mark equity but do not act
            mark = None
            if p.current_position:
                mark = prices.get(p.current_position["ticker"])
            equity = p.total_equity(mark)
            if not already_acted_today:
                p.history.append({
                    "date": today_iso,
                    "action": "FROZEN",
                    "reason": (prior_agent_risk.get(agent_name).frozen_reason
                               if prior_agent_risk.get(agent_name)
                               else "System safe mode"),
                    "equity": round(equity, 4),
                })
                p.equity_curve.append({"date": today_iso, "equity": round(equity, 4)})
        elif not already_acted_today:
            portfolios[agent_name] = agent_portfolio_act(
                portfolios[agent_name], debate_dicts, prices,
            )
        # else: already acted today, no new action — equity will mark-to-market via prices
    save_portfolios(portfolios_path, portfolios, prices)

    # ── Phase C: outcome scoring (the learning loop) ────────────
    # Step 1: read existing history (which has yesterday's votes + tags)
    # Step 2: score those votes against today's prices
    # Step 3: append new outcomes to scoring.json
    # Step 4: rebuild the per-agent summary (win rate, EV, regime cuts)
    history_path = out / "history.json"
    history_data = {"runs": []}
    if history_path.exists():
        try:
            history_data = json.loads(history_path.read_text())
        except Exception:
            history_data = {"runs": []}

    scoring_path = out / "scoring.json"
    scoring_data = load_scoring(scoring_path)

    new_outcomes = score_prior_run(history_data, prices, today_iso)
    new_outcome_dicts = [o.to_dict() for o in new_outcomes]

    # Dedupe — never score the same (agent, ticker, predicted_at) twice
    existing_keys = {
        (o["agent"], o["ticker"], o["predicted_at"])
        for o in scoring_data.get("outcomes", [])
    }
    new_unique = [
        o for o in new_outcome_dicts
        if (o["agent"], o["ticker"], o["predicted_at"]) not in existing_keys
    ]
    all_outcomes = scoring_data.get("outcomes", []) + new_unique

    agent_codenames = [a.codename for a in AGENTS]
    scoring_summary = build_scoring_summary(all_outcomes, agent_codenames)
    save_scoring(scoring_path, all_outcomes, scoring_summary)

    log.info("  Scored %d new predictions (total tracked: %d)",
             len(new_unique), len(all_outcomes))
    if scoring_summary.get("best_agent"):
        b = scoring_summary["best_agent"]
        log.info("  Best agent: %s (win rate %.1f%%, EV %+.2f%%)",
                 b["agent"], (b["win_rate"] or 0) * 100, b["expected_value"] or 0)

    # ── Phase E: hard risk engine ───────────────────────────────
    # Use the prior_* state we loaded above as the basis; evaluate;
    # save updated state to disk
    agent_risk, system_risk = prior_agent_risk, prior_system_risk

    # Build a quick lookup of weight multipliers from scoring
    weight_lookup: Dict[str, float] = {}
    calls_lookup: Dict[str, int] = {}
    for r in scoring_summary.get("leaderboard", []):
        weight_lookup[r["agent"]] = r.get("weight_multiplier") or 1.0
        calls_lookup[r["agent"]] = r.get("scored_calls") or 0

    # Evaluate per-agent risk (use $10K career portfolio equity as the metric)
    main_agent_returns: List[float] = []
    for agent_name, p in portfolios.items():
        mark = None
        if p.current_position:
            mark = prices.get(p.current_position["ticker"])
        equity = p.total_equity(mark)

        state = agent_risk.get(agent_name) or AgentRiskState(agent=agent_name)
        state, log_msg = evaluate_agent_risk(
            state,
            current_equity=equity,
            weight_multiplier=weight_lookup.get(agent_name),
            scored_calls=calls_lookup.get(agent_name, 0),
            today_iso=today_iso,
        )
        agent_risk[agent_name] = state
        if log_msg:
            log.info("  %s", log_msg)

        ret_pct = ((equity / 10_000.0) - 1) * 100
        main_agent_returns.append(ret_pct)

    # System-wide cohort kill switch
    system_risk, sys_log = evaluate_cohort_risk(
        system_risk, main_agent_returns, today_iso,
    )
    if sys_log:
        log.warning("  ⚠ %s", sys_log)

    save_risk_state(risk_path, agent_risk, system_risk, DEFAULT_CONFIG)

    frozen = [n for n, s in agent_risk.items() if s.frozen]
    if frozen:
        log.info("  Frozen agents: %s", ", ".join(frozen))
    if system_risk.safe_mode:
        log.warning("  ⚠ SYSTEM IN SAFE MODE: %s", system_risk.safe_mode_reason)

    # ── Risk-filter the trade plans ─────────────────────────────
    plans_kept, plans_rejected = filter_plans_by_risk(plans)
    if plans_rejected:
        log.info("  %d plans rejected by risk engine", len(plans_rejected))

    # ── Handoff Blocks ──────────────────────────────────────────
    per_asset_handoffs = {
        d["ticker"]: build_asset_deep_dive(_attach_headlines(d, contexts))
        for d in debate_dicts
    }

    per_plan_handoffs = {
        p["plan_id"]: build_trade_plan_handoff(p)
        for p in plans_kept
    }

    # Regime/VIX from the first context (all have the same macro)
    first = contexts[0]
    # Build per-specialist narratives (lightweight wrappers for each)
    def _agent_narrative(name, state, role):
        """Build a generic narrative handoff block for any agent state dict."""
        from .handoff.deeplinks import build_handoffs
        balance = state.get('balance', 0) if state else 0
        history = (state or {}).get('history', [])
        recent_trades = '\n'.join([
            f"  - {h.get('date', '?')}: {h.get('action', '?')} {h.get('ticker', h.get('market', '?'))}"
            for h in history[-5:]
        ]) or '  (no recent trades)'
        text = f"""You are reviewing the trading record of {name}, a SILMARIL specialist agent.

Role: {role}
Current balance: ${balance}
Lifetime trades: {len(history)}
Most recent activity:
{recent_trades}

Stress-test {name}'s recent decisions. Are they consistent with their stated philosophy?
Where would you push back? What blind spots might {name} have given the current market regime?
Reply concisely.
"""
        return {
            "title": f"{name} Stress Test",
            "context_text": text,
            "handoffs": build_handoffs(text),
        }

    # Build macro brief from market regime
    def _macro_brief():
        from .handoff.deeplinks import build_handoffs
        vix_str = f"{first.vix:.1f}" if first.vix is not None else "n/a"
        regime_str = first.market_regime if first.market_regime else "UNKNOWN"
        text = f"""SILMARIL Daily Macro Brief

Market regime: {regime_str}
VIX: {vix_str}
Total assets tracked: {len(contexts)}
Total debates resolved: {len(debate_dicts)}
Trade plans surviving risk filter: {len(plans_kept)}

Synthesize the macro picture for an investor reviewing this dashboard.
What are the 2-3 most important things they should know about today's tape?
What sectors or asset classes are showing the highest agreement among the agents?
What's being avoided?
Reply in 3-5 bullets, no preamble.
"""
        return {
            "title": "Macro Brief",
            "context_text": text,
            "handoffs": build_handoffs(text),
        }

    handoff_blocks = {
        "debate_summary": build_debate_summary(
            debate_dicts, market_regime=first.market_regime, vix=first.vix
        ),
        "scrooge_narrative": build_scrooge_narrative(scrooge_dict),
        "midas_narrative": _agent_narrative("MIDAS", midas_dict, "Hard-currency compounder · 7-day cycle · trades only FXE/FXY/FXF/UUP/GLD"),
        "cryptobro_narrative": _agent_narrative("CRYPTOBRO", cryptobro_dict, "Multi-trade crypto compounder · 5/day cap · highest volatility tolerance"),
        "jrr_token_narrative": _agent_narrative("JRR_TOKEN", jrr_token_dict, "Two-tier token trader · 6/day per tier · sub-$100M and over-$100M coins"),
        "sports_bro_narrative": _agent_narrative("SPORTS_BRO", sports_bro_dict, "Prediction-market bettor · half-Kelly · Polymarket + Kalshi only · never sportsbooks"),
        "baron_narrative": _agent_narrative("BARON", (portfolios.get("BARON").to_dict() if portfolios.get("BARON") else {}), "Oil & energy specialist · long/short · 2/day max · EIA Wednesday catalyst-aware"),
        "steadfast_narrative": _agent_narrative("STEADFAST", (portfolios.get("STEADFAST").to_dict() if portfolios.get("STEADFAST") else {}), "American blue-chip patriot · Crown Jewels universe · 30-day minimum hold"),
        "macro_brief": _macro_brief(),
        "per_asset": per_asset_handoffs,
        "per_plan": per_plan_handoffs,
    }

    # ── Agent roster for UI (with full bios) ────────────────────
    agent_roster = []
    for a in AGENTS:
        bio = get_bio(a.codename)
        agent_roster.append({
            "codename": a.codename,
            "specialty": a.specialty,
            "temperament": a.temperament,
            "inspiration": a.inspiration,
            "bio": bio,
        })

    # ── Main output ─────────────────────────────────────────────
    signals_output = {
        "meta": {
            "version": "2.1.0",
            "project": "SILMARIL",
            "run_type": mode,
            "generated_at": now.isoformat(),
            "disclaimer": (
                "SILMARIL is an educational simulation. All content is for informational "
                "and entertainment purposes only. NOT financial advice. Always consult a "
                "licensed professional before investing."
            ),
        },
        "market_state": {
            "regime": first.market_regime,
            "vix": first.vix,
            "spy_trend": spy_trend_label(
                next((c.price for c in contexts if c.ticker == "SPY"), None),
                next((c.sma_50 for c in contexts if c.ticker == "SPY"), None),
            ),
        },
        "universe": {
            "core_count": len(contexts),
            "watchlist_count": 0,
            "discovered_count": 0,
            "total": len(contexts),
        },
        "agent_roster": agent_roster,
        "summary": _compute_summary(debate_dicts),
        "debates": debate_dicts,
    }

    _write(out / "signals.json", signals_output)

    # Decorate each kept plan with broker deeplinks BEFORE writing
    for p in plans_kept:
        p["brokers"] = build_broker_links(
            p.get("ticker", ""),
            p.get("asset_class", "equity"),
        )

    _write(out / "trade_plans.json", {
        "meta": signals_output["meta"],
        "plans": plans_kept,
        "rejected": plans_rejected,
        "risk_filter_applied": True,
    })
    _write(out / "scrooge.json", scrooge_dict)
    _write(out / "midas.json", midas_dict)
    _write(out / "cryptobro.json", cryptobro_dict)
    _write(out / "jrr_token.json", jrr_token_dict)
    _write(out / "sports_bro.json", sports_bro_dict)
    _write(out / "handoff_blocks.json", handoff_blocks)

    # ── Rolling history (per-agent track record, accumulates each run) ─
    _append_history(out / "history.json", debate_dicts, plans, now)

    # Portfolio leaderboard for the log
    leaderboard = []
    for name, p in portfolios.items():
        mark = None
        if p.current_position:
            mark = prices.get(p.current_position["ticker"])
        equity = p.total_equity(mark)
        leaderboard.append((name, equity))
    leaderboard.sort(key=lambda r: r[1], reverse=True)

    log.info("✦ SILMARIL run complete")
    log.info("  %d debates resolved", len(debate_dicts))
    log.info("  %d trade plans (kept after risk filter; %d rejected)",
             len(plans_kept), len(plans_rejected))
    log.info("  SCROOGE:   $%.4f (life #%d)", scrooge_dict["balance"], scrooge_dict["current_life"])
    log.info("  MIDAS:     $%.4f (life #%d)", midas_dict["balance"], midas_dict["current_life"])
    log.info("  CRYPTOBRO: $%.4f (life #%d, %d trades today)",
             cryptobro_dict["balance"], cryptobro_dict["current_life"],
             cryptobro_dict.get("trades_today", 0))
    log.info("  JRR_TOKEN: $%.4f (life #%d, sub:$%.4f over:$%.4f)",
             jrr_token_dict["balance"], jrr_token_dict["current_life"],
             jrr_token_dict["tiers"]["sub_100m"]["balance"],
             jrr_token_dict["tiers"]["over_100m"]["balance"])
    log.info("  Top agent portfolio: %s @ $%.2f", leaderboard[0][0], leaderboard[0][1])
    log.info("  Output: %s", out.resolve())


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _load_or_init_scrooge(path: Path) -> ScroogeState:
    if not path.exists():
        return ScroogeState()
    try:
        with path.open() as f:
            data = json.load(f)
        return ScroogeState(
            balance=data.get("balance", 1.0),
            current_position=data.get("current_position"),
            lifetime_peak=data.get("lifetime_peak", 1.0),
            current_life=data.get("current_life", 1),
            life_start_date=data.get("life_start_date", datetime.now(timezone.utc).date().isoformat()),
            history=data.get("history", []),
            deaths=data.get("deaths", []),
        )
    except Exception:
        return ScroogeState()


def _load_or_init_midas(path: Path) -> MidasState:
    if not path.exists():
        return MidasState()
    try:
        with path.open() as f:
            data = json.load(f)
        return MidasState(
            balance=data.get("balance", 1.0),
            current_position=data.get("current_position"),
            lifetime_peak=data.get("lifetime_peak", 1.0),
            current_life=data.get("current_life", 1),
            life_start_date=data.get("life_start_date", datetime.now(timezone.utc).date().isoformat()),
            history=data.get("history", []),
            deaths=data.get("deaths", []),
        )
    except Exception:
        return MidasState()


def _load_or_init_cryptobro(path: Path) -> CryptoBroState:
    if not path.exists():
        return CryptoBroState()
    try:
        with path.open() as f:
            data = json.load(f)
        return CryptoBroState(
            balance=data.get("balance", 1.0),
            current_position=data.get("current_position"),
            lifetime_peak=data.get("lifetime_peak", 1.0),
            current_life=data.get("current_life", 1),
            life_start_date=data.get("life_start_date", datetime.now(timezone.utc).date().isoformat()),
            history=data.get("history", []),
            deaths=data.get("deaths", []),
            trades_today=data.get("trades_today", 0),
            last_action_date=data.get("last_action_date", ""),
        )
    except Exception:
        return CryptoBroState()


def _load_or_init_jrr_token(path: Path) -> JRRTokenState:
    from .agents.jrr_token import TierState
    if not path.exists():
        return JRRTokenState()
    try:
        with path.open() as f:
            data = json.load(f)
        tiers = data.get("tiers", {})
        sub_data = tiers.get("sub_100m", {})
        over_data = tiers.get("over_100m", {})
        sub_history = sub_data.get("recent_history", [])
        over_history = over_data.get("recent_history", [])
        return JRRTokenState(
            sub_tier=TierState(
                name="SUB_100M",
                balance=sub_data.get("balance", 0.50),
                current_position=sub_data.get("current_position"),
                history=sub_history,
            ),
            over_tier=TierState(
                name="OVER_100M",
                balance=over_data.get("balance", 0.50),
                current_position=over_data.get("current_position"),
                history=over_history,
            ),
            lifetime_peak=data.get("lifetime_peak", 1.0),
            current_life=data.get("current_life", 1),
            life_start_date=data.get("life_start_date", datetime.now(timezone.utc).date().isoformat()),
            deaths=data.get("deaths", []),
            trades_today=data.get("trades_today", 0),
            last_action_date=data.get("last_action_date", ""),
        )
    except Exception:
        return JRRTokenState()


def _load_or_init_sports_bro(path: Path) -> SportsBroState:
    if not path.exists():
        return SportsBroState()
    try:
        with path.open() as f:
            data = json.load(f)
        return SportsBroState(
            balance=data.get("balance", 1.0),
            open_bets=data.get("open_bets", []),
            history=data.get("history", []),
            lifetime_peak=data.get("lifetime_peak", 1.0),
            current_life=data.get("current_life", 1),
            life_start_date=data.get("life_start_date", datetime.now(timezone.utc).date().isoformat()),
            deaths=data.get("deaths", []),
            trades_today=data.get("trades_today", 0),
            last_action_date=data.get("last_action_date", ""),
        )
    except Exception:
        return SportsBroState()


def _append_history(path: Path, debate_dicts, plans, now) -> None:
    """Append a compact per-run snapshot to history.json so agent track
    records accumulate across runs. Kept small (verdicts only — not full
    debate transcripts) to avoid unbounded file growth."""
    today = now.date().isoformat()
    snapshot = {
        "date": today,
        "generated_at": now.isoformat(),
        "verdicts": [
            {
                "ticker": d["ticker"],
                "consensus": d["consensus"]["signal"],
                "consensus_score": d["consensus"]["score"],
                "agreement": d["consensus"]["agreement_score"],
                "votes": [
                    {
                        "agent": v["agent"],
                        "signal": v["signal"],
                        "conviction": v["conviction"],
                    }
                    for v in d.get("verdicts", [])
                ],
                "price": d.get("price"),
                "tags": d.get("tags", {}),
            }
            for d in debate_dicts
        ],
        "plans": [
            {
                "ticker": p["ticker"],
                "entry": p.get("entry"),
                "stop": p.get("stop"),
                "target": p.get("target"),
                "reward_risk_ratio": p.get("reward_risk_ratio"),
                "backers": [b["agent"] for b in p.get("backers", [])],
            }
            for p in plans
        ],
    }

    # Load existing, append, trim to last 120 snapshots (~6 months of trading days)
    data = {"runs": []}
    if path.exists():
        try:
            with path.open() as f:
                data = json.load(f)
        except Exception:
            data = {"runs": []}

    # Dedupe: if a run already exists for this date, replace it
    runs = [r for r in data.get("runs", []) if r.get("date") != today]
    runs.append(snapshot)
    runs = runs[-120:]
    data["runs"] = runs

    with path.open("w") as f:
        json.dump(_sanitize_for_json(data), f, indent=2, default=str, allow_nan=False)


def _attach_headlines(debate: dict, contexts: List[AssetContext]) -> dict:
    for ctx in contexts:
        if ctx.ticker == debate["ticker"]:
            return {**debate, "recent_headlines": ctx.recent_headlines}
    return debate


# Realistic synthetic-headline pool for demo mode. In --live mode these
# come from RSS via news.py; demo mode needs them to demonstrate the UI.
_DEMO_HEADLINE_POOLS = {
    "Technology": [
        ("Tech earnings season frames AI capex debate", "Reuters"),
        ("Hyperscaler spending guide raised for 2026", "Bloomberg"),
        ("Semis sector breadth widens beyond top three names", "Barron's"),
        ("Cloud infrastructure outlook: revenue acceleration likely", "WSJ"),
    ],
    "Index": [
        ("Index breadth improves as small-caps participate", "Bloomberg"),
        ("Volatility compressed; range-bound trading continues", "Reuters"),
        ("Quarter-end rebalance flows expected this week", "WSJ"),
    ],
    "Crypto": [
        ("Spot ETF flows turn positive after week of outflows", "CoinDesk"),
        ("Layer-1 activity ticks higher on weekend volume", "The Block"),
        ("Stablecoin supply growth signals risk-on positioning", "Bloomberg"),
    ],
    "Commodities": [
        ("Gold holds near record on real-rate compression", "Bloomberg"),
        ("Central bank gold buying continues into Q2", "Reuters"),
        ("Silver industrial demand outlook lifts on solar growth", "WSJ"),
    ],
    "FX": [
        ("Dollar firms on hawkish Fed minutes language", "Reuters"),
        ("DXY consolidates as rate-cut expectations recede", "Bloomberg"),
    ],
    "Rates": [
        ("Long-duration bonds catch bid on duration buying", "Bloomberg"),
        ("Treasury auction demand exceeds expectations", "WSJ"),
    ],
    "Energy": [
        ("OPEC+ production discipline supports crude floor", "Reuters"),
        ("Refining margins expand into summer driving season", "Bloomberg"),
    ],
    "Discretionary": [
        ("Consumer credit data softens; discretionary at risk", "Bloomberg"),
        ("Retail same-store sales miss on weather effects", "WSJ"),
    ],
    "Financials": [
        ("Bank earnings highlight net-interest-margin pressure", "Reuters"),
        ("Loan-loss provisions tick higher in commercial real estate", "Bloomberg"),
    ],
}
_DEMO_HEADLINE_DEFAULT = [
    ("Markets digest mixed economic data ahead of catalysts", "Reuters"),
    ("Sector rotation continues; cross-asset correlations easing", "Bloomberg"),
]


def _backfill_demo_headlines(contexts: List[AssetContext]) -> None:
    """Mutate contexts so any ticker without headlines gets 2 plausible ones."""
    import random
    rng = random.Random(42)  # deterministic across runs
    for ctx in contexts:
        if ctx.recent_headlines:
            continue
        pool = _DEMO_HEADLINE_POOLS.get(ctx.sector, _DEMO_HEADLINE_DEFAULT)
        picks = rng.sample(pool, k=min(2, len(pool)))
        ctx.recent_headlines = [
            {"title": t, "source": s, "url": ""} for (t, s) in picks
        ]


def _compute_summary(debates: List[dict]) -> dict:
    from collections import Counter
    counts = Counter(d["consensus"]["signal"] for d in debates)
    return {
        "total_tracked": len(debates),
        "strong_buy_count": counts.get("STRONG_BUY", 0),
        "buy_count": counts.get("BUY", 0),
        "hold_count": counts.get("HOLD", 0),
        "sell_count": counts.get("SELL", 0),
        "strong_sell_count": counts.get("STRONG_SELL", 0),
        "vetoes": sum(1 for d in debates if d.get("aegis_veto")),
    }


def _sanitize_for_json(obj):
    """Recursively replace NaN, +Inf, -Inf with None so the resulting
    JSON is valid for browsers. JSON spec forbids these values; Python's
    default encoder writes them as 'NaN'/'Infinity' which JS cannot parse."""
    import math
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _write(path: Path, data) -> None:
    clean = _sanitize_for_json(data)
    with path.open("w") as f:
        json.dump(clean, f, indent=2, default=str, allow_nan=False)


# ─────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SILMARIL — multi-agent financial intelligence")
    parser.add_argument("--live", action="store_true", help="Fetch real market data")
    parser.add_argument("--demo", action="store_true", help="Use sample data (default)")
    parser.add_argument("--output", default="docs/data", help="Output directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    mode = "live" if args.live else "demo"
    run(mode=mode, output_dir=args.output)


if __name__ == "__main__":
    main()
