"""
silmaril.cli — The main runner. Alpha 2.0 — Full Learning Mode.

Two modes:

  python -m silmaril --live    # Fetch real market data from yfinance + news RSS
  python -m silmaril --demo    # Use hand-crafted sample contexts for offline testing

The --live mode is what GitHub Actions runs on schedule. It populates
the live site at theseanmitchell.github.io/SILMARIL with real data.

The --demo mode is for local development and the repository's initial
commit, so the site renders meaningfully before the first scheduled run.

ALPHA 2.0 ADDITIONS:
  - Bayesian beliefs update each cycle (agent_beliefs.json — PROTECTED)
  - Thompson-sampled conviction multipliers boost hot agents
  - Evolution cards advance on every scored outcome (only grow)
  - Counterfactual logging for every overruled dissent
  - Operator reflections injected into agent contexts
  - Drift detection auto-dampens cold agents
  - Time-of-day performance buckets
  - Position correlation matrix nightly snapshot
  - Anomaly detection (volume spikes, price gaps)
  - Alpaca paper trading bridge (paper-only, hardcoded)
  - Two new agents: CONTRARIAN, SHORT_ALPHA
  - Persistence guard: training NEVER resets across any workflow
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
    sports_bro, sports_bro_act, SportsBroState, settle_expired_bets,
)

# ── v2.0 agents ─────────────────────────────────────────────────
from .agents.atlas import atlas
from .agents.nightshade import nightshade
from .agents.cicada import cicada
from .agents.shepherd import shepherd
from .agents.nomad import nomad
from .agents.barnacle import barnacle
from .agents.kestrel_plus import kestrel_plus

# ── ALPHA 2.0 new agents ────────────────────────────────────────
# These are imported defensively — if the modules don't exist yet
# (e.g. mid-merge), we gracefully skip them rather than crash.
try:
    from .agents.contrarian import Contrarian as _ContrarianClass
    contrarian = _ContrarianClass()
    _HAS_CONTRARIAN = True
except Exception as _e:
    contrarian = None
    _HAS_CONTRARIAN = False

try:
    from .agents.short_alpha import ShortAlpha as _ShortAlphaClass
    short_alpha = _ShortAlphaClass()
    _HAS_SHORT_ALPHA = True
except Exception as _e:
    short_alpha = None
    _HAS_SHORT_ALPHA = False

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

# ── ALPHA 2.0 Full Learning Mode imports ────────────────────────
# All defensively imported so if a module is missing mid-merge, the
# old runner still works. Each capability is gated by its _HAS flag.
try:
    from .learning.persistence_guard import (
        PROTECTED_LEARNING_FILES, emit_persistence_status, verify_persistence,
    )
    from .learning.bayesian_winrate import (
        load_beliefs, save_beliefs, update_beliefs,
    )
    from .learning.thompson_arbiter import sample_conviction_multipliers
    from .learning.dissent_digest import build_dissent_digest, attach_digest_to_contexts
    from .learning.reflection import load_reflection, format_reflection_for_context
    from .learning.evolution_cards import load_cards, save_cards, ensure_card
    from .learning.counterfactual import log_counterfactual
    from .learning.regime_bandit import RegimeBanditStore, context_key
    from .learning.time_of_day import get_tod_bucket, record_tod_outcome
    from .learning.drift_detector import (
        detect_drift, update_drift_state, get_drift_dampeners,
    )
    from .learning.correlation_matrix import (
        compute_position_correlations, append_to_history as append_corr_history,
    )
    from .learning.anomaly_detector import (
        detect_volume_spike, detect_price_gap, record_anomalies,
    )
    from .learning.premortem import generate_premortem, archive_premortem
    _HAS_LEARNING = True
except Exception as _e:
    _HAS_LEARNING = False
    logging.getLogger("silmaril").warning(
        "Alpha 2.0 learning modules not yet installed; running in compatibility mode. (%s)", _e
    )

try:
    from .execution.alpaca_paper import execute_consensus_signals
    _HAS_ALPACA = True
except Exception as _e:
    _HAS_ALPACA = False

try:
    from .agents._rename_map import display_label, all_new_codenames
    _HAS_RENAME_MAP = True
except Exception as _e:
    _HAS_RENAME_MAP = False


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
# Alpha 2.0 additions to the voter panel
if _HAS_CONTRARIAN and contrarian is not None:
    MAIN_VOTERS.append(contrarian)
if _HAS_SHORT_ALPHA and short_alpha is not None:
    MAIN_VOTERS.append(short_alpha)

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
                {"title": a.title, "source": a.source, "url": a.url,
                 "published": a.published_iso or ""}
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
# ALPHA 2.0 — Pre-debate learning setup
# Loads beliefs, builds dissent digest, injects reflection.
# Returns a bundle that post-debate update consumes.
# ─────────────────────────────────────────────────────────────────

def _pre_debate_learning(out: Path, contexts: List[AssetContext]) -> dict:
    """Returns a learning context bundle. Empty dict if learning unavailable."""
    if not _HAS_LEARNING:
        return {}

    bundle = {
        "out": out,
        "beliefs": {},
        "cards": {},
        "rolling_winrates": {},
        "drift_dampeners": {},
        "tod_bucket": "UNKNOWN",
        "digest": "",
        "reflection": None,
        "multipliers": {},
    }

    try:
        bundle["beliefs"] = load_beliefs(out / "agent_beliefs.json")
    except Exception as e:
        log.warning("learning: load_beliefs failed: %s", e)

    try:
        bundle["cards"] = load_cards(out / "agent_evolution_cards.json")
    except Exception as e:
        log.warning("learning: load_cards failed: %s", e)

    # Build dissent digest from history + scoring
    try:
        bundle["digest"] = build_dissent_digest(
            scoring_path=out / "scoring.json",
            history_path=out / "history.json",
            counterfactuals_path=out / "counterfactuals.json",
            lookback_days=7,
        )
    except Exception as e:
        log.warning("learning: dissent digest failed: %s", e)

    # Operator reflection
    try:
        bundle["reflection"] = load_reflection(out / "reflections.json")
    except Exception as e:
        log.warning("learning: load_reflection failed: %s", e)

    # Inject into asset contexts
    reflection_block = format_reflection_for_context(bundle["reflection"]) if bundle["reflection"] else ""
    learning_block = f"{bundle['digest']}\n{reflection_block}".strip()
    if learning_block:
        try:
            attach_digest_to_contexts(contexts, learning_block)
            log.info("learning: injected %d chars of context into %d assets",
                     len(learning_block), len(contexts))
        except Exception as e:
            log.warning("learning: attach_digest failed: %s", e)

    # Compute rolling winrates from existing scoring.json
    scoring_path = out / "scoring.json"
    if scoring_path.exists():
        try:
            sd = json.loads(scoring_path.read_text())
            for row in sd.get("leaderboard", []):
                agent = row.get("agent")
                wr = row.get("rolling_30d_win_rate")
                if wr is None:
                    wr = row.get("win_rate")
                if agent and wr is not None:
                    bundle["rolling_winrates"][agent] = float(wr)
        except Exception as e:
            log.warning("learning: rolling_winrates failed: %s", e)

    # Drift dampeners
    try:
        bundle["drift_dampeners"] = get_drift_dampeners(out / "drift_state.json")
    except Exception as e:
        log.warning("learning: drift_dampeners failed: %s", e)

    # Time-of-day bucket
    try:
        bundle["tod_bucket"] = get_tod_bucket()
    except Exception:
        pass

    # Thompson-sampled conviction multipliers per agent for current regime
    try:
        regime = contexts[0].market_regime if contexts else "NEUTRAL"
        if bundle["beliefs"]:
            mults = sample_conviction_multipliers(bundle["beliefs"], regime)
            # Apply drift dampeners
            for agent, dmp in bundle["drift_dampeners"].items():
                if agent in mults and dmp < 1.0:
                    mults[agent] *= dmp
            bundle["multipliers"] = mults
    except Exception as e:
        log.warning("learning: thompson sampling failed: %s", e)

    return bundle


def _apply_conviction_multipliers(verdicts: list, multipliers: dict) -> list:
    """Scale each verdict's conviction by its agent's Thompson multiplier.
    Caps conviction at [0, 1] after scaling. Mutates in place."""
    if not multipliers:
        return verdicts
    for v in verdicts:
        agent = v.get("agent") if isinstance(v, dict) else getattr(v, "agent", None)
        if not agent:
            continue
        mult = multipliers.get(agent, 1.0)
        if isinstance(v, dict):
            cur = float(v.get("conviction", 0) or 0)
            v["conviction"] = max(0.0, min(1.0, cur * mult))
            v.setdefault("learning_multiplier", round(mult, 3))
        else:
            cur = float(getattr(v, "conviction", 0) or 0)
            try:
                v.conviction = max(0.0, min(1.0, cur * mult))
            except Exception:
                pass
    return verdicts


def _scan_anomalies(out: Path, contexts: List[AssetContext]) -> List[dict]:
    """Scan all contexts for anomalies, persist with TTL."""
    if not _HAS_LEARNING:
        return []
    state_path = out / "anomaly_state.json"
    fresh = []
    for ctx in contexts:
        anomalies = []
        try:
            cur_v = getattr(ctx, "volume", None) or 0
            avg_v = getattr(ctx, "avg_volume_30d", None) or 0
            if cur_v and avg_v:
                # Construct a synthetic 30-day history near the avg for z-score
                hist = [avg_v] * 30
                vs = detect_volume_spike(int(cur_v), hist, threshold_sigma=3.0)
                if vs:
                    anomalies.append(vs)
        except Exception:
            pass
        try:
            ph = getattr(ctx, "price_history", None) or []
            if len(ph) >= 2 and ctx.price:
                pg = detect_price_gap(open_price=ctx.price, prev_close=ph[-2])
                if pg:
                    anomalies.append(pg)
        except Exception:
            pass
        if anomalies and ctx.ticker:
            try:
                f = record_anomalies(state_path, ctx.ticker, anomalies)
                fresh.extend(f)
            except Exception:
                pass
    if fresh:
        log.info("learning: detected %d fresh anomalies", len(fresh))
    return fresh


# ─────────────────────────────────────────────────────────────────
# ALPHA 2.0 — Post-debate learning update
# Updates beliefs, evolution cards, drift state, counterfactuals.
# ─────────────────────────────────────────────────────────────────

def _post_debate_learning(
    bundle: dict,
    *,
    debate_dicts: list,
    portfolios: dict,
    new_outcome_dicts: list,
    contexts: List[AssetContext],
    today_iso: str,
) -> None:
    """Update all learning state after consensus + outcome scoring."""
    if not _HAS_LEARNING or not bundle:
        return

    out: Path = bundle.get("out")
    if not out:
        return

    # 1) Update Bayesian beliefs from newly scored outcomes
    if new_outcome_dicts:
        try:
            outcomes_for_beliefs = [
                {
                    "agent": o.get("agent"),
                    "regime": o.get("regime") or o.get("market_regime") or "UNKNOWN",
                    "won": bool(o.get("correct", o.get("was_correct", o.get("won", False)))),
                }
                for o in new_outcome_dicts
                if o.get("agent")
                # Alpha 2.2: Only directional calls update beliefs.
                # HOLD votes carry no signal about future direction.
                and o.get("signal") not in ("HOLD",)
            ]
            beliefs = update_beliefs(bundle["beliefs"], outcomes_for_beliefs)
            save_beliefs(out / "agent_beliefs.json", beliefs)
            log.info("learning: updated beliefs on %d outcomes", len(outcomes_for_beliefs))
        except Exception as e:
            log.warning("learning: belief update failed: %s", e)

    # 2) Advance evolution cards (only grow)
    if new_outcome_dicts:
        try:
            cards = bundle.get("cards", {})
            for o in new_outcome_dicts:
                agent = o.get("agent")
                if not agent:
                    continue
                card = ensure_card(cards, agent)
                card.record_call(
                    won=bool(o.get("correct", o.get("was_correct", o.get("won", False)))),
                    conviction=float(o.get("conviction", 0.5) or 0.5),
                    regime=o.get("regime") or "UNKNOWN",
                    was_dissent=bool(o.get("was_dissent", False)),
                )
            save_cards(out / "agent_evolution_cards.json", cards)
            log.info("learning: advanced %d evolution cards", len(cards))
        except Exception as e:
            log.warning("learning: evolution cards update failed: %s", e)

    # 3) Counterfactual logging — for each debate, log dissent vs consensus
    try:
        for d in debate_dicts:
            ndr = d.get("next_day_return")
            if ndr is None:
                continue
            consensus_signal = (d.get("consensus") or {}).get("signal", "HOLD")
            for v in d.get("verdicts", []):
                v_signal = v.get("signal")
                if v_signal in (consensus_signal, "ABSTAIN"):
                    continue
                try:
                    log_counterfactual(
                        out / "counterfactuals.json",
                        date_str=today_iso,
                        ticker=d.get("ticker", ""),
                        consensus_signal=consensus_signal,
                        dissenting_agent=v.get("agent", ""),
                        dissent_signal=v_signal,
                        next_day_return=float(ndr),
                    )
                except Exception:
                    pass
    except Exception as e:
        log.warning("learning: counterfactual logging failed: %s", e)

    # 4) Drift detection — scan evolution cards vs rolling winrates
    try:
        drift_by_agent = {}
        for agent, card in bundle.get("cards", {}).items():
            rolling = bundle["rolling_winrates"].get(agent, None)
            if rolling is None:
                continue
            n_calls = getattr(card, "lifetime_calls", 0) or 0
            if n_calls < 30:
                continue
            lt = getattr(card, "lifetime_win_rate", 0.5)
            d = detect_drift(
                rolling_30d_winrate=float(rolling),
                lifetime_winrate=float(lt),
                n_recent_calls=min(n_calls, 100),
            )
            if d.get("drifting"):
                drift_by_agent[agent] = d
        update_drift_state(out / "drift_state.json", drift_by_agent)
        if drift_by_agent:
            log.info("learning: drift detected for %s", list(drift_by_agent.keys()))
    except Exception as e:
        log.warning("learning: drift detection failed: %s", e)

    # 5) Time-of-day bucket update
    if new_outcome_dicts:
        try:
            bucket = bundle.get("tod_bucket") or "UNKNOWN"
            for o in new_outcome_dicts:
                agent = o.get("agent")
                if not agent:
                    continue
                record_tod_outcome(
                    out / "time_of_day_performance.json",
                    agent,
                    bucket,
                    bool(o.get("correct", o.get("won", False))),
                )
        except Exception as e:
            log.warning("learning: TOD update failed: %s", e)

    # 6) Correlation matrix snapshot
    try:
        portfolio_snap = {}
        for name, p in (portfolios or {}).items():
            cp = getattr(p, "current_position", None)
            if cp:
                portfolio_snap[name] = {"current_position": cp}
        # Build price_history map from contexts
        price_history = {}
        for ctx in contexts:
            ph = getattr(ctx, "price_history", None)
            if ph:
                price_history[ctx.ticker] = list(ph)[-90:]
        if portfolio_snap and price_history:
            snap = compute_position_correlations(portfolio_snap, price_history)
            append_corr_history(out / "correlation_history.json", snap)
            alerts = snap.get("concentration_alerts", [])
            if alerts:
                log.info("learning: %d concentration alerts", len(alerts))
    except Exception as e:
        log.warning("learning: correlation snapshot failed: %s", e)

    # 7) Persistence health check
    try:
        emit_persistence_status(out, out / "persistence_status.json")
    except Exception as e:
        log.warning("learning: persistence_status failed: %s", e)


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

    # ── ALPHA 2.0: Pre-debate learning setup ────────────────────
    # Loads agent_beliefs.json, builds dissent digest, injects operator
    # reflection into every asset context, computes Thompson-sampled
    # conviction multipliers, and applies drift dampeners.
    learning_bundle = _pre_debate_learning(out, contexts)

    # Anomaly scan (volume spikes, price gaps) — flagged for next debate
    _scan_anomalies(out, contexts)

    # ── Run the debate ──────────────────────────────────────────
    # Only the main voters vote in the debate. Specialists act on consensus
    # but their narrow universes would distort the cross-asset signal if
    # they could vote.
    arbiter = Arbiter(agents=MAIN_VOTERS, aegis_veto_enabled=True)
    debates = arbiter.resolve(contexts)
    debate_dicts = [d.to_dict() for d in debates]

    # ── ALPHA 2.0: Apply Thompson-sampled conviction multipliers ─
    # Each agent's voted conviction gets scaled by how confident the
    # Bayesian posterior is in that agent's win rate in this regime.
    # Confident hot agents get amplified voice; cold agents get muted.
    if learning_bundle.get("multipliers"):
        for d in debate_dicts:
            verdicts = d.get("verdicts", [])
            _apply_conviction_multipliers(verdicts, learning_bundle["multipliers"])
            # Recompute consensus signal/score from scaled verdicts
            _recompute_consensus_in_place(d)

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

    # ── ALPHA 2.0: Pre-mortem on high-conviction calls ──────────
    # For consensus calls with conviction >= 0.55, generate explicit
    # kill-criteria and bear-case statements written into the rationale.
    if _HAS_LEARNING:
        try:
            for d in debate_dicts:
                cons = d.get("consensus") or {}
                conv = float(cons.get("avg_conviction", 0) or 0)
                sig = cons.get("signal", "HOLD")
                if conv < 0.55 or sig in ("HOLD", "ABSTAIN"):
                    continue
                c = ctx_lookup.get(d["ticker"])
                if not c:
                    continue
                ctx_summary = {
                    "price": c.price,
                    "sma_20": getattr(c, "sma_20", None),
                    "sma_50": getattr(c, "sma_50", None),
                }
                pm = generate_premortem(
                    signal=sig, conviction=conv, ticker=d["ticker"],
                    rationale=d.get("dissent_summary", ""), ctx_summary=ctx_summary,
                )
                if pm:
                    d["premortem"] = pm
                    archive_premortem(
                        out / "premortem_archive.json",
                        agent="CONSENSUS", ticker=d["ticker"],
                        signal=sig, conviction=conv, premortem=pm,
                    )
        except Exception as e:
            log.warning("learning: premortem generation failed: %s", e)

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
    # The cron fires every 10 min during market hours. We want trade
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
    sb_state = settle_expired_bets(sb_state)  # v3: auto-resolve expired bets
    sb_state = sports_bro_act(sb_state, sports_markets)
    sports_bro_dict = sb_state.to_dict()
    write_markets_json(out / "sports_markets.json", sports_markets)

    # ── Catalysts roundup ─── moved to after plans_kept is built
    # (see below, after risk filter) so we can pass relevant tickers.

    # ── Chart bundles for each debated ticker ───────────────────
    write_charts_json(out / "charts.json", debate_dicts, ctx_lookup)

    # ── Per-agent $10K career portfolios ─────────────────────────
    # Includes the main voters PLUS Baron and Steadfast (specialists
    # who run $10K career books). $1 compounders are excluded.
    portfolios_path = out / "agent_portfolios.json"
    portfolios = load_portfolios(portfolios_path)
    DOLLAR_COMPOUNDERS = {"SCROOGE", "MIDAS", "CRYPTOBRO", "JRR_TOKEN", "SPORTS_BRO"}
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
            h.get("date") == today_iso and h.get("action") in (
                "BUY", "SELL", "ROTATE", "HODL", "OPEN", "CLOSE", "FROZEN", "HOLD",
            )
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
                    "timestamp": now.isoformat(),  # ALPHA 2.0: real time, not just date
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

    # ── ALPHA 2.0: Post-debate learning update ──────────────────
    # Update beliefs, evolution cards, drift state, counterfactuals,
    # time-of-day buckets, correlation matrix, persistence health.
    _post_debate_learning(
        learning_bundle,
        debate_dicts=debate_dicts,
        portfolios=portfolios,
        new_outcome_dicts=new_unique,
        contexts=contexts,
        today_iso=today_iso,
    )

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

        risk_state = agent_risk.get(agent_name) or AgentRiskState(agent=agent_name)
        risk_state, log_msg = evaluate_agent_risk(
            risk_state,
            current_equity=equity,
            weight_multiplier=weight_lookup.get(agent_name),
            scored_calls=calls_lookup.get(agent_name, 0),
            today_iso=today_iso,
        )
        agent_risk[agent_name] = risk_state
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

    # ── Catalysts roundup (with portfolio context for noise filtering) ──
    # Built here, AFTER plans_kept and portfolios are populated, so we can
    # pass the relevant ticker set. The aggregator uses this to filter the
    # 1,500-event firehose down to ~80 events that actually affect us.
    relevant_tickers = set()
    for _agent_p in portfolios.values():
        if getattr(_agent_p, "current_position", None):
            t = _agent_p.current_position.get("ticker")
            if t: relevant_tickers.add(t.upper())
    for _plan in plans_kept[:12]:
        t = _plan.get("ticker")
        if t: relevant_tickers.add(t.upper())
    write_catalysts_json(out / "catalysts.json", today_iso, relevant_tickers=relevant_tickers)

    # ── ALPHA 2.0: Alpaca paper-trading bridge ──────────────────
    # Every kept plan with consensus_conviction >= 0.60 becomes a real-shaped
    # market order in your free Alpaca paper account. Hardcoded paper-only.
    # No env var, secret, or argument can flip this to live trading.
    # Skipped silently if alpaca-py not installed or secrets not set.
    if _HAS_ALPACA:
        try:
            # Adapt plan dicts to what alpaca_paper expects
            alpaca_plans = []
            for p in plans_kept:
                # The plan dict needs: ticker, consensus_signal,
                # consensus_conviction, entry_price, asset_class
                ticker = p.get("ticker", "")
                # Find the matching debate for the consensus
                d = next((x for x in debate_dicts if x["ticker"] == ticker), None)
                if not d:
                    continue
                cons = d.get("consensus") or {}
                alpaca_plans.append({
                    "ticker": ticker,
                    "consensus_signal": cons.get("signal", "HOLD"),
                    "consensus_conviction": float(cons.get("avg_conviction", 0) or 0),
                    "entry_price": p.get("entry") or p.get("entry_price"),
                    "price": d.get("price"),
                    "asset_class": p.get("asset_class") or d.get("asset_class") or "equity",
                })
            alpaca_state = execute_consensus_signals(
                plans=alpaca_plans,
                state_path=out / "alpaca_paper_state.json",
                max_position_pct=0.08,
                min_consensus_conviction=0.40,
                max_total_positions=15,
                enable_shorts=True,
                profit_take_pct=0.03,    # v4: harvest at +5%
                trailing_stop_pct=0.025,  # v4: stop at -4% from peak
                # CRITICAL FIX: pass every debated ticker's consensus signal so the
                # exit loop can close positions whose tickers fell outside the top-16
                # plan cut. Without this, positions accumulate until the 15-position
                # cap is hit and zero new orders can be placed — Alpaca goes silent.
                all_debate_signals={
                    d["ticker"]: (d.get("consensus") or {}).get("signal", "HOLD")
                    for d in debate_dicts
                },
            )
            if alpaca_state.get("enabled"):
                eq = alpaca_state.get("account", {}).get("equity")
                n_orders = len(alpaca_state.get("orders_placed", []))
                log.info("  Alpaca paper: equity=$%s, orders=%d", eq, n_orders)
                if alpaca_state.get("errors"):
                    log.warning("  Alpaca errors: %s", alpaca_state["errors"][:3])
            else:
                log.info("  Alpaca paper bridge skipped: %s", alpaca_state.get("reason", ""))
        except Exception as e:
            log.warning("alpaca: bridge failed: %s", e)

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
        roster_entry = {
            "codename": a.codename,
            "specialty": a.specialty,
            "temperament": a.temperament,
            "inspiration": getattr(a, "inspiration", ""),
            "bio": bio,
        }
        # Include display label from rename map if available
        if _HAS_RENAME_MAP:
            try:
                roster_entry["display_label"] = display_label(a.codename)
            except Exception:
                pass
        agent_roster.append(roster_entry)

    # ── Main output ─────────────────────────────────────────────
    signals_output = {
        "meta": {
            "version": "2.0.0",
            "project": "SILMARIL",
            "run_type": mode,
            "generated_at": now.isoformat(),
            "alpha_2_0_features": {
                "learning_loop": _HAS_LEARNING,
                "alpaca_paper": _HAS_ALPACA,
                "rename_map": _HAS_RENAME_MAP,
                "contrarian_agent": _HAS_CONTRARIAN,
                "short_alpha_agent": _HAS_SHORT_ALPHA,
            },
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
    if leaderboard:
        log.info("  Top agent portfolio: %s @ $%.2f", leaderboard[0][0], leaderboard[0][1])
    log.info("  Output: %s", out.resolve())

    # ── ALPHA 2.0: Final persistence sanity check ───────────────
    if _HAS_LEARNING:
        try:
            persistence_health = verify_persistence(out)
            log.info("  Learning state: %d/%d protected files present",
                     len(persistence_health["present"]), persistence_health["total_protected"])
        except Exception:
            pass

    # ── ALPHA 2.1: write run_health.json (single source of truth) ────
    # Captures: Alpaca account/equity/savings, last cycle activity,
    # catalyst source statuses, every agent's status today (silent or active),
    # and any issues. Read this ONE file to know if the system is healthy.
    try:
        from .diagnostics.run_health import write_run_health
        cat_diag = {}
        try:
            cat_path = out / "catalysts.json"
            if cat_path.exists():
                cat_payload = json.loads(cat_path.read_text())
                cat_diag = cat_payload.get("_diagnostic", {})
        except Exception:
            pass
        write_run_health(
            out_dir=out,
            debate_dicts=debate_dicts,
            portfolios=portfolios if 'portfolios' in dir() else None,
            alpaca_state=alpaca_state if 'alpaca_state' in dir() else None,
            catalysts_diag=cat_diag,
            main_agents=main_agents if 'main_agents' in dir() else None,
            today_iso=today_iso,
        )
    except Exception as e:
        log.warning("run_health write failed: %s", e)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

# ALPHA 2.0: Recompute consensus from scaled verdicts after applying
# Thompson multipliers. We re-derive signal/score from the modified
# convictions without changing the existing Arbiter class.
_SIGNAL_SCORE = {
    "STRONG_BUY":  +2.0, "BUY":         +1.0,
    "HOLD":         0.0, "ABSTAIN":      0.0,
    "SELL":        -1.0, "STRONG_SELL": -2.0,
}


def _recompute_consensus_in_place(debate: dict) -> None:
    """After verdicts have had their conviction scaled, recompute the
    consensus block to reflect the new weighting. Conservative — only
    updates avg_conviction and consensus.score; preserves agreement_score
    and signal threshold logic from the existing arbiter."""
    verdicts = debate.get("verdicts", []) or []
    if not verdicts:
        return
    total = 0.0
    weight = 0.0
    n_directional = 0  # count only non-ABSTAIN, non-HOLD voters
    for v in verdicts:
        sig = v.get("signal", "HOLD")
        if sig == "ABSTAIN":
            continue
        s = _SIGNAL_SCORE.get(sig, 0.0)
        c = float(v.get("conviction", 0) or 0)
        total += s * c
        weight += c
        if sig not in ("HOLD", "ABSTAIN"):
            n_directional += 1
    if weight == 0:
        return
    avg_score = total / weight
    cons = debate.setdefault("consensus", {})
    cons["score"] = round(avg_score, 4)
    # FIX: divide by directional voters only — not all verdicts (which includes
    # every ABSTAIN agent and dilutes conviction from ~0.79 down to ~0.07).
    cons["avg_conviction"] = round(weight / max(1, n_directional), 4)
    # Keep the existing signal unless it crosses a major threshold
    # (we don't want to flip signal direction here — that's the arbiter's job)


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
    debate transcripts) to avoid unbounded file growth.

    ALPHA 2.0: Adds `timestamp` (full ISO datetime) alongside the
    date-only `date` field, so the dashboard can show real run times
    instead of always displaying 17:00.
    """
    today = now.date().isoformat()
    timestamp_iso = now.isoformat()  # ALPHA 2.0: real time
    snapshot = {
        "date": today,
        "timestamp": timestamp_iso,  # ALPHA 2.0
        "generated_at": timestamp_iso,
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

